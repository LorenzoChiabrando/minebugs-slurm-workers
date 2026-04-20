import re
from typing import List, Optional, Set

from .constants import CC_PREFIXES

def extract_cc(tokens: List[str], cc_prefixes: List[str] = CC_PREFIXES) -> List[str]:
    cc_rx = rf"^({'|'.join(cc_prefixes)})_[A-Za-z0-9-]+$"

    return [t for t in tokens if re.match(cc_rx, t, re.IGNORECASE)]


def choose_cc(ccs: List[str],
              ref_overlap: Optional[List[str]] = None,
              cc_prefixes: List[str] = CC_PREFIXES) -> Optional[str]:
    if not ccs:
        return None

    cand = list(set(ccs) & set(ref_overlap)) if ref_overlap else ccs

    if not cand:
        cand = ccs

    def get_rank(token: str) -> int:
        prefix = re.sub(r'^([A-Z]+)_.*$', r'\1', token)
        try:
            return cc_prefixes.index(prefix)
        except ValueError:
            return len(cc_prefixes) + 1

    cand_sorted = sorted(cand, key=lambda x: (get_rank(x), x))

    return cand_sorted[0]


def containment_jaccard_distance(tokens_taxa: List[str],
                                 tokens_model: List[str],
                                 cc_prefixes: List[str] = CC_PREFIXES) -> float:

    T0 = list(set(tokens_taxa))
    M0 = list(set(tokens_model))

    Tcc = extract_cc(T0, cc_prefixes)
    Mcc = extract_cc(M0, cc_prefixes)

    cc_rx = rf"^({'|'.join(cc_prefixes)})_[A-Za-z0-9-]+$"

    if Tcc or Mcc:
        overlap = list(set(Tcc) & set(Mcc))

        keep_T = choose_cc(Tcc, ref_overlap=overlap, cc_prefixes=cc_prefixes)
        keep_M = choose_cc(Mcc, ref_overlap=overlap, cc_prefixes=cc_prefixes)

        Tset = list(set(
            [t for t in T0 if not re.match(cc_rx, t, re.IGNORECASE)] +
            ([keep_T] if keep_T else [])
        ))

        Mset = list(set(
            [t for t in M0 if not re.match(cc_rx, t, re.IGNORECASE)] +
            ([keep_M] if keep_M else [])
        ))
    else:
        Tset = T0
        Mset = M0

    inter = len(set(Tset) & set(Mset))
    uni = len(set(Tset) | set(Mset))

    if uni == 0:
        return 1.0

    return 1.0 - (inter / uni)