#!/bin/bash
# PreToolUse hook: catches agents trying to create files via Bash
# (python3 -c "open(...).write(...)", echo > file, cat > file, tee, etc.)
# instead of using the Write tool (which is checked by other hooks).
#
# This is a heuristic — it looks for common file-creation patterns in
# the command string. Can't catch everything, but catches the obvious ones.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [[ -z "$COMMAND" ]]; then
  exit 0
fi

# Allow known safe patterns (our own scripts, pip, git, etc.)
# These scripts are authorized to create files in allowed directories
if echo "$COMMAND" | grep -qE "^python3 scripts/|^pip |^git |^mkdir |^cp |^mv |^rm |^ls |^wc |^grep |^head |^tail|^chmod "; then
  exit 0
fi

# Block patterns that create files in the project root
# Pattern: python3 -c "...open('something.py'..." or open("something.txt"
if echo "$COMMAND" | grep -qP "open\(['\"][^/]*\.(py|sh|txt|md|csv|json|jsonl|tsv|html|report)['\"]"; then
  FILENAME=$(echo "$COMMAND" | grep -oP "open\(['\"]([^'\"]+)['\"]" | head -1 | sed "s/open(['\"]//;s/['\"]//")
  echo "BLOCKED: Bash command creates file '$FILENAME' — use the Write tool instead so hooks can validate the path." >&2
  exit 2
fi

# Block: echo/cat/tee redirect to files in current directory
if echo "$COMMAND" | grep -qP "(?:echo|cat|tee|printf)\s.*>\s*[^/\s]+\.(py|sh|txt|md|csv|json|jsonl|tsv|html|report)"; then
  echo "BLOCKED: Bash redirect creates file in project — use the Write tool instead." >&2
  exit 2
fi

# Block: python3 -c that writes files (heuristic: contains .write( and open()
if echo "$COMMAND" | grep -qP "python3\s+-c.*\.write\(.*open\("; then
  echo "BLOCKED: Bash python3 -c creating files — use the Write tool or an authorized script." >&2
  exit 2
fi

exit 0
