#!/usr/bin/env python3
"""
Iterative database anomaly scanner for results.csv.
Runs multiple passes of increasingly specific checks.
Each pass reports problems found, then fixes what it can.
Re-run until it reports 0 problems.

Run after every data addition:
    python3 db_scanner.py

Checks (22 total):
 1. Genus contains English/junk words (paper titles parsed as taxonomy)
 2. Species contains English/junk words
 3. Genus doesn't match ^[A-Z][a-z]{2,}$ (malformed, OCR garbage, numbers)
 4. Binomial left in species field (genus repeated)
 5. Species too long (>60 chars = OCR garbage)
 6. Genus too long (>40 chars)
 7. Species has numbers appended (OCR artifacts: "herbacea19")
 8. Species has author abbreviation appended (camelCase: "rufaDuft.")
 9. Species has comma (multi-species records, paper titles)
10. Species <=2 chars (truncated OCR fragments)
11. Species has parenthetical location ("epithet (California)")
12. Empty genus but has species (extract genus from binomial)
13. Empty genus AND species with chromosome data (orphan data)
14. Family not in valid whitelist
15. sex_chr_system not in canonical vocabulary
16. Extreme 2n (<4 or >120)
17. hac >= 2n (impossible)
18. 2n vs hac vs sex_chr_system inconsistency
19. paper_year outside 1900-2026
20. URLs in taxonomy/categorical fields
21. Fake DOI placeholders (no_doi_*)
22. Numeric values in text fields (author, journal)
"""

import csv
import re
import sys
from collections import Counter

CSV_PATH = 'results.csv'

# ── Known good values ──────────────────────────────────────────────
VALID_FAMILIES = {
    'Aderidae','Anthicidae','Anthribidae','Biphyllidae','Boganiidae','Bostrichidae',
    'Brentidae','Buprestidae','Byrrhidae','Cantharidae','Carabidae','Cephaloidae',
    'Cerambycidae','Cerylonidae','Chrysomelidae','Ciidae','Cleridae','Coccinellidae',
    'Corylophidae','Cryptophagidae','Cucujidae','Cupedidae','Curculionidae',
    'Dascillidae','Dermestidae','Derodontidae','Discolomatidae','Drilidae','Dryopidae',
    'Dytiscidae','Elateridae','Elmidae','Endomychidae','Erotylidae','Eucinetidae',
    'Geotrupidae','Gyrinidae','Haliplidae','Heteroceridae','Histeridae','Hydraenidae',
    'Hydrophilidae','Hygrobiidae','Jacobsoniidae','Kateretidae','Laemophloeidae',
    'Lampyridae','Languriidae','Latridiidae','Leiodidae','Lucanidae','Lycidae',
    'Lymexylidae','Malachiidae','Megalopodidae','Melandryidae','Meloidae','Melyridae',
    'Micromalthidae','Monotomidae','Mordellidae','Mycetophagidae','Nitidulidae',
    'Noteridae','Oedemeridae','Orsodacnidae','Passalidae','Phalacridae','Phengodidae',
    'Platypodidae','Prostomidae','Ptiliidae','Ptinidae','Pyrochroidae','Pythidae',
    'Rhagophthalmidae','Rhynchitidae','Ripiphoridae','Salpingidae','Scarabaeidae',
    'Scirtidae','Scraptiidae','Silphidae','Silvanidae','Staphylinidae','Tenebrionidae',
    'Tetratomidae','Throscidae','Trogidae','Trogossitidae','Vesperidae','Zopheridae',
}

VALID_SEX_CHR = {
    '','XY','Xyp','Xyr','X0','neoXY','Parthenogenetic','XXY','XXXY','XXXXY',
    'Xyyp','XXYY','XYY','Xyc','neoXp,neoXneoYp','PGE+Y','XYYY','neoXX',
    'XXXYYY','XXXYY',
}

# Words that should NEVER appear in genus or species fields
JUNK_WORDS = {
    'karyotype','chromosome','cytogenetic','mitotic','meiotic','analysis',
    'comparative','banding','staining','morphology','review','evolution',
    'taxonomy','phylogen','molecular','genome','genomic',
    'assembly','sequence','sequencing',
    'abstract','introduction','methods','results','discussion',
    'conclusion','references','acknowledgment','supplementary',
    'material','journal','copyright',
    'downloaded','accessed','available','online',
    'investigation','observations','characterization','variability',
    'chromosomal','divergence','relationships','description',
}

# Author surnames commonly mis-parsed as genera
AUTHOR_GENERA = {
    'Julio','Mittal','Petitpierre','Zurita','Barion','Barrion',
    'Holecova','Yua','Angus','Juan','Sharma','Okutaner','Smith',
}

def load_csv():
    with open(CSV_PATH, 'r') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    return rows, fieldnames

def save_csv(rows, fieldnames):
    with open(CSV_PATH, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def scan_and_fix(rows, fieldnames):
    """Run all checks. Returns (problems, fixes, rows_deleted, cleaned_rows)."""
    problems = []
    fixes = 0
    to_delete = set()

    for i, r in enumerate(rows):
        genus = r.get('genus','').strip()
        species = r.get('species','').strip()
        family = r.get('family','').strip()

        # ── CHECK 1: Genus contains junk words ──
        gl = genus.lower()
        for junk in JUNK_WORDS:
            if junk in gl and len(junk) > 4:
                problems.append(f"Row {i}: genus '{genus}' contains junk '{junk}' [sp='{species}']")
                to_delete.add(i)
                break

        # ── CHECK 1b: Genus is a known author surname ──
        if genus in AUTHOR_GENERA and species in ('et','et.','n.','al','al.',''):
            problems.append(f"Row {i}: author-as-genus '{genus}' [sp='{species}']")
            to_delete.add(i)

        # ── CHECK 2: Species contains junk words ──
        sl = species.lower()
        for junk in JUNK_WORDS:
            if junk in sl and len(junk) > 4:
                if junk == sl or f' {junk}' in sl or sl.startswith(junk):
                    problems.append(f"Row {i}: species '{species}' contains junk '{junk}' [genus='{genus}']")
                    to_delete.add(i)
                    break

        # ── CHECK 3: Genus format ──
        if genus and not re.match(r'^[A-Z][a-z]{2,}$', genus):
            problems.append(f"Row {i}: malformed genus '{genus}' [sp='{species}']")
            if re.search(r'\d', genus) or len(genus) <= 2:
                to_delete.add(i)

        # ── CHECK 4: Binomial in species field ──
        if species and genus:
            parts = species.split()
            if len(parts) >= 2 and parts[0] == genus:
                r['species'] = ' '.join(parts[1:])
                fixes += 1

        # ── CHECK 5-6: Length limits ──
        if len(genus) > 40:
            to_delete.add(i)
            problems.append(f"Row {i}: genus too long ({len(genus)} chars)")
        if len(species) > 60:
            to_delete.add(i)
            problems.append(f"Row {i}: species too long ({len(species)} chars)")

        # ── CHECK 7: Numbers appended to species (OCR artifacts) ──
        if species and re.search(r'[a-z]\d+', species) and not re.match(r'^sp\.\s*\d', species):
            cleaned = re.sub(r'\d+.*$', '', species)
            if cleaned and len(cleaned) >= 3:
                r['species'] = cleaned
                fixes += 1
                problems.append(f"Row {i}: OCR numbers stripped: '{species}' → '{cleaned}'")

        # ── CHECK 8: Author abbreviation appended (camelCase) ──
        if species and re.search(r'[a-z][A-Z]', species):
            cleaned = re.sub(r'([a-z])[A-Z].*$', r'\1', species)
            if cleaned and len(cleaned) >= 3 and cleaned != species:
                r['species'] = cleaned
                fixes += 1
                problems.append(f"Row {i}: author stripped: '{species}' → '{cleaned}'")

        # ── CHECK 9: Comma in species ──
        if ',' in species and genus:
            problems.append(f"Row {i}: comma in species: {genus} '{species}'")

        # ── CHECK 10: Very short species (<=2 chars) ──
        if species and len(species) <= 2 and species not in ('sp','sp.'):
            problems.append(f"Row {i}: truncated species: {genus} '{species}'")
            r['notes'] = f"{r.get('notes','').strip()}; OCR-truncated: '{species}'".lstrip('; ')
            r['species'] = 'sp.'
            fixes += 1

        # ── CHECK 11: Parenthetical locations in species ──
        if species and '(' in species:
            m = re.match(r'^(.+?)\s*\(([^)]+)\)\s*$', species)
            if m:
                paren = m.group(2).strip()
                if not paren.startswith('=') and not paren.endswith('group') and \
                   paren not in ('s.l.','s.str.') and not re.match(r'^\d', paren):
                    r['species'] = m.group(1).strip()
                    if not r.get('collection_locality','').strip():
                        r['collection_locality'] = paren
                    fixes += 1

        # ── CHECK 12: Empty genus, species has binomial ──
        if not genus and species:
            parts = species.split()
            if len(parts) >= 2 and parts[0][0].isupper() and parts[1][0].islower():
                r['genus'] = parts[0]
                r['species'] = ' '.join(parts[1:])
                fixes += 1

        # ── CHECK 13: No taxonomy but has data ──
        if not genus and not species and (r.get('chromosome_number_2n','').strip() or r.get('sex_chr_system','').strip()):
            problems.append(f"Row {i}: orphan data, no taxonomy")
            to_delete.add(i)

        # ── CHECK 14: Family whitelist ──
        if family and family not in VALID_FAMILIES:
            problems.append(f"Row {i}: unknown family '{family}' for {genus} {species}")

        # ── CHECK 15: sex_chr_system ──
        scs = r.get('sex_chr_system','').strip()
        if scs and scs not in VALID_SEX_CHR:
            problems.append(f"Row {i}: unknown sex_chr_system '{scs}'")

        # ── CHECK 16: Extreme 2n ──
        cn = r.get('chromosome_number_2n','').strip()
        if cn:
            try:
                n = int(cn)
                if n < 4 or n > 120:
                    problems.append(f"Row {i}: extreme 2n={n} for {genus} {species}")
            except ValueError:
                pass

        # ── CHECK 17-18: hac vs 2n consistency ──
        hac = r.get('haploid_autosome_count','').strip()
        if cn and hac:
            try:
                if int(hac) >= int(cn):
                    problems.append(f"Row {i}: hac={hac} >= 2n={cn}")
            except ValueError:
                pass

        # ── CHECK 19: paper_year ──
        py = r.get('paper_year','').strip()
        if py:
            try:
                y = int(py)
                if y < 1900 or y > 2026:
                    problems.append(f"Row {i}: paper_year={y}")
            except ValueError:
                pass

        # ── CHECK 20: URLs in wrong fields ──
        for field in ['genus','species','family','author','staining_method','sex_chr_system','country']:
            v = r.get(field,'').strip()
            if v.startswith('http'):
                if not r.get('pdf_url','').strip():
                    r['pdf_url'] = v
                r[field] = ''
                fixes += 1

        # ── CHECK 21: Fake DOI ──
        doi = r.get('doi','').strip()
        if doi.startswith('no_doi_'):
            r['doi'] = ''
            fixes += 1

        # ── CHECK 22: Numeric text fields ──
        for field in ['author','paper_title','journal']:
            v = r.get(field,'').strip()
            if v and v.replace('.','').replace('-','').isdigit():
                r[field] = ''
                fixes += 1

        # ── FIX: "sp" → "sp." ──
        if r.get('species','').strip() == 'sp':
            r['species'] = 'sp.'
            fixes += 1

        # ── FIX: Lowercase genus ──
        g = r.get('genus','').strip()
        if g and g[0].islower():
            r['genus'] = g[0].upper() + g[1:]
            fixes += 1

    rows_out = [r for idx, r in enumerate(rows) if idx not in to_delete]
    return problems, fixes, len(to_delete), rows_out


# ── Main ──
rows, fieldnames = load_csv()
print(f"Loaded {len(rows)} records")

pass_num = 0
total_deleted = 0
total_fixed = 0

while True:
    pass_num += 1
    print(f"\n{'═'*60}")
    print(f" PASS {pass_num}")
    print(f"{'═'*60}")
    problems, fixes, deleted, rows = scan_and_fix(rows, fieldnames)
    total_deleted += deleted
    total_fixed += fixes

    seen = set()
    unique = [p for p in problems if p not in seen and not seen.add(p)]

    print(f"  Problems: {len(unique)} | Auto-fixes: {fixes} | Deleted: {deleted}")
    for p in unique[:40]:
        print(f"    {p}")
    if len(unique) > 40:
        print(f"    ... and {len(unique)-40} more")

    if deleted == 0 and fixes == 0:
        if unique:
            print(f"\n  {len(unique)} issues need manual review.")
        else:
            print(f"\n  DATABASE IS CLEAN.")
        break
    if pass_num >= 5:
        print(f"\n  Stopping after {pass_num} passes.")
        break

save_csv(rows, fieldnames)
print(f"\n{'═'*60}")
print(f" SUMMARY: {pass_num} passes, {total_deleted} deleted, {total_fixed} fixed")
print(f" Final: {len(rows)} records")
print(f"{'═'*60}")
