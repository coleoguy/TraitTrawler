#!/bin/bash
# PostToolUse hook: validates dealer_results/ files after write.
# Catches agents writing wrong format to dealer_results/.

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only check files in dealer_results/
if [[ "$FILE_PATH" != *"/dealer_results/"* ]] || [[ "$FILE_PATH" != *".json" ]]; then
  exit 0
fi

# Check valid JSON
if ! jq empty "$FILE_PATH" 2>/dev/null; then
  echo "HOOK: Invalid JSON in dealer_results/ file: $FILE_PATH" >&2
  exit 1
fi

# Must have 'outcome' field (no_data, consensus_failed, invalid_handoff)
HAS_OUTCOME=$(jq -r '.outcome // empty' "$FILE_PATH" 2>/dev/null)

if [[ -z "$HAS_OUTCOME" ]]; then
  echo "HOOK: dealer_results/ file missing 'outcome' field: $FILE_PATH" >&2
  exit 1
fi

# Must have some identifier — doi OR title (pre-DOI papers won't have a DOI)
HAS_DOI=$(jq -r '.doi // empty' "$FILE_PATH" 2>/dev/null)
HAS_TITLE=$(jq -r '.title // empty' "$FILE_PATH" 2>/dev/null)

if [[ -z "$HAS_DOI" ]] && [[ -z "$HAS_TITLE" ]]; then
  echo "HOOK: dealer_results/ file has neither 'doi' nor 'title': $FILE_PATH" >&2
  exit 1
fi

exit 0
