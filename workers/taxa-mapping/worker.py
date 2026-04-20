import sys
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

sys.path.append(os.getcwd())

try:
    from taxa_mapping.config import settings
    from taxa_mapping.infrastructure.rabbit_listener import start_listening

except ImportError as e:
    logger.critical(f"Import modules error: {e}")
    sys.exit(1)

if __name__ == "__main__":
    logger.info("--- Starting Taxa Mapping Worker ---")
    logger.info(f"Environment: RabbitMQ at {settings.rabbit_host}")
    logger.info(f"Storage: MinIO Bucket '{settings.minio_bucket}' at {settings.minio_endpoint}")

    try:
        start_listening()

    except KeyboardInterrupt:
        logger.info("Worker stopped manually.")
    except Exception as e:
        logger.critical(f"Worker crashed unexpectadly: {e}")
        sys.exit(1)