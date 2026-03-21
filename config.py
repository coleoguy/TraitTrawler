"""
Configuration for the Coleoptera karyotype agent.
All secrets come from environment variables — never hardcode keys here.
"""
import os

# ── API Keys ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")       # optional; raises limit to 10 req/s
NCBI_EMAIL = os.environ.get("NCBI_EMAIL", "")           # required by NCBI Entrez policy
UNPAYWALL_EMAIL = os.environ.get("UNPAYWALL_EMAIL", "") or os.environ.get("NCBI_EMAIL", "")  # falls back to NCBI_EMAIL
# Validation is handled in agent.py validate_env() — not here, so --dry-run works

# ── LLM Provider ──────────────────────────────────────────────────────────────
# "anthropic" uses Claude (default). "openai" uses GPT-4o-class models.
# Set OPENAI_API_KEY in .env and flip this to "openai" to use your TAMU key.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic")

# ── Models ────────────────────────────────────────────────────────────────────
# Anthropic models
TRIAGE_MODEL  = "claude-haiku-4-5-20251001"  # classifies papers — haiku is ~10x cheaper than Sonnet
EXTRACT_MODEL = "claude-sonnet-4-6"           # extracts karyotype data (best structured-JSON quality)

# OpenAI models (used when LLM_PROVIDER = "openai")
OPENAI_TRIAGE_MODEL  = os.environ.get("OPENAI_TRIAGE_MODEL",  "gpt-4o-mini")  # cheap + fast for triage
OPENAI_EXTRACT_MODEL = os.environ.get("OPENAI_EXTRACT_MODEL", "gpt-4o")       # best available for extraction

TRIAGE_MAX_TOKENS = 256
EXTRACT_MAX_TOKENS = 4096                    # 2048 too tight for large supplementary tables

# ── Search ────────────────────────────────────────────────────────────────────
RESULTS_PER_SOURCE = 50        # papers to fetch per query per source
MAX_SEARCH_ROUNDS = 100        # stop after this many search rounds with no new results
STOP_AFTER_EMPTY_ROUNDS = 5    # consecutive rounds with 0 new papers → stop
TRIAGE_BATCH_SIZE = 20         # papers to triage per round

def _family_terms(families: list[str], keywords: list[str]) -> list[str]:
    """Cross-product of family names × cytogenetics keywords."""
    return [f"{fam} {kw}" for fam in families for kw in keywords]


_CYTOGENETICS_KW = ["karyotype", "chromosomes", "cytogenetics", "sex chromosome", "cytology"]

# ── General Coleoptera terms ───────────────────────────────────────────────────
_GENERAL_TERMS = [
    "Coleoptera karyotype",
    "Coleoptera chromosomes",
    "beetle chromosomes karyotype",
    "Coleoptera cytogenetics",
    "Coleoptera chromosome number",
    "beetle cytogenetics 2n",
    "Coleoptera B chromosomes",
    "Coleoptera sex chromosomes",
    "Coleoptera chromosome evolution",
    "Coleoptera genome karyomorphology",
]

# ── Archostemata ───────────────────────────────────────────────────────────────
_ARCHOSTEMATA = [
    "Cupedidae", "Micromalthidae", "Ommatidae", "Crowsoniellidae",
]

# ── Myxophaga ─────────────────────────────────────────────────────────────────
_MYXOPHAGA = [
    "Lepiceridae", "Torridincolidae", "Microsporidae", "Sphaeriusidae",
]

# ── Adephaga ──────────────────────────────────────────────────────────────────
_ADEPHAGA = [
    "Gyrinidae", "Haliplidae", "Trachypachidae", "Noteridae", "Dytiscidae",
    "Amphizoidae", "Aspidytidae", "Hygrobiidae", "Carabidae", "Rhysodidae",
]

# ── Polyphaga: Staphyliniformia ────────────────────────────────────────────────
_STAPHYLINIFORMIA = [
    "Hydrophilidae", "Histeridae", "Sphaeritidae", "Synteliidae",
    "Staphylinidae", "Ptiliidae", "Agyrtidae", "Leiodidae",
]

# ── Polyphaga: Scarabaeiformia ─────────────────────────────────────────────────
_SCARABAEIFORMIA = [
    "Scarabaeidae", "Geotrupidae", "Trogidae", "Glaresidae", "Ochodaeidae",
    "Glaphyridae", "Hybosoridae", "Passalidae", "Lucanidae",
]

# ── Polyphaga: Elateriformia ──────────────────────────────────────────────────
_ELATERIFORMIA = [
    "Dascillidae", "Rhipiceridae", "Clambidae", "Scirtidae", "Eucinetidae",
    "Buprestidae", "Schizopodidae", "Artematopodidae", "Elateridae",
    "Eucnemidae", "Throscidae", "Lycidae", "Lampyridae", "Phengodidae",
    "Cantharidae", "Cerophytidae", "Perothopidae", "Brachypsectridae",
    "Rhinorhipidae", "Callirhipidae",
]

# ── Polyphaga: Bostrichiformia ────────────────────────────────────────────────
_BOSTRICHIFORMIA = [
    "Endecatomidae", "Dermestidae", "Bostrichidae", "Ptinidae",
    "Nosodendridae", "Jacobsoniidae", "Derodontidae",
]

# ── Polyphaga: Cleroidea ──────────────────────────────────────────────────────
_CLEROIDEA = [
    "Phycosecidae", "Cleridae", "Melyridae", "Prionoceridae", "Trogossitidae",
    "Acanthocnemidae", "Chaetosomatidae", "Lymexylidae",
]

# ── Polyphaga: Coccinelloidea ─────────────────────────────────────────────────
_COCCINELLOIDEA = [
    "Corylophidae", "Coccinellidae", "Endomychidae", "Latridiidae",
    "Mycetophagidae", "Cerylonidae", "Alexiidae", "Anamorphidae",
    "Bothrideridae", "Discolomatidae",
]

# ── Polyphaga: Cucujoidea ─────────────────────────────────────────────────────
_CUCUJOIDEA = [
    "Silvanidae", "Passandridae", "Cucujidae", "Phalacridae", "Monotomidae",
    "Byturidae", "Boganiidae", "Biphyllidae", "Cryptophagidae", "Languriidae",
    "Erotylidae", "Sphindidae", "Nitidulidae", "Kateretidae", "Smicripidae",
    "Propalticidae", "Phloeostichidae",
]

# ── Polyphaga: Tenebrionoidea ─────────────────────────────────────────────────
_TENEBRIONOIDEA = [
    "Tenebrionidae", "Zopheridae", "Melandryidae", "Mordellidae",
    "Ripiphoridae", "Aderidae", "Mycteridae", "Salpingidae", "Anthicidae",
    "Pyrochroidae", "Meloidae", "Oedemeridae", "Boridae", "Stenotrachelidae",
    "Synchroidae", "Prostomidae", "Pythidae", "Ischaliidae", "Cephaloidae",
    "Scraptiidae", "Pedilidae", "Euglenidae",
]

# ── Polyphaga: Chrysomeloidea ─────────────────────────────────────────────────
_CHRYSOMELOIDEA = [
    "Cerambycidae", "Chrysomelidae", "Megalopodidae", "Orsodacnidae",
    "Vesperidae", "Disteniidae", "Oxypeltidae", "Aulacoscelididae",
]

# ── Polyphaga: Curculionoidea ─────────────────────────────────────────────────
_CURCULIONOIDEA = [
    "Brentidae", "Ithyceridae", "Nemonychidae", "Curculionidae",
    "Anthribidae", "Belidae", "Attelabidae", "Erirhinidae", "Dryophthoridae",
]

# ── Polyphaga: Dryopoidea / aquatic beetles ───────────────────────────────────
_DRYOPOIDEA = [
    "Dryopidae", "Elmidae", "Lutrochidae", "Psephenidae",
    "Eulichadidae", "Ptilodactylidae", "Limnichidae", "Heteroceridae",
]

# ── Build combined INITIAL_SEARCH_TERMS ───────────────────────────────────────
_ALL_FAMILIES = (
    _ARCHOSTEMATA + _MYXOPHAGA + _ADEPHAGA +
    _STAPHYLINIFORMIA + _SCARABAEIFORMIA + _ELATERIFORMIA +
    _BOSTRICHIFORMIA + _CLEROIDEA + _COCCINELLOIDEA +
    _CUCUJOIDEA + _TENEBRIONOIDEA + _CHRYSOMELOIDEA +
    _CURCULIONOIDEA + _DRYOPOIDEA
)

INITIAL_SEARCH_TERMS = _GENERAL_TERMS + _family_terms(_ALL_FAMILIES, _CYTOGENETICS_KW)

# ── Journal-targeted searches ─────────────────────────────────────────────────
# Key cytogenetics/entomology journals: many OA since 2000, and heavily index beetle karyotypes
_JOURNAL_TERMS = [
    # High-yield cytogenetics journals for beetles
    "Caryologia Coleoptera karyotype",
    "Cariologia Coleoptera chromosomes",
    "Cytologia beetle chromosomes",
    "Genetica Coleoptera cytogenetics",
    "Chromosoma beetle karyotype",
    "Chromosome Research Coleoptera",
    "Comparative Cytogenetics Coleoptera",
    "European Journal of Entomology karyotype",
    "Zookeys beetle chromosomes",
    "Coleopterists Bulletin karyotype",
    "Revista brasileira entomologia karyotype",
    "Folia Biologica karyotype beetle",
    "Cytogenetic Genome Research Coleoptera",
    "Genetics and Molecular Biology Coleoptera",
    # Brazilian/Indian cytogenetics groups — very prolific with beetle karyotypes
    "Coleoptera karyotype Brazil chromosomes",
    "Coleoptera chromosomes India cytology",
    "Virkki cytogenetics Coleoptera",
    "Smith cytogenetics Coleoptera",
    "Manna chromosomes Coleoptera",
    # FISH / molecular cytogenetics (post-2000, more OA)
    "Coleoptera FISH ribosomal chromosome",
    "Coleoptera telomere FISH karyotype",
    "Coleoptera C-banding karyotype",
    "Coleoptera rDNA chromosome mapping",
    "Coleoptera heterochromatin C-band",
    "Coleoptera NOR silver staining",
    # B chromosomes — unique to specific groups
    "Coleoptera B chromosome supernumerary",
]

# Append journal terms to the initial search list
INITIAL_SEARCH_TERMS = INITIAL_SEARCH_TERMS + _JOURNAL_TERMS

# Add taxon-specific terms from your guide.md to expand coverage
PRIORITY_FAMILIES = []   # e.g. ["Cerambycidae", "Carabidae"] — leave empty for all

# ── Source toggles ────────────────────────────────────────────────────────────
USE_PUBMED = True
USE_CROSSREF = True
USE_SEMANTIC_SCHOLAR = False
USE_OPENALEX = True             # free, no key needed; good coverage of non-English cytogenetics journals
USE_GOOGLE_SCHOLAR = False      # legally gray, aggressively blocks scrapers — disabled by default

# ── Rate Limits ───────────────────────────────────────────────────────────────
PUBMED_DELAY = 0.34             # seconds between requests (≈3/s; 0.10 with API key)
CROSSREF_DELAY = 1.0            # seconds between requests (polite pool)
SEMANTIC_SCHOLAR_DELAY = 0.6   # 100 req/min = 0.6s
OPENALEX_DELAY = 0.1            # 10 req/s polite pool; no key needed but mailto in User-Agent helps
GOOGLE_SCHOLAR_DELAY_MIN = 10   # random delay range to avoid blocks (only if USE_GOOGLE_SCHOLAR)
GOOGLE_SCHOLAR_DELAY_MAX = 200
PDF_DOWNLOAD_DELAY = 5.0        # seconds between PDF downloads

# ── PDF handling ──────────────────────────────────────────────────────────────
# "pdfplumber" recommended for table-heavy papers; "pymupdf" faster for text-only
PDF_PARSER = "pdfplumber"
MAX_PDF_SIZE_MB = 50            # skip PDFs larger than this — likely corrupted or book-length

# Vision fallback for scanned/image PDFs (BHL, old journals, etc.)
# When pdfplumber returns empty text, render pages as images and run Sonnet vision.
# Costs ~$0.02–0.10 per paper but recovers otherwise-lost karyotype data.
USE_VISION_FALLBACK = True
VISION_MAX_PAGES = 10           # max pages sent per vision call (older papers are often short)
VISION_DPI = 150                # page render resolution — 150 dpi is sufficient for text OCR

# ── Language ──────────────────────────────────────────────────────────────────
# Substantial Coleoptera cytogenetics literature exists in Russian, Spanish, German.
# "en" only is safe but lossy. Set to None to attempt extraction across all languages.
LANGUAGE_FILTER = "en"          # set to None to disable filtering

# ── Extraction thresholds ─────────────────────────────────────────────────────
MIN_CONFIDENCE = 0.75           # discard extractions below this confidence score
FLAG_FOR_REVIEW_THRESHOLD = 0.75  # flag extractions below this for manual review

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, "state")
PDF_DIR = os.path.join(BASE_DIR, "pdfs")
LOG_DIR = os.path.join(BASE_DIR, "logs")
PRIORITY_PDF_DIR = os.path.join(BASE_DIR, "priority_pdfs")   # drop PDFs here to process them
RESULTS_CSV = os.path.join(BASE_DIR, "results.csv")
GUIDE_PATH = os.path.join(BASE_DIR, "guide.md")
PROCESSED_FILE = os.path.join(STATE_DIR, "processed.json")
QUEUE_FILE = os.path.join(STATE_DIR, "queue.json")
SEARCH_LOG_FILE = os.path.join(STATE_DIR, "search_log.json")
AGENT_LOG = os.path.join(LOG_DIR, "agent.log")
