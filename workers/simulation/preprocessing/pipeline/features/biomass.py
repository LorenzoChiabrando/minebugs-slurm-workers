import os
from typing import List, Tuple, Optional

from ..core.structs import CommunityModel

def _find_biomass_local(comm: CommunityModel, org_idx: int) -> Tuple[int, Optional[str]]:
    start, end = comm.org_rxn_col_ranges[org_idx]
    names = comm.rxns[start:end]
    for pos, name in enumerate(names):
        lname = name.lower()
        if lname.startswith("ex_"): continue
        if ("biomass" in lname) or lname.startswith("bio1"): return pos + 1, name
    return -1, None

def write_biomass_lists(comm: CommunityModel, outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    local_indices, names = [], []
    for i in range(len(comm.sp_tags)):
        idx, nm = _find_biomass_local(comm, i)
        local_indices.append(idx)
        names.append(nm if nm is not None else "NA")
    with open(os.path.join(outdir, "biomass_indices.txt"), "w") as f:
        for v in local_indices: f.write(f"{v}\n")
    with open(os.path.join(outdir, "biomass_reactions.txt"), "w") as f:
        for nm in names: f.write(f"{nm}\n")
