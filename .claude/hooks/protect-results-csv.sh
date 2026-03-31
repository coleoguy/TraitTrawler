#!/bin/bash
# PreToolUse hook: blocks direct Write/Edit to results.csv.
# Only csv_writer.py (via Bash python3) should touch results.csv.
# Exit 2 = block the tool call.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only check Write and Edit tools
if [[ "$TOOL_NAME" != "Write" ]] && [[ "$TOOL_NAME" != "Edit" ]]; then
  exit 0
fi

# Block if target is results.csv
if [[ "$FILE_PATH" == *"results.csv" ]]; then
  echo "BLOCKED: Direct writes to results.csv are not allowed. Use the Writer agent (scripts/write_finds.py) instead." >&2
  exit 2
fi

exit 0
