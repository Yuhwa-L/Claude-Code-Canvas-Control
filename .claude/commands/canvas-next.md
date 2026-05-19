---
description: Show the next pending Canvas assignment after the last one you viewed. Advances a per-course cursor each call. Use /canvas-oldest to reset or find the earliest-due one.
argument-hint: [course-name]
allowed-tools: mcp__canvas__list_courses, mcp__canvas__list_assignments, Read, Write
---

The user wants to see the next pending Canvas assignment after the last one they viewed. Arguments: `$ARGUMENTS` (may be empty, or a course name / partial match).

## Cursor file

The cursor is stored at `.claude/canvas-cursor.json` in the project root. Structure:

```json
{
  "81646": 2197122,
  "all": 99999
}
```

Keys are course_id as a string (or `"all"` when no course filter). Values are the assignment ID last shown to the user. Read this file at the start; write it at the end with the new ID.

If the file does not exist, treat all cursors as absent (start from the beginning).

## What to do

### 1. Resolve course (same as canvas-next)

- If `$ARGUMENTS` is empty: use `course_key = "all"`, no `course_id` filter.
- If `$ARGUMENTS` has content: call `mcp__canvas__list_courses`, find the matching course.
  - Multiple matches: list them and ask the user to pick. Stop (do not fetch assignments yet).
  - No match: say so, list all courses. Stop.
  - One match: use its `id` as `course_id`, `course_key = "<id>"`.

### 2. Fetch assignments

Call `mcp__canvas__list_assignments` with `only_pending=true` and `limit=20` (and `course_id` if resolved).

**Filter:** remove any row where `submission_types` is `["none"]` or empty — these are in-class assignments that cannot be submitted online.

If zero rows remain after filtering, say "No submittable pending assignments." and stop (do not update cursor).

### 3. Apply cursor

Read `.claude/canvas-cursor.json`. Look up the cursor for `course_key`.

- If no cursor exists for this key: the target is the **first** row in the filtered list.
- If a cursor exists: find the row whose `id` matches the cursor, then take the row immediately after it.
  - If the cursor ID is not found (already submitted or removed): start from the **first** row.
  - If the cursor ID was the **last** row: say "You have reached the end of the list. Run /canvas-oldest to start over." and stop (do not update cursor).

### 4. Display

Render as a compact one-row table:

| Due | Course | Assignment | Type | Pts | ID |
|-----|--------|------------|------|-----|----|
| 2026-05-20 | HIST 201 | Essay 3: Reformation | text | 100 | 12345 |

For the **Type** column, map `submission_types` to a short label:
- `["discussion_topic"]` → `discussion`
- `["online_text_entry"]` → `text`
- `["online_upload"]` → `upload`
- `["none"]` or empty → `in-class`
- anything else → the raw value

Due dates as `YYYY-MM-DD`.

Below the table, one line: `Next step: /canvas-do <ID>`

### 5. Save cursor

Write `.claude/canvas-cursor.json` with the shown assignment's ID saved under `course_key`. Preserve all other keys already in the file.

## What NOT to do

- Do NOT call `get_assignment`.
- Do NOT call any submission tools.
- Do NOT show more than one row.
- Do NOT auto-run `/canvas-do`.
- Do NOT add commentary beyond the table and next-step line.
