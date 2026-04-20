from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    worker_token: str = Field(default="", alias="APP_WORKER_TOKEN")
    backend_url:  str = Field(default="", alias="BACKEND_BASE_URL")
    minio_endpoint:   str  = Field(default="",              alias="MINIO_ENDPOINT")
    minio_access_key: str  = Field(default="minio_admin",   alias="MINIO_ACCESS_KEY")
    minio_secret_key: str  = Field(default="minio_secret",  alias="MINIO_SECRET_KEY")
    minio_bucket:     str  = Field(default="minebugs-data", alias="MINIO_BUCKET")
    minio_secure:     bool = Field(default=False,           alias="MINIO_SECURE")
    agora_models_path: str = Field(default="/data/minebugs/shared/ref_data/mat_files_list.csv",
                                   alias="AGORA_MODELS_PATH")
    ncbi_cache_path:   str = Field(default="/data/minebugs/shared/ref_data/ncbi_cache.json",
                                   alias="NCBI_CACHE_PATH")

    class Config:
        env_file = None

settings = Settings()