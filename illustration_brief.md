# TraitTrawler Illustration Brief

## For the AI Artist

Create an illustration showing how TraitTrawler works — an autonomous
multi-agent system that mines scientific literature for biological trait
data. The tone should be scientific but visually engaging, suitable for
a paper figure or project landing page.

---

## The Core Metaphor

A deep-sea trawling operation, but instead of fish, the net pulls
structured data out of an ocean of scientific papers. The "ocean" is
a vast sea of floating PDF documents, journal covers, and tables of
data. The "trawler" is an AI-powered vessel crewed by specialized
agents.

---

## The Pipeline (left to right flow)

### 1. The Searcher (lookout in the crow's nest)
- Scans the horizon across four channels: PubMed, OpenAlex, bioRxiv, Crossref
- Uses a spyglass/telescope
- Papers appear as fish-shaped documents in the water
- Some glow (relevant), some are dark (rejected)
- Sorts catches into a queue

### 2. The Fetcher (diver / net operator)
- Two modes shown: one diver using API hooks (fast, surface-level),
  another using a browser/submarine for deeper paywalled papers
- Retrieves full-text PDFs from the water
- Some papers slip through the net (leads — marked for later)
- Hands retrieved PDFs up to the deck

### 3. The Dealer (deck boss)
- Receives papers on deck
- Inspects each one briefly (handoff validation)
- Hands them to three workers simultaneously

### 4. The Three Extractors (the consensus crew)
- Three distinct workers examining the SAME paper independently
- Agent A: methodical, systematic, works through tables row by row
- Agent B: starts by counting every species first, then extracts
- Agent C: skeptical, has a magnifying glass, questions everything,
  marks things with "?" flags
- Each produces their own data sheet
- Their sheets flow into a VOTING mechanism (shown as overlapping
  circles / Venn diagram) where 2-of-3 agreement wins
- Disagreements are highlighted in red

### 5. The Writer (record keeper)
- Sits at a desk with a large ledger (results.csv)
- Validates incoming records against a rulebook
- Checks species names against a taxonomy reference (GBIF globe icon)
- Stamps each record with a session ID
- Rejects bad records into a side pile (needs_attention)
- The ledger grows row by row — append only, never rewrite

### 6. The Manager (captain on the bridge)
- Oversees everything from above
- Has a dashboard/control panel showing pipeline state
- Dispatches agents, monitors throughput
- Never touches the data directly — only coordinates
- Connected to all agents by communication lines (file-based queues
  shown as conveyor belts or pneumatic tubes between stations)

---

## Key Visual Elements

**File-based communication**: Between each station, show physical
folders/trays/conveyor belts labeled: `search_results/`,
`ready_for_extraction/`, `finds/`, `writer_results/`. This is how
agents talk — not directly, but by dropping files for the next
station to pick up.

**The database**: A growing CSV spreadsheet or ledger at the end,
with thousands of rows of species names and trait values. Each row
has a provenance trail back to a specific paper.

**Scale indicators**: Show numbers floating nearby — "1,669 search
queries", "5,339 records", "148 families" — to convey the scale
of autonomous operation.

**The domain**: Beetles (Coleoptera) are the flagship organism.
Scatter beetle silhouettes throughout — on papers, in the data,
as decorative elements. Karyotype diagrams (paired chromosomes)
could appear in the extracted data flowing through the pipeline.

---

## Style Notes

- Scientific illustration meets technical diagram
- Color palette: deep ocean blues and teals for the paper ocean,
  warm amber/gold for extracted data, red for flagged/rejected items
- Clean lines, not cluttered — each stage should be visually distinct
- Could work as either a horizontal panorama (left to right flow)
  or a circular/spiral composition
- Label each stage clearly
- The overall impression should be: "a small fleet of specialized
  AI agents systematically converting a chaotic ocean of literature
  into a clean, structured database"

---

## Optional Details

- A small "learning" feedback loop arrow from the Extractors back
  to a knowledge base (guide.md), showing the system improves over time
- A quality control station after the Writer (statistical QC, audits)
- A "dashboard" screen showing real-time charts of progress
- Rejected/uncertain papers floating in a separate "leads" pool,
  waiting for a human to provide access
