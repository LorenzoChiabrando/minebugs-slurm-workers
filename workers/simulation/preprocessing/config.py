from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):

    # --- 1. RabbitMQ Configuration ---
    rabbit_host: str = Field(..., alias="RABBITMQ_HOST")
    exchange: str = Field(..., alias="RABBITMQ_EXCHANGE")
    queue: str = Field(..., alias="RABBITMQ_QUEUE_SIMULATION")
    routing_key: str = Field(..., alias="RABBITMQ_ROUTING_SIMULATION")

    # --- 2. Backend / Security ---
    worker_token: str = Field(..., alias="APP_WORKER_TOKEN")
    backend_url: str = Field(..., alias="BACKEND_BASE_URL")

    # --- 3. MinIO Configuration ---
    minio_endpoint: str = Field(..., alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(..., alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(..., alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(..., alias="MINIO_BUCKET")
    minio_secure: bool = Field(False, alias="MINIO_SECURE")

    minio_bucket_ref: str = Field("reference-data", alias="MINIO_BUCKET_REF")
    agora_zip_key: str = Field("agora2_seed.zip", alias="AGORA_ZIP_KEY")

    # --- 4. Paths  ---
    work_dir_base: str = Field(..., alias="WORK_DIR_BASE")

    agora_models_dir: str = Field(..., alias="AGORA_MODELS_PATH")


    # --- 5. SOLVER  CONFIG ---
    _default_solver_path = Path(__file__).resolve().parent.parent / "solver" / "pipeline" / "build" / "solver_cpp"
    solver_binary_path: str = Field(str(_default_solver_path), alias="SOLVER_BINARY_PATH")

    # --- 6. AGORA VMH Configuration ---
    agora_vmh_base_url: str = Field(
        "https://vmh.life/files/reconstructions/AGORA2/version2.01/mat_files/individual_reconstructions/",
        alias="AGORA_VMH_BASE_URL"
    )

    class Config:
        env_file = None

settings = Settings()