# Self-Improving Domain Knowledge

This is the agent's learning system. As you process papers, you encounter
patterns, edge cases, and notation variants that aren't covered in `guide.md`.
Rather than silently adapting, capture these discoveries so the project's
domain knowledge improves over time.

## 14a. When to log a discovery

After extracting records from each paper, check whether you encountered any of:
- A notation variant not in `guide.md` or `extraction_examples.md`
- A new taxonomic name (family, subfamily) not previously seen in results.csv
- A field value that required interpretation not covered by existing rules
- A recurring low-confidence pattern (same type of ambiguity across papers)
- A journal or source type with unusual formatting worth noting
- A validation rule that should exist but doesn't

If so, append an entry to `state/discoveries.jsonl`:

```json
{
  "session_id": "2026-03-24T14:30:00Z",
  "timestamp": "2026-03-24T15:12:00Z",
  "type": "notation_variant",
  "source_doi": "10.1234/example.5678",
  "description": "Sex chromosome system written as 'X1X2X3Y' — not in normalization table. Wrote as XXXY per existing rule but the subscript notation suggests this may be a distinct system in Cicindelidae.",
  "proposed_rule": "Add to sex_chr_system normalization: X₁X₂X₃Y → XXXY. Add note in guide.md §Sex Chromosome Systems that numbered notation is equivalent.",
  "affected_fields": ["sex_chr_system"],
  "confidence": 0.85,
  "guide_section": "Sex Chromosome Systems"
}
```

## 14b. Discovery types

| Type | When to log |
|---|---|
| `notation_variant` | New way of writing a known value |
| `new_taxon` | Family/subfamily/tribe not previously encountered |
| `ambiguity_pattern` | Same type of unclear data across 2+ papers |
| `validation_gap` | A check that should exist but doesn't |
| `extraction_pattern` | Recurring document structure worth noting |
| `terminology` | Domain term with meaning not in guide.md |

## 14c. Session-end knowledge review

At the end of each session (after the session summary), if any discoveries
were logged during this session:

1. Read `state/discoveries.jsonl` for this session's entries.
2. Group discoveries by `guide_section`.
3. **Classify each proposal** as routine or structural:
   - **Routine**: adding a row to a normalization table, noting a new
     journal format, adding a synonym. Draft with sonnet (or current model).
   - **Structural**: creating a new canonical vocabulary entry, changing
     or removing a rejection/validation rule, resolving a conflict between
     two existing rules, redefining what counts as a distinct category.
     Escalate to opus for the draft — these are domain-reasoning judgments
     where deeper analysis prevents errors that would propagate to all
     future extractions. Log the escalation per model_routing.md.
4. For each group, propose a **specific, diff-formatted amendment** to `guide.md`:

```
🔬 Domain Knowledge Review — {N} discoveries this session
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Discovery 1: New notation variant for sex chromosome systems
  Source: Smith et al. 2003 (10.1234/example.5678)

  Proposed addition to guide.md § Sex Chromosome Systems:
  ┌──────────────────────────────────────────────────┐
  │ + | X₁X₂X₃Y, X1X2X3Y | `XXXY` | Numbered       │
  │ + |   notation equivalent to repeated-letter form  │
  │ + |   Common in Cicindelidae (tiger beetles)       │
  └──────────────────────────────────────────────────┘

  Apply this change? [y/n/edit]
```

5. For each proposed change the user approves:
   - Apply the edit to `guide.md` using the Edit tool
   - Log the change to `state/run_log.jsonl`:
     ```json
     {"timestamp": "...", "session_id": "...", "event": "guide_updated", "section": "Sex Chromosome Systems", "change": "Added X₁X₂X₃Y normalization rule", "source_doi": "10.1234/example.5678"}
     ```
   - Mark the discovery as `"applied": true` in `discoveries.jsonl`

6. For rejected changes, mark as `"applied": false, "reason": "user rejected"`.

## 14d. Cumulative knowledge report

Every 5 sessions (tracked via `run_log.jsonl`), print a brief summary:

```
📚 Knowledge Growth Report
   guide.md: {N} agent-proposed amendments accepted ({M} rejected)
   Notation variants discovered: {N}
   New taxa encountered: {N}
   Validation rules suggested: {N}
```

## 14e. Never modify guide.md without approval

The agent proposes; the human decides. Never silently edit `guide.md`,
`extraction_examples.md`, or `collector_config.yaml`. The user must
explicitly approve every change. This maintains scientific integrity
and keeps the human as the domain authority.

## 14g. Cross-project transfer learning (§25)

At session end, during the knowledge review, check if any discoveries
have cross-project value — patterns that would help a DIFFERENT
TraitTrawler project extracting a different trait.

**Transferable discovery types**:
- `extraction_pattern`: journal-specific document structure (e.g.,
  "Comparative Cytogenetics always puts data in Table 1")
- `terminology`: domain terms with meanings not specific to this trait
- Notation variants that are NOT trait-specific (e.g., "±" means SD)

**Where to store**: `~/.claude/traittrawler_shared/` (configurable via
`transfer_learning.shared_dir` in config). Write transferable discoveries
with provenance:

```json
{
  "source_project": "coleoptera-karyotypes",
  "discovery_type": "extraction_pattern",
  "journal": "Comparative Cytogenetics",
  "pattern": "Data in Table 1 or 2; methods in section 2.1",
  "confidence": 0.9,
  "n_papers_observed": 15,
  "date": "2026-03-24"
}
```

**When to read**: During setup wizard (§0) or calibration (§0b), if the
shared knowledge directory exists, load relevant entries and present to
user for approval before incorporating into guide.md.

See [advanced_features.md](references/advanced_features.md) §25 for
the full transfer learning protocol.

## 14f. Mid-session correction

When the user identifies a systematic error during an active session
(e.g., "you're miscoding Xyp as XY — those are different systems"),
the agent should:

1. **Stop extraction immediately.** Do not process additional papers
   until the correction is applied.

2. **Apply the correction to `guide.md`** with user approval (per §14e).
   Log the change to `run_log.jsonl` with `"event": "guide_updated"`.

3. **Offer warm re-extraction:**
   ```
   ⚠ This correction may affect {N} records written this session.
   Want me to re-extract those papers using the corrected rule? [y/n]
   ```
   Identify affected records by matching `session_id` in `results.csv`.
   Count only records where the corrected field is non-empty.

4. **If yes — re-extract from cached PDFs:**
   - For each affected paper (identified by DOI from this session's records):
     - Read the cached PDF from `pdfs/` using `pdf_filename`
     - Re-extract using the corrected `guide.md`, focused on the affected
       field(s). Use `source_page` to go directly to the relevant pages.
     - Diff old values vs. new values and present to the user:
       ```
       📝 Re-extraction: Smith et al. 2003 (10.1234/example.5678)
          species: Cicindela campestris
          sex_chr_system: XY → Xyp  (corrected)
          extraction_confidence: 0.78 → 0.92  (improved)
          [accept / reject / edit]
       ```
     - On accept: update the record in `results.csv` in place. Append
       `"mid-session correction: {field} {old}→{new}"` to `notes`.
     - On reject: keep original value.
   - Use sonnet for re-extraction. Do NOT escalate to opus unless the
     re-extraction confidence is still below 0.5 after correction.

5. **Log the correction event** to `state/run_log.jsonl`:
   ```json
   {"timestamp": "...", "session_id": "...", "event": "mid_session_correction", "rule_changed": "sex_chr_system normalization", "records_reviewed": 8, "records_corrected": 5, "records_unchanged": 3}
   ```

6. **Resume normal extraction** with the corrected `guide.md`.

**Triggers** — the user says anything like:
```
"that's wrong", "you're miscoding", "stop, that field should be",
"go back and fix", "that's not how you read that notation",
"the rule for X should be Y", "correction:"
```
