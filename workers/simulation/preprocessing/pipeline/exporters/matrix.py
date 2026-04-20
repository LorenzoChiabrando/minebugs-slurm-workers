import os
import json
import numpy as np
from scipy import sparse
from ..core.structs import CommunityModel
from ..core.builder import get_community_met_indices

def _write_sparse_coo(matrix: sparse.spmatrix, path: str, delimiter=" ", float_fmt="%.15g"):
    if not sparse.isspmatrix_coo(matrix):
        matrix = matrix.tocoo()
    data = np.column_stack((matrix.row, matrix.col, matrix.data))
    np.savetxt(path, data, fmt=["%d", "%d", float_fmt], delimiter=delimiter)

def export_mappings(comm: CommunityModel, outdir: str):
    os.makedirs(outdir, exist_ok=True)
    org_map = {i: tag for i, tag in enumerate(comm.sp_tags)}
    with open(os.path.join(outdir, "species_map.json"), "w") as f:
        json.dump(org_map, f, indent=2)

    comm_rxn_map = {}
    last_org_end = comm.org_rxn_col_ranges[-1][1]
    for i in range(last_org_end, len(comm.rxns)):
        comm_rxn_map[f"EX_comm_{i - last_org_end}"] = comm.rxns[i]
    with open(os.path.join(outdir, "community_flux_map.json"), "w") as f:
        json.dump(comm_rxn_map, f, indent=2)

def export_community_data(comm: CommunityModel, outdir: str):
    os.makedirs(outdir, exist_ok=True)
    u_rows = get_community_met_indices(comm)
    if not u_rows: return
    
    S_comm_sub = comm.S[u_rows, :]
    _write_sparse_coo(S_comm_sub, os.path.join(outdir, "community_stoichiometric_matrix.csv"))
    
    with open(os.path.join(outdir, "community_mets.txt"), "w") as f:
        for i in u_rows: f.write(comm.mets[i] + "\n")
    with open(os.path.join(outdir, "community_rxns.txt"), "w") as f:
        f.write("\n".join(comm.rxns) + "\n")

def export_per_organism(comm: CommunityModel, outdir: str, include_u_rows=False):
    os.makedirs(outdir, exist_ok=True)
    
    for i, tag in enumerate(comm.sp_tags):
        prefix = os.path.join(outdir, f"org{i+1}")
        start, end = comm.org_rxn_col_ranges[i]
        
        S_cols = comm.S[:, start:end]
        
        org_rxns = comm.rxns[start:end]
        with open(prefix + "_rxns.txt", "w") as f:
            for rxn in org_rxns:
                f.write(rxn + "\n")

        all_rows_with_entries = np.unique(S_cols.nonzero()[0])
        valid_rows = []
        for r_idx in all_rows_with_entries:
            met_name = comm.mets[r_idx]
            if not met_name.endswith("[u]"):
                valid_rows.append(r_idx)
            elif include_u_rows:
                valid_rows.append(r_idx)
                
        row_indices = np.array(valid_rows, dtype=int)
        
        S_sub = comm.S[row_indices, :][:, np.arange(start, end)]
        
        _write_sparse_coo(S_sub, prefix + "_stoichiometric_matrix.csv")
        
        with open(prefix + "_meta.json", "w") as f:
            json.dump({
                "original_id": tag,
                "n_rxns": int(end - start),
                "n_mets": len(row_indices)
            }, f, indent=2)
            
        print(f"[PER-ORG] {tag} (org{i+1}): {S_sub.shape} sparse exported + rxns names.")
