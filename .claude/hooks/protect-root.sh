#!/bin/bash
# PreToolUse hook: blocks file creation in project root.
# Agents must write to their designated folders (finds/, dealer_results/, etc.)
# Exit 2 = block the tool call.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [[ "$TOOL_NAME" != "Write" ]]; then
  exit 0
fi

if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# Get the project root from cwd
PROJECT_DIR=$(echo "$INPUT" | jq -r '.cwd // empty')
if [[ -z "$PROJECT_DIR" ]]; then
  exit 0
fi

# Calculate relative path
REL_PATH=$(python3 -c "
import os.path, sys
try:
    print(os.path.relpath('$FILE_PATH', '$PROJECT_DIR'))
except:
    print('')
" 2>/dev/null)

if [[ -z "$REL_PATH" ]]; then
  exit 0
fi

# If the file has no directory separator, it's in the project root
if [[ "$REL_PATH" != *"/"* ]]; then
  # Allow known root files
  case "$REL_PATH" in
    collector_config.yaml|config.py|guide.md|extraction_examples.md|\
    results.csv|leads.csv|dashboard.html|\
    dashboard_generator.py|verify_session.py|export_dwc.py|\
    .gitignore|README.md|LICENSE|CHANGELOG.md|CITATION.cff)
      exit 0
      ;;
    *)
      echo "BLOCKED: Cannot create '$REL_PATH' in project root. Use a subdirectory (finds/, dealer_results/, state/, etc.)." >&2
      exit 2
      ;;
  esac
fi

exit 0
