import os
import logging
from minio import Minio
from minio.error import S3Error
from ..config import settings

logger = logging.getLogger(__name__)

class MinioStorage:
    def __init__(self):
        try:
            self.client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure
            )
            self.bucket = settings.minio_bucket
            self._ensure_bucket(self.bucket)
        except Exception as e:
            logger.critical(f"Failed to connect to MinIO: {e}")
            raise e

    def _ensure_bucket(self, bucket_name):
        if not self.client.bucket_exists(bucket_name):
            try:
                self.client.make_bucket(bucket_name)
                logger.info(f"Created bucket: {bucket_name}")
            except Exception as e:
                logger.error(f"Bucket creation failed: {e}")

    def upload_file(self, local_path: str, object_name: str) -> None:
        try:
            logger.info(f"Uploading {local_path} -> {object_name}")
            self.client.fput_object(self.bucket, object_name, local_path)
        except S3Error as e:
            logger.error(f"MinIO Upload Error: {e}")
            raise RuntimeError(f"Could not upload result to MinIO")

    def download_reference_data(self, object_name: str, local_dest_path: str) -> None:
        bucket_ref = settings.minio_bucket_ref
        try:
            logger.info(f"Downloading reference data '{object_name}' from bucket '{bucket_ref}'...")

            if not self.client.bucket_exists(bucket_ref):
                raise RuntimeError(f"Reference bucket '{bucket_ref}' does not exist inside MinIO.")

            self.client.fget_object(bucket_ref, object_name, local_dest_path)
            logger.info(f"Download completed: {local_dest_path}")

        except S3Error as e:
            logger.critical(f"Failed to download reference data: {e}")
            raise e

storage_client = MinioStorage()