#!/bin/bash
# PreToolUse hook: ensures agents only write .json files to
# dealer_results/ and finds/. Blocks .csv, .txt, .md, .jsonl,
# .tmp, and other formats that agents have been observed writing.

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')

if [[ "$TOOL" != "Write" ]]; then
  exit 0
fi

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# Check dealer_results/ and finds/ directories
if [[ "$FILE_PATH" == *"/dealer_results/"* ]] || [[ "$FILE_PATH" == *"/finds/"* ]]; then
  if [[ "$FILE_PATH" != *".json" ]]; then
    EXTENSION="${FILE_PATH##*.}"
    echo "HOOK: Blocked non-JSON write to pipeline directory: $FILE_PATH" >&2
    echo "HOOK: dealer_results/ and finds/ only accept .json files, got .$EXTENSION" >&2
    exit 1
  fi
fi

exit 0
