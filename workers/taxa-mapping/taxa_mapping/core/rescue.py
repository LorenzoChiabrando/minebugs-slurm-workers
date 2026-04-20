import json
import logging
import statistics
from typing import Any, Dict, List

import pandas as pd

from ..infrastructure.ncbi_repository import NcbiRepository
from . import ncbi_scoring

logger = logging.getLogger(__name__)

def _coerce_candidates(v) -> List[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return []
    s = str(v).strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        try:
            lst = json.loads(s.replace("'", '"'))
            if isinstance(lst, list):
                return [str(x).strip() for x in lst if str(x).strip()]
        except Exception:
            pass
    return [x.strip() for x in s.split(";") if x.strip()]


def process_single_taxon(row_data: dict, repo: NcbiRepository) -> dict:
    raw_taxon = row_data["taxon"]
    taxon, _ = ncbi_scoring.normalize_name(raw_taxon)

    cands = row_data.get("mat_candidates_str")
    cands = _coerce_candidates(cands) if not isinstance(cands, list) else cands
    if not cands:
        mat = row_data.get("mat")
        if mat is not None and pd.notna(mat) and str(mat).strip():
            cands = [str(mat).strip()]

    recs = repo.fetch_records(taxon)
    if not recs:
        confres = ncbi_scoring.compute_confidence_from_scores([])
        comp = confres["components"]
        return {
            "taxon": taxon,
            "suggested_gem": "",
            "canonical": "",
            "rank": "",
            "lineage_genera": "",
            "synonyms": "",
            "n_candidates": len(cands),
            "ranked_candidates": "",
            "ncbi_taxid": "",
            "confidence": confres["tier"],
            "tier": confres["tier"],
            "n_top_ties": comp["n_top"],
            "top_score": comp["top_score"],
            "rationale_scoring": "No NCBI record",
        }

    rec = next((r for r in recs if r.get("ScientificName", "") == taxon), recs[0])
    info = ncbi_scoring.parse_tax_record(rec)
    info = ncbi_scoring.expand_with_aka_merged(info, repo.cache)

    pool = ncbi_scoring.build_name_pool(info)
    lineage_genera = info.get("lineage_genera", [])

    scored: list[tuple[str, int, str]] = []
    seen: set[str] = set()
    for m in (cands or []):
        if not m or m in seen:
            continue
        seen.add(m)
        sc, why = ncbi_scoring.score_gem_against_pool(m, pool, lineage_genera, info=info)
        scored.append((m, sc, why))

    scored.sort(key=lambda x: (-x[1], len(x[0]) if isinstance(x[0], str) else 1_000_000))
    score_list = [sc for (_, sc, __) in scored]
    confres = ncbi_scoring.compute_confidence_from_scores(score_list)
    comp = confres["components"]

    ranked_str = ";".join(f"{m}@@{s}@@{r}" for (m, s, r) in scored) if scored else ""
    suggestion = scored[0][0] if scored else ""
    rationale_scoring = scored[0][2] if scored else "No scored candidate"

    return {
        "taxon": taxon,
        "suggested_gem": suggestion,
        "canonical": info.get("canonical", ""),
        "rank": info.get("rank", ""),
        "lineage_genera": "|".join(info.get("lineage_genera", [])),
        "synonyms": "|".join(sorted(pool)),
        "n_candidates": len(scored),
        "n_top_ties": comp["n_top"],
        "top_score": comp["top_score"],
        "tier": confres["tier"],
        "confidence": confres["tier"],
        "ranked_candidates": ranked_str,
        "ncbi_taxid": info.get("taxid", ""),
        "rationale_scoring": rationale_scoring,
    }


def run_ncbi_rescue(candidates: List[Dict[str, Any]], ncbi_cache_path: str) -> List[Dict[str, Any]]:
    repo = NcbiRepository(ncbi_cache_path)
    if not candidates:
        return []

    rows: List[Dict[str, Any]] = []
    for row in candidates:
        base = process_single_taxon(row, repo)
        merged = dict(row)
        merged.update(base)
        rows.append(merged)

    out = pd.DataFrame(rows)

    out["canonical_gs"] = out["canonical"].astype(str).apply(ncbi_scoring._canonical_to_gs)
    out["gs_aliases"] = out["synonyms"].astype(str).apply(ncbi_scoring._gs_aliases_from_pool)

    res = out.apply(ncbi_scoring._reclassify_row, axis=1)
    out = pd.concat([out, res], axis=1)

    def _count_100s_and_median(row):
        ranked = row.get("ranked_candidates", "")
        if not isinstance(ranked, str) or not ranked.strip():
            return pd.Series({"n_100s": 0, "median_score": None})
        try:
            scores = []
            for item in ranked.split(";"):
                parts = item.split("@@")
                if len(parts) >= 2:
                    try:
                        scores.append(float(parts[1]))
                    except Exception:
                        pass
            if not scores:
                return pd.Series({"n_100s": 0, "median_score": None})
            return pd.Series({
                "n_100s": sum(s == 100 for s in scores),
                "median_score": statistics.median(scores)
            })
        except Exception:
            return pd.Series({"n_100s": 0, "median_score": None})

    stats_df = out.apply(_count_100s_and_median, axis=1)
    out = pd.concat([out, stats_df], axis=1)

    def _to_float(x, default=0.0):
        try:
            if x is None or (isinstance(x, float) and pd.isna(x)):
                return default
            return float(x)
        except Exception:
            return default

    def _to_int(x, default=0):
        try:
            if x is None or (isinstance(x, float) and pd.isna(x)):
                return default
            return int(x)
        except Exception:
            return default

    single_100_mask = (
            (out["final_color"] == "yellow")
            & (out["top_score"].apply(_to_float) >= 99.999)
            & (out["n_top_ties"].apply(_to_int) == 1)
    )
    if single_100_mask.any():
        out.loc[single_100_mask, "final_color"] = "yellow_green"
        if "rationale_final" not in out.columns:
            out["rationale_final"] = ""
        out.loc[single_100_mask, "rationale_final"] = (
                out.loc[single_100_mask, "rationale_final"].fillna("").astype(str)
                + " | reclassified to YELLOW_GREEN: unique 100-score top candidate"
        )

    heavy_ties_mask = (
            (out["final_color"] == "yellow")
            & (
                    (out["n_top_ties"].fillna(0).astype(float) > 10)
                    | (out["n_100s"].fillna(0).astype(float) > 10)
            )
    )
    if heavy_ties_mask.any():
        out.loc[heavy_ties_mask, "final_color"] = "red"
        if "rationale_final" not in out.columns:
            out["rationale_final"] = ""
        out.loc[heavy_ties_mask, "rationale_final"] = (
                out.loc[heavy_ties_mask, "rationale_final"].fillna("").astype(str)
                + "downgraded to RED: excessive candidate degeneracy (n_top_ties > 10 or n_100s > 10)"
        )

    def _leq20_or_nan(x):
        try:
            if x is None or (isinstance(x, float) and pd.isna(x)):
                return True
            return float(x) <= 20.0
        except Exception:
            return True

    ms_bad = out["median_score"].apply(_leq20_or_nan)
    ts_bad = out["top_score"].apply(_leq20_or_nan)
    out["is_not_found"] = ms_bad & ts_bad

    mask_nf = out["is_not_found"]
    out.loc[mask_nf, "final_color"] = "black"
    out.loc[mask_nf, "match_level"] = "none"
    out.loc[mask_nf, "suggested_gem"] = "no_suggestion"
    out.loc[mask_nf, "ranked_candidates"] = "no candidates"

    out["final_band"] = out["final_color"]

    return out.to_dict(orient="records")
