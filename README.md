# TraitTrawler — Cowork Skill

An autonomous literature agent that searches scientific databases, retrieves full-text papers, and extracts structured trait data into a CSV. Runs inside [Claude Cowork](https://claude.ai) — no API key or Python environment required.

This repository is configured for **Coleoptera karyotype data** but the skill is fully reusable for any taxa and any trait by editing three files.

---

## Quickstart

1. **Install the skill** — drag `traittrawler.skill` into Cowork (Settings → Plugins → Install)
2. **Open Cowork** and select this folder as your workspace
3. **Say** `"let's collect some data"` — the skill picks up where it left off, or runs first-time setup if this is a fresh clone

That's it. The skill manages everything else: searching, fetching PDFs, extracting records, and writing to `results.csv`.

---

## What it does

Each session the skill:
- Pulls unrun search queries from `config.py` and searches PubMed + bioRxiv
- Triages papers by relevance using the criteria in `collector_config.yaml`
- Retrieves full text — first from open-access sources (Unpaywall, OpenAlex, Europe PMC, Semantic Scholar), then through your institution's library proxy using your browser session
- Extracts structured records from full text, including dense tables and catalogue-style reference entries
- Appends records to `results.csv` and updates state so the next session resumes exactly where this one ended

Progress is reported as it goes. Stop anytime — nothing is lost.

---

## Repository structure

```
traittrawler.skill   — install this in Cowork
collector_config.yaml        — the main config you edit to customize the project
config.py                    — search term list (one query per entry)
guide.md                     — domain knowledge that guides extraction
README.md                    — this file
context.md                   — technical reference for Claude (do not edit)
skill/                       — skill source files (do not edit)
```

The skill creates `state/`, `pdfs/`, and `results.csv` automatically on first run.

---

## Customizing for your project

To repurpose this skill for different taxa or a different trait, edit these three files:

### 1. `collector_config.yaml`

This is the master config. Change:

```yaml
project_name: "My Species Trait Database"
target_taxa:
  - "Aves"
  - "birds"
trait_name: "body size"
trait_description: >
  Body mass (g), body length (mm), wing span (mm). Primary measurements
  from wild-caught specimens. Includes both focal-species and comparative data.
triage_keywords:
  - body size
  - body mass
  - morphometrics
proxy_url: "https://your-institution-proxy/login?url="
contact_email: "you@youruniversity.edu"
output_fields:
  - doi
  - species
  - family
  - body_mass_g
  - body_length_mm
  # ... your trait-specific fields
```

Also update `pdf_subfolder_field` if you want PDFs organized by something other than `family` (e.g., `order`, `genus`).

### 2. `config.py`

Replace the search term list with queries relevant to your taxa and trait. The format is a Python list of strings — one query per entry. Example:

```python
SEARCH_TERMS = [
    "Passeriformes body mass",
    "Columbiformes morphometrics",
    "bird body size allometry",
    # ...
]
```

### 3. `guide.md`

Replace the domain knowledge with guidance relevant to your field. This file is injected into every triage and extraction decision Claude makes. Include:
- How to recognize a relevant paper from its title/abstract
- What notation or abbreviations are used in your literature
- Any ambiguities Claude should know how to resolve
- Example records showing what good extracted data looks like

---

## Institution proxy setup

The skill uses your browser's authenticated session to retrieve paywalled papers. To enable this:

1. Set `proxy_url` in `collector_config.yaml` to your institution's EZProxy address
   - Texas A&M: `http://proxy.library.tamu.edu/login?url=`
   - Most universities follow the pattern `https://ezproxy.youruniversity.edu/login?url=`
   - Check your library's "off-campus access" page if unsure
2. Log into your library proxy in Chrome before starting a session
3. The skill uses Chrome silently — you'll see `🌐 browser` in the progress output when it fetches a paywalled paper

If you're not authenticated, the skill reports it once and falls back to open-access sources and abstracts for that session.

---

## Output

Records are appended to `results.csv` with one row per species per paper. Fields are defined in `collector_config.yaml` → `output_fields`. The full field reference with types and confidence guidelines is in `skill/references/csv_schema.md`.

PDFs are saved to `pdfs/{family}/{FirstAuthor}_{Year}_{Journal}_{DOI}.pdf` — organized so you can browse them directly.

---

## Requirements

- [Claude Cowork](https://claude.ai) with a Pro or Max subscription
- Claude in Chrome extension installed and enabled
- Your institution's library proxy URL (for paywalled papers)
- Chrome logged into your library proxy before starting a session

No Python, no API keys, no setup scripts.

---

## Questions / contributions

Contact Heath Blackmon — coleoguy@gmail.com
