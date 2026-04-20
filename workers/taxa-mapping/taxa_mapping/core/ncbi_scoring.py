import logging
import re
import math
import statistics
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

_CANDIDATUS_RE = re.compile(r"^\s*Candidatus\s+", flags=re.IGNORECASE)
_SP_RE = re.compile(r"\bsp\.?\b", re.IGNORECASE)

_INFRASPECIFIC_RE = re.compile(
    r"\b(subsp\.?|ssp\.?|subspecies|strain|pv\.?|pathovar|serovar|biovar|var\.?|variant|f\.?|forma)\b",
    flags=re.IGNORECASE
)
_INFRA_PAIR_RE = re.compile(
    r"\b(subsp\.?|ssp\.?|subspecies|pv\.?|pathovar|serovar|biovar|var\.?|variant|f\.?|forma)\s+([A-Za-z0-9_.-]+)\b",
    flags=re.IGNORECASE
)
_AUTHORSHIP_RE = re.compile(r"\s*\([^)]*\)\s*")

_SUBSP_MARKER_RE = re.compile(r"(?i)\b(subsp(?:\.|ecies)?|ssp\.?)\b")


def _soft_rescue_stage(n_top_ties, top_score, median_score,
                       tie_red_threshold=5, median_yellow_threshold=70.0) -> Optional[str]:
    try:
        if float(top_score) < 100:
            return None
    except Exception:
        return None
    try:
        nt = int(n_top_ties)
    except Exception:
        nt = 0
    ms = median_score
    if nt <= tie_red_threshold and (ms is None or (isinstance(ms, (int, float)) and ms < median_yellow_threshold)):
        return "yellow"
    return None


def _extract_infraspecific_epithet(name: str) -> str | None:
    if not isinstance(name, str):
        return None
    m = _INFRA_PAIR_RE.search(name)
    if not m:
        return None
    return m.group(2)


def _sanitize_punct(s: str) -> str:
    s = re.sub(r"[\[\]\(\)\{\}:;,\|]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _strip_candidatus(s: str) -> str:
    return _CANDIDATUS_RE.sub("", s).strip()


def _strip_infraspecific(s: str) -> str:
    s2 = s
    m = _INFRASPECIFIC_RE.search(s2)
    if m:
        s2 = s2[:m.start()].strip()
    s2 = re.sub(r"\bsp\.?\s+\S.*$", "sp.", s2, flags=re.IGNORECASE).strip()
    s2 = re.sub(r"\s+", " ", s2).strip()
    return s2


def normalize_name(raw: str) -> Tuple[str, Dict[str, Any]]:
    meta = {"original": raw}
    name = raw or ""
    if name.startswith("NAME::"):
        name = name[len("NAME::"):]
        meta["dropped_prefix"] = True
    name = re.sub(r"\s+", " ", name).strip()
    meta["with_authorship"] = name
    stripped = _AUTHORSHIP_RE.sub("", name).strip()
    if stripped != name:
        meta["stripped_authorship"] = stripped
    stripped2 = re.sub(r"\bsp\.\s*$", "", stripped, flags=re.IGNORECASE).strip()
    if stripped2 != stripped:
        meta["removed_sp"] = True
    meta["normalized"] = stripped2
    return name, meta


def _norm(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s.strip())
    s = re.sub(r"^\[([^\]]+)\]\s*", r"\1 ", s)
    parts = s.split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return s


def _canon_name(s: str) -> str:
    if not s:
        return ""
    s = s.replace("/", " ")
    s = re.sub(r"[_\-.]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = _SP_RE.sub("sp", s)
    return s


def _is_sp_placeholder(s: str) -> bool:
    s2 = _canon_name(s)
    return bool(re.search(r"^\w+\s+sp(\s|$)", s2))


def _norm_tokens(s: str) -> List[str]:
    s = re.sub(r"[=:\-\./\+\(\)]", "_", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("_")
    return [t for t in s.split("_") if t]


def _extract_gs_from_model_name(mat: str) -> Optional[str]:
    toks = _norm_tokens(mat)
    if len(toks) >= 2 and toks[0] and toks[0][0].isupper():
        return f"{toks[0]} {toks[1]}"
    return None


def score_gem_against_pool(model_id: str, pool: set[str], lineage_genera: list[str], info: dict = None):
    gs = _extract_gs_from_model_name(model_id)
    if not gs:
        return 0, "no genus/species parsed from model"
    mg, ms = gs.split()[:2]
    mg_c, ms_c = _canon_name(mg), _canon_name(ms)
    pool_canon = {_canon_name(x) for x in (pool or [])}

    if f"{mg_c} {ms_c}" in pool_canon and ms_c != "sp":
        return 100, "exact genus+species match"

    model_is_sp = (ms_c == "sp")
    pool_has_genus_sp = any(_is_sp_placeholder(x) and _canon_name(x).startswith(f"{mg_c} sp") for x in pool)
    if model_is_sp and pool_has_genus_sp:
        return 75, "genus + 'sp' placeholder match"

    lineage_canon = {_canon_name(g) for g in (lineage_genera or [])}
    if mg_c in lineage_canon:
        canonical = (info or {}).get("canonical", "")
        if _is_sp_placeholder(canonical):
            return 70, "genus matches and NCBI canonical is 'Genus sp'"
        return 60, "genus matches NCBI lineage"

    return 20, "weak/partial token overlap"


def compute_confidence_from_scores(scores, tie_red_threshold=5, median_yellow_threshold=75.0):
    s = []
    if scores:
        try:
            s = [int(x) for x in scores if x is not None and not (isinstance(x, float) and math.isnan(x))]
        except Exception:
            s = []
    s.sort(reverse=True)
    K = len(s)
    if K == 0:
        return {"tier": "red", "components": {"n_top": 0, "K": 0, "top_score": 0, "scores": [], "median_other": None}}

    top = s[0]
    n_top = sum(1 for x in s if x == top)
    others = [x for x in s if x < top]
    med_other = statistics.median(others) if others else None

    if top < 100:
        return {"tier": "red", "components": {"n_top": n_top, "K": K, "top_score": top, "scores": s, "median_other": med_other}}

    if n_top == 1:
        return {"tier": "green", "components": {"n_top": n_top, "K": K, "top_score": top, "scores": s, "median_other": med_other}}

    tier = "red" if n_top > tie_red_threshold else ("yellow" if (med_other is None or med_other < median_yellow_threshold) else "red")
    return {"tier": tier, "components": {"n_top": n_top, "K": K, "top_score": top, "scores": s, "median_other": med_other}}


def parse_tax_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    sci = rec.get("ScientificName") or ""
    txid = rec.get("TaxId") or ""
    rank = rec.get("Rank") or ""
    other = rec.get("OtherNames") or {}
    aka = rec.get("AkaTaxIds") or []
    merged = rec.get("MergedTaxIds") or []

    lin_ex: List[Dict[str, Any]] = rec.get("LineageEx") or []
    lineage = [
        {"name": x.get("ScientificName", "") or "", "rank": x.get("Rank", "") or "", "taxid": x.get("TaxId", "") or ""}
        for x in lin_ex if isinstance(x, dict)
    ]
    lineage_genera = sorted({x["name"] for x in lineage if x.get("rank") == "genus" and x.get("name")})

    syns: Set[str] = set()
    syns.add(_norm(sci))

    for key in ("Synonym", "GenbankSynonym", "EquivalentName", "Includes"):
        v = other.get(key)
        if isinstance(v, list):
            for s in v:
                if isinstance(s, str):
                    syns.add(_norm(s))
        elif isinstance(v, str):
            syns.add(_norm(v))

    v = other.get("Name")
    if isinstance(v, list):
        for item in v:
            if isinstance(item, dict) and "DispName" in item:
                syns.add(_norm(item["DispName"]))
            elif isinstance(item, str):
                syns.add(_norm(item))
    elif isinstance(v, str):
        syns.add(_norm(v))

    canonical = _norm(sci)
    parts = canonical.split()
    genus = parts[0] if parts else ""
    epithet = parts[1] if len(parts) >= 2 else ""

    return {
        "canonical": canonical,
        "taxid": txid,
        "rank": rank,
        "genus": genus,
        "species_epithet": epithet,
        "lineage_genera": lineage_genera,
        "synonyms": sorted({s for s in syns if s}),
        "aka_taxids": aka,
        "merged_taxids": merged,
    }


def cache_fetch_by_taxids(taxids: List[str], cache: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not taxids:
        return []
    ids = sorted({str(x).strip() for x in taxids if str(x).strip()})
    if not ids:
        return []
    key = f"IDS::{','.join(ids)}"
    recs = cache.get(key)
    return recs if isinstance(recs, list) else []


def expand_with_aka_merged(base: Dict[str, Any], cache: Dict[str, Any]) -> Dict[str, Any]:
    extra_ids = []
    extra_ids.extend([str(x) for x in base.get("aka_taxids", []) if x])
    extra_ids.extend([str(x) for x in base.get("merged_taxids", []) if x])
    if not extra_ids:
        return base

    recs = cache_fetch_by_taxids(extra_ids, cache)
    add_syn: Set[str] = set(base["synonyms"])

    for r in recs:
        add_syn.add(_norm(r.get("ScientificName", "")))
        o = r.get("OtherNames") or {}
        for key in ("Synonym", "GenbankSynonym", "EquivalentName", "Includes"):
            v = o.get(key)
            if isinstance(v, list):
                for x in v:
                    if isinstance(x, str):
                        add_syn.add(_norm(x))
            elif isinstance(v, str):
                add_syn.add(_norm(v))

        v = o.get("Name")
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and "DispName" in item:
                    add_syn.add(_norm(item["DispName"]))
                elif isinstance(item, str):
                    add_syn.add(_norm(item))
        elif isinstance(v, str):
            add_syn.add(_norm(v))

    base["synonyms"] = sorted({s for s in add_syn if s})
    return base


def build_name_pool(info: Dict[str, Any]) -> Set[str]:
    primary: str = info.get("canonical", "") or ""
    syns: List[str] = info.get("synonyms", []) or []
    lineage_genera: List[str] = info.get("lineage_genera", []) or []

    pool: Set[str] = set()
    all_names = [primary] + syns
    pool.update(all_names)

    for nm in list(all_names):
        parts = nm.split()
        if len(parts) >= 2:
            epithet = parts[1]
            for g in lineage_genera:
                pool.add(f"{g} {epithet}")

    return {_norm(x) for x in pool if _norm(x)}


def _canonical_to_gs(canonical: str) -> str:
    if not canonical:
        return ""
    parts = re.sub(r"\s+", " ", canonical.strip()).split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return canonical


def _gs_aliases_from_pool(synonyms_field: str) -> set[tuple[str, str]]:
    aliases = set()
    if isinstance(synonyms_field, str) and synonyms_field.strip():
        for nm in synonyms_field.split("|"):
            parts = re.sub(r"\s+", " ", nm.strip()).split()
            if len(parts) >= 2:
                g, s = parts[0].lower(), parts[1].lower().rstrip(".")
                aliases.add((g, s))
    return aliases


def norm_id_strict(s: str) -> str:
    s = re.sub(r"[^\w]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_").lower()


def _split_tokens_strict(s: str) -> List[str]:
    return [t for t in norm_id_strict(s).split("_") if t]


def _has_subspecies_marker(s: str) -> bool:
    return bool(isinstance(s, str) and _SUBSP_MARKER_RE.search(s))


def _classify_match_strict(input_name: str,
                           model_id: str,
                           canonical_gs: str,
                           gs_aliases: set[tuple[str, str]]):
    in_tokens = _split_tokens_strict(input_name)
    if len(in_tokens) < 2:
        return {"match_level": "none", "gs_match": False}

    canon_tokens = _split_tokens_strict(canonical_gs)
    if len(canon_tokens) < 2:
        return {"match_level": "none", "gs_match": False}

    model_id_core = re.sub(r"\.mat$", "", str(model_id), flags=re.IGNORECASE)
    model_norm_full = norm_id_strict(model_id_core).lower()
    model_gs_tokens = _split_tokens_strict(model_id_core)[:2]
    model_gs_l = tuple(t.lower() for t in model_gs_tokens)

    candidates: list[tuple[str, str]] = [tuple(t.lower() for t in canon_tokens[:2])]
    if gs_aliases:
        for g, s in gs_aliases:
            if g and s:
                candidates.append((g.lower(), s.lower()))

    input_tail = [t.lower() for t in in_tokens[2:]]
    for gs in candidates:
        syn_tokens = list(gs) + input_tail
        input_norm_full = "_".join(syn_tokens)
        if input_norm_full == model_norm_full:
            return {"match_level": "full_exact", "gs_match": True}

    if any(model_gs_l == gs for gs in candidates):
        return {"match_level": "gs_exact", "gs_match": True}

    return {"match_level": "none", "gs_match": False}


def _to_int(x, default=0):
    try:
        if x is None:
            return default
        return int(float(x))
    except Exception:
        return default


def _reclassify_row(row: pd.Series) -> pd.Series:
    input_name = str(row.get("input_name", "") or row.get("taxon", "") or "").strip()
    model_id_raw = str(row.get("suggested_gem", "") or "").strip()
    model_id = re.sub(r"\.mat$", "", model_id_raw, flags=re.IGNORECASE)
    canonical_gs = str(row.get("canonical_gs", "") or "").strip()
    gs_aliases = row.get("gs_aliases", set())
    if not isinstance(gs_aliases, (set, list, tuple)):
        gs_aliases = set()

    if not input_name or not model_id:
        return pd.Series({
            "final_color": row.get("confidence", ""),
            "match_level": "none",
            "rationale_final": "unchanged: missing fields for strict check"
        })

    model_core = re.sub(r"\.mat$", "", model_id, flags=re.IGNORECASE)
    model_tokens = _split_tokens_strict(model_core)
    model_gs_l = tuple(t.lower() for t in model_tokens[:2]) if len(model_tokens) >= 2 else ()

    verdict = _classify_match_strict(input_name, model_id, canonical_gs, gs_aliases)
    ml = verdict.get("match_level", "none")

    in_tok = _split_tokens_strict(input_name)
    if len(in_tok) >= 2 and model_gs_l:
        genus_tok = in_tok[0].lower()
        species_tok = in_tok[1].lower()
        infra_ep = _extract_infraspecific_epithet(input_name)
        infra_ep_l = infra_ep.lower() if infra_ep else None

        if _has_subspecies_marker(input_name) and infra_ep_l and infra_ep_l != species_tok:
            promoted_gs = (genus_tok, infra_ep_l)
            if model_gs_l == promoted_gs:
                return pd.Series({
                    "final_color": "green",
                    "match_level": "full_exact",
                    "rationale_final": "species elevation: subspecies epithet equals promoted species in model (promoted to full_exact)"
                })

    if ml == "full_exact":
        return pd.Series({"final_color": "green", "match_level": "full_exact",
                          "rationale_final": "full 1:1 normalized match after GS synonymization"})

    if ml == "gs_exact":
        ntie = _to_int(row.get("n_top_ties"), 0)
        if ntie > 10:
            return pd.Series({
                "final_color": "red",
                "match_level": "gs_exact",
                "rationale_final": "GS exact via canonical/alias, but downgraded to RED: high 100s-tie count"
            })

    soft = _soft_rescue_stage(
        n_top_ties=row.get("n_top_ties", 0),
        top_score=row.get("top_score", 0),
        median_score=row.get("median_score", None),
        tie_red_threshold=5,
        median_yellow_threshold=70.0
    )

    if soft == "yellow":
        return pd.Series({
            "final_color": "yellow",
            "match_level": "none",
            "rationale_final": "soft-rescue (Stage B): tie structure consistent with species-level agreement, but no GS equality"
        })

    return pd.Series({
        "final_color": "yellow",
        "match_level": "gs_exact",
        "rationale_final": "GS exact via canonical or pool alias (synonym/reclassification)"
    })
