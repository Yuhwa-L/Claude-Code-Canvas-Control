---
description: Show the oldest (earliest-due) pending submittable Canvas assignment. Does not use or change the canvas-next cursor.
argument-hint: [course-name]
allowed-tools: mcp__canvas__list_courses, mcp__canvas__list_assignments
---

The user wants to see the earliest-due pending submittable Canvas assignment. Arguments: `$ARGUMENTS` (may be empty, or a course name / partial match).

## What to do

### 1. Resolve course

- If `$ARGUMENTS` is empty: no `course_id` filter.
- If `$ARGUMENTS` has content: call `mcp__canvas__list_courses`, find the matching course.
  - Multiple matches: list them and ask the user to pick. Stop.
  - No match: say so, list all courses. Stop.
  - One match: use its `id` as `course_id`.

### 2. Fetch and filter

Call `mcp__canvas__list_assignments` with `only_pending=true` and `limit=20` (and `course_id` if resolved).

**Filter:** remove any row where `submission_types` is `["none"]` or empty.

Take the **first** row from the filtered list (earliest due date).

If zero rows remain, say "No submittable pending assignments. Nice." and stop.

### 3. Display

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

## What NOT to do

- Do NOT call `get_assignment`.
- Do NOT call any submission tools.
- Do NOT read or write the cursor file.
- Do NOT show more than one row.
- Do NOT auto-run `/canvas-do`.
- Do NOT add commentary beyond the table and next-step line.
