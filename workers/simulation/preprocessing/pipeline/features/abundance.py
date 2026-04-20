import numpy as np
from typing import List, Optional

from ..core.structs import CommunityModel

def read_abundances(path: Optional[str], sp_tags: List[str]) -> Optional[np.ndarray]:
    if not path: return None
    tags_set = set(sp_tags)
    values_only: List[float] = []
    tag_map: dict[str, float] = {}
    
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            s = ln.strip()
            if not s or s.startswith("#"): continue
            parts = s.split()
            parts = [p.replace(",", ".") for p in parts]
            
            if len(parts) >= 2 and parts[0] in tags_set:
                tag_map[parts[0]] = float(parts[1])
            elif len(parts) == 1:
                values_only.append(float(parts[0]))
                
    if tag_map:
        return np.array([float(tag_map.get(t, 1.0)) for t in sp_tags], dtype=float)
    
    if values_only:
        weights = np.ones(len(sp_tags))
        count = min(len(values_only), len(sp_tags))
        weights[:count] = values_only[:count]
        return weights
        
    return None


def apply_abundance_scale_species_ex_bounds(
    comm: CommunityModel, 
    org_weights: np.ndarray, 
    *, 
    scale_lb: bool, 
    scale_ub: bool, 
    only_linked_to_u: bool
) -> int:
    if not scale_lb and not scale_ub: return 0
    updated = 0
    
    rxn_to_idx = {r: i for i, r in enumerate(comm.rxns)}
    linked_ok = set()
    
    if only_linked_to_u:
        for i_row, met in enumerate(comm.mets):
            if not met.endswith("[u]"): continue
            base = met[:-3]
            
            j_u_candidates = [f"EX_{base}(u)", f"EX_{base}_D(u)"]
            j_u = next((rxn_to_idx[c] for c in j_u_candidates if c in rxn_to_idx), None)
            
            row = comm.S.getrow(i_row)
            for j in row.indices:
                if j == j_u: continue
                
                if comm.rxns[j].startswith("EX_"):
                    linked_ok.add(j)
    
    for sp_i, (start, end) in enumerate(comm.org_rxn_col_ranges):
        weight = float(org_weights[sp_i])
        
        if abs(weight - 1.0) < 1e-9:
            continue

        for j in range(start, end):
            name = comm.rxns[j]
            
            if not name.startswith("EX_"): continue
            
            if only_linked_to_u and j not in linked_ok: continue
            
            if scale_lb:
                old = comm.lb[j]
                new = weight * old
                if abs(new - old) > 1e-15: 
                    comm.lb[j] = new
                    updated += 1
                    
            if scale_ub:
                old = comm.ub[j]
                new = weight * old
                if abs(new - old) > 1e-15: 
                    comm.ub[j] = new
                    updated += 1
            
            if comm.lb[j] > comm.ub[j]:
                m = min(comm.lb[j], comm.ub[j])
                comm.lb[j] = m
                comm.ub[j] = m

    return updated
