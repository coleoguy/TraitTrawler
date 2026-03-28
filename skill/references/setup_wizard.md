# Setup Wizard — First-Run Reference

Load this file when `collector_config.yaml` does not exist in the project root.

---

## Philosophy

The setup wizard is a **conversation**, not a questionnaire. You know what
information you need to build the project. Your job is to have a natural
dialogue with the user, extract what you can from what they share, research
what they don't know, and collaboratively build the best possible starting
configuration. The more the user tells you upfront, the less you need to ask.

---

## Opening

First, check for any `.csv` in the project root (other than `leads.csv`).
If one exists, offer the CSV bootstrap path (see below). Otherwise, open
with something like:

> Tell me about the data you want to collect — what organisms, what trait,
> and what you're hoping to build. Share as much or as little as you like
> and I'll ask follow-up questions for anything I need.

Then **listen**. The user's first response often contains half of what you
need. Extract everything before asking more.

---

## What You Need to Learn

During the conversation, gather enough information to generate all project
files. Not everything needs to be asked directly — many items can be
inferred, researched, or derived.

### Must-have (cannot generate config without these)

| Information | How to get it |
|-------------|---------------|
| **Target taxa** | Usually in the user's first message |
| **Trait name + description** | From conversation; probe for units, measurement methods, edge cases |
| **Among-species vs within-species** | Infer from context. "Body mass for all bird species" = among-species. "Wing length variation across Song Sparrow populations" = within-species. Confirm if ambiguous. |
| **Output field schema** | Build collaboratively as the user describes what they need. Propose fields, show the running list, ask if anything is missing. |
| **Contact email** | Needed for API polite-pool access. Ask once, naturally. |

### Should-have (research if user doesn't provide)

| Information | How to get it |
|-------------|---------------|
| **Triage keywords** | Derive from the trait description. Spawn a subagent to find common title words in relevant papers if user is unsure. |
| **Taxonomic groups to search** | If user says "beetles" but not which families, research the major groups via GBIF or OpenAlex. |
| **Domain knowledge** | Everything the user tells you about notation, measurement conventions, common pitfalls, and edge cases goes into `guide.md`. Research more with seed papers during calibration. |
| **Proxy URL / institution** | Ask if they want access to paywalled papers. For known institutions, look up the proxy URL pattern yourself. |
| **Relevant journals / authors** | Research automatically once you know the taxon + trait — don't make the user provide these. |

### Conversation guidelines

- **Listen first, ask second.** If the user writes a paragraph, extract
  everything you can before responding with questions.
- **Build the schema live.** As the user mentions data fields, propose the
  schema incrementally: "Based on what you've described, here's the field
  list I'm building: ..." Let them react and refine.
- **Research proactively.** Once you know the taxon + trait, spawn a
  subagent to find keywords, journals, and taxonomic breakdowns while
  continuing the conversation. Don't wait to be asked.
- **Share what you're building.** This is collaborative, not interrogative.
  Show drafts of the config, guide, and field list as they take shape.
- **Bundle practical questions.** Instead of asking email, proxy, and
  institution in three separate turns, group them: "For API access and
  paywalled papers, I'll need your email and institution — what do you use
  for library access?"
- **Delegate freely.** Anything the user is vague about ("I don't know
  which families to search"), research with a subagent and propose an answer.
- **Note potential seed papers.** If the user mentions a paper during
  conversation, remember it — those are perfect calibration seeds.

---

## Among-Species vs Within-Species

This decision shapes the config. Infer it when possible, confirm when ambiguous.

**Among-species** (most common):
- One or a few values per species across many species
- `species` is a required field; `taxonomy_resolution: true`
- Include `species`, `family`, `genus` in output_fields
- Dedup key: `[species, doi, {trait_fields}]`

**Within-species**:
- Multiple observations for one or few species, keyed by population/locality/individual
- `species` is NOT required; `taxonomy_resolution: false`
- Ask what the key field is (e.g., `population`, `locality`, `individual_id`)
- Dedup key: `[{key_field}, doi, {trait_fields}]`

---

## Building the Schema

As you learn about the trait, build the output field list following these conventions:

- **snake_case**, include unit when applicable (e.g., `body_mass_g_mean`)
- For continuous measurements, include `_mean`, `_sd`, `_min`, `_max` variants
  as appropriate
- For per-individual traits, consider adding `sex`, `sample_size`, `age_class`
- **Always include provenance fields**: `source_page`, `source_context`,
  `extraction_reasoning` — these are non-negotiable

Show the user the field list and ask: "Here's the schema I've put together —
anything to add, remove, or rename?" Iterate until they're satisfied.

For the dedup key, explain it plainly: "I'll consider a record a duplicate
when these fields all match an existing record: {dedup_key}. Sound right?"

---

## Generating Project Files

Once you have enough information, generate all project files. You don't need
to wait until every question is answered — generate what you can and refine.

### Config files

- **`collector_config.yaml`** from template at
  `${CLAUDE_SKILL_DIR}/references/config_template.yaml`
  - Set `extraction_mode: consensus` (default)
  - Set `concurrency: {max_concurrent_dealers: 2}`
  - Populate trait-specific fields from the schema you built
  - Set `required_fields` based on among/within-species decision

- **`config.py`** with cross-product of taxonomic groups x trait keywords

- **`guide.md`** with everything the user shared about:
  - Units and notation conventions
  - What to extract and what to skip
  - Common pitfalls and edge cases
  - Taxonomy notes
  - This file grows substantially during calibration — the initial version
    captures what the user told you; calibration adds what you learn from
    real papers.

### Data files and directories

- `results.csv` — header row only
- `leads.csv` — empty
- All folders: `state/`, `finds/`, `ready_for_extraction/`, `learning/`,
  `provided_pdfs/`, `pdfs/`, `state/dealt/`, `state/extraction_traces/`,
  `state/snapshots/`
- Empty state files: `processed.json` (`{}`), `queue.json` (`[]`),
  `search_log.json` (`{}`), `run_log.jsonl` (empty), `discoveries.jsonl`
  (empty), `taxonomy_cache.json` (`{}`), `calibration_data.jsonl` (empty),
  `triage_outcomes.jsonl` (empty), `source_stats.json` (`{}`),
  `consensus_stats.json` (`{}`)

---

## CSV Bootstrap Path

Before opening the conversation, check for any `.csv` in the project root
(other than `leads.csv`). If found, offer:

> I see `{filename}` here — {N} columns, {M} data rows. Want me to use
> this as the starting point? I can infer the schema and settings from it,
> or we can start fresh.

If the user says yes:

1. **Infer output_fields** from column headers (numeric → number,
   boolean → boolean, else string). Recognize standard TraitTrawler columns
   automatically: `species`, `family`, `genus`, `doi`, `paper_title`,
   `paper_year`, `first_author`, `paper_journal`, `extraction_confidence`,
   `flag_for_review`, `session_id`, `source_page`, `source_context`,
   `extraction_reasoning`, `consensus`, `accepted_name`, `gbif_key`,
   `taxonomy_note`, `pdf_source`, `source_type`, `notes`
2. **Ask only what can't be inferred** — typically taxon, trait name, email,
   proxy. Have a brief conversation to fill gaps rather than a checklist.
3. **Import data**: copy CSV to `results.csv`, populate `processed.json`
   from DOIs
4. **Skip calibration** if 20+ records exist (the data itself serves as
   calibration)
5. **Generate `extraction_examples.md`** from 3-5 high-confidence records

---

## Transition to Calibration

Once config files are generated and the user approves the schema, transition
naturally:

> Everything's set up. Before I start mining at scale, it really helps to
> learn from a few real papers first — notation, table formats, the way
> authors report this trait. Do you have 2-5 example papers I should look
> at? DOIs or titles work. If not, I'll find some myself using the keywords
> we set up.

If the user mentioned specific papers during the conversation, reference them:
"You mentioned {paper} earlier — want me to use that as one of the seeds?"

Then follow `${CLAUDE_SKILL_DIR}/references/calibration.md` for the
calibration phase.

**Do NOT proceed to the Startup phase in the same invocation.** Wizard + calibration
consumes most of the context window. A fresh session gets the full budget
for collection.

---

## Researching Answers

When you need to research something (keywords, journals, taxonomic groups,
proxy URLs), **spawn a subagent** to do it. This keeps the research overhead
out of the main context window.

Pass the subagent the taxon, trait, and specific research question. The
subagent returns a concise proposed answer. Present findings to the user
for approval.

Research strategies by topic:

- **Keywords**: Search OpenAlex for 10-20 recent papers matching taxon +
  trait. Extract common title words that co-occur with the trait.
- **Proxy URL**: Search for "{institution} library proxy URL" or
  "{institution} ezproxy". Common patterns:
  `http://proxy.library.{domain}/login?url=`
- **Taxonomic groups**: Use GBIF taxonomy or OpenAlex facets to identify
  the major groups within the target taxon for this trait.
- **Journals/authors**: Search OpenAlex for top journals and authors
  publishing on taxon + trait in the last 20 years.
- **Domain knowledge**: Find 3-5 open-access papers, read Methods and
  Results, draft guide.md sections. If the user delegated domain knowledge
  entirely, use the papers you find as seed papers and merge directly into
  calibration.
