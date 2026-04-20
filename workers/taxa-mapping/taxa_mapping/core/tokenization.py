import re
import unicodedata
import pandas as pd
from typing import List, Optional, Set

from .constants import (
    CC_PREFIXES, CONTEXT_STOPS, ADJ_MODS, HEADS, DESC_START,
    COMMON_CONTEXT_NOUNS, EPITHET_RX, INFRA_RX,
    ADMIN_TOKENS_RX, CODE_WORD_RX, CODE_NUM_RX,
    AUTH_RX_1, AUTH_RX_2, CODE_OR_CC_RX
)

def has_code_or_cc(text: str) -> int:
    if not isinstance(text, str):
        return 0
    return 1 if CODE_OR_CC_RX.search(text) else 0


def _is_code_word(w: str) -> bool:
    return (CODE_WORD_RX.match(w) is not None
            and w.lower() not in COMMON_CONTEXT_NOUNS)


def _is_code_num(w: str) -> bool:
    return CODE_NUM_RX.match(w) is not None


def is_descriptive_anchor(a: str) -> bool:
    if not isinstance(a, str) or not a:
        return False
    w = a.split()
    if not w:
        return False
    if w[0].lower() in DESC_START:
        return True
    return len(w) >= 2 and w[0].lower() in ADJ_MODS and w[1].lower() in HEADS

def strip_authorship_notes(s: str) -> str:

    if not isinstance(s, str):
        return s
    s = AUTH_RX_1.sub('', s)
    s = AUTH_RX_2.sub('', s)
    return s


def clean_and_tokenize(s: str, cc_prefixes: List[str] = CC_PREFIXES) -> List[str]:
    s = re.sub(r'\[([^\]]+)\]', r'\1', s)
    s = strip_authorship_notes(s)

    cc_alt = "|".join(cc_prefixes)

    cc_pat_pre = rf"(?i)\b({cc_alt})\s*[-/]?[A-Z]*\s*\d+[A-Za-z0-9-]*\b"

    cc_pat_post = rf"(?i)(?<![A-Za-z0-9])({cc_alt})(?:_[A-Z]+)?_\d+[A-Za-z0-9-]*(?![A-Za-z0-9])"

    cc_pat_compact = rf"(?i)(?<![A-Za-z0-9])({cc_alt})[A-Z]*\d+[A-Za-z0-9-]*(?![A-Za-z0-9])"

    cc_pre_tokens = []
    for match in re.finditer(cc_pat_pre, s):
        token = match.group(0).strip()
        token = re.sub(r'[\s]+|[-/]', '_', token)
        token = re.sub(r'[^A-Za-z0-9_]', '_', token)
        token = re.sub(r'_+', '_', token)
        cc_pre_tokens.append(token)
    cc_pre_tokens = list(set(cc_pre_tokens))

    s_norm = s
    replacements = {
        ' ': '_', ':': '_', '-': '_', '.': '_', '/': '_',
        '+': '_', '(': '_', ')': '_', '=': '_'
    }
    for old, new in replacements.items():
        s_norm = s_norm.replace(old, new)

    s_norm = re.sub(r'substr_|str_|subsp_', '', s_norm)
    s_norm = re.sub(r'_{2,}', '_', s_norm)

    cc_post_u_full = [m.group(0) for m in re.finditer(cc_pat_post, s_norm)]
    cc_post_c_full = [m.group(0) for m in re.finditer(cc_pat_compact, s_norm)]
    cc_post = list(set(cc_post_u_full + [c for c in cc_post_c_full if c not in cc_post_u_full]))

    base_tokens = [t for t in s_norm.split('_') if t]

    all_alias_tokens = list(set(cc_pre_tokens + cc_post))
    if all_alias_tokens:
        parts_to_drop = set()
        for alias in all_alias_tokens:
            parts_to_drop.update(alias.split('_'))
        base_tokens = [t for t in base_tokens if t not in parts_to_drop]

    return sorted(list(set(base_tokens + all_alias_tokens)))


def _toklist(s: str) -> List[str]:

    if not isinstance(s, str):
        return []
    toks = [re.sub(r'^[\W_]+|[\W_]+$', '', t) for t in s.split()]
    return [t for t in toks if t]


def extract_anchor(taxon: str) -> Optional[str]:
    if taxon is None:
        return None

    if isinstance(taxon, float) and pd.isna(taxon):
        return None

    s = str(taxon).strip()
    if not s:
        return None

    s = re.sub(r'\[([A-Za-z][^\]]*)\]', r'\1', s)
    s = re.sub(r'^\s*\[([A-Za-z][^\]]*)\]\s+', r'\1 ', s)

    words = s.split()
    if not words:
        return None

    def _clean(tok: str) -> str:
        return tok.rstrip('.,;')

    first = _clean(words[0])
    first_l = first.lower()

    if len(words) >= 3 and first_l in {'candidatus', '"candidatus"'} and words[1][0].isupper():
        g = _clean(words[1])
        w2 = _clean(words[2])
        w2l = w2.lower()
        if w2l in {'sp', 'sp.', 'spp', 'spp.'}:
            return f"{g} {'spp' if w2l.startswith('spp') else 'sp'}"
        if EPITHET_RX.match(w2):
            return f"{g} {w2}"

    if len(words) >= 2 and words[0][0].isupper() and words[0][0].isalpha():
        second = _clean(words[1])
        second_l = second.lower()
        if second_l in {'sp', 'sp.', 'spp', 'spp.'}:
            return f"{words[0]} {'spp' if second_l.startswith('spp') else 'sp'}"
        if EPITHET_RX.match(second):
            return f"{words[0]} {second}"

    if len(words) >= 2 and first_l in ADJ_MODS and _clean(words[1]).lower() in HEADS:
        return f"{first} {_clean(words[1])}"

    if first_l == 'uncultured' and len(words) >= 2 and words[1][0].isupper():
        genus = _clean(words[1])
        if len(words) >= 3 and _clean(words[2]).lower() in {'sp', 'sp.', 'spp', 'spp.'}:
            return f"uncultured {genus} {'spp' if _clean(words[2]).lower().startswith('spp') else 'sp'}"
        return f"uncultured {genus} sp"

    if first_l in DESC_START:
        anchor = [first]
        i = 1
        while i < len(words) and len(anchor) < 3:
            w = _clean(words[i])
            wl = w.lower()

            if wl == 'bacterial' and (i + 1) < len(words):
                w2 = _clean(words[i + 1])
                if w2.lower() in HEADS:
                    anchor.append('bacterial')
                    if len(anchor) < 3:
                        anchor.append(w2)
                    break

            if any(ch.isdigit() for ch in w) or w.isupper() or len(w) <= 2 or wl in CONTEXT_STOPS:
                break

            anchor.append(w)

            if wl in {'bacterium', 'archaeon', 'organism', 'cyanobacterium'}:
                break
            i += 1

        return ' '.join(anchor)

    if len(words) >= 2:
        second = _clean(words[1])
        second_l = second.lower()

        if second_l in ADJ_MODS and len(words) >= 3 and _clean(words[2]).lower() in HEADS:
            return f"{_clean(words[0])} {second} {_clean(words[2])}"

        if second_l == 'bacterial' and len(words) >= 3 and _clean(words[2]).lower() in HEADS:
            return f"{_clean(words[0])} bacterial {_clean(words[2])}"

        if second_l in (HEADS | {'bacterial'}):
            a = [_clean(words[0]), second]
            if len(words) >= 3:
                w3 = _clean(words[2])
                if not (any(ch.isdigit() for ch in w3) or w3.isupper() or w3.lower() in CONTEXT_STOPS):
                    a.append(w3)
            return ' '.join(a)

    if len(words) >= 2:
        return f"{_clean(words[0])} {_clean(words[1])}"
    return _clean(words[0])

def _best_digit_token(tokens: List[str]) -> Optional[str]:

    if not tokens:
        return None
    alnum = [t for t in tokens if re.search(r'\d', t) and re.search(r'[A-Za-z]', t)]
    if alnum:
        return sorted(alnum, key=lambda t: (-len(t), t))[0].rstrip('._/-')
    digit_only = [t for t in tokens if re.search(r'\d', t)]
    if digit_only:
        return digit_only[-1].rstrip('._/-')
    return None


def build_anchor(name: str, anchor: str, cc_prefixes: List[str] = CC_PREFIXES) -> str:

    if not isinstance(anchor, str) or not anchor:
        return anchor
    if is_descriptive_anchor(anchor):
        return anchor

    s = name
    try:
        s = unicodedata.normalize('NFKC', s)
    except Exception:
        pass

    s = re.sub(r'[\u200B\u200C\u200D\u2060\uFEFF]+', '', s)
    s = re.sub(r'[\s\u00A0]+', ' ', s).strip()
    s = re.sub(r'[\u2010-\u2015\u2212\u2043]', '-', s)
    s = re.sub(r'[\u2044\u2215\uFF0F]', '/', s)
    s = re.sub(r'^["\'](.+)["\']$', r'\1', s)
    s = re.sub(r'\[([A-Za-z][^\]]*)\]', r'\1', s)

    cand_prefix = ''
    if re.match(r'^\s*"?candidatus"?\s+', s, flags=re.IGNORECASE):
        cand_prefix = '' if anchor.lower().startswith('candidatus ') else 'Candidatus '

    toks = anchor.split()
    if len(toks) < 2:
        return (cand_prefix + anchor).strip() if cand_prefix else anchor

    G, S = toks[0], toks[1]
    gs = f"{G} {S}"
    if S.lower() in {'sp', 'spp'}:
        return (cand_prefix + anchor).strip() if cand_prefix else anchor

    try:
        gs_rx = re.compile(rf'(?i)\b{re.escape(G)}\s+{re.escape(S)}\b')
    except re.error:
        gs_rx = None
    tail = s[gs_rx.search(s).end():] if (gs_rx and gs_rx.search(s)) else s

    m_var = re.search(
        r'(?i)\b(?:subsp(?:\.|ecies)?|pv\.?|pathovar|var\.?|variety|biovar|serovar)\s+([A-Za-z][A-Za-z0-9-]*)\b',
        tail
    )
    if m_var:
        epithet = m_var.group(1)
        out = f"{cand_prefix}{gs} {epithet}"
        post = tail[m_var.end():]

        cc_alt = '|'.join(cc_prefixes)
        m_cc = re.search(rf'(?i)\b({cc_alt})\s*[-_/]?\s*[A-Z]*\s*\d+[A-Za-z0-9-]*\b', post)
        if m_cc:
            cc = re.sub(r'\s+|[-/]', '_', m_cc.group(0))
            cc = re.sub(r'_+', '_', cc).strip('_')
            return f"{out} {cc.replace('_', ' ')}"

        toks_post = re.findall(r'[A-Za-z0-9\-_/]+', post)
        for i in range(len(toks_post) - 1):
            t1, t2 = toks_post[i], toks_post[i + 1]
            if t1.lower() in {'et', 'al', 'ex'} or re.match(r'^(19|20)\d{2}$', t2):
                continue
            if (_is_code_word(t1) and _is_code_num(t2)) or (
                    re.match(r'^[A-Za-z][A-Za-z0-9]{0,6}[-_./]$', t1 or '') and _is_code_num(t2)
            ):
                return f"{out} {re.sub(r'[-_./]+$', '', t1)} {t2}"

        cand_tok = _best_digit_token(re.findall(r'[A-Za-z0-9._/-]+', post))
        if cand_tok:
            return f"{out} {cand_tok}"

        return out

    m_pair = re.search(r'(?i)\b(O\d+[A-Za-z]?)\s*[:\-_ ]\s*((?:H|K)\d+[A-Za-z]?)\b', tail)
    if m_pair:
        return f"{cand_prefix}{gs} {m_pair.group(1).upper()}:{m_pair.group(2).upper()}"
    m_o = re.search(r'(?i)\b(O\d+[A-Za-z]?)\b', tail)
    if m_o:
        return f"{cand_prefix}{gs} {m_o.group(0).upper()}"

    m_grid = re.search(
        r'(?i)\b(?:\d+(?:\s+\d+)+)\s+([A-Za-z]*[A-Za-z]\d[A-Za-z0-9-]*)\b',
        tail
    )
    if m_grid:
        grid_and_code = tail[m_grid.start():m_grid.end()]
        grid_and_code = re.sub(r'\s{2,}', ' ', grid_and_code).strip()
        return f"{cand_prefix}{gs} {grid_and_code}"

    toks_all = clean_and_tokenize(s, cc_prefixes)
    cc_alt = '|'.join(cc_prefixes)
    cc_rx_tok = re.compile(rf'(?i)^({cc_alt})_[A-Za-z0-9-]+$')

    cc_hits = [t for t in toks_all if cc_rx_tok.match(t)]
    if cc_hits:
        def _get_rank(token: str) -> int:
            prefix = token.split('_')[0]
            for idx, p in enumerate(cc_prefixes):
                if p.lower() == prefix.lower():
                    return idx
            return 999

        cc_hits.sort(key=lambda x: (_get_rank(x), x))

        return f"{cand_prefix}{gs} {cc_hits[0].replace('_', ' ')}"

    tail_tokens = re.findall(r'[A-Za-z0-9\-_/]+', tail)
    for i in range(len(tail_tokens) - 1):
        t1, t2 = tail_tokens[i], tail_tokens[i + 1]
        if t1.lower() in {'et', 'al', 'ex'} or re.match(r'^(19|20)\d{2}$', t2):
            continue
        if (_is_code_word(t1) and _is_code_num(t2)) or (
                re.match(r'^[A-Za-z][A-Za-z0-9]{0,6}[-_./]$', t1 or '') and _is_code_num(t2)
        ):
            return f"{cand_prefix}{gs} {re.sub(r'[-_./]+$', '', t1)} {t2}"

    m_impl = re.search(rf'(?i)\b{re.escape(G)}\s+{re.escape(S)}\s+([a-z][a-z0-9-]*)\b', s)
    if m_impl:
        cand = m_impl.group(1)
        if (cand.lower() not in CONTEXT_STOPS
                and not ADMIN_TOKENS_RX.match(cand)
                and cand.upper() not in cc_prefixes
                and not re.match(r'(?i)^O\d+[A-Za-z]?$', cand)
                and not re.match(r'(?i)^(H|K)\d+[A-Za-z]?$', cand)):
            return f"{cand_prefix}{gs} {cand}"

    cand_tok = _best_digit_token(re.findall(r'[A-Za-z0-9._/-]+', tail))
    if cand_tok:
        return f"{cand_prefix}{gs} {cand_tok}"

    return (cand_prefix + anchor).strip() if cand_prefix else anchor


def count_anchor_tokens_subspp(a: str, cc_prefixes: List[str] = CC_PREFIXES) -> int:

    if not isinstance(a, str) or not a.strip():
        return 0

    s = a.strip()
    s = re.sub(r'^\s*"?candidatus"?\s+', '', s, flags=re.IGNORECASE)

    if is_descriptive_anchor(s):
        return 2

    s = re.sub(r'\b(O\d+[A-Za-z]?)[:\-_ ]((?:H|K)\d+[A-Za-z]?)\b', r'\1:\2', s, flags=re.IGNORECASE)

    cc_alt = '|'.join(cc_prefixes)
    s = re.sub(rf'(?i)\b({cc_alt})\s+([A-Za-z0-9-]+)\b', r'\1_\2', s)

    s = re.sub(r'(?i)\bet\s+al\b', ' ', s)
    s = re.sub(r'(?i)\bal\b', ' ', s)
    s = re.sub(r'(?i)\bex\b', ' ', s)
    s = re.sub(r'\b(18|19|20)\d{2}\b', ' ', s)

    toks = ' '.join(s.split()).split()
    return len([t for t in toks if t])