# Skill: New Feature
# Invoke: "use the new-feature skill"

## Step 1 — Clarify before touching code
Ask these questions. Do not proceed until answered:
1. What is the user-facing behaviour in one sentence?
2. What are the edge cases? (empty, error, duplicate, missing data)
3. What existing code does this touch?
4. Does this require a migration?
5. What is the acceptance test?

## Step 2 — Write the plan
```
[ ] 1. <file path> — <what and why> (~X min)
[ ] 2. Run: <verification command>
```
Get approval before implementing.

## Step 3 — Implement in task order
- Check off each task as done.
- Run verification after each logical group.
- Stop and report unexpected complexity — do not silently expand scope.
- Do not add anything not in the plan.

## Step 4 — Verify
Run full test suite. Confirm the acceptance test from Step 1 passes.

## Step 5 — Commit and update memory
```bash
git add -A && git commit -m "<type>: <description>"
```
Then: `"update checkpoint"`
