import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CANDIDATUS_RE = re.compile(r"^\s*Candidatus\s+", flags=re.IGNORECASE)
_INFRASPECIFIC_RE = re.compile(
    r"\b(subsp\.?|ssp\.?|subspecies|strain|pv\.?|pathovar|serovar|biovar|var\.?|variant|f\.?|forma)\b",
    flags=re.IGNORECASE
)
_STRAIN_TOKEN_RE = re.compile(r"\b([A-Za-z]{1,5}[A-Za-z0-9_.-]{2,})\b")


def _strip_parenthetical_authorship(s: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*", " ", s).strip()


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


def _extract_strain_token(s: str) -> Optional[str]:
    if not s:
        return None
    STOP = {"strain", "subsp", "ssp", "pv", "serovar", "biovar", "var", "variant", "sp", "genus", "species", "candidatus"}
    toks = re.split(r"\s+", s.strip())
    for t in reversed(toks):
        t_clean = re.sub(r"[^A-Za-z0-9_.-]", "", t)
        if not t_clean or t_clean.lower() in STOP:
            continue
        m = _STRAIN_TOKEN_RE.fullmatch(t_clean)
        if m:
            return m.group(1)
    return None


class NcbiRepository:

    def __init__(self, cache_path: str):
        self.cache_path = Path(cache_path)
        self.cache: Dict[str, Any] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            logger.warning(f"NCBI cache not found: {self.cache_path}")
            self.cache = {}
            return
        try:
            self.cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.exception(f"Failed to load cache {self.cache_path}: {e}")
            self.cache = {}

    def fetch_records(self, raw_name: str) -> List[Dict[str, Any]]:
        if not raw_name:
            return []

        name = re.sub(r"\s+", " ", str(raw_name)).strip()
        if not name:
            return []

        stripped = _strip_parenthetical_authorship(name)
        san = _sanitize_punct(stripped or name)

        cand = _strip_candidatus(san or stripped or name)
        infra = _strip_infraspecific(cand or san or stripped or name)

        variants: List[str] = []
        for v in [name, stripped, san, cand, infra]:
            if v and v not in variants:
                variants.append(v)

        token = _extract_strain_token(infra or cand or san or stripped or name)
        genus = (infra or cand or san or stripped or name).split()[0] if (infra or cand or san or stripped or name).split() else None

        if token:
            for v in [token, f"{genus} {token}" if genus else None]:
                if v and v not in variants:
                    variants.append(v)

        if genus and genus not in variants:
            variants.append(genus)

        for v in variants:
            recs = self.cache.get(f"TAX::{v}")
            if isinstance(recs, list) and recs:
                return recs

        return []

    def fetch_by_taxids(self, taxids: List[str]) -> List[Dict[str, Any]]:
        if not taxids:
            return []
        ids = sorted({str(x).strip() for x in taxids if str(x).strip()})
        if not ids:
            return []
        key = f"IDS::{','.join(ids)}"
        recs = self.cache.get(key)
        return recs if isinstance(recs, list) else []
