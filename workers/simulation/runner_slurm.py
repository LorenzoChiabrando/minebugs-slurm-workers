#!/usr/bin/env python3
"""
CLI entry point for the simulation SLURM job.

The Dispatcher writes the full RabbitMQ message as config.json to the NFS job
directory before calling sbatch. This script reads that file and runs the
complete simulation pipeline synchronously:

  Phase 0 — Download any AGORA models missing from the NFS cache.
  Phase 1 — Translate the JSON configuration into physical input files.
  Phase 2 — Run the Python preprocessing pipeline (community model + FBA).
  Phase 3 — Run the C++ HiGHS MILP solver.
  Phase 4 — Upload the result JSON to RustFS (S3).
  Phase 5 — Report the final status to the backend via HTTP PATCH.

Usage (invoked from run_simulation.sh):
    python3 runner_slurm.py \
        --job-id      "${JOB_UUID}" \
        --config-file "${CONFIG_FILE}"
"""

import sys
import json
import shutil
import argparse
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Simulation — SLURM CLI entry point")
    p.add_argument("--job-id",      required=True, help="Simulation UUID (simulationId from the Dispatcher message)")
    p.add_argument("--config-file", required=True, help="Path to config.json written by the Dispatcher")
    return p.parse_args()


def _download_models(model_ids: list, models_dir: Path, vmh_base_url: str) -> None:
    """Download AGORA models absent from the NFS cache.

    Writes to a hidden temporary file first, then renames atomically so that
    concurrent SLURM jobs downloading the same model do not corrupt each other's
    writes. If the final file is already present when the rename is attempted,
    the temporary file is discarded silently.
    """
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    missing = [m for m in model_ids if not (models_dir / f"{m}.mat").exists()]
    if not missing:
        logger.info("All %d model(s) found in NFS cache: %s", len(model_ids), models_dir)
        return

    logger.info("Downloading %d missing model(s) from VMH", len(missing))
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=Retry(
        total=5, backoff_factor=2, status_forcelist=[500, 502, 503, 504],
    )))

    for model_id in missing:
        dest = models_dir / f"{model_id}.mat"
        if dest.exists():
            continue  # concurrently downloaded by another job
        tmp = models_dir / f".{model_id}.mat.tmp.{logger.handlers[0].stream.fileno()}"
        url = f"{vmh_base_url}{model_id}.mat"
        logger.info("  Fetching: %s", url)
        try:
            resp = session.get(url, timeout=120)
            resp.raise_for_status()
            tmp.write_bytes(resp.content)
            tmp.rename(dest)
            logger.info("  Cached:   %s", dest)
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"Failed to download model '{model_id}': {exc}") from exc


if __name__ == "__main__":
    args = parse_args()

    config_path = Path(args.config_file)
    if not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        sys.exit(1)

    message       = json.loads(config_path.read_text())
    job_id        = message.get("simulationId", args.job_id)
    user_id       = message.get("userId", "unknown")
    configuration = message.get("configuration", {})

    logger.info("=" * 60)
    logger.info("Simulation SLURM Runner")
    logger.info("  Job ID   : %s", job_id)
    logger.info("  User     : %s", user_id)
    logger.info("  Config   : %s", config_path)
    logger.info("=" * 60)

    # Deferred imports: env vars from secrets.env are already in the process
    # environment at this point (sourced by run_simulation.sh before exec).
    from preprocessing.config import settings
    from preprocessing.infrastructure import backend_client
    from preprocessing.infrastructure.input_adapter import InputAdapter
    from preprocessing.infrastructure.minio_storage import MinioStorage
    from preprocessing.pipeline.main import run_preprocessing_pipeline, PreprocessingConfig
    from solver.runner import SolverRunner

    output_key = f"users/{user_id}/simulations/{job_id}.json"

    try:
        backend_client.update_simulation_status(job_id, "PROCESSING")
    except Exception as exc:
        logger.warning("Could not set PROCESSING status: %s", exc)

    job_work_dir = Path(settings.work_dir_base) / f"sim_{job_id}"
    job_work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ── Phase 0: Download missing AGORA models ─────────────────────────
        logger.info("Phase 0: Checking AGORA model cache")
        models_dir = Path(settings.agora_models_dir)
        models_dir.mkdir(parents=True, exist_ok=True)

        model_ids = configuration.get("models", [])
        if not model_ids:
            raise ValueError("Configuration contains no models — nothing to simulate.")

        _download_models(model_ids, models_dir, settings.agora_vmh_base_url)

        # ── Phase 1: Translate JSON configuration → input files ────────────
        logger.info("Phase 1: Generating input files from configuration")
        adapter        = InputAdapter(job_work_dir)
        adapter_result = adapter.generate_all_inputs(configuration)

        preprocessing_output_dir = job_work_dir / "preprocessing_output"
        result_file              = job_work_dir / "simulation_result.json"

        prep_cfg = PreprocessingConfig(
            models_list=adapter_result["models_list"],
            models_dir=str(models_dir),
            output=str(preprocessing_output_dir),
            diet=adapter_result["diet"],
            abundance_file=adapter_result.get("abundance_file"),
            per_org=adapter_result.get("per_org", True),
            community_data=adapter_result.get("community_data", True),
            compute_reference=adapter_result.get("compute_reference", True),
            solver=adapter_result.get("solver", "highs"),
            gr_opt_frac=adapter_result.get("gr_opt_frac", 0.99),
            scfa_file=adapter_result.get("scfa_file"),
            final_report_path=str(result_file),
        )

        # ── Phase 2: Python preprocessing pipeline ─────────────────────────
        logger.info("Phase 2: Running preprocessing pipeline")
        success = run_preprocessing_pipeline(prep_cfg)
        if not success:
            raise RuntimeError(
                "Preprocessing pipeline failed — check the failure report at "
                f"{result_file} for details."
            )

        # ── Phase 3: C++ HiGHS MILP solver ────────────────────────────────
        logger.info("Phase 3: Running C++ MILP solver")
        solver = SolverRunner(binary_path=settings.solver_binary_path)
        solver_config = {
            "min_community_growth": adapter_result.get("min_community_growth", 0.8),
            "production_floor":     adapter_result.get("production_floor",     0.8),
            "time_limit":           adapter_result.get("time_limit",           3600),
            "min_species":          adapter_result.get("min_species",          1),
        }
        solver.run_solver(
            input_dir=preprocessing_output_dir,
            output_file=result_file,
            config=solver_config,
        )

        # ── Phase 4: Upload result to RustFS ───────────────────────────────
        logger.info("Phase 4: Uploading result — S3 key: %s", output_key)
        storage = MinioStorage()
        storage.upload_file(str(result_file), output_key)

        # ── Phase 5: Notify backend ────────────────────────────────────────
        logger.info("Phase 5: Notifying backend — COMPLETED")
        backend_client.update_simulation_status(job_id, "COMPLETED", result_path=output_key)

        logger.info("Pipeline completed successfully — job %s", job_id)
        sys.exit(0)

    except Exception as exc:
        logger.exception("Pipeline failed for job %s: %s", job_id, exc)
        try:
            backend_client.update_simulation_status(job_id, "ERROR", error_message=str(exc))
        except Exception as update_exc:
            logger.error("Critical: could not report ERROR status to backend: %s", update_exc)
        sys.exit(1)

    finally:
        if job_work_dir.exists():
            try:
                shutil.rmtree(job_work_dir)
                logger.info("Cleaned up work directory: %s", job_work_dir)
            except OSError as exc:
                logger.warning("Could not remove work directory %s: %s", job_work_dir, exc)
