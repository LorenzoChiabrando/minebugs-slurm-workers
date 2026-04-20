import re

CC_PREFIXES = [
    "ATCC", "DSM", "JCM", "NCTC", "CCUG", "LMG", "CECT", "NRRL", "KCTC", "NBRC",
    "CIP", "APEC", "Nissle", "NJS", "CGMCC", "BCCM", "IFO", "IAM", "CBS", "MTCC",
    "KACC", "BCRC", "DSMZ", "NZCM", "WAL", "ETEC", "ABU", "ECC"
]

CONTEXT_STOPS = {
    'strain', 'isolate', 'clone', 'str', 'str.', 'of', 'from', 'in', 'on', 'associated',
    'host', 'et', 'al', 'ex'
}

ADJ_MODS = {
    'primary', 'secondary', 'facultative', 'obligate', 'obligatory',
    'intracellular', 'extracellular'
}

HEADS = {'endosymbiont', 'symbiont', 'epibiont'}

DESC_START = {
    'uncultured', 'unidentified', 'unclassified', 'unknown',
    'environmental', 'candidate', 'bacterium', 'bacterial',
    'archaeon', 'archaeal', 'endosymbiont', 'symbiont', 'epibiont', 'cyanobacterium'
}

COMMON_CONTEXT_NOUNS = {
    'lake', 'river', 'spring', 'bay', 'island', 'islet', 'mount', 'mt', 'valley', 'forest',
    'host', 'leaf', 'root', 'soil', 'sediment', 'gut', 'mouse', 'human', 'epithemia', 'turgida'
}


CC_ALT_PATTERN = '|'.join(CC_PREFIXES)

EPITHET_RX = re.compile(r'^[a-z][a-z-]*$')

INFRA_RX = re.compile(r'(?i)\b(?:subsp(?:\.|ecies)?|pv\.?|pathovar|var\.?|variety|biovar|serovar)\b')

CC_ALIAS_RX = re.compile(rf'(?i)\b(?:{CC_ALT_PATTERN})\s*[A-Z]*[-_/]*\d[A-Za-z0-9-]*\b')

SEROTYPE_RX = re.compile(r'(?i)\bO\d+[A-Za-z]?(?::(?:H|K)\d+[A-Za-z]?)?\b')
SEROTYPE_PAIR_RX = re.compile(r'(?i)\b(O\d+[A-Za-z]?)\s*[:\-_ ]\s*((?:H|K)\d+[A-Za-z]?)\b')
SEROTYPE_LONE_O_RX = re.compile(r'(?i)\b(O\d+[A-Za-z]?)\b')

ADMIN_TOKENS_RX = re.compile(r'(?i)^(sp|spp|strain|str|substr|subspecies|cf|aff|pv|var|biovar|serovar)$')

CODE_WORD_RX = re.compile(r'^[A-Za-z][A-Za-z0-9]{0,6}$')
CODE_WORD_WITH_SEP_RX = re.compile(r'^[A-Za-z][A-Za-z0-9]{0,6}[-_./]$')
CODE_NUM_RX = re.compile(r'^\d+[A-Za-z0-9-]*$')

AUTH_RX_1 = re.compile(r'\([^()]*\b(ex|et\s+al\.?)\b[^()]*\d{4}[^()]*\)', re.IGNORECASE)
AUTH_RX_2 = re.compile(r'\bex\s+[A-Z][a-z]+(?:\s+et\s+al\.?)?\s+\d{4}\b', re.IGNORECASE)

CODE_OR_CC_RX = re.compile(
    rf'(?i)\b(?:{CC_ALT_PATTERN})\s*[-_/]?[A-Z]*\s*\d+[A-Za-z0-9-]*\b|'
    r'\b[A-Za-z][A-Za-z0-9]{1,6}[-_./]?\s*\d+[A-Za-z0-9-]*\b'
)