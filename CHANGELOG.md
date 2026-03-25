# Changelog

All notable changes to TraitTrawler will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] — 2026-03-24

Initial public release accompanying the MEE manuscript submission.

### Added
- Core autonomous agent: search → triage → retrieve → extract → validate → write pipeline
- 1,669 search queries covering 148 Coleoptera families × 11 cytogenetics keywords
- PDF retrieval cascade: Unpaywall → OpenAlex → Europe PMC → Semantic Scholar → institutional proxy
- 22 cross-field validation rules for karyotype data
- Leads tracking for papers needing manual PDF retrieval
- Self-contained HTML dashboard generator (Chart.js)
- Avian body mass example configuration in `examples/`
- Validation study: 5,339 records benchmarked against 4,959-record human-curated database
- GBIF taxonomy validation at session end
- Domain knowledge guide (`guide.md`) with Coleoptera karyotype notation conventions
