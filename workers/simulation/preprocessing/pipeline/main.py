import os
import json
import argparse
import traceback
import numpy as np
from dataclasses import dataclass
from typing import Optional

from .utils.timer import SectionTimer
from .utils.io import (
    load_minimal_model_from_mat,
    read_models_list,
    read_diet_file,
    read_reaction_names_file
)

from .features.biomass import write_biomass_lists
from .features import abundance as abund
from .features.diet import apply_diet_bounds

from .core.builder import create_community_model

from .exporters.matrix import export_per_organism, export_community_data, export_mappings
from .exporters.bounds import export_lower_upper_bounds

from .validation.fba import compute_and_write_reference_flux

@dataclass
class PreprocessingConfig:
    models_list: str
    models_dir: str
    output: str
    diet: str
    timing: bool = False
    abundance_file: Optional[str] = None

    final_report_path: Optional[str] = None

    per_org: bool = False
    per_org_no_u_rows: bool = True
    community_data: bool = False

    compute_reference: bool = False
    solver: str = "highs"
    gr_opt_frac: float = 0.99
    scfa_file: Optional[str] = None


def write_failure_report(path: str, status: str, error_msg: str):
    report = {
        "status": status,
        "phase": "preprocessing",
        "error_message": error_msg,
        "objective_value": 0.0,
        "solve_time_sec": 0.0,
        "total_community_biomass": 0.0,
        "total_target_production": 0.0,
        "biomass_breakdown": [],
        "target_breakdown": {},
        "detailed_composition": [],
        "community_fluxes": {},
        "reference_original_biomass": 0.0,
        "reference_biomass_constraint": 0.0,
        "reference_original_target": 0.0,
        "reference_target_constraint": 0.0,
        "reference_target_breakdown": {},
        "target_reactions": [],
        "configuration": {
            "note": "Failed during Python Preprocessing phase"
        }
    }

    try:
        parent_dir = os.path.dirname(path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        with open(path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"[PREPROC] Failure report written to: {path}")
    except Exception as e:
        print(f"[PREPROC] CRITICAL: Could not write failure report: {e}")


def run_preprocessing_pipeline(cfg: PreprocessingConfig) -> bool:
    os.makedirs(cfg.output, exist_ok=True)

    timer = SectionTimer(enabled=cfg.timing, outdir=cfg.output)
    print(f"--- Starting Preprocessing Pipeline ---")
    print(f"[CONF] Output Dir: {cfg.output}")
    print(f"[CONF] Solver: {cfg.solver}")

    try:
        # --- LOADING ---
        with timer("load_models"):
            names = read_models_list(cfg.models_list)
            mats = [os.path.join(cfg.models_dir, f"{n}.mat") for n in names]

            models = []
            for i, p in enumerate(mats):
                if not os.path.exists(p):
                    raise FileNotFoundError(f"Model file not found: {p}")

                model_id = names[i]
                models.append(load_minimal_model_from_mat(p, model_id))
                if (i+1) % 10 == 0:
                    print(f"[LOAD] Loaded {i+1}/{len(mats)} models...")

            print(f"[LOAD] Completed. Total models: {len(models)}")

        # --- BUILDING ---
        with timer("build_community"):
            comm = create_community_model(
                models,
                sep_utex=False,
                met_ex_id="[e]",
                add_ex_rxns=True,
                verbose=True
            )

        with timer("unlock_species_EX_lb"):
            for j, r in enumerate(comm.rxns):
                if r.startswith("EX_") and "_org" in r:
                    comm.lb[j] = min(comm.lb[j], -1000.0)

        with timer("apply_diet"):
            diet_pairs = read_diet_file(cfg.diet)
            apply_diet_bounds(comm, diet_pairs, verbose=True)

        org_weights = None
        with timer("load_abundance"):
            if cfg.abundance_file:
                org_weights = abund.read_abundances(cfg.abundance_file, comm.sp_tags)
                print(f"[ABUND] Loaded weights for {len(comm.sp_tags)} organisms.")

                weights_path = os.path.join(cfg.output, "weights.txt")
                np.savetxt(weights_path, org_weights, fmt="%.6g")
                print(f"[ABUND] Weights copy saved to: {weights_path}")
            else:
                print("[ABUND] No abundance file provided. Using unit weights.")

        # --- EXPORTS ---
        with timer("export_artifacts"):
            bounds_dir = os.path.join(cfg.output, "lower_upper_bounds")
            export_lower_upper_bounds(comm, outdir=bounds_dir)
            write_biomass_lists(comm, cfg.output)

            export_mappings(comm, cfg.output)

            if cfg.per_org:
                export_per_organism(
                    comm,
                    outdir=os.path.join(cfg.output, "per_org"),
                    include_u_rows=not cfg.per_org_no_u_rows
                )

            if cfg.community_data:
                export_community_data(comm, outdir=os.path.join(cfg.output, "community_data"))

        # --- REFERENCE COMPUTATION ---
        if cfg.compute_reference:
            with timer("compute_reference"):
                print("[PREPROC] Computing reference fluxes (FBA)...")
                scfa_names = read_reaction_names_file(cfg.scfa_file) if cfg.scfa_file else []

                success, msg = compute_and_write_reference_flux(
                    comm=comm,
                    outdir=cfg.output,
                    scfa_names=scfa_names,
                    gr_opt_frac=cfg.gr_opt_frac,
                    solver=cfg.solver,
                    org_weights=org_weights
                )

                if not success:
                    print(f"[PREPROC] Reference FBA Failed: {msg}")
                    if cfg.final_report_path:
                        write_failure_report(
                            cfg.final_report_path,
                            "Infeasible",
                            f"Preprocessing FBA Failed: {msg}"
                        )
                    return False

        if cfg.timing:
            timer.finish_and_dump()

        print(f"\n[OK] Pipeline Completed Successfully -> {cfg.output}")
        return True

    except Exception as e:
        print(f"[PREPROC] Unhandled Exception: {e}")
        traceback.print_exc()

        if cfg.final_report_path:
            write_failure_report(
                cfg.final_report_path,
                "Error",
                f"Preprocessing Crash: {str(e)}"
            )
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="MINeBUGS Preprocessor (Optimized Modular Version)")

    io = parser.add_argument_group("I/O")
    io.add_argument("--models-list", required=True)
    io.add_argument("--models-dir", required=True)
    io.add_argument("--output", required=True)
    io.add_argument("--final-report-path", default=None, help="Where to write the JSON report on failure")
    io.add_argument("--timing", action="store_true")

    parser.add_argument("--diet", required=True)
    parser.add_argument("--abundance-file", default=None)

    parser.add_argument("--per-org", action="store_true")
    parser.add_argument("--per-org-no-u-rows", action="store_true")
    parser.add_argument("--community-data", action="store_true")

    parser.add_argument("--compute-reference", action="store_true")
    parser.add_argument("--solver", default="highs")
    parser.add_argument("--gr-opt-frac", type=float, default=0.99)
    parser.add_argument("--scfa-file", default=None)

    args = parser.parse_args()

    config = PreprocessingConfig(
        models_list=args.models_list,
        models_dir=args.models_dir,
        output=args.output,
        final_report_path=args.final_report_path,
        diet=args.diet,
        timing=args.timing,
        abundance_file=args.abundance_file,
        per_org=args.per_org,
        per_org_no_u_rows=args.per_org_no_u_rows,
        community_data=args.community_data,
        compute_reference=args.compute_reference,
        solver=args.solver,
        gr_opt_frac=args.gr_opt_frac,
        scfa_file=args.scfa_file
    )

    success = run_preprocessing_pipeline(config)

    if not success:
        exit(1)

if __name__ == "__main__":
    main()