import os
from typing import List

from ..core.structs import CommunityModel
from ..core.builder import get_community_rxn_indices

def _is_biomass_name(name: str) -> bool:
    lname = name.lower()
    if lname.startswith("ex_"): return False
    return ("biomass" in lname) or lname.startswith("bio1")

def _collect_biomass_rxn_indices(comm: CommunityModel) -> List[int]:
    idxs = []
    for org_i, (start, end) in enumerate(comm.org_rxn_col_ranges):
        for j in range(start, end):
            if _is_biomass_name(comm.rxns[j]): idxs.append(j)
    return idxs

def export_lower_upper_bounds(comm: CommunityModel, outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    for k, (start, end) in enumerate(comm.org_rxn_col_ranges, start=1):
        with open(os.path.join(outdir, f"org{k}_lower_bounds.txt"), "w") as fl, open(os.path.join(outdir, f"org{k}_upper_bounds.txt"), "w") as fu:
            for j in range(start, end):
                fl.write(f"{comm.lb[j]:.15g}\n"); fu.write(f"{comm.ub[j]:.15g}\n")
    
    exu_idx = get_community_rxn_indices(comm)
    with open(os.path.join(outdir, "community_lower_bounds.txt"), "w") as fl, open(os.path.join(outdir, "community_upper_bounds.txt"), "w") as fu:
        for j in exu_idx:
            fl.write(f"{comm.lb[j]:.15g}\n"); fu.write(f"{comm.ub[j]:.15g}\n")

    bio_idx = _collect_biomass_rxn_indices(comm)
    with open(os.path.join(outdir, "biomass_lower_bounds.txt"), "w") as fl, open(os.path.join(outdir, "biomass_upper_bounds.txt"), "w") as fu:
        for j in bio_idx:
            fl.write(f"{comm.lb[j]:.15g}\n"); fu.write(f"{comm.ub[j]:.15g}\n")
