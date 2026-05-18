---
description: List pending Canvas assignments. Optionally filter by course name.
argument-hint: [course-name]
allowed-tools: mcp__canvas__list_courses, mcp__canvas__list_assignments
---

The user wants to see pending Canvas assignments. Arguments: `$ARGUMENTS` (may be empty, or a course name / partial match).

## What to do

1. If `$ARGUMENTS` is empty, call `mcp__canvas__list_assignments` with no `course_id` and `only_pending=true`.

2. If `$ARGUMENTS` has content, first call `mcp__canvas__list_courses` and find the course whose `name` or `course_code` matches (case-insensitive substring match). Then call `mcp__canvas__list_assignments` with that `course_id`.
   - If multiple courses match, list them and ask the user to pick.
   - If no course matches, say so and list all courses for reference.

3. Render the result as a compact markdown table:

   | Due | Course | Assignment | Pts | ID |
   |-----|--------|-----------|-----|------|
   | 2026-05-20 | HIST 201 | Essay 3: Reformation | 100 | 12345 |

   Sort by due date (already sorted by the server, but verify). Show due dates in `YYYY-MM-DD` format in the user's local sense (Canvas returns UTC ISO — just slice the date portion is fine).

4. Below the table, add one line: `Next step: /canvas-do <ID>` if there are any pending assignments. If none, say "No pending assignments. Nice."

## What NOT to do

- Do NOT call `get_assignment` here — this is a list view only.
- Do NOT call any submission tools.
- Do NOT add extra commentary, recommendations, or analysis beyond the table.
