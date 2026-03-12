#!/usr/bin/env python3
"""
SessionStart hook: re-inject context after compaction.

Part of the Two-Stage Compaction Resilience pipeline for Claude Code.
Reads the JSON snapshot written by precompact-snapshot.py and emits both
static project reminders and dynamic work-in-progress context to stderr,
where Claude Code picks it up as restored context.

Hook type: SessionStart
Matcher: "compact" (only fires after compaction, not on fresh sessions)
"""

import json
import os
import sys

SNAPSHOT_FILE = os.path.expanduser("~/.claude/precompact-state.json")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# Fallback reminders if config.json is missing
DEFAULT_REMINDERS = [
    "Check your project rules before making changes.",
    "Review session state or coordination files before touching shared resources.",
]


def load_config() -> dict:
    """Load config.json for static reminders."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def build_static_reminders(config: dict) -> str:
    """Build the static reminders block from config."""
    reminders = config.get("static_reminders", DEFAULT_REMINDERS)
    if not reminders:
        return ""
    lines = ["POST-COMPACTION CONTEXT REMINDER:"]
    for reminder in reminders:
        lines.append(f"- {reminder}")
    return "\n".join(lines)


def load_dynamic_state() -> str:
    """Load the pre-compaction snapshot and format it as human-readable context."""
    try:
        with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            snapshot = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return ""

    parts = []

    # Work signals summary
    signals = snapshot.get("work_signals", [])
    if signals:
        parts.append("WORK IN PROGRESS before compaction:")
        for sig in signals:
            parts.append(f"  - {sig}")

    # Recent files (basenames for readability)
    recent = snapshot.get("recent_files", [])
    if recent:
        basenames = [os.path.basename(f) for f in recent[-10:]]
        parts.append(f"Recent files: {', '.join(basenames)}")

    # Per-category file details
    categorized = snapshot.get("categorized_files", {})
    for cat_name, cat_files in categorized.items():
        if cat_files:
            basenames = [os.path.basename(f) for f in cat_files[:5]]
            action_hint = ""
            if cat_name == "code":
                action_hint = " (may need build/test)"
            elif cat_name == "data":
                action_hint = " (may need apply/validate)"
            elif cat_name == "docs":
                action_hint = " (documentation edits)"
            parts.append(
                f"{cat_name} files touched{action_hint}: {', '.join(basenames)}"
            )

    # Tool usage summary
    tools = snapshot.get("tool_usage", {})
    if tools:
        top_tools = ", ".join(f"{t}={c}" for t, c in list(tools.items())[:5])
        parts.append(f"Tool usage: {top_tools}")

    # Timestamp for staleness detection
    ts = snapshot.get("timestamp", "")
    if ts:
        parts.append(f"Snapshot taken: {ts}")

    return "\n".join(parts)


def main():
    config = load_config()

    output_parts = []

    # Static reminders
    static = build_static_reminders(config)
    if static:
        output_parts.append(static)

    # Dynamic state from pre-compaction snapshot
    dynamic = load_dynamic_state()
    if dynamic:
        output_parts.append("")
        output_parts.append(dynamic)
    else:
        output_parts.append("")
        output_parts.append(
            "(No pre-compaction snapshot found. This may be a fresh session.)"
        )

    print("\n".join(output_parts), file=sys.stderr)


if __name__ == "__main__":
    main()
