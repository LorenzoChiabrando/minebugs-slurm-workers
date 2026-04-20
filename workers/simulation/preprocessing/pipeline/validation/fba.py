import os
import json
import numpy as np
from scipy import sparse
from scipy.optimize import linprog
from typing import List, Optional, Tuple

from ..core.structs import CommunityModel

def _solve_lp_max(c_max, S, lb, ub, A_ub=None, b_ub=None, tol=1e-9, solver="highs"):
    """
    Wrapper for scipy.optimize.linprog to maximize c_max @ x.
    Returns: (success, objective_value, solution_vector, status_message)
    """
    bounds = list(zip(lb, ub))

    res = linprog(
        c=-c_max,
        A_ub=A_ub, b_ub=b_ub,
        A_eq=S, b_eq=np.zeros(S.shape[0]),
        bounds=bounds,
        method=solver
    )

    if not res.success:
        return False, np.nan, np.zeros(len(c_max)), res.message

    val = float(c_max @ res.x)
    v = res.x.copy()
    v[np.abs(v) < tol] = 0.0
    return True, val, v, "optimal"

def _write_scfa_indices(outdir: str, indices_0based: List[int]) -> None:
    path = os.path.join(outdir, "scfa_indices.txt")
    with open(path, "w") as f:
        for idx in indices_0based:
            f.write(f"{idx + 1}\n")

def _get_biomass_indices_and_weights(comm: CommunityModel, org_weights: Optional[np.ndarray]) -> List[tuple]:
    mapped = []
    if org_weights is None:
        weights = np.ones(len(comm.sp_tags))
    else:
        weights = org_weights

    for i, (start, end) in enumerate(comm.org_rxn_col_ranges):
        w = weights[i]
        found = False
        for j in range(start, end):
            name = comm.rxns[j].lower()
            if name.startswith("ex_"): continue
            if ("biomass" in name) or name.startswith("bio1"):
                mapped.append((j, w))
                found = True
                break
        if not found:
            print(f"[WARN] No biomass reaction found for organism {comm.sp_tags[i]}")
    return mapped


def compute_and_write_reference_flux(
        comm: CommunityModel,
        outdir: str,
        scfa_names: List[str],
        gr_opt_frac: float = 0.99,
        tol: float = 1e-9,
        solver: str = "highs",
        export_lp: bool = False,
        org_weights: Optional[np.ndarray] = None
) -> Tuple[bool, str]:

    os.makedirs(outdir, exist_ok=True)

    # --- MAXIMIZE COMMUNITY BIOMASS ---

    bio_map = _get_biomass_indices_and_weights(comm, org_weights)
    biomass_indices = [x[0] for x in bio_map]

    if not biomass_indices:
        return False, "No biomass reactions found in any model."

    c_grow = np.zeros(len(comm.rxns))
    for idx, w in bio_map:
        c_grow[idx] = w

    ok_g, weighted_obj_val, v_grow, msg_g = _solve_lp_max(c_grow, comm.S, comm.lb, comm.ub, tol=tol, solver=solver)

    if not ok_g:
        return False, f"Growth Optimization Failed: {msg_g}"

    total_biomass_flux_unweighted = sum(v_grow[j] for j in biomass_indices)

    if total_biomass_flux_unweighted < 1e-6:
        return False, f"Zero Growth Possible (Max Biomass < 1e-6). Check Diet constraints."

    # --- MAXIMIZE SCFA PRODUCTION ---

    rxn_map = {r: i for i, r in enumerate(comm.rxns)}
    scfa_idx = [rxn_map[n] for n in (scfa_names or []) if n in rxn_map]
    _write_scfa_indices(outdir, scfa_idx)

    scfa_val = np.nan

    if scfa_idx:
        rows = []
        cols = []
        data = []

        for idx in biomass_indices:
            rows.append(0)
            cols.append(idx)
            data.append(-1.0)

        bvals = [-gr_opt_frac * total_biomass_flux_unweighted]

        A_ub = sparse.csr_matrix((data, (rows, cols)), shape=(1, len(comm.rxns)))
        b_ub = np.array(bvals)

        c_scfa = np.zeros(len(comm.rxns))
        for j in scfa_idx:
            c_scfa[j] = 1.0

        ok_s, scfa_val, v_scfa, msg_s = _solve_lp_max(c_scfa, comm.S, comm.lb, comm.ub, A_ub, b_ub, tol=tol, solver=solver)

        if not ok_s:
            return False, f"SCFA Optimization Failed (Biomass Constraint violation): {msg_s}"

        # Write per-reaction SCFA breakdown (name → flux at reference optimum)
        valid_scfa_names = [n for n in (scfa_names or []) if n in rxn_map]
        scfa_ref_breakdown = {name: float(v_scfa[idx]) for name, idx in zip(valid_scfa_names, scfa_idx)}
        with open(os.path.join(outdir, "reference_scfa_breakdown.json"), "w") as f:
            json.dump(scfa_ref_breakdown, f, indent=2)

    # --- WRITE OUTPUTS ---
    try:

        with open(os.path.join(outdir, "reference_flux_values.txt"), "w") as f:
            f.write(f"{total_biomass_flux_unweighted:.15g}\n")
            f.write(f"{scfa_val if not np.isnan(scfa_val) else 'NaN'}\n")

        meta = {
            "weighted_obj_val_step1": weighted_obj_val,
            "total_biomass_flux_unweighted": total_biomass_flux_unweighted,
            "growth_min_constraint": gr_opt_frac * total_biomass_flux_unweighted,
            "scfa_opt": scfa_val if not np.isnan(scfa_val) else None,
            "gr_opt_frac": gr_opt_frac,
            "solver": solver,
            "status": "ok"
        }
        with open(os.path.join(outdir, "reference_meta.json"), "w") as f:
            json.dump(meta, f, indent=2)

    except Exception as e:
        return False, f"IO Error writing reference results: {e}"

    return True, "Optimal"