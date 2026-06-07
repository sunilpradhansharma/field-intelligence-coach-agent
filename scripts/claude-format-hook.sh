#!/usr/bin/env bash
# Claude Code PostToolUse hook: auto-format a Python file after Claude edits it.
# Claude Code passes the tool event as JSON on stdin; we read the edited file path.
input="$(cat)"
file="$(printf '%s' "$input" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('tool_input',{}).get('file_path',''))" 2>/dev/null || true)"

case "$file" in
  *.py)
    ruff check --fix "$file" >/dev/null 2>&1 || true
    ruff format "$file" >/dev/null 2>&1 || true
    ;;
esac

exit 0
