import numpy as np
from scipy import io as sio, sparse
from typing import List, Tuple

from ..core.structs import MinimalModel

def _as_list_of_str(x) -> List[str]:
    if isinstance(x, (list, tuple)):
        out: List[str] = []
        for y in x:
            out.extend(_as_list_of_str(y))
        return out
    if hasattr(x, "tolist"):
        return _as_list_of_str(x.tolist())
    if isinstance(x, str):
        return [x]
    return [str(x)]

def _ensure_1d(a) -> np.ndarray:
    arr = np.array(a).squeeze()
    return arr.astype(float)

def load_minimal_model_from_mat(path: str, model_id: str) -> MinimalModel:
    try:
        mat = sio.loadmat(path, squeeze_me=True, struct_as_record=False)
    except NotImplementedError:
        raise ValueError(f"Could not read MAT file {path}. Ensure it is v7 or lower, or install hdf5storage.")

    model = None
    for key in ("model", "Model", "m", "cobra_model"):
        if key in mat:
            model = mat[key]
            break
    if model is None:
        for v in mat.values():
            if hasattr(v, "S") and hasattr(v, "rxns"):
                model = v
                break
    if model is None:
        raise ValueError(f"Could not find a COBRA model struct in {path}")

    S = getattr(model, "S")
    if not sparse.issparse(S):
        S = sparse.csr_matrix(S)

    rxns = _as_list_of_str(getattr(model, "rxns"))
    mets = _as_list_of_str(getattr(model, "mets"))
    lb = _ensure_1d(getattr(model, "lb"))
    ub = _ensure_1d(getattr(model, "ub"))
    c = _ensure_1d(getattr(model, "c"))

    if S.shape[1] != len(rxns) or S.shape[0] != len(mets):
        raise ValueError(
            f"Inconsistent dimensions in {path}: S={S.shape}, rxns={len(rxns)}, mets={len(mets)}"
        )

    return MinimalModel(id=model_id, S=S.tocsr(), rxns=rxns, mets=mets, lb=lb, ub=ub, c=c)

def read_models_list(list_file: str) -> List[str]:
    with open(list_file, "r") as f:
        return [ln.strip() for ln in f if ln.strip()]

def read_diet_file(diet_file: str) -> List[Tuple[str, float]]:
    pairs: List[Tuple[str, float]] = []
    with open(diet_file, "r") as f:
        for ln in f:
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            rxn = parts[0]
            try:
                val = float(parts[1])
            except ValueError:
                val = float(parts[1].replace(",", "."))
            pairs.append((rxn, val))
    return pairs

def read_reaction_names_file(path: str) -> List[str]:
    names: List[str] = []
    if not path:
        return names
    with open(path, "r") as f:
        for ln in f:
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            names.append(s)
    return names
