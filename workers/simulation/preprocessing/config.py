from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    # --- Backend / Security ---
    worker_token: str = Field(default="",              alias="APP_WORKER_TOKEN")
    backend_url:  str = Field(default="",              alias="BACKEND_BASE_URL")

    # --- MinIO / RustFS ---
    minio_endpoint:   str  = Field(default="",              alias="MINIO_ENDPOINT")
    minio_access_key: str  = Field(default="minio_admin",   alias="MINIO_ACCESS_KEY")
    minio_secret_key: str  = Field(default="minio_secret",  alias="MINIO_SECRET_KEY")
    minio_bucket:     str  = Field(default="minebugs-data", alias="MINIO_BUCKET")
    minio_secure:     bool = Field(default=False,           alias="MINIO_SECURE")

    minio_bucket_ref: str = Field(default="reference-data", alias="MINIO_BUCKET_REF")
    agora_zip_key:    str = Field(default="agora2_seed.zip", alias="AGORA_ZIP_KEY")

    # --- Paths (all default to the NFS shared structure) ---
    work_dir_base:      str = Field(
        default="/tmp/minebugs_sim",
        alias="WORK_DIR_BASE",
    )
    agora_models_dir:   str = Field(
        default="/data/minebugs/shared/ref_data/agora",
        alias="AGORA_MODELS_DIR",
    )
    solver_binary_path: str = Field(
        default="/data/minebugs/shared/solver/solver_cpp",
        alias="SOLVER_BINARY_PATH",
    )

    # --- AGORA VMH download base URL ---
    agora_vmh_base_url: str = Field(
        default="https://vmh.life/files/reconstructions/AGORA2/version2.01/mat_files/individual_reconstructions/",
        alias="AGORA_VMH_BASE_URL",
    )

    class Config:
        env_file = None


settings = Settings()
