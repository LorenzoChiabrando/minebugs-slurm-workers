import sys
import os
import logging
import json
import shutil
import pika
import time
import requests
import threading
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import uuid
import zipfile
import functools
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.append(os.getcwd())

try:
    from preprocessing.config import settings
    from preprocessing.infrastructure.minio_storage import storage_client
    from preprocessing.infrastructure.backend_client import update_simulation_status
    from preprocessing.infrastructure.input_adapter import InputAdapter
    from preprocessing.pipeline.main import run_preprocessing_pipeline, PreprocessingConfig
    from solver.runner import SolverRunner
except ImportError as e:
    logging.critical(f"Import Error: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
PREFETCH_COUNT = 2 # Process up to 2 simulations concurrently per worker
HEARTBEAT_INTERVAL = 600  # 10 minutes — must survive long-running simulations

# Thread pool to manage concurrent execution safely
executor = ThreadPoolExecutor(max_workers=PREFETCH_COUNT)

# In-process deduplication guard.
# Tracks job IDs currently being executed to prevent double-execution caused by
# RabbitMQ redelivery (e.g. consumer_timeout, channel close, reconnect).
_running_jobs: set = set()
_running_jobs_lock = threading.Lock()

# Configure a session with automatic retries for robust downloads
download_session = requests.Session()
retry_strategy = Retry(
    total=5, # Maximum number of retries
    backoff_factor=1, # Waits 1s, 2s, 4s, 8s, etc.
    status_forcelist=[429, 500, 502, 503, 504]
)
download_session.mount('http://', HTTPAdapter(max_retries=retry_strategy))
download_session.mount('https://', HTTPAdapter(max_retries=retry_strategy))

def check_and_download_models():
    """
    Ensures the cache directory exists at startup.
    Actual downloads are now deferred (Just-In-Time) per simulation.
    """
    models_dir = Path(settings.agora_models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"[WARMUP] Models cache directory ready: {models_dir}")

def download_required_models(model_ids, models_dir, base_url):
    """
    Downloads the required .mat models from VMH if not already cached.
    Uses atomic temporary files to handle multi-threading safely.
    """
    dir_path = Path(models_dir)

    for model_id in model_ids:
        file_path = dir_path / f"{model_id}.mat"
        tmp_file_path = dir_path / f"{model_id}.mat.tmp"

        if not file_path.exists():
            logger.info(f"Model {model_id} missing in cache. Downloading from VMH...")
            url = f"{base_url}{model_id}.mat"

            try:
                # Stream the download to avoid high memory usage
                response = download_session.get(url, stream=True, timeout=60)
                response.raise_for_status()

                # Write to a temporary file for thread safety
                with open(tmp_file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                # Atomic rename ensures other threads don't read partial files
                tmp_file_path.rename(file_path)
                logger.info(f"Successfully downloaded: {model_id}.mat")

            except Exception as e:
                logger.error(f"Error downloading {model_id}: {e}")
                # Clean up the partial temporary file if it failed
                if tmp_file_path.exists():
                    tmp_file_path.unlink()
                raise RuntimeError(f"Failed to download reference model: {model_id}")

def ack_message(channel, delivery_tag):
    """Thread-safe method to acknowledge the message, wrapped to prevent crashes"""
    try:
        if channel.is_open:
            logger.info(f"Acknowledging message {delivery_tag}")
            channel.basic_ack(delivery_tag=delivery_tag)
        else:
            logger.error("Channel closed, cannot ack message. (Database is already updated though)")
    except Exception as e:
        logger.error(f"Failed to ACK message {delivery_tag} due to connection error: {e}")

def nack_message(channel, delivery_tag):
    """Thread-safe method to reject the message, wrapped to prevent crashes"""
    try:
        if channel.is_open:
            logger.warning(f"Nacking message {delivery_tag}")
            channel.basic_nack(delivery_tag=delivery_tag, requeue=False)
        else:
            logger.error("Channel closed, cannot nack message.")
    except Exception as e:
        logger.error(f"Failed to NACK message {delivery_tag} due to connection error: {e}")

def run_simulation_task(job_id, config_payload, output_file_path, delivery_tag, connection, channel):
    """
    Core function executed inside the ThreadPool.
    """
    # --- IDEMPOTENCY GUARD ---
    # If this job_id is already being processed (duplicate RabbitMQ delivery caused by
    # consumer_timeout or reconnect), ACK the duplicate message and bail out immediately.
    with _running_jobs_lock:
        if job_id in _running_jobs:
            logger.warning(f"[Job {job_id}] Duplicate delivery detected — already in progress. ACKing and discarding.")
            connection.add_callback_threadsafe(functools.partial(ack_message, channel, delivery_tag))
            return
        _running_jobs.add(job_id)

    job_work_dir = Path(settings.work_dir_base) / f"job_{job_id}"
    is_success = False

    try:
        logger.info(f"--- [Job {job_id}] EXECUTION STARTED ---")
        update_simulation_status(job_id, "RUNNING")

        if job_work_dir.exists(): shutil.rmtree(job_work_dir)
        job_work_dir.mkdir(parents=True, exist_ok=True)

        preprocessing_out_dir = job_work_dir / "preprocessing_output"
        solver_output_file = job_work_dir / "simulation_result.json"

        # --- PHASE 0: Fetch Required Models ---
        logger.info(f"[Job {job_id}] Phase 0: Fetching reference models")
        required_models = config_payload.get("models", [])
        if not required_models:
            raise ValueError("No models provided in the simulation configuration.")

        download_required_models(
            model_ids=required_models,
            models_dir=settings.agora_models_dir,
            base_url=settings.agora_vmh_base_url
        )

        # --- ADAPTER ---
        logger.info(f"[Job {job_id}] Phase 1: Adapter")
        adapter = InputAdapter(job_work_dir)
        input_files = adapter.generate_all_inputs(config_payload)

        # --- PREPROCESSING ---
        logger.info(f"[Job {job_id}] Phase 2: Preprocessing")
        pipeline_cfg = PreprocessingConfig(
            models_list=input_files["models_list"],
            models_dir=settings.agora_models_dir,
            output=str(preprocessing_out_dir),
            diet=input_files["diet"],
            final_report_path=str(solver_output_file),
            timing=True,
            gr_opt_frac=float(input_files.get("gr_opt_frac", 0.99)),
            solver=input_files.get("solver", "highs"),
            scfa_file=input_files.get("scfa_file"),
            abundance_file=input_files.get("abundance_file"),
            compute_reference=True,
            per_org=True,
            community_data=True
        )

        is_preproc_success = run_preprocessing_pipeline(pipeline_cfg)

        # --- SOLVER  ---
        if not is_preproc_success:
            logger.warning(f"[Job {job_id}] Preprocessing reported FAILURE/INFEASIBLE. Skipping C++ Solver.")
            raise RuntimeError("Preprocessing returned infeasible or failed.")
        else:
            logger.info(f"[Job {job_id}] Phase 3: C++ Solver Execution")
            runner = SolverRunner(binary_path=settings.solver_binary_path)
            runner.run_solver(
                input_dir=preprocessing_out_dir,
                output_file=solver_output_file,
                config=input_files
            )

        # --- UPLOAD ---
        if solver_output_file.exists():
            logger.info(f"[Job {job_id}] Result generated. Uploading to {output_file_path}...")
            minio_object_path = output_file_path if output_file_path else f"simulations/{job_id}/result.json"
            storage_client.upload_file(str(solver_output_file), minio_object_path)

            update_simulation_status(job_id, "COMPLETED", result_path=minio_object_path)
            is_success = True

        else:
            raise FileNotFoundError(f"Simulation result file not found at {solver_output_file}")

    except Exception as e:
        logger.exception(f"[Job {job_id}] CRITICAL FAILURE: {e}")
        try:
            update_simulation_status(job_id, "FAILED", error_message=str(e))
        except Exception as update_err:
            logger.error(f"[Job {job_id}] Could not send FAILED status to backend: {update_err}")

    finally:
        # Release the deduplication slot so a legitimate retry (e.g. after FAILED)
        # can be accepted in the future.
        with _running_jobs_lock:
            _running_jobs.discard(job_id)

        # --- CLEANUP ---
        if job_work_dir.exists():
            try:
                shutil.rmtree(job_work_dir)
                logger.info(f"[Job {job_id}] Cleanup: Removed temp dir")
            except Exception as e:
                logger.warning(f"[Job {job_id}] Cleanup warning: {e}")

        try:
            if is_success:
                cb = functools.partial(ack_message, channel, delivery_tag)
            else:
                cb = functools.partial(nack_message, channel, delivery_tag)

            if connection.is_open:
                connection.add_callback_threadsafe(cb)
            else:
                # Connection died while the task was running (e.g. reconnect happened).
                # The message has already been requeued by RabbitMQ; the idempotency
                # guard will reject the duplicate delivery on the new connection.
                logger.warning(f"[Job {job_id}] Cannot schedule ACK/NACK: connection is dead. Status is securely stored in DB.")
        except Exception as queue_err:
            logger.error(f"[Job {job_id}] Unexpected error scheduling callback: {queue_err}")

        logger.info(f"[Job {job_id}] Execution finished.")

def start_worker():
    """
    Initializes the RabbitMQ connection and starts the consumer loop.
    """
    while True:
        try:
            logger.info(f"Connecting to RabbitMQ at {settings.rabbit_host}...")

            conn_params = pika.ConnectionParameters(
                host=settings.rabbit_host,
                heartbeat=HEARTBEAT_INTERVAL,
                blocked_connection_timeout=3600  # 1 hour: survive long simulations under RabbitMQ load
            )

            connection = pika.BlockingConnection(conn_params)
            channel = connection.channel()

            channel.exchange_declare(exchange=settings.exchange, exchange_type='direct', durable=True)
            channel.queue_declare(queue=settings.queue, durable=True)
            channel.queue_bind(exchange=settings.exchange, queue=settings.queue, routing_key=settings.routing_key)

            channel.basic_qos(prefetch_count=PREFETCH_COUNT)

            logger.info("[*] Worker Ready (ThreadPool Mode). Waiting for jobs...")

            def callback(ch, method, properties, body):
                msg = json.loads(body)
                job_id = msg.get("jobId")
                config_payload = msg.get("configuration", {})
                output_file_path = msg.get("outputFilePath")

                logger.info(f"Received Job {job_id}. Dispatching to ThreadPool...")
                executor.submit(
                    run_simulation_task,
                    job_id,
                    config_payload,
                    output_file_path,
                    method.delivery_tag,
                    connection,
                    ch
                )

            channel.basic_consume(queue=settings.queue, on_message_callback=callback)
            channel.start_consuming()

        except KeyboardInterrupt:
            logger.info("Stopping worker manually...")
            if 'channel' in locals():
                channel.stop_consuming()
            executor.shutdown(wait=True)
            if 'connection' in locals():
                connection.close()
            break
        except Exception as e:
            logger.error(f"Connection lost: {e}. Retrying in 5s...")
            try:
                if 'connection' in locals() and connection.is_open:
                    connection.close()
            except:
                pass
            time.sleep(5)

if __name__ == "__main__":
    check_and_download_models()
    start_worker()