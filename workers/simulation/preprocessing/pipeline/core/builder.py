import numpy as np
from scipy import sparse
from typing import List, Tuple, Optional, Dict, Iterable

from .structs import MinimalModel, CommunityModel

# String helpers for standardize reactions and metabolites names

def _strip_compartment(met_name: str) -> Tuple[str, Optional[str]]:
    """
    Parses 'glc[e]' -> ('glc', 'e'); 'atp[c]' -> ('atp','c'); 'met' -> ('met', None).
    """
    if met_name.endswith(']') and '[' in met_name:
        base = met_name[:met_name.rfind('[')]
        comp = met_name[met_name.rfind('[')+1:-1]
        return base, comp
    return met_name, None

def _tag_mets_with_org(mets: List[str], org_tag: str) -> List[str]:
    """
    Tags metabolites with organism suffix:
    'glc[c]' -> 'glc[c_org1]', 'glc[e]' -> 'glc[e_org1]'.
    If no compartment brackets, appends '[org1]'.
    """
    tagged = []
    for m in mets:
        base, comp = _strip_compartment(m)
        if comp is None:
            tagged.append(f"{base}[{org_tag}]")
        else:
            tagged.append(f"{base}[{comp}_{org_tag}]")
    return tagged


# Preprocessing for community model construction

def _add_missing_exchange_rxns(
    S: sparse.csr_matrix,
    rxns: List[str],
    mets: List[str],
    lb: np.ndarray,
    ub: np.ndarray,
    c:  np.ndarray,
    met_ex_id: str = "[e]",
    add_ex_rxns: bool = True,
) -> Tuple[sparse.csr_matrix, List[str], np.ndarray, np.ndarray, np.ndarray, Dict[int,int]]:
    """
    Ensures every extracellular metabolite (ending in met_ex_id) has an exchange reaction.
    If missing, adds 'EX_metname' with lb=0, ub=1000 (efflux allowed).
    Returns updated arrays and a map {met_index -> rxn_index} for exchanges.
    """
    n_mets, n_rxns = S.shape
    S = S.tocsc()
    is_ex_met = np.array([m.endswith(met_ex_id) for m in mets], dtype=bool)


    ex_mask = np.zeros(n_rxns, dtype=bool)
    ex_met_for_rxn = -np.ones(n_rxns, dtype=int)

    for j in range(n_rxns):
        col_rows = S.indices[S.indptr[j]:S.indptr[j+1]]
        if col_rows.size == 1 and is_ex_met[col_rows[0]]:
            ex_mask[j] = True
            ex_met_for_rxn[j] = col_rows[0]

    # Map met_idx -> rxn_idx
    met_to_exrxn: Dict[int,int] = {}
    for j in range(n_rxns):
        if ex_mask[j]:
            met_to_exrxn[ex_met_for_rxn[j]] = j

    if not add_ex_rxns:
        return S.tocsr(), rxns, lb, ub, c, met_to_exrxn

    # Create missing EX reactions
    new_cols = []
    new_rxn_names = []
    new_met_ids = []
    
    for i_met, is_ex in enumerate(is_ex_met):
        if not is_ex:
            continue
        if i_met in met_to_exrxn:
            continue  # Already has exchange

        # Add column: coefficient -1.0 for the metabolite (flow OUT of system by default)
        col = sparse.csc_matrix(([-1.0], ([i_met], [0])), shape=(n_mets, 1))
        new_cols.append(col)
        
        clean_name = mets[i_met].replace('[','(').replace(']',')')
        new_rxn_names.append(f"EX_{clean_name}")
        new_met_ids.append(i_met)

    if new_cols:
        S = sparse.hstack([S] + new_cols, format="csc")
        rxns = rxns + new_rxn_names
        add_n = len(new_cols)
        
        # Default bounds for new exchanges: allow excretion (0 to 1000)
        lb = np.concatenate([lb, np.zeros(add_n)])
        ub = np.concatenate([ub, np.full(add_n, 1000.0)])
        c  = np.concatenate([c,  np.zeros(add_n)])
        
        start = n_rxns
        for k, i_met in enumerate(new_met_ids):
            met_to_exrxn[i_met] = start + k

    return S.tocsr(), rxns, lb, ub, c, met_to_exrxn


# Community Matrix Builder

def create_community_model(
    models: List[MinimalModel],
    sep_utex: bool = False,         
    met_ex_id: str = "[e]",
    add_ex_rxns: bool = True,
    verbose: bool = True,
) -> CommunityModel:
    """
    Builds the minimal community model:
    1. Tags each organism's metabolites and reactions (e.g., _org1).
    2. Diagonalizes stoichiometric matrices.
    3. Creates a shared compartment [u].
    4. Links extracellular exchanges of each organism to [u].
    5. Adds community exchanges EX_...(u) <=> Environment.
    """
    # Uses real IDs from MinimalModel instead of generic org1, org2
    sp_tags = [m.id for m in models]

    S_blocks = []
    rxns_all: List[str] = []
    lb_all: List[np.ndarray] = []
    ub_all: List[np.ndarray] = []
    c_all:  List[np.ndarray] = []
    org_col_ranges: List[Tuple[int,int]] = []
    base_col = 0

    per_org_met_to_ex: List[Dict[int,int]] = []
    per_org_ex_met_base: List[List[Optional[str]]] = []
    mets_tagged_all: List[str] = []

    for i, m in enumerate(models):
        tag = sp_tags[i]

        S_i, rxns_i, lb_i, ub_i, c_i, met_to_ex = _add_missing_exchange_rxns(
            m.S.copy(), m.rxns.copy(), m.mets.copy(),
            m.lb.copy(), m.ub.copy(), m.c.copy(),
            met_ex_id=met_ex_id,
            add_ex_rxns=add_ex_rxns,
        )

        mets_tagged = _tag_mets_with_org(m.mets, tag)
        rxns_tagged = [f"{r}_{tag}" for r in rxns_i]

        S_blocks.append(S_i)
        n_cols_i = S_i.shape[1]
        rxns_all.extend(rxns_tagged)
        mets_tagged_all.extend(mets_tagged)
        lb_all.append(lb_i)
        ub_all.append(ub_i)
        c_all.append(c_i)
        org_col_ranges.append((base_col, base_col + n_cols_i))
        base_col += n_cols_i

        per_org_met_to_ex.append(met_to_ex)

        ex_bases = []
        for idx, met in enumerate(m.mets):
            if met.endswith(met_ex_id):
                base, _ = _strip_compartment(met)
                ex_bases.append(base)
            else:
                ex_bases.append(None)
        per_org_ex_met_base.append(ex_bases)

        if verbose:
            print(f"[BUILD] {tag}: rxns={S_i.shape[1]}, mets={S_i.shape[0]}, EX_present={len(set(met_to_ex.values()))}")

    # Block Diagonalization 
    S_sp = sparse.block_diag(S_blocks, format="csr")
    lb_sp = np.concatenate(lb_all)
    ub_sp = np.concatenate(ub_all)
    c_sp  = np.concatenate(c_all)

    # Community Metabolites 
    comm_set = set()
    for i, m in enumerate(models):
        for imet, base in enumerate(per_org_ex_met_base[i]):
            if base is not None and imet in per_org_met_to_ex[i]:
                comm_set.add(base)
    comm_list = sorted(comm_set)
    
    if verbose:
        print(f"[BUILD] Shared community metabolites detected: {len(comm_list)}")

    mCom = len(comm_list)
    if mCom == 0:
        return CommunityModel(
            S=S_sp, rxns=rxns_all, mets=mets_tagged_all,
            lb=lb_sp, ub=ub_sp, c=c_sp, sp_tags=sp_tags,
            comm_met_base=[], org_rxn_col_ranges=org_col_ranges,
            global_rxn_map={}
        )

    # Create Shared Community Pool [u]
    rows = []
    cols = []
    data = []
    base_to_urow = {b: r for r, b in enumerate(comm_list)}

    for i, m in enumerate(models):
        start, end = org_col_ranges[i]
        S_i = S_blocks[i].tocsc()
        
        for imet, ex_rxn_local in per_org_met_to_ex[i].items():
            base, _ = _strip_compartment(m.mets[imet])
            if base not in base_to_urow:
                continue
            
            urow = base_to_urow[base]
            col = S_i[:, ex_rxn_local]
            nz = col.nonzero()[0]
            if nz.size == 1 and nz[0] == imet:
                coeff = -col.data[0] 
            else:
                coeff = -float(col.data[0]) if nz.size else 1.0
                
            rows.append(urow)
            cols.append(start + ex_rxn_local)
            data.append(coeff)

    EXu_cols = []
    EXu_names = []
    for r, base in enumerate(comm_list):
        EXu_cols.append(sparse.csc_matrix(([-1.0], ([r], [0])), shape=(mCom, 1)))
        EXu_names.append(f"EX_{base}(u)")

    L = sparse.csr_matrix((data, (rows, cols)), shape=(mCom, S_sp.shape[1]))
    EXu_block = sparse.hstack(EXu_cols, format="csc")
    
    top = sparse.hstack([S_sp, sparse.csr_matrix((S_sp.shape[0], mCom))], format="csr")
    bottom = sparse.hstack([L, EXu_block], format="csr")
    
    S_comm = sparse.vstack([top, bottom], format="csr")

    rxns_comm = rxns_all + EXu_names
    mets_comm = mets_tagged_all + [f"{b}[u]" for b in comm_list]

    lb_comm = np.concatenate([lb_sp, np.zeros(mCom)])
    ub_comm = np.concatenate([ub_sp, np.full(mCom, 1000.0)])
    c_comm  = np.concatenate([c_sp,  np.zeros(mCom)])

    # Create mapping for reporting
    global_map = {i: name for i, name in enumerate(rxns_comm)}

    return CommunityModel(
        S=S_comm, 
        rxns=rxns_comm, 
        mets=mets_comm,
        lb=lb_comm, 
        ub=ub_comm, 
        c=c_comm,
        sp_tags=sp_tags, 
        comm_met_base=comm_list,
        org_rxn_col_ranges=org_col_ranges,
        global_rxn_map=global_map # Pass the map
    )

# UTILITIES 

def get_community_rxn_indices(comm: CommunityModel) -> List[int]:
    """Returns indices of EX_*(u) reactions (community boundary)."""
    return [i for i, r in enumerate(comm.rxns)
            if r.startswith("EX_") and r.endswith("(u)") and "_org" not in r]

def get_community_met_indices(comm: CommunityModel) -> List[int]:
    """Returns indices of [u] metabolites."""
    return [i for i, m in enumerate(comm.mets) if m.endswith("[u]")]
