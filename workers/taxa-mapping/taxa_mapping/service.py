import logging
import pandas as pd
import shutil
from pathlib import Path
from typing import List, Dict, Any

from .config import settings
from .infrastructure.storage import storage_client
from .infrastructure import backend_client

from .core import cleaning
from .core import matching
from .core import filtering
from .core import rescue
from .core import assembly

logger = logging.getLogger(__name__)

def run_mapping_pipeline(job_id: str, s3_input_key: str, s3_output_key: str) -> None:

    logger.info(f"--- [Job {job_id}] Starting Cloud Pipeline ---")
    logger.info(f"Target S3 Input: {s3_input_key}")

    job_work_dir = Path(f"/tmp/minebugs_job_{job_id}")
    job_work_dir.mkdir(parents=True, exist_ok=True)

    local_input_path = job_work_dir / "input.csv"
    local_output_path = job_work_dir / f"mapping_result_{job_id}.json"

    try:
        backend_client.update_job(job_id, {"status": "PROCESSING"})
    except Exception as e:
        logger.error(f"Warning: Could not update status to PROCESSING: {e}")

    try:
        logger.info(f"Downloading from MinIO: {s3_input_key} -> {local_input_path}")
        storage_client.download_file(s3_input_key, str(local_input_path))

        if not local_input_path.exists():
            raise FileNotFoundError(f"Download failed. File not found at: {local_input_path}")

        logger.info(f"Reading CSV from: {local_input_path}")
        df = pd.read_csv(local_input_path)

        target_col = None
        possible_name_cols = ["taxa_name", "taxon", "name", "organism", "species"]
        for col in possible_name_cols:
            if col in df.columns:
                target_col = col
                break
        if not target_col:
            target_col = df.columns[0]
            logger.warning(f"No standard name header found. Using first column: '{target_col}'")

        abundance_col = None
        possible_abd_cols = ["abundance", "relative_abundance", "rel_abundance", "count", "value", "proportion"]
        for col in possible_abd_cols:
            if col in df.columns:
                abundance_col = col
                break

        raw_names = df[target_col].astype(str).tolist()

        abundance_map = {}
        if abundance_col:
            logger.info(f"Found abundance column: '{abundance_col}'")
            abundances = pd.to_numeric(df[abundance_col], errors='coerce').fillna(0.0).tolist()
            abundance_map = dict(zip(raw_names, abundances))
        else:
            logger.info("No abundance column found. Defaulting to None.")
            abundance_map = {name: None for name in raw_names}

        logger.info(f"Phase 1 Loaded: {len(raw_names)} taxa.")

        logger.info(f"Phase 1 Loaded: {len(raw_names)} taxa.")

        # Phase 2: Cleaning
        logger.info("Phase 2: Cleaning taxa names...")
        cleaned_names = cleaning.clean_taxa_names(raw_names)
        logger.info("Phase 2 Completed.")

        # Phase 3: Matching (Jaccard)
        logger.info(f"Phase 3: Running Complex Jaccard Matching...")

        jaccard_results: List[Dict[str, Any]] = matching.run_jaccard_matching(
            taxa_list=cleaned_names,
            raw_taxa_list=raw_names,
            models_csv_path=settings.agora_models_path,
            abundance_map=abundance_map,
            n_jobs=-2
        )
        logger.info(f"Phase 3 Completed.")

        # Phase 3.5: Filtering
        rescue_candidates = filtering.get_candidates_for_rescue(jaccard_results)
        logger.info(f"Phase 3.5: {len(rescue_candidates)} items selected for NCBI Rescue.")

        # Phase 4: Rescue (NCBI)
        final_results = jaccard_results

        if not rescue_candidates:
            logger.info("Skipping Phase 4 (All taxa auto-accepted or no rescue needed).")
        else:
            logger.info(f"Phase 4: Running NCBI Rescue on {len(rescue_candidates)} taxa...")

            rescued_items = rescue.run_ncbi_rescue(
                candidates=rescue_candidates,
                ncbi_cache_path=settings.ncbi_cache_path
            )

            rescue_map = {item['taxon']: item for item in rescued_items}
            updated_results = []
            for item in jaccard_results:
                key = item['taxon']
                if key in rescue_map:
                    updated_results.append(rescue_map[key])
                else:
                    updated_results.append(item)

            final_results = updated_results

        # Phase 5: Assembly & Save
        logger.info("Phase 5: Assembling final JSON report...")
        report = assembly.assemble_report(job_id, final_results)

        with open(local_output_path, "w", encoding="utf-8") as f:
            f.write(report.to_json())

        logger.info(f"Uploading result to MinIO: {s3_output_key}")
        storage_client.upload_file(str(local_output_path), s3_output_key)

        logger.info(f"--- [Job {job_id}] SUCCESS! Result available at S3 key: {s3_output_key} ---")

        try:
            backend_client.update_job(job_id, {
                "status": "COMPLETED",
                "outputFilePath": s3_output_key
            })
        except Exception as e:
            logger.warning(f"Could not update COMPLETED status to backend: {e}")

    except Exception as e:
        logger.exception(f"--- [Job {job_id}] Pipeline FAILED: {e} ---")

        try:
            backend_client.update_job(job_id, {
                "status": "FAILED",
                "errorMessage": str(e)
            })
        except Exception as update_error:
            logger.error(f"Critical: Failed to report error status to backend: {update_error}")

        raise e

    finally:
        if job_work_dir.exists():
            try:
                shutil.rmtree(job_work_dir)
                logger.info(f"Cleaned up temp directory: {job_work_dir}")
            except OSError as e:
                logger.warning(f"Error removing temp dir {job_work_dir}: {e}")