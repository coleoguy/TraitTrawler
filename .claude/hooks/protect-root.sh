#!/bin/bash
# PreToolUse hook: blocks file creation in project root.
# v6 rewrite — only allows a minimal, explicit set of root files and
# subdirectories. Most state lives under state/, pdfs/, reports/, or
# inside skill/.
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

PROJECT_DIR=$(echo "$INPUT" | jq -r '.cwd // empty')
if [[ -z "$PROJECT_DIR" ]]; then
  exit 0
fi

REL_PATH=$(python3 -c "
import os.path
try:
    print(os.path.relpath('$FILE_PATH', '$PROJECT_DIR'))
except Exception:
    print('')
" 2>/dev/null)

if [[ -z "$REL_PATH" ]]; then
  exit 0
fi

# File in project root (no directory separator)?
if [[ "$REL_PATH" != *"/"* ]]; then
  case "$REL_PATH" in
    # v6 allowed root files
    config.yaml|candidates.jsonl|results.csv|legacy_rejected.csv|\
    .gitignore|README.md|LICENSE|CHANGELOG.md|CITATION.cff|\
    CONTRIBUTING.md|VALIDATION_GUIDE.md|requirements.txt|\
    traittrawler.skill)
      exit 0
      ;;
    *)
      echo "BLOCKED: Cannot create '$REL_PATH' in project root. Use state/, pdfs/, reports/, or skill/." >&2
      exit 2
      ;;
  esac
fi

# In a subdirectory — check it's an allowed top-level dir
TOP_DIR=$(echo "$REL_PATH" | cut -d'/' -f1)
case "$TOP_DIR" in
  # v6 canonical directories
  state|pdfs|reports|skill|tests|docs|evals|examples|\
  .claude|.github|.pytest_cache|.ruff_cache)
    exit 0
    ;;
  *)
    echo "BLOCKED: Cannot write to unauthorized directory '$TOP_DIR/'. Allowed v6 dirs: state/, pdfs/, reports/, skill/, tests/, docs/." >&2
    exit 2
    ;;
esac
