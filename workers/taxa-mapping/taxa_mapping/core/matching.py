import logging
import pandas as pd
from typing import List, Dict, Any
from joblib import Parallel, delayed

from .constants import CC_PREFIXES
from .tokenization import (
    clean_and_tokenize,
    extract_anchor,
    build_anchor,
    count_anchor_tokens_subspp,
    has_code_or_cc
)
from .scoring import containment_jaccard_distance

logger = logging.getLogger(__name__)

def process_single_taxa(
        taxon_clean: str,
        anchor: str,
        model_tokens_list: List[List[str]],
        model_filenames: List[str],
        cc_prefixes: List[str]
) -> Dict[str, Any]:

    tokens_taxa = clean_and_tokenize(taxon_clean, cc_prefixes)

    gs_tokens = []
    if anchor:
        tokens_species = clean_and_tokenize(anchor, cc_prefixes)
        gs_tokens = tokens_species[:2] if len(tokens_species) >= 2 else tokens_species

    distances = [
        containment_jaccard_distance(tokens_taxa, tokens_mat, cc_prefixes)
        for tokens_mat in model_tokens_list
    ]

    d_min = min(distances)

    tie_idx = [i for i, d in enumerate(distances) if abs(d - d_min) <= 1e-5]

    pick_idx = None
    for k in tie_idx:
        chosen_tokens_k = model_tokens_list[k]

        has_gs_k = (all(t in tokens_taxa for t in gs_tokens) and
                    all(t in chosen_tokens_k for t in gs_tokens))

        if has_gs_k:
            pick_idx = k
            break

    if pick_idx is None:
        pick_idx = tie_idx[0]

    best_mat = model_filenames[pick_idx]
    j_star = 1.0 - distances[pick_idx]

    chosen_tokens = model_tokens_list[pick_idx]

    has_gs = (len(gs_tokens) == 2 and
              all(t in tokens_taxa for t in gs_tokens) and
              all(t in chosen_tokens for t in gs_tokens))

    if pd.isna(j_star):
        bands = "na"
    elif j_star >= 0.90 and has_gs:
        bands = "auto-accept"
    elif j_star >= 0.30 and has_gs:
        bands = "grey-zone"
    elif j_star >= 0.30 and not has_gs:
        bands = "flag"
    else:
        bands = "not-accept"

    mat_cands = [model_filenames[idx] for idx in tie_idx]
    mat_cands_str = ';'.join(mat_cands)

    return {
        'mat': best_mat,
        'j_score': j_star,
        'has_gs': has_gs,
        'bands': bands,
        'n_candidates': len(mat_cands),
        'mat_candidates_str': mat_cands_str
    }

def _deduplicate_within_anchor(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    rows = []
    for anchor, g in df.groupby("anchor", dropna=False, sort=False):
        g = g.copy()

        g["_subspp_tokens"] = g["subspp_anchor"].apply(lambda x: str(x).split() if x else [])

        keep_mask = [True] * len(g)
        toks_list = g["_subspp_tokens"].tolist()

        for i in range(len(g)):
            ti = toks_list[i]
            for j in range(len(g)):
                if i == j:
                    continue
                tj = toks_list[j]

                if len(tj) > len(ti) and ti and tj[:len(ti)] == ti:
                    keep_mask[i] = False
                    break

        g = g.iloc[keep_mask].copy()

        g = g.sort_values(
            by=["has_code_or_cc", "j_score", "n_candidates"],
            ascending=[False, False, True]
        )
        g = g.drop_duplicates(subset=["subspp_anchor"], keep="first")

        rows.append(g.drop(columns=["_subspp_tokens"], errors="ignore"))

    return pd.concat(rows, axis=0, ignore_index=True)

def run_jaccard_matching(
        taxa_list: List[str],
        raw_taxa_list: List[str],
        models_csv_path: str,
        abundance_map: Dict[str, float] = None,
        n_jobs: int = -2
) -> List[Dict[str, Any]]:

    logger.info(f"Starting Jaccard Matching with {len(taxa_list)} queries...")

    try:
        models_df = pd.read_csv(models_csv_path)
        models_df['Filename'] = models_df['Filename'].astype(str).str.replace(r'\.mat$', '', regex=True)
        model_filenames = models_df['Filename'].tolist()
    except Exception as e:
        logger.error(f"Failed to load models CSV: {e}")
        raise e

    model_tokens_list = [clean_and_tokenize(fn, CC_PREFIXES) for fn in model_filenames]

    input_df = pd.DataFrame({
        'taxa_name': raw_taxa_list,
        'taxon': taxa_list
    })

    if abundance_map:
        input_df['abundance'] = input_df['taxa_name'].map(abundance_map)
    else:
        input_df['abundance'] = None

    input_df['anchor'] = input_df['taxon'].apply(extract_anchor)

    results = Parallel(n_jobs=n_jobs)(
        delayed(process_single_taxa)(
            row['taxon'],
            row['anchor'],
            model_tokens_list,
            model_filenames,
            CC_PREFIXES
        )
        for _, row in input_df.iterrows()
    )

    results_df = pd.DataFrame(results)
    combined_df = pd.concat([input_df.reset_index(drop=True), results_df], axis=1)

    combined_df['subspp_anchor'] = combined_df.apply(
        lambda row: build_anchor(row['taxon'], row['anchor'], CC_PREFIXES),
        axis=1
    )

    combined_df['anchor_tokens'] = combined_df['subspp_anchor'].apply(
        lambda x: count_anchor_tokens_subspp(x, CC_PREFIXES)
    )

    combined_df['anchor_tokens_base'] = combined_df['anchor'].apply(
        lambda x: count_anchor_tokens_subspp(x, CC_PREFIXES)
    )

    combined_df['has_code_or_cc'] = combined_df['taxon'].apply(has_code_or_cc)

    final_df = _deduplicate_within_anchor(combined_df)

    desired_order = [
        "taxa_name",
        "abundance",
        "taxon",
        "anchor",
        "mat",
        "j_score",
        "has_gs",
        "bands",
        "n_candidates",
        "mat_candidates_str",
        "subspp_anchor",
        "anchor_tokens",
        "anchor_tokens_base",
        "has_code_or_cc"
    ]

    final_cols = [c for c in desired_order if c in final_df.columns]
    final_df = final_df[final_cols]

    return final_df.to_dict(orient='records')