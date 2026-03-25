"""
Search queries for the Avian Body Mass Database.
Adapt this list to your target taxon and trait.

API rate-limit notes:
  - PubMed E-utilities: 3 req/s without API key, 10/s with key.
    The agent batches queries and backs off on HTTP 429 automatically.
  - OpenAlex / Crossref: use the polite pool via contact_email in your config.
  - See skill/references/troubleshooting.md for rate-limit recovery.
"""

# --- Focal order × trait keyword combinations ---
_ORDERS = [
    "Passeriformes", "Psittaciformes", "Columbiformes",
    "Accipitriformes", "Strigiformes", "Charadriiformes",
    "Anseriformes", "Galliformes", "Pelecaniformes",
    "Coraciiformes", "Piciformes", "Apodiformes",
    "Caprimulgiformes", "Gruiformes", "Suliformes",
    "Procellariiformes", "Cuculiformes", "Trogoniformes",
    "Bucerotiformes", "Falconiformes",
]

_TRAIT_KW = [
    "body mass",
    "body weight",
    "morphometrics",
    "morphometric measurements",
]

# --- General queries ---
_GENERAL = [
    "avian body mass database",
    "bird body size allometry",
    "bird morphometric data compilation",
    "Handbook of the Birds of the World body mass",
    "avian life history body size",
]

# --- Journal-targeted queries ---
_JOURNAL = [
    "body mass Ibis",
    "body mass Condor",
    "morphometrics Auk",
    "morphometrics Journal of Ornithology",
    "body mass Emu Austral Ornithology",
    "bird weight Wilson Journal of Ornithology",
]

# --- Build final list (order × keyword + general + journal) ---
SEARCH_TERMS = [f"{o} {k}" for o in _ORDERS for k in _TRAIT_KW]
SEARCH_TERMS += _GENERAL
SEARCH_TERMS += _JOURNAL

# Deduplicate preserving order
SEARCH_TERMS = list(dict.fromkeys(SEARCH_TERMS))
