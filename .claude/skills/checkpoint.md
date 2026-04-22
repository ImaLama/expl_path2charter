# Skill: Update Checkpoint
# Invoke: "update checkpoint" / "end of session" / "wrap up"

## Step 1 — Tier 1: Rewrite CHECKPOINT.md
Rewrite the entire file (not append) with:
- Current phase and what was accomplished this session (specific — file paths, function names)
- What is in progress (exact state left in)
- What comes next (2-3 concrete tasks, actionable immediately)
- Decisions made this session with rationale
- Gotchas discovered (Podman, SQLModel, library quirks — be specific)
- Known blockers

Vague checkpoints are useless. Good: "implemented `extract_from_url` in `services/extractor.py`
— returns `{title, content, author}` dict; handles unreachable URLs by returning
`{title: None, content: None}` rather than raising."

## Step 2 — Tier 2: Reinforce auto memory
Summarise explicitly for the auto-memory system:
- New files or directories created
- Commands that now work or changed
- Patterns established this session

## Step 3 — Tier 3: Save to Memory MCP
For each non-obvious insight, gotcha, or reusable pattern discovered, say:
`"Save to memory: <the insight>"`

Examples of good Memory MCP entries:
- `"Save to memory: trafilatura returns None (not empty string) on extraction failure — always check for None"`
- `"Save to memory: Podman volume mounts silently fail without :Z on SELinux — always add :Z"`
- `"Save to memory: SQLModel autogenerate misses server_default changes — add manually to Alembic migration"`
- `"Save to memory: feedparser doesn't raise on network errors — check bozo=True and empty entries list"`

## Step 4 — Commit
```bash
git add -A && git commit -m "checkpoint: <brief session summary>"
```
