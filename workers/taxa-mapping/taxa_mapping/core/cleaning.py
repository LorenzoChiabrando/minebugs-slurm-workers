import re
import logging
from typing import List

logger = logging.getLogger(__name__)

def clean_taxa_names(raw_names: List[str]) -> List[str]:

    cleaned_list = []

    re_brackets = re.compile(r"^\[([^\]]+)\]")

    re_strain_dash = re.compile(r"(\b[A-Za-z]{1,4})-([0-9]+)\b")

    re_punct = re.compile(r"[,;]+")

    for name in raw_names:
        if not isinstance(name, str):
            cleaned_list.append("")
            continue

        s = name

        s = re_brackets.sub(r"\1", s)

        s = re_strain_dash.sub(r"\1 \2", s)

        s = re_punct.sub("", s)

        s = " ".join(s.split())

        cleaned_list.append(s)

    return cleaned_list