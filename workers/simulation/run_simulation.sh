#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  run_simulation.sh — SLURM job script for the MINeBUGS simulation pipeline
#
#  The Dispatcher calls:
#    sbatch run_simulation.sh <job-uuid> <config-file>
#  where <config-file> is the absolute NFS path to the config.json file written
#  by the Dispatcher before submitting this job. The script passes that path
#  directly to runner_slurm.py without re-parsing the JSON.
#
#  Production copy: /data/minebugs/shared/scripts/run_simulation.sh
# ─────────────────────────────────────────────────────────────────────────────

#SBATCH --job-name=sim
#SBATCH --partition=simulation
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=2000M
#SBATCH --time=08:00:00
#SBATCH --output=/data/minebugs/logs/sim_%j.out
#SBATCH --error=/data/minebugs/logs/sim_%j.err

set -euo pipefail

SECRETS_FILE="/data/minebugs/shared/secrets.env"
[[ -f "$SECRETS_FILE" ]] || { echo "[FATAL] secrets.env not found: ${SECRETS_FILE}" >&2; exit 1; }
set -a          # export every variable defined from here
source "${SECRETS_FILE}"
set +a

JOB_UUID="${1:-}"
CONFIG_FILE="${2:-}"

if [[ -z "$JOB_UUID" || -z "$CONFIG_FILE" ]]; then
    echo "[FATAL] Usage: sbatch $0 <job-uuid> <config-file>" >&2
    exit 1
fi

[[ -f "$CONFIG_FILE" ]] || { echo "[FATAL] Config file not found: ${CONFIG_FILE}" >&2; exit 1; }

echo "════════════════════════════════════════════════════════════"
echo " Simulation Job — MINeBUGS"
echo " UUID:   ${JOB_UUID}  |  SLURM: ${SLURM_JOB_ID}  |  CPUs: ${SLURM_CPUS_PER_TASK}"
echo " Config: ${CONFIG_FILE}"
echo " Start:  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "════════════════════════════════════════════════════════════"

JOB_DIR="/data/minebugs/jobs/${JOB_UUID}"
mkdir -p "${JOB_DIR}"
echo "${SLURM_JOB_ID}" > "${JOB_DIR}/slurm_id.txt"
echo "RUNNING"           > "${JOB_DIR}/status.txt"

VENV_PATH="/data/minebugs/shared/venvs/venv_simulation"
[[ -f "${VENV_PATH}/bin/activate" ]] || {
    echo "[FATAL] venv not found: ${VENV_PATH}" >&2
    echo "Run: python3 -m venv ${VENV_PATH} && pip install -r requirements.txt" >&2
    exit 1
}
source "${VENV_PATH}/bin/activate"

WORKERS_DIR="/data/minebugs/shared/workers/simulation"
[[ -d "$WORKERS_DIR" ]] || { echo "[FATAL] Worker sources not found: ${WORKERS_DIR}" >&2; exit 1; }
export PYTHONPATH="${WORKERS_DIR}:${PYTHONPATH:-}"

# Make libhighs.so visible to the dynamic linker when the C++ solver runs.
export LD_LIBRARY_PATH="/data/minebugs/shared/solver/lib:${LD_LIBRARY_PATH:-}"

# Allow secrets.env to override the solver binary path; otherwise use the
# standard NFS location where build_pipeline.sh places the compiled binary.
export SOLVER_BINARY_PATH="${SOLVER_BINARY_PATH:-/data/minebugs/shared/solver/solver_cpp}"

# Cap all threading libraries to the CPUs allocated by SLURM.
# HiGHS (OpenMP), NumPy/SciPy (OpenBLAS/MKL), and joblib all respect these.
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export OPENBLAS_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export LOKY_MAX_CPU_COUNT="${SLURM_CPUS_PER_TASK}"

# Temporarily disable set -e so that a non-zero Python exit code does not
# terminate the shell before we can capture it and update status.txt.
set +e
python3 "${WORKERS_DIR}/runner_slurm.py" \
    --job-id      "${JOB_UUID}" \
    --config-file "${CONFIG_FILE}"
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
