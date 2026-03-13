# Two-Stage Compaction Resilience for Claude Code

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue) ![License: MIT](https://img.shields.io/github/license/VoxCore84/claude-code-compaction-keeper) ![GitHub release](https://img.shields.io/github/v/release/VoxCore84/claude-code-compaction-keeper)

When Claude Code compacts your conversation context, it preserves the broad strokes but loses the nuance of what you were actively doing -- which files you had open, what tools you were using, whether you were mid-build or mid-debug. Static project rules survive compaction fine. Dynamic work state does not.

This pipeline solves that with a two-stage hook architecture that captures real session state *before* compaction and restores it *after*.

## The Problem

Claude Code's context compaction is a necessary mechanism for long sessions. But it creates a discontinuity:

- **Before compaction**: Claude knows you were editing `server.cpp` and `handler.h`, had spawned 3 subagents, and were halfway through a SQL migration.
- **After compaction**: Claude knows your project rules (from CLAUDE.md) but has no idea what it was *doing*. It starts fresh, asks what you need, and you lose momentum.

Static context injection (adding reminders at session start) helps with project rules but cannot restore *dynamic* state -- it does not know what changed between sessions.

## The Solution

A two-stage pipeline that bridges the compaction gap:

```
 Active Session                    Compaction                     Resumed Session
 +----------------+              +----------+                   +------------------+
 | Tool usage     |              |          |                   |                  |
 | File edits     |-- Stage 1 -->| snapshot |--- Stage 2 ------>| Static rules     |
 | Work patterns  |   PreCompact | .json    |    SessionStart   | + Dynamic state  |
 | Subagent count |              |          |    (compact)      | + Work signals   |
 +----------------+              +----------+                   +------------------+
```

**Stage 1 -- PreCompact** (`precompact-snapshot.py`): Fires right before compaction. Reads `session-stats.jsonl` (a running log of every tool call), detects work patterns (code editing, SQL work, subagent spawning, heavy shell usage), and writes a structured JSON snapshot to `~/.claude/precompact-state.json`.

**Stage 2 -- SessionStart** (`compact-reinject.py`): Fires when the session resumes after compaction. Reads the snapshot and emits both your static project reminders *and* the dynamic work context. Claude sees exactly what it was doing before compaction hit.

**Dependency** (`session-stats.py`): A PostToolUse hook that logs every tool invocation to `~/.claude/session-stats.jsonl`. This is the raw data that Stage 1 reads. Without it, Stage 1 has nothing to snapshot.

## How It Works

### session-stats.py (PostToolUse -- runs on every tool call)

Appends one JSON line per tool invocation:

```json
{"timestamp": "2026-03-11T15:30:00+00:00", "tool": "Edit", "file_path": "/src/main.py"}
{"timestamp": "2026-03-11T15:30:05+00:00", "tool": "Bash", "command": "npm test"}
{"timestamp": "2026-03-11T15:30:10+00:00", "tool": "Agent", "session_id": "abc123"}
```

Includes automatic file rotation at 10 MB to prevent unbounded growth.

### precompact-snapshot.py (PreCompact -- runs before compaction)

Reads the JSONL log, filters to a configurable time window (default: 2 hours), and produces:

- **recent_files**: Deduplicated list of files touched (most recent last)
- **tool_usage**: Top 10 tools by frequency (e.g., `{"Edit": 15, "Read": 8, "Bash": 6}`)
- **work_signals**: Human-readable summary of detected patterns
- **categorized_files**: Files grouped by configurable categories (code, data, docs, config)

Example snapshot:

```json
{
  "timestamp": "2026-03-11T15:45:00+00:00",
  "trigger": "compaction",
  "recent_files": ["/src/auth.py", "/src/handler.py", "/tests/test_auth.py", "/migrations/003.sql"],
  "tool_usage": {"Edit": 12, "Read": 8, "Bash": 5, "Agent": 2},
  "work_signals": [
    "code files: auth.py, handler.py, test_auth.py",
    "data files: 003.sql",
    "Spawned 2 subagent(s)",
    "Heavy shell usage (5 commands)"
  ],
  "categorized_files": {
    "code": ["/src/auth.py", "/src/handler.py", "/tests/test_auth.py"],
    "data": ["/migrations/003.sql"]
  }
}
```

### compact-reinject.py (SessionStart -- runs after compaction)

Reads both `config.json` (static reminders) and the snapshot (dynamic state), then emits a combined context block to stderr:

```
POST-COMPACTION CONTEXT REMINDER:
- Check your project rules before making changes
- Review coordination/state files before touching shared resources
- Use /wrap-up at end of session

WORK IN PROGRESS before compaction:
  - code files: auth.py, handler.py, test_auth.py
  - data files: 003.sql
  - Spawned 2 subagent(s)
code files touched (may need build/test): auth.py, handler.py, test_auth.py
data files touched (may need apply/validate): 003.sql
Tool usage: Edit=12, Read=8, Bash=5, Agent=2
Snapshot taken: 2026-03-11T15:45:00+00:00
```

## Installation

### 1. Clone or copy the scripts

```bash
git clone https://github.com/VoxCore84/claude-code-compaction-keeper.git
# Or just copy the 3 .py files + config.json anywhere on your machine
```

### 2. Edit config.json

Customize `static_reminders` for your project and `file_categories` for your stack:

```json
{
  "static_reminders": [
    "Never push to main without PR approval",
    "Run tests before claiming a fix is complete",
    "Check .env.example when adding new environment variables"
  ],
  "file_categories": {
    "code": [".py", ".ts", ".tsx"],
    "data": [".sql", ".json", ".yaml"],
    "styles": [".css", ".scss", ".less"],
    "tests": [".test.ts", ".spec.ts", ".test.py"]
  },
  "lookback_hours": 2,
  "max_recent_files": 20
}
```

### 3. Wire the hooks into Claude Code settings

Add these three entries to your Claude Code `settings.json` (at `~/.claude/settings.json` or your project's `.claude/settings.json`). Update the paths to match where you placed the scripts:

```json
{
  "hooks": {
    "PreCompact": [
      {
        "type": "command",
        "command": "python /path/to/claude-code-compaction-keeper/precompact-snapshot.py"
      }
    ],
    "PostToolUse": [
      {
        "type": "command",
        "command": "python /path/to/claude-code-compaction-keeper/session-stats.py"
      }
    ],
    "SessionStart": [
      {
        "type": "command",
        "command": "python /path/to/claude-code-compaction-keeper/compact-reinject.py",
        "matcher": "compact"
      }
    ]
  }
}
```

A complete example is provided in `settings.json.example`.

## Configuration

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `static_reminders` | `string[]` | Generic project reminders | Lines injected after every compaction. Put your project-specific rules here. |
| `file_categories` | `object` | code/data/docs | Maps category names to file extension arrays. Categories appear in work signals and the restored context. |
| `lookback_hours` | `number` | `2` | How far back (in hours) to scan session-stats.jsonl. Shorter = less noise, longer = catches slow-burn sessions. |
| `max_recent_files` | `number` | `20` | Maximum number of recent files to include in the snapshot. |

## Why Two Stages?

A single-stage approach (just injecting static reminders at session start) cannot tell Claude what it was *doing*. It can remind Claude of project rules, but not that it was mid-refactor across 4 files with 2 subagents running.

The two-stage approach captures actual runtime state:

| Capability | Static-only | Two-stage |
|-----------|------------|----------|
| Project rules | Yes | Yes |
| Files being edited | No | Yes |
| Tool usage patterns | No | Yes |
| Subagent awareness | No | Yes |
| Work category detection | No | Yes |
| Staleness detection | No | Yes (timestamp) |

The PreCompact hook fires at the exact right moment -- after Claude has done real work but before compaction erases the evidence. This timing is what makes it work.

## Files

| File | Hook Type | Purpose |
|------|-----------|--------|
| `precompact-snapshot.py` | PreCompact | Captures work state to JSON before compaction |
| `compact-reinject.py` | SessionStart (matcher: "compact") | Restores static + dynamic context after compaction |
| `session-stats.py` | PostToolUse | Logs every tool call to JSONL (data source for Stage 1) |
| `config.json` | -- | User configuration (reminders, file categories, lookback) |
| `settings.json.example` | -- | Copy-paste hook wiring for Claude Code settings |

## Data Files (auto-created at runtime)

| File | Location | Purpose |
|------|----------|--------|
| `session-stats.jsonl` | `~/.claude/` | Running log of tool calls (rotated at 10 MB) |
| `precompact-state.json` | `~/.claude/` | Snapshot written by Stage 1, read by Stage 2 |

## Requirements

- Python 3.10+ (uses PEP 604 union types; stdlib only, no pip dependencies)
- Claude Code with hooks support

> **Note:** [claude-code-workflow-guard](https://github.com/VoxCore84/claude-code-workflow-guard) also ships a `session-stats.py` implementation. If you install both, choose one `session-stats.py` to avoid duplicate JSONL logging.

## License

MIT -- see [LICENSE](LICENSE).

---

Built by [VoxCore84](https://github.com/VoxCore84)
