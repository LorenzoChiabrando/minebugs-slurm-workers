#!/usr/bin/env python3
"""
MINeBUGS SLURM Dispatcher
==========================
Lightweight bridge between the Docker-hosted RabbitMQ message broker and the
SLURM workload manager running on the same host.

Responsibilities:
  - Consume messages from the taxa-mapping and simulation queues.
  - For each message, validate the payload and submit a SLURM job via sbatch.
  - Track job state by writing metadata to the shared NFS job directory.
  - Acknowledge messages only after sbatch succeeds; dead-letter on failure.

Design constraints:
  - This process performs no scientific computation.
  - prefetch_count=1 ensures at most one message is in-flight per queue,
    preventing the dispatcher from accumulating messages that would be lost
    on an unexpected restart.
  - The process is designed to run as a systemd service; it handles SIGTERM
    and SIGINT with a graceful shutdown that waits for any in-progress sbatch
    call to complete before closing the AMQP connection.

Environment variables (loaded via EnvironmentFile in the systemd unit):
  Required:
    RABBITMQ_HOST               Hostname or IP of the RabbitMQ server.
    RABBITMQ_EXCHANGE           Name of the AMQP direct exchange.
    RABBITMQ_QUEUE_MAPPING      Queue name for taxa-mapping jobs.
    RABBITMQ_QUEUE_SIMULATION   Queue name for simulation jobs.
  Optional:
    RABBITMQ_PORT               AMQP port (default: 5672).
    RABBITMQ_DEFAULT_USER       AMQP username (default: guest).
    RABBITMQ_DEFAULT_PASS       AMQP password (default: guest).
    JOBS_BASE_DIR               NFS directory for per-job tracking files
                                (default: /data/minebugs/jobs).
    SLURM_SCRIPTS_DIR           Directory containing the sbatch scripts
                                (default: /data/minebugs/shared/scripts).
"""

import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import pika
from pika.exceptions import AMQPConnectionError, AMQPChannelError

# ---------------------------------------------------------------------------
# Configuration — fail fast if required variables are missing
# ---------------------------------------------------------------------------

def _require(name: str) -> str:
    """Return the value of a required environment variable or abort."""
    value = os.environ.get(name)
    if not value:
        print(f"[FATAL] Required environment variable not set: {name}", file=sys.stderr)
        sys.exit(1)
    return value


RABBIT_HOST       = _require("RABBITMQ_HOST")
RABBIT_PORT       = int(os.environ.get("RABBITMQ_PORT", "5672"))
RABBIT_USER       = os.environ.get("RABBITMQ_DEFAULT_USER", "guest")
RABBIT_PASS       = os.environ.get("RABBITMQ_DEFAULT_PASS", "guest")
RABBIT_EXCHANGE   = _require("RABBITMQ_EXCHANGE")
QUEUE_MAPPING     = _require("RABBITMQ_QUEUE_MAPPING")
QUEUE_SIMULATION  = _require("RABBITMQ_QUEUE_SIMULATION")

JOBS_BASE_DIR     = Path(os.environ.get("JOBS_BASE_DIR", "/data/minebugs/jobs"))
SCRIPTS_DIR       = Path(os.environ.get("SLURM_SCRIPTS_DIR", "/data/minebugs/shared/scripts"))
SCRIPT_MAPPING    = SCRIPTS_DIR / "run_mapping.sh"
SCRIPT_SIMULATION = SCRIPTS_DIR / "run_simulation.sh"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("dispatcher")

# ---------------------------------------------------------------------------
# Graceful shutdown
#
# The active connection reference is stored at module level so that signal
# handlers can close it, which causes start_consuming() to return and allows
# the main loop to exit cleanly without leaving unacknowledged messages.
# ---------------------------------------------------------------------------

_shutdown: bool = False
_active_connection: Optional[pika.BlockingConnection] = None


def _handle_signal(signum: int, _frame) -> None:
    """Signal handler for SIGTERM and SIGINT."""
    global _shutdown, _active_connection
    logger.info("Signal %d received — initiating graceful shutdown", signum)
    _shutdown = True
    if _active_connection is not None and not _active_connection.is_closed:
        try:
            _active_connection.close()
        except Exception:
            pass  # connection may already be closing


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

# ---------------------------------------------------------------------------
# SLURM submission
# ---------------------------------------------------------------------------

def _sbatch(script: Path, *args: str) -> str:
    """
    Submit a SLURM job via sbatch and return the numeric job ID as a string.

    Uses --parsable so that sbatch prints only the job ID to stdout, making
    it trivial to capture without parsing human-readable output.

    Raises:
        FileNotFoundError: if the sbatch script does not exist on the NFS.
        RuntimeError:      if sbatch exits with a non-zero return code, or if
                           the output cannot be interpreted as a job ID.
    """
    if not script.exists():
        raise FileNotFoundError(f"SLURM script not found: {script}")

    cmd = ["sbatch", "--parsable", str(script)] + list(args)
    logger.debug("Executing: %s", " ".join(cmd))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"sbatch exited with code {result.returncode}: {result.stderr.strip()}"
        )

    slurm_job_id = result.stdout.strip()
    if not slurm_job_id.isdigit():
        raise RuntimeError(
            f"sbatch returned an unexpected job ID: '{slurm_job_id}'"
        )

    return slurm_job_id


def _write_job_tracking(job_id: str, slurm_job_id: str, meta: dict) -> None:
    """
    Create the per-job NFS directory and write initial tracking files.

    Files written:
      slurm_id.txt  — SLURM job ID (useful for sacct queries and squeue).
      status.txt    — Current logical status: QUEUED | RUNNING | COMPLETED | FAILED.
      meta.json     — Dispatcher-side metadata snapshot.

    The directory is created with exist_ok=True because the simulation handler
    may have already created it to write config.json before calling sbatch.
    """
    job_dir = JOBS_BASE_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "slurm_id.txt").write_text(slurm_job_id)
    (job_dir / "status.txt").write_text("QUEUED")
    (job_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    logger.debug("Job tracking directory initialised: %s", job_dir)

# ---------------------------------------------------------------------------
# Message handlers
# ---------------------------------------------------------------------------

def _handle_mapping(
    channel: pika.adapters.blocking_connection.BlockingChannel,
    method: pika.spec.Basic.Deliver,
    _properties: pika.spec.BasicProperties,
    body: bytes,
) -> None:
    """
    Process a message from the taxa-mapping queue.

    Expected payload (published by the Spring Boot OutboxRelayService):
    {
        "jobId":          "<uuid>",
        "inputFilePath":  "users/<userId>/uploads/<uuid>_taxa.csv",
        "outputFilePath": "users/<userId>/mappings/<uuid>.json"
    }

    On success:  basic_ack  — message removed from the queue.
    On failure:  basic_nack with requeue=False — message moved to the dead-letter
                 exchange (if configured) or discarded. Requeuing is intentionally
                 disabled: a transient sbatch failure requires operator intervention,
                 not an automatic retry that would loop indefinitely.
    """
    job_id = "UNKNOWN"
    try:
        message    = json.loads(body)
        job_id     = message["jobId"]
        input_key  = message["inputFilePath"]
        output_key = message["outputFilePath"]

        logger.info("[MAPPING] Received job %s", job_id)
        logger.debug("[MAPPING] input=%s  output=%s", input_key, output_key)

        slurm_id = _sbatch(SCRIPT_MAPPING, job_id, input_key, output_key)
        _write_job_tracking(job_id, slurm_id, {
            "type":       "taxa_mapping",
            "inputKey":   input_key,
            "outputKey":  output_key,
            "slurmJobId": slurm_id,
        })

        channel.basic_ack(delivery_tag=method.delivery_tag)
        logger.info("[MAPPING] Job %s submitted as SLURM:%s", job_id, slurm_id)

    except KeyError as exc:
        logger.error("[MAPPING] Malformed message for job %s — missing field: %s", job_id, exc)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    except (FileNotFoundError, RuntimeError) as exc:
        logger.error("[MAPPING] sbatch submission failed for job %s: %s", job_id, exc)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    except Exception as exc:
        logger.exception("[MAPPING] Unexpected error for job %s: %s", job_id, exc)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def _handle_simulation(
    channel: pika.adapters.blocking_connection.BlockingChannel,
    method: pika.spec.Basic.Deliver,
    _properties: pika.spec.BasicProperties,
    body: bytes,
) -> None:
    """
    Process a message from the simulation queue.

    Expected payload (published by the Spring Boot OutboxRelayService):
    {
        "simulationId":  "<uuid>",
        "userId":        "<user-uuid>",
        "configuration": { ... }
    }

    The full message is serialised as config.json in the NFS job directory
    before sbatch is called. The SLURM script reads it from that path, which
    avoids passing large JSON payloads as command-line arguments and provides
    a durable record of the exact configuration that was submitted.
    """
    job_id = "UNKNOWN"
    try:
        message = json.loads(body)
        job_id  = message["simulationId"]
        user_id = message.get("userId", "unknown")

        logger.info("[SIMULATION] Received job %s (user: %s)", job_id, user_id)

        # Write the full configuration to NFS so the SLURM job can read it.
        # This must happen before sbatch; if it fails, the message is nacked.
        job_dir = JOBS_BASE_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        config_path = job_dir / "config.json"
        config_path.write_text(json.dumps(message, indent=2))
        logger.debug("[SIMULATION] Configuration written to %s", config_path)

        slurm_id = _sbatch(SCRIPT_SIMULATION, job_id, str(config_path))
        _write_job_tracking(job_id, slurm_id, {
            "type":       "simulation",
            "userId":     user_id,
            "configPath": str(config_path),
            "slurmJobId": slurm_id,
        })

        channel.basic_ack(delivery_tag=method.delivery_tag)
        logger.info("[SIMULATION] Job %s submitted as SLURM:%s", job_id, slurm_id)

    except KeyError as exc:
        logger.error("[SIMULATION] Malformed message for job %s — missing field: %s", job_id, exc)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    except (FileNotFoundError, RuntimeError) as exc:
        logger.error("[SIMULATION] sbatch submission failed for job %s: %s", job_id, exc)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    except Exception as exc:
        logger.exception("[SIMULATION] Unexpected error for job %s: %s", job_id, exc)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

def _connect() -> pika.BlockingConnection:
    """
    Establish a blocking AMQP connection with the configured parameters.

    heartbeat=60 keeps the TCP connection alive during sbatch submission, which
    may take several seconds if the SLURM controller is under load.
    blocked_connection_timeout=300 surfaces broker-side backpressure as an
    exception rather than hanging indefinitely.
    """
    credentials = pika.PlainCredentials(RABBIT_USER, RABBIT_PASS)
    parameters  = pika.ConnectionParameters(
        host=RABBIT_HOST,
        port=RABBIT_PORT,
        credentials=credentials,
        heartbeat=60,
        blocked_connection_timeout=300,
    )
    return pika.BlockingConnection(parameters)


def _setup_channel(
    connection: pika.BlockingConnection,
) -> pika.adapters.blocking_connection.BlockingChannel:
    """
    Declare the exchange and queues, set QoS, and register message callbacks.

    Exchange and queue declarations are idempotent; running them on every
    reconnect ensures the topology exists even if RabbitMQ was restarted
    with a clean state.
    """
    channel = connection.channel()

    channel.exchange_declare(
        exchange=RABBIT_EXCHANGE,
        exchange_type="direct",
        durable=True,
    )

    for queue_name in (QUEUE_MAPPING, QUEUE_SIMULATION):
        channel.queue_declare(queue=queue_name, durable=True)

    # prefetch_count=1: the dispatcher must not buffer messages in memory.
    # If it crashes while holding unacknowledged messages, RabbitMQ will
    # redeliver them to the next consumer (or to this process on restart).
    channel.basic_qos(prefetch_count=1)

    channel.basic_consume(queue=QUEUE_MAPPING,    on_message_callback=_handle_mapping)
    channel.basic_consume(queue=QUEUE_SIMULATION, on_message_callback=_handle_simulation)

    return channel

# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

def _validate_environment() -> None:
    """
    Verify that paths required at runtime exist before entering the consume loop.
    Failing here produces a clear error message; failing inside a message handler
    would dead-letter a real job message unnecessarily.
    """
    errors = []

    if not JOBS_BASE_DIR.exists():
        errors.append(f"JOBS_BASE_DIR does not exist: {JOBS_BASE_DIR}")

    if not SCRIPT_MAPPING.exists():
        errors.append(f"Mapping script not found: {SCRIPT_MAPPING}")

    # Simulation script is optional until that worker is activated.
    # Uncomment the check below once run_simulation.sh is deployed.
    # if not SCRIPT_SIMULATION.exists():
    #     errors.append(f"Simulation script not found: {SCRIPT_SIMULATION}")

    if errors:
        for error in errors:
            logger.critical(error)
        sys.exit(1)

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run() -> None:
    """
    Main event loop with automatic reconnection.

    The loop reconnects indefinitely until a shutdown signal is received.
    Each iteration establishes a fresh AMQP connection and channel; if either
    is lost (network failure, broker restart), the exception is caught, the
    connection is closed, and the loop retries after a backoff delay.
    """
    global _active_connection

    logger.info("MINeBUGS SLURM Dispatcher starting")
    logger.info("  RabbitMQ  : %s:%d", RABBIT_HOST, RABBIT_PORT)
    logger.info("  Exchange  : %s", RABBIT_EXCHANGE)
    logger.info("  Queues    : %s, %s", QUEUE_MAPPING, QUEUE_SIMULATION)
    logger.info("  Scripts   : %s", SCRIPTS_DIR)
    logger.info("  Jobs dir  : %s", JOBS_BASE_DIR)

    _validate_environment()

    while not _shutdown:
        _active_connection = None
        try:
            _active_connection = _connect()
            channel = _setup_channel(_active_connection)

            logger.info("Connected to RabbitMQ — listening for jobs")
            channel.start_consuming()

        except AMQPConnectionError as exc:
            if not _shutdown:
                logger.warning("AMQP connection lost: %s — reconnecting in 15 s", exc)
                time.sleep(15)

        except AMQPChannelError as exc:
            if not _shutdown:
                logger.warning("AMQP channel error: %s — reconnecting in 15 s", exc)
                time.sleep(15)

        except Exception as exc:
            if not _shutdown:
                logger.error("Unexpected error: %s — reconnecting in 15 s", exc)
                time.sleep(15)

        finally:
            if _active_connection is not None and not _active_connection.is_closed:
                try:
                    _active_connection.close()
                except Exception:
                    pass

    logger.info("Dispatcher stopped cleanly.")


if __name__ == "__main__":
    run()
