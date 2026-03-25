"""
Search terms for Coleoptera karyotype collection.

This file defines INITIAL_SEARCH_TERMS — the list of queries the TraitTrawler
skill iterates through. The skill reads this file at startup (§1b) and pulls
the next unrun query each cycle.

To adapt for a different project, replace the family lists and keywords.
"""


def _family_terms(families: list[str], keywords: list[str]) -> list[str]:
    """Cross-product of family names × keywords."""
    return [f"{fam} {kw}" for fam in families for kw in keywords]


# ── Cytogenetics keywords ────────────────────────────────────────────────────
# Used in cross-product with every family name below.
_CYTOGENETICS_KW = [
    "karyotype",
    "chromosomes",
    "cytogenetics",
    "sex chromosome",
    "cytology",
    "chromosome number",
    "diploid number",
    "2n",
    "spermatogenesis",
    "meiosis",
    "chromosome count",
]

# ── General Coleoptera terms ─────────────────────────────────────────────────
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
    "beetle spermatogenesis meiosis",
    "beetle diploid number chromosome",
]

# ── Archostemata ─────────────────────────────────────────────────────────────
_ARCHOSTEMATA = [
    "Cupedidae", "Micromalthidae", "Ommatidae", "Crowsoniellidae",
]

# ── Myxophaga ────────────────────────────────────────────────────────────────
_MYXOPHAGA = [
    "Lepiceridae", "Torridincolidae", "Microsporidae", "Sphaeriusidae",
]

# ── Adephaga ─────────────────────────────────────────────────────────────────
_ADEPHAGA = [
    "Gyrinidae", "Haliplidae", "Trachypachidae", "Noteridae", "Dytiscidae",
    "Amphizoidae", "Aspidytidae", "Hygrobiidae", "Carabidae", "Rhysodidae",
]

# ── Polyphaga: Staphyliniformia ──────────────────────────────────────────────
_STAPHYLINIFORMIA = [
    "Hydrophilidae", "Histeridae", "Sphaeritidae", "Synteliidae",
    "Staphylinidae", "Silphidae", "Ptiliidae", "Agyrtidae", "Leiodidae",
]

# ── Polyphaga: Scarabaeiformia ───────────────────────────────────────────────
_SCARABAEIFORMIA = [
    "Scarabaeidae", "Geotrupidae", "Trogidae", "Glaresidae", "Ochodaeidae",
    "Glaphyridae", "Hybosoridae", "Passalidae", "Lucanidae",
]

# ── Polyphaga: Elateriformia ─────────────────────────────────────────────────
_ELATERIFORMIA = [
    "Dascillidae", "Rhipiceridae", "Clambidae", "Scirtidae", "Eucinetidae",
    "Buprestidae", "Schizopodidae", "Artematopodidae", "Elateridae",
    "Eucnemidae", "Throscidae", "Lycidae", "Lampyridae", "Phengodidae",
    "Cantharidae", "Cerophytidae", "Perothopidae", "Brachypsectridae",
    "Rhinorhipidae", "Callirhipidae",
]

# ── Polyphaga: Byrrhoidea ───────────────────────────────────────────────────
_BYRRHOIDEA = [
    "Byrrhidae", "Chelonariidae", "Cneoglossidae",
]

# ── Polyphaga: Bostrichiformia ───────────────────────────────────────────────
_BOSTRICHIFORMIA = [
    "Endecatomidae", "Dermestidae", "Bostrichidae", "Ptinidae",
    "Nosodendridae", "Jacobsoniidae", "Derodontidae",
]

# ── Polyphaga: Cleroidea ────────────────────────────────────────────────────
_CLEROIDEA = [
    "Phycosecidae", "Cleridae", "Melyridae", "Prionoceridae", "Trogossitidae",
    "Acanthocnemidae", "Chaetosomatidae", "Lymexylidae",
]

# ── Polyphaga: Coccinelloidea ───────────────────────────────────────────────
_COCCINELLOIDEA = [
    "Corylophidae", "Coccinellidae", "Endomychidae", "Latridiidae",
    "Mycetophagidae", "Cerylonidae", "Alexiidae", "Anamorphidae",
    "Bothrideridae", "Discolomatidae",
]

# ── Polyphaga: Cucujoidea ───────────────────────────────────────────────────
_CUCUJOIDEA = [
    "Silvanidae", "Passandridae", "Cucujidae", "Phalacridae", "Monotomidae",
    "Byturidae", "Boganiidae", "Biphyllidae", "Cryptophagidae", "Languriidae",
    "Erotylidae", "Sphindidae", "Nitidulidae", "Kateretidae", "Smicripidae",
    "Propalticidae", "Phloeostichidae",
]

# ── Polyphaga: Tenebrionoidea ───────────────────────────────────────────────
_TENEBRIONOIDEA = [
    "Tenebrionidae", "Zopheridae", "Melandryidae", "Mordellidae",
    "Ripiphoridae", "Aderidae", "Mycteridae", "Salpingidae", "Anthicidae",
    "Pyrochroidae", "Meloidae", "Oedemeridae", "Boridae", "Stenotrachelidae",
    "Synchroidae", "Prostomidae", "Pythidae", "Ischaliidae", "Cephaloidae",
    "Scraptiidae", "Pedilidae", "Euglenidae",
]

# ── Polyphaga: Chrysomeloidea ───────────────────────────────────────────────
_CHRYSOMELOIDEA = [
    "Cerambycidae", "Chrysomelidae", "Megalopodidae", "Orsodacnidae",
    "Vesperidae", "Disteniidae", "Oxypeltidae", "Aulacoscelididae",
]

# ── Polyphaga: Curculionoidea ───────────────────────────────────────────────
_CURCULIONOIDEA = [
    "Brentidae", "Ithyceridae", "Nemonychidae", "Curculionidae",
    "Anthribidae", "Belidae", "Attelabidae", "Erirhinidae", "Dryophthoridae",
]

# ── Polyphaga: Dryopoidea / aquatic beetles ─────────────────────────────────
_DRYOPOIDEA = [
    "Dryopidae", "Elmidae", "Lutrochidae", "Psephenidae",
    "Eulichadidae", "Ptilodactylidae", "Limnichidae", "Heteroceridae",
]

# ── Build combined INITIAL_SEARCH_TERMS ─────────────────────────────────────
_ALL_FAMILIES = (
    _ARCHOSTEMATA + _MYXOPHAGA + _ADEPHAGA +
    _STAPHYLINIFORMIA + _SCARABAEIFORMIA + _ELATERIFORMIA +
    _BYRRHOIDEA + _BOSTRICHIFORMIA + _CLEROIDEA + _COCCINELLOIDEA +
    _CUCUJOIDEA + _TENEBRIONOIDEA + _CHRYSOMELOIDEA +
    _CURCULIONOIDEA + _DRYOPOIDEA
)

# ── Journal-targeted searches ────────────────────────────────────────────────
# Key cytogenetics/entomology journals — many OA, heavily index beetle karyotypes
_JOURNAL_TERMS = [
    "Caryologia Coleoptera karyotype",
    "Caryologia Coleoptera chromosomes",
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
    # Brazilian/Indian/Russian cytogenetics groups — very prolific
    "Coleoptera karyotype Brazil chromosomes",
    "Coleoptera chromosomes India cytology",
    "Coleoptera karyotype Russia chromosomes",
    "Virkki cytogenetics Coleoptera",
    "Manna chromosomes Coleoptera",
    "Petitpierre Coleoptera chromosomes",
    "Schneider Coleoptera karyotype Brazil",
    "Kuznetsova beetle chromosomes",
    # FISH / molecular cytogenetics
    "Coleoptera FISH ribosomal chromosome",
    "Coleoptera telomere FISH karyotype",
    "Coleoptera C-banding karyotype",
    "Coleoptera rDNA chromosome mapping",
    "Coleoptera heterochromatin C-band",
    "Coleoptera NOR silver staining",
    # B chromosomes
    "Coleoptera B chromosome supernumerary",
]

INITIAL_SEARCH_TERMS = (
    _GENERAL_TERMS
    + _family_terms(_ALL_FAMILIES, _CYTOGENETICS_KW)
    + _JOURNAL_TERMS
)
