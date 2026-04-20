import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalStorage:
    """
    Local filesystem storage backend.
    Active when MINIO_ENDPOINT is not set.
    Input/output are absolute paths on the SLURM VM filesystem.
    """

    def download_file(self, object_name: str, local_path: str) -> None:
        logger.info(f"[LOCAL] {object_name} -> {local_path}")
        src = Path(object_name)
        if not src.exists():
            raise FileNotFoundError(f"Input file not found: {object_name}")
        shutil.copy2(str(src), local_path)

    def upload_file(self, local_path: str, object_name: str) -> None:
        logger.info(f"[LOCAL] {local_path} -> {object_name}")
        dst = Path(object_name)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, str(dst))


class MinioStorage:
    """
    S3-compatible storage backend (MinIO / RustFS).
    Active when MINIO_ENDPOINT is set.
    Input/output are object keys within the configured bucket.
    """

    def __init__(self):
        from minio import Minio
        from ..config import settings
        try:
            self.client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure
            )
            self.bucket = settings.minio_bucket
            self._ensure_bucket()
            logger.info(f"[S3] Connected to {settings.minio_endpoint}, bucket: {self.bucket}")
        except Exception as e:
            logger.critical(f"MinIO/RustFS connection failed: {e}")
            raise e

    def _ensure_bucket(self):
        if not self.client.bucket_exists(self.bucket):
            logger.info(f"Bucket {self.bucket} not found, creating...")
            self.client.make_bucket(self.bucket)

    def download_file(self, object_name: str, local_path: str) -> None:
        from minio.error import S3Error
        try:
            logger.info(f"[S3] Download {object_name} -> {local_path}")
            self.client.fget_object(self.bucket, object_name, local_path)
        except S3Error as e:
            logger.error(f"S3 Download error: {e}")
            raise FileNotFoundError(f"Could not download {object_name} from bucket {self.bucket}")

    def upload_file(self, local_path: str, object_name: str) -> None:
        from minio.error import S3Error
        try:
            logger.info(f"[S3] Upload {local_path} -> {object_name}")
            self.client.fput_object(self.bucket, object_name, local_path)
        except S3Error as e:
            logger.error(f"S3 Upload error: {e}")
            raise RuntimeError(f"Could not upload {object_name} to bucket {self.bucket}")


def _make_storage_client():
    from ..config import settings
    if settings.minio_endpoint:
        return MinioStorage()
    else:
        logger.info("[STORAGE] MINIO_ENDPOINT not set — using local filesystem mode")
        return LocalStorage()


storage_client = _make_storage_client()
