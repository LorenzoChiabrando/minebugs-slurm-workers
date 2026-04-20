import re
from typing import List, Tuple, Optional, Iterable, Set

from ..core.structs import CommunityModel

def _diet_automap(rxns: List[str], diet_name: str) -> Optional[str]:
    if diet_name in rxns: return diet_name
    m = re.fullmatch(r'EX_(.+)\(u\)', diet_name)
    if not m: return None
    base = m.group(1)
    cand1 = f"EX_{base}_D(u)"
    if cand1 in rxns: return cand1
    pat = re.compile(rf'^EX_{re.escape(base)}(_[A-Za-z0-9]+)?\(u\)$')
    matches = [r for r in rxns if pat.match(r)]
    return matches[0] if len(matches) == 1 else None

def apply_diet_bounds(comm: CommunityModel, diet_pairs: Iterable[Tuple[str, float]], verbose: bool = True) -> Tuple[int, List[str]]:
    rxn_to_idx = {r: i for i, r in enumerate(comm.rxns)}
    applied = 0
    missing = []
    for name, val in diet_pairs:
        target = _diet_automap(comm.rxns, name)
        if target is None:
            missing.append(name)
            continue
        j = rxn_to_idx[target]
        comm.lb[j] = float(val)
        applied += 1
    if verbose: print(f"[DIET] Applied {applied} entries; Missing mappings: {len(missing)}")
    return applied, missing
