#!/bin/bash
# PostToolUse hook: validates finds/ JSON files after write.
# Catches agent format violations (CSV, JSONL, missing fields) immediately.
# Non-blocking (exit 1 = warning) — the file is already written.

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only check files in finds/
if [[ "$FILE_PATH" != *"/finds/"* ]] || [[ "$FILE_PATH" != *".json" ]]; then
  exit 0
fi

# Check valid JSON
if ! jq empty "$FILE_PATH" 2>/dev/null; then
  echo "HOOK: Invalid JSON in $FILE_PATH — agent wrote non-JSON output" >&2
  exit 1
fi

# Check top-level has 'records' array
RECORDS_TYPE=$(jq -r 'if .records then (.records | type) else "missing" end' "$FILE_PATH" 2>/dev/null)
if [[ "$RECORDS_TYPE" == "missing" ]]; then
  echo "HOOK: $FILE_PATH missing 'records' key — wrong schema" >&2
  exit 1
fi
if [[ "$RECORDS_TYPE" != "array" ]]; then
  echo "HOOK: $FILE_PATH 'records' is $RECORDS_TYPE, must be array" >&2
  exit 1
fi

# Check each record has species and extraction_confidence
MISSING=$(jq -r '[.records[] | select(.species == null or .species == "" or .extraction_confidence == null)] | length' "$FILE_PATH" 2>/dev/null)
if [[ "$MISSING" -gt 0 ]]; then
  echo "HOOK: $FILE_PATH has $MISSING records missing species or extraction_confidence" >&2
  exit 1
fi

exit 0
