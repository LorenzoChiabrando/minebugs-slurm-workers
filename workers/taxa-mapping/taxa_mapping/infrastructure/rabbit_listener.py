import json
import time
import pika
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from ..config import settings
from ..service import run_mapping_pipeline

logger = logging.getLogger(__name__)

# Thread pool to execute jobs without blocking Pika.
executor = ThreadPoolExecutor(max_workers=2)

def connect_with_retry() -> pika.BlockingConnection:
    while True:
        try:
            logger.info(f"Connecting to RabbitMQ at {settings.rabbit_host}...")
            params = pika.ConnectionParameters(
                host=settings.rabbit_host,
                heartbeat=60,
                blocked_connection_timeout=300
            )
            return pika.BlockingConnection(params)
        except pika.exceptions.AMQPConnectionError:
            logger.warning("RabbitMQ not ready. Retrying in 5 seconds...")
            time.sleep(5)

def setup_channel(connection: pika.BlockingConnection):
    channel = connection.channel()
    channel.exchange_declare(exchange=settings.exchange, exchange_type="direct", durable=True)
    channel.queue_declare(queue=settings.queue, durable=True)
    channel.queue_bind(exchange=settings.exchange, queue=settings.queue, routing_key=settings.routing_key)
    channel.basic_qos(prefetch_count=2)
    return channel

def ack_message(channel, delivery_tag):
    """Thread-safe method to acknowledge the message"""
    if channel.is_open:
        logger.info(f"Acknowledging message {delivery_tag}")
        channel.basic_ack(delivery_tag=delivery_tag)
    else:
        logger.warning("Channel closed, cannot ack message.")

def nack_message(channel, delivery_tag):
    """Thread-safe method to reject the message"""
    if channel.is_open:
        logger.warning(f"Nacking message {delivery_tag}")
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)

def do_work(connection, channel, delivery_tag, message):
    try:
        job_id = message.get("jobId")
        input_path = message.get("inputFilePath")
        output_path = message.get("outputFilePath")

        if not job_id or not input_path:
            raise ValueError("Invalid message format: missing 'jobId' or 'inputFilePath'")

        run_mapping_pipeline(job_id, input_path, output_path)

        cb = lambda: ack_message(channel, delivery_tag)
        connection.add_callback_threadsafe(cb)

    except Exception as e:
        logger.exception(f"Critical error processing job {message}: {e}")
        cb = lambda: nack_message(channel, delivery_tag)
        connection.add_callback_threadsafe(cb)

def start_listening():
    connection = connect_with_retry()
    channel = setup_channel(connection)

    logger.info(f"[*] Waiting for messages in queue '{settings.queue}'. To exit press CTRL+C")

    def callback(ch, method, properties, body):
        message = json.loads(body)
        logger.info(f"Received job: {message}")

        executor.submit(do_work, connection, ch, method.delivery_tag, message)

    try:
        channel.basic_consume(queue=settings.queue, on_message_callback=callback)
        channel.start_consuming()
    except KeyboardInterrupt:
        logger.info("Stopping worker...")
        channel.stop_consuming()
        executor.shutdown(wait=True)
        connection.close()
    except Exception as e:
        logger.error(f"Unexpected connection loss: {e}")
        raise e