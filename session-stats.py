#!/usr/bin/env python3
"""
PostToolUse hook: lightweight JSONL logger for tool usage stats.

Appends one JSON line per tool invocation to ~/.claude/session-stats.jsonl.
This data powers precompact-snapshot.py's work detection -- without it,
the pre-compaction snapshot has no tool/file history to capture.

Hook type: PostToolUse
Matcher: (none -- fires on every tool use)

Each entry records:
  - timestamp (UTC ISO 8601)
  - tool name (Read, Write, Edit, Bash, Grep, Glob, Agent, etc.)
  - file_path / path / pattern (if present in the tool input)
  - session_id (from Claude Code hook context, if available)
"""

import json
import os
import sys
from datetime import datetime, timezone

STATS_FILE = os.path.expanduser("~/.claude/session-stats.jsonl")

# Maximum file size before rotation (10 MB)
MAX_FILE_SIZE = 10 * 1024 * 1024


def rotate_if_needed():
    """Rotate the stats file if it exceeds MAX_FILE_SIZE."""
    try:
        if os.path.exists(STATS_FILE) and os.path.getsize(STATS_FILE) > MAX_FILE_SIZE:
            backup = STATS_FILE + ".old"
            # Keep only the most recent backup
            if os.path.exists(backup):
                os.remove(backup)
            os.rename(STATS_FILE, backup)
    except OSError:
        pass


def main():
    # Read hook input from stdin
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    # Extract tool name -- Claude Code sends this in the hook context
    tool_name = data.get("tool_name", "") or data.get("tool", "")

    # Build the log entry
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool_name,
    }

    # Extract file/path references from tool input
    tool_input = data.get("tool_input", {})
    if isinstance(tool_input, dict):
        for key in ("file_path", "path", "pattern", "command"):
            val = tool_input.get(key)
            if val and isinstance(val, str):
                entry[key] = val

    # Include session ID if available
    session_id = data.get("session_id", "")
    if session_id:
        entry["session_id"] = session_id

    # Rotate if file is getting large
    rotate_if_needed()

    # Append to JSONL file
    try:
        os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
        with open(STATS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        # Silent failure -- logging should never break the workflow
        pass


if __name__ == "__main__":
    main()
