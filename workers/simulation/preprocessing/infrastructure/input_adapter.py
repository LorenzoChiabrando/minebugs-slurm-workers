import os
import logging
from pathlib import Path
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class InputAdapter:
    """
    Translates JSON configuration (from Frontend) into physical files on disk.

    ROBUSTNESS FEATURES:
    - Sorts models alphabetically (Deterministic Matrix).
    - Normalizes percentages (80 -> 0.8).
    - Translates (e) -> (u).
    """

    def __init__(self, job_work_dir: Path):
        self.work_dir = job_work_dir
        self.config_dir = self.work_dir / "input_config"
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def generate_all_inputs(self, config: Dict[str, Any]) -> Dict[str, Any]:
        paths = {}

        raw_models = config.get("models", [])
        raw_abundances = config.get("abundances", [])

        if not raw_abundances or len(raw_abundances) != len(raw_models):
            if raw_models:
                logger.warning(f"Abundances mismatch. Defaulting to 1.0.")
            current_abundances = [1.0] * len(raw_models)
        else:
            current_abundances = raw_abundances

        if raw_models:
            combined = sorted(zip(raw_models, current_abundances), key=lambda x: x[0])
            sorted_models, sorted_abundances = zip(*combined)
            sorted_models = list(sorted_models)
            sorted_abundances = list(sorted_abundances)
            logger.info(f"Sorted {len(sorted_models)} models alphabetically.")
        else:
            sorted_models, sorted_abundances = [], []

        paths["models_list"] = self._write_list_file("bacteria_list.txt", sorted_models)
        paths["abundance_file"] = self._write_abundance_file("abundance.txt", sorted_models, sorted_abundances)


        diet_fluxes = config.get("diet", {}).get("fluxes", [])
        paths["diet"] = self._write_diet_file("diet.txt", diet_fluxes)


        constraints = config.get("constraints", {})

        def to_fraction(val, default):
            """Converte 80 -> 0.8, mantiene 0.8 -> 0.8"""
            if val is None: return default
            v = float(val)
            if v > 1.0:
                logger.info(f"Converting constraint {v} to {v/100.0}")
                return v / 100.0
            return v

        params = {
            "solver": constraints.get("solver", "highs"),
            "compute_reference": True,
            "per_org": True,
            "community_data": True,

            "gr_opt_frac": to_fraction(constraints.get("growthOptimalityFraction"), 0.99),

            "min_community_growth": to_fraction(constraints.get("minCommunityGrowth"), 0.8),
            "production_floor": to_fraction(constraints.get("reactionProductionFloor"), 0.8),

            "time_limit": constraints.get("timeLimit", 3600),
            "min_species": constraints.get("minSpeciesCount", 1)
        }


        objectives = config.get("objectives", [])
        if objectives:
            paths["scfa_file"] = self._write_list_file("scfa_list.txt", objectives)
        else:
            paths["scfa_file"] = None

        return {**paths, **params}

    def _write_list_file(self, filename: str, items: List[str]) -> str:
        path = self.config_dir / filename
        with open(path, "w") as f:
            for item in items:
                if not item: continue
                val = str(item).strip()
                if val.endswith("(e)"): val = val.replace("(e)", "(u)")
                f.write(f"{val}\n")
        return str(path)

    def _write_diet_file(self, filename: str, fluxes: List[Dict]) -> str:
        path = self.config_dir / filename
        with open(path, "w") as f:
            for flux in fluxes:
                rxn = flux.get("communityReaction") or flux.get("metaboliteCode")
                val = flux.get("fluxValue")
                if rxn and val is not None:
                    rxn = str(rxn).strip()
                    if rxn.endswith("(e)"): rxn = rxn.replace("(e)", "(u)")
                    f.write(f"{rxn} {val}\n")
        return str(path)

    def _write_abundance_file(self, filename: str, models: List[str], values: List[float]) -> str:
        path = self.config_dir / filename
        with open(path, "w") as f:
            for m, v in zip(models, values):
                f.write(f"{m} {v}\n")
        return str(path)