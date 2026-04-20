from dataclasses import dataclass, field
from typing import List, Tuple, Dict
import numpy as np
from scipy import sparse

@dataclass
class MinimalModel:
    """Simplified representation of AGORA metabolic model"""
    id: str                  # filename (without extension)
    S: sparse.csr_matrix     # (n_mets, n_rxns)
    rxns: List[str]          # len = n_rxns
    mets: List[str]          # len = n_mets
    lb: np.ndarray           # shape (n_rxns,)
    ub: np.ndarray           # shape (n_rxns,)
    c:  np.ndarray           # shape (n_rxns,)

@dataclass
class CommunityModel:
    """Community model representation"""
    S: sparse.csr_matrix
    rxns: List[str]
    mets: List[str]
    lb: np.ndarray
    ub: np.ndarray
    c:  np.ndarray
    
    # Metadata
    sp_tags: List[str]                        # ["org1", "org2", ...] -> Now holds real IDs
    comm_met_base: List[str]                  # community metabolites names (ex: glc_D[u])
    org_rxn_col_ranges: List[Tuple[int,int]]  # delimiters of organisms column in final matrix
    
    # Mapping for reporting
    global_rxn_map: Dict[int, str] = field(default_factory=dict)
