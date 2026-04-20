import logging
import json
from typing import List, Dict, Any

from ..schemas.report import MappingReport, MappingItem, MappingCandidate, MappingStatus

logger = logging.getLogger(__name__)

def determine_status_and_score(row: Dict[str, Any]) -> tuple[MappingStatus, float]:
    raw_band = str(row.get("final_band") or row.get("bands") or "red")
    band = raw_band.lower().replace("-", "_").strip()

    j_score = float(row.get("j_score") or 0.0)
    final_score = j_score

    if "green" in band and "yellow" not in band:
        return MappingStatus.GREEN, 1.0

    if "auto_accept" in band:
        return MappingStatus.GREEN, 1.0

    if "yellow_green" in band:
        return MappingStatus.YELLOW_GREEN, 0.95

    if "yellow" in band or "grey_zone" in band:
        return MappingStatus.YELLOW, max(final_score, 0.60)

    if "black" in band or "not_found" in band:
        return MappingStatus.BLACK, 0.0

    return MappingStatus.RED, final_score


def parse_candidates(row: Dict[str, Any]) -> List[MappingCandidate]:

    candidates: List[MappingCandidate] = []

    ranked_data = row.get("ranked_candidates")
    if ranked_data and isinstance(ranked_data, list) and len(ranked_data) > 0:
        for cand in ranked_data:
            raw_s = cand.get("score", 0)
            try:
                c_score = float(raw_s) / 100.0
            except Exception:
                c_score = 0.0

            candidates.append(MappingCandidate(
                model_id=str(cand.get("model", "unknown")),
                score=round(c_score, 2),
                reason=str(cand.get("reason", "Rescue Analysis"))
            ))
        return candidates

    cands_input = row.get("mat_candidates_str")
    raw_list: List[Any] = []

    if isinstance(cands_input, list):
        raw_list = cands_input
    elif isinstance(cands_input, str) and cands_input.strip():
        s = cands_input.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                raw_list = json.loads(s.replace("'", '"'))
            except Exception:
                raw_list = [x.strip() for x in s.split(";") if x.strip()]
        else:
            raw_list = [x.strip() for x in s.split(";") if x.strip()]

    if not raw_list:
        mat = row.get("mat")
        if mat:
            raw_list = [mat]
        else:
            return []

    winner = row.get("suggested_gem") or row.get("mat")
    try:
        j_score = float(row.get("j_score") or 0.5)
    except Exception:
        j_score = 0.5

    for mod in raw_list:
        mod = str(mod).strip()
        if not mod:
            continue
        is_winner = (mod == winner)
        score_val = j_score if is_winner else 0.5

        candidates.append(MappingCandidate(
            model_id=mod,
            score=round(score_val, 2),
            reason="Jaccard Similarity"
        ))

    return candidates


def assemble_report(job_id: str, rows: List[Dict[str, Any]]) -> MappingReport:
    items: List[MappingItem] = []

    for row in rows:
        status, conf = determine_status_and_score(row)

        mapped_id = row.get("suggested_gem") or row.get("mat") or ""
        query_name = row.get("taxa_name") or row.get("taxon") or row.get("input_name") or "Unknown"

        abundance_val = row.get("abundance")
        if abundance_val is not None:
            try:
                if isinstance(abundance_val, float) and (abundance_val != abundance_val):
                    abundance_val = None
                else:
                    abundance_val = float(abundance_val)
            except (ValueError, TypeError):
                abundance_val = None
        items.append(MappingItem(
            query_name=query_name,
            abundance=abundance_val,
            mapped_id=mapped_id,
            status=status,
            confidence_score=round(float(conf), 4),
            candidates=parse_candidates(row)
        ))

    return MappingReport(
        job_id=job_id,
        total_bacteria=len(items),
        results=items
    )
