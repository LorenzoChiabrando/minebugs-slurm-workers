import subprocess
import logging
import json
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

class SolverRunner:
    def __init__(self, binary_path: str):
        self.binary_path = Path(binary_path)
        if not self.binary_path.exists():
            logger.warning(f"Solver binary not found at: {self.binary_path}")

    def run_solver(self,
                   input_dir: Path,
                   output_file: Path,
                   config: Dict[str, Any]) -> Dict[str, Any]:

        cmd = [
            str(self.binary_path),
            "--input-dir", str(input_dir),
            "--output-file", str(output_file)
        ]

        min_growth = config.get("min_community_growth", 0.8)
        cmd.extend(["--min-growth", str(min_growth)])

        prod_floor = config.get("production_floor", 0.8)
        cmd.extend(["--prod-floor", str(prod_floor)])

        time_limit = config.get("time_limit", 3600.0)
        cmd.extend(["--time-limit", str(time_limit)])

        min_species = config.get("min_species", 1)
        cmd.extend(["--min-species", str(min_species)])

        logger.info(f"Running Solver: {' '.join(cmd)}")

        # Python-level timeout: time_limit + 5 minutes safety buffer.
        # Prevents a hung solver binary from blocking the thread pool indefinitely.
        python_timeout = int(config.get("time_limit", 3600)) + 300

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=False,
                timeout=python_timeout
            )

            if result.stdout:
                for line in result.stdout.splitlines(): logger.info(f"[CPP] {line}")
            if result.stderr:
                for line in result.stderr.splitlines(): logger.warning(f"[CPP-ERR] {line}")

            if result.returncode != 0:
                raise RuntimeError(f"Solver exited with error code {result.returncode}")

            if not output_file.exists():
                raise FileNotFoundError(f"Solver completed but output file not found: {output_file}")

            with open(output_file, 'r') as f:
                return json.load(f)

        except subprocess.TimeoutExpired:
            logger.error(f"Solver process exceeded Python timeout ({python_timeout}s) and was forcibly killed.")
            raise RuntimeError(f"Solver process timed out after {python_timeout}s (time_limit + 5min buffer)")
        except Exception as e:
            logger.exception("Failed to run C++ solver")
            raise e