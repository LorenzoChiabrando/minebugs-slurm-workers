#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  run_mapping.sh — SLURM job script for the MINeBUGS taxa-mapping pipeline
#
#  Local mode (no Docker):
#    sbatch run_mapping.sh test-001 \
#      /data/minebugs/jobs/test-001/taxa.csv \
#      /data/minebugs/jobs/test-001/result.json
#
#  S3 mode (RustFS):
#    sbatch run_mapping.sh job-001 \
#      inputs/job-001/taxa.csv \
#      outputs/job-001/result.json
#
#  Production copy: /data/minebugs/shared/scripts/run_mapping.sh
# ─────────────────────────────────────────────────────────────────────────────

#SBATCH --job-name=taxa_map
#SBATCH --partition=mapping
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=6G
#SBATCH --time=01:00:00
#SBATCH --output=/data/minebugs/logs/map_%j.out
#SBATCH --error=/data/minebugs/logs/map_%j.err

set -euo pipefail

SECRETS_FILE="/data/minebugs/shared/secrets.env"
[[ -f "$SECRETS_FILE" ]] || { echo "[FATAL] secrets.env not found: ${SECRETS_FILE}" >&2; exit 1; }
set -a          # auto-export all variables defined from here
source "${SECRETS_FILE}"
set +a          # restore default (no auto-export)

JOB_UUID="${1:-}"
INPUT_KEY="${2:-}"
OUTPUT_KEY="${3:-}"

if [[ -z "$JOB_UUID" || -z "$INPUT_KEY" || -z "$OUTPUT_KEY" ]]; then
    echo "[FATAL] Usage: sbatch $0 <job-uuid> <input> <output>" >&2
    exit 1
fi

echo "════════════════════════════════════════════════════════════"
echo " Taxa Mapping Job — MINeBUGS"
echo " UUID: ${JOB_UUID}  |  SLURM: ${SLURM_JOB_ID}  |  CPUs: ${SLURM_CPUS_PER_TASK}"
echo " Input:  ${INPUT_KEY}"
echo " Output: ${OUTPUT_KEY}"
echo " Start:  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "════════════════════════════════════════════════════════════"

# Track job state in a directory accessible from the local machine
JOB_DIR="/data/minebugs/jobs/${JOB_UUID}"
mkdir -p "${JOB_DIR}"
echo "${SLURM_JOB_ID}" > "${JOB_DIR}/slurm_id.txt"
echo "RUNNING"         > "${JOB_DIR}/status.txt"

VENV_PATH="/data/minebugs/shared/venvs/venv_mapping"
[[ -f "${VENV_PATH}/bin/activate" ]] || {
    echo "[FATAL] venv not found: ${VENV_PATH}" >&2
    echo "Run: python3 -m venv ${VENV_PATH} && pip install -r requirements.txt" >&2
    exit 1
}
source "${VENV_PATH}/bin/activate"

WORKERS_DIR="/data/minebugs/shared/workers/taxa-mapping"
[[ -d "$WORKERS_DIR" ]] || { echo "[FATAL] Worker sources not found: ${WORKERS_DIR}" >&2; exit 1; }
export PYTHONPATH="${WORKERS_DIR}:${PYTHONPATH:-}"

# Temporarily disable set -e so that a non-zero Python exit code does not
# terminate the shell before we can capture it and update status.txt.
set +e
python3 "${WORKERS_DIR}/runner_slurm.py" \
    --job-id     "${JOB_UUID}" \
    --input-key  "${INPUT_KEY}" \
    --output-key "${OUTPUT_KEY}"
PYTHON_EXIT=$?
set -e

if [[ $PYTHON_EXIT -eq 0 ]]; then
    echo "COMPLETED" > "${JOB_DIR}/status.txt"
    echo " Job ${JOB_UUID} completed — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
else
    echo "FAILED" > "${JOB_DIR}/status.txt"
    echo "[FATAL] Job ${JOB_UUID} failed (exit: ${PYTHON_EXIT})" >&2
    exit ${PYTHON_EXIT}
fi
