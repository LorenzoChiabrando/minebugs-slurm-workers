#!/bin/bash

export RABBITMQ_HOST="localhost"
export RABBITMQ_EXCHANGE="minebugs_exchange"
export RABBITMQ_QUEUE_MAPPING="queue_taxa_mapping"
export RABBITMQ_ROUTING_MAPPING="key_taxa_mapping"

export APP_WORKER_TOKEN="dev-only-change-me"
export BACKEND_BASE_URL="http://localhost:8080"

export AGORA_MODELS_PATH="./data/mat_files_list.csv"
export NCBI_CACHE_PATH="./data/ncbi_cache.json"

export MINIO_ENDPOINT="localhost:9000"
export MINIO_ACCESS_KEY="rustfsadmin"
export MINIO_SECRET_KEY="rustfsadmin"
export MINIO_BUCKET="minebugs-data"
export MINIO_SECURE="False"

echo " Worker Start ... "
python3 worker.py