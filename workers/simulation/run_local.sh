#!/bin/bash

# --- 1. RabbitMQ Configuration  ---
export RABBITMQ_HOST="localhost"
export RABBITMQ_EXCHANGE="minebugs_exchange"
export RABBITMQ_QUEUE_SIMULATION="queue_simulation"
export RABBITMQ_ROUTING_SIMULATION="key_simulation"

# --- 2. Backend / Security ---
export APP_WORKER_TOKEN="dev-only-change-me"
export BACKEND_BASE_URL="http://localhost:8080"

# --- 3. MinIO Configuration ---
export MINIO_ENDPOINT="localhost:9000"
export MINIO_ACCESS_KEY="rustfsadmin"
export MINIO_SECRET_KEY="rustfsadmin"
export MINIO_BUCKET="minebugs-data"
export MINIO_SECURE="False"
export MINIO_BUCKET_REF="reference-data"
export AGORA_ZIP_KEY="agora2_seed.zip"


export WORK_DIR_BASE="/tmp/minebugs_debug_sim"

export AGORA_MODELS_PATH="/tmp/minebugs_models_cache/agora"

rm -rf "$AGORA_MODELS_PATH"


echo "------------------------------------------------"
echo " Simulation Worker - WARMUP TEST MODE"
echo " Models Path: $AGORA_MODELS_PATH (Should be empty initially)"
echo " Zip Source:  $MINIO_BUCKET_REF / $AGORA_ZIP_KEY"
echo "------------------------------------------------"

export SOLVER_BINARY_PATH="$(pwd)/solver/pipeline/build/solver_cpp"

echo "------------------------------------------------"
echo " Simulation Worker - WARMUP TEST MODE"
echo " Solver Binary: $SOLVER_BINARY_PATH"
echo "------------------------------------------------"

python3 worker.py