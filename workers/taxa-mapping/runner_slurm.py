#!/usr/bin/env python3
"""
CLI entry point for the taxa-mapping SLURM job.
Bypasses RabbitMQ: job parameters are passed as command-line arguments.

Usage (from SBATCH script):
    python3 runner_slurm.py \
        --job-id   "${JOB_UUID}" \
        --input-key  "${INPUT}"  \
        --output-key "${OUTPUT}"

Local mode (no Docker):
    --input-key  /data/minebugs/jobs/test-001/taxa.csv
    --output-key /data/minebugs/jobs/test-001/result.json

S3 mode (RustFS):
    --input-key  inputs/test-001/taxa.csv
    --output-key outputs/test-001/result.json

Manual test (set env vars first via secrets.env, then):
    python3 runner_slurm.py \
        --job-id   "test-001" \
        --input-key  "inputs/test-001/taxa.csv" \
        --output-key "outputs/test-001/result.json"
"""
import sys
import argparse
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def parse_args():
    p = argparse.ArgumentParser(description="Taxa Mapping — SLURM CLI entry point")
    p.add_argument("--job-id",     required=True, help="Unique job identifier")
    p.add_argument("--input-key",  required=True, help="S3 key or local path for input CSV")
    p.add_argument("--output-key", required=True, help="S3 key or local path for output JSON")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    logger.info("=" * 60)
    logger.info("Taxa Mapping SLURM Runner")
    logger.info(f"  Job ID:     {args.job_id}")
    logger.info(f"  Input:      {args.input_key}")
    logger.info(f"  Output:     {args.output_key}")
    logger.info("=" * 60)

    try:
        from taxa_mapping.service import run_mapping_pipeline
        run_mapping_pipeline(args.job_id, args.input_key, args.output_key)
        logger.info(f"Pipeline completed successfully — job {args.job_id}")
        sys.exit(0)

    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")
        sys.exit(1)
