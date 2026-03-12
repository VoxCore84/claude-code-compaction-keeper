#!/usr/bin/env python3
"""
PreCompact hook: snapshot active work context before compaction destroys it.

Part of the Two-Stage Compaction Resilience pipeline for Claude Code.
Reads recent tool usage from session-stats.jsonl, detects work patterns,
and writes a structured JSON snapshot that compact-reinject.py restores
after compaction.

Hook type: PreCompact
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from collections import Counter

STATS_FILE = os.path.expanduser("~/.claude/session-stats.jsonl")
SNAPSHOT_FILE = os.path.expanduser("~/.claude/precompact-state.json")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# Defaults if config.json is missing or incomplete
DEFAULT_CONFIG = {
    "file_categories": {
        "code": [".py", ".ts", ".tsx", ".js", ".jsx", ".cpp", ".h", ".rs", ".go"],
        "data": [".sql", ".json", ".yaml", ".yml", ".toml"],
        "docs": [".md", ".rst", ".txt"],
    },
    "lookback_hours": 2,
    "max_recent_files": 20,
}


def load_config() -> dict:
    """Load config.json, falling back to defaults for any missing keys."""
    config = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        # Merge — user values override defaults
        for key in DEFAULT_CONFIG:
            if key in user_config:
                config[key] = user_config[key]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return config


def categorize_file(filepath: str, categories: dict) -> str | None:
    """Return the category name for a file based on its extension, or None."""
    _, ext = os.path.splitext(filepath)
    ext = ext.lower()
    for category, extensions in categories.items():
        if ext in extensions:
            return category
    return None


def main():
    # Read hook input from stdin (Claude Code sends JSON context)
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    config = load_config()
    categories = config["file_categories"]
    lookback_hours = config["lookback_hours"]
    max_recent = config["max_recent_files"]

    recent_tools = []
    recent_files = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    # Read session-stats.jsonl for recent tool activity
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Filter by time window
                ts_str = entry.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue

                # Collect tool names
                tool = entry.get("tool", "")
                if tool:
                    recent_tools.append(tool)

                # Collect file paths from any path-like key
                for key in ("file_path", "path", "pattern"):
                    val = entry.get(key)
                    if val and isinstance(val, str):
                        recent_files.append(val)
    except FileNotFoundError:
        pass

    # Aggregate tool usage counts
    tool_counts = Counter(recent_tools)

    # Deduplicate files, preserving most-recent-last order
    seen = set()
    unique_files = []
    for filepath in reversed(recent_files):
        if filepath not in seen:
            seen.add(filepath)
            unique_files.append(filepath)
    unique_files = list(reversed(unique_files[-max_recent:]))

    # Categorize files by configured extensions
    categorized_files = {}
    for filepath in unique_files:
        cat = categorize_file(filepath, categories)
        if cat:
            if cat not in categorized_files:
                categorized_files[cat] = []
            categorized_files[cat].append(filepath)

    # Build human-readable work signals
    work_signals = []
    for cat_name, cat_files in categorized_files.items():
        basenames = [os.path.basename(f) for f in cat_files[:5]]
        suffix = f" (+{len(cat_files) - 5} more)" if len(cat_files) > 5 else ""
        work_signals.append(f"{cat_name} files: {', '.join(basenames)}{suffix}")

    if tool_counts.get("Agent", 0) > 0:
        work_signals.append(f"Spawned {tool_counts['Agent']} subagent(s)")

    if tool_counts.get("Bash", 0) > 5:
        work_signals.append(f"Heavy shell usage ({tool_counts['Bash']} commands)")

    # Build the snapshot
    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trigger": data.get("trigger", "unknown"),
        "recent_files": unique_files,
        "tool_usage": dict(tool_counts.most_common(10)),
        "work_signals": work_signals,
        "categorized_files": {
            cat: files for cat, files in categorized_files.items()
        },
    }

    # Write snapshot to disk
    try:
        os.makedirs(os.path.dirname(SNAPSHOT_FILE), exist_ok=True)
        with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not write snapshot: {e}", file=sys.stderr)

    # Emit summary to stderr (visible in Claude Code hook output)
    if work_signals:
        print(
            f"Pre-compaction snapshot saved: {', '.join(work_signals)}",
            file=sys.stderr,
        )
    else:
        print("Pre-compaction snapshot saved (no active work detected).", file=sys.stderr)


if __name__ == "__main__":
    main()
