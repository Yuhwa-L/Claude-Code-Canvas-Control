---
description: Show ONLY the next-due pending Canvas assignment. Use this when you don't want to scroll a long list to find an ID.
argument-hint: [course-name]
allowed-tools: mcp__canvas__list_courses, mcp__canvas__list_assignments
---

The user wants to see the **single** next-due pending Canvas assignment so they can grab the ID and run `/canvas-do` without scrolling a long list.

Arguments: `$ARGUMENTS` (may be empty, or a course name / partial match).

## What to do

1. **If `$ARGUMENTS` is empty:** call `mcp__canvas__list_assignments` with `only_pending=true` and `limit=1` and no `course_id`. This returns at most one row — the earliest-due unsubmitted assignment across all courses.

2. **If `$ARGUMENTS` has content:** first call `mcp__canvas__list_courses` and find the course whose `name` or `course_code` matches (case-insensitive substring match).
   - If multiple courses match, list them in a compact table and ask the user to pick one. Do NOT call `list_assignments` yet.
   - If no course matches, say so and list all courses for reference. Stop.
   - If exactly one matches, call `mcp__canvas__list_assignments` with that `course_id`, `only_pending=true`, and `limit=1`.

3. Render the result as a compact one-row markdown table:

   | Due | Course | Assignment | Pts | ID |
   |-----|--------|-----------|-----|------|
   | 2026-05-20 | HIST 201 | Essay 3: Reformation | 100 | 12345 |

   Due dates as `YYYY-MM-DD` (slice the date portion off the UTC ISO).

4. Below the table, write exactly one line: `Next step: /canvas-do <ID>` substituting the assignment's id.

5. If `list_assignments` returns zero rows, say "No pending assignments. Nice." and stop.

## What NOT to do

- Do NOT call `get_assignment` — this is still a list view, just trimmed.
- Do NOT call any submission tools.
- Do NOT loop or paginate — `limit=1` already gives you the single earliest row.
- Do NOT auto-run `/canvas-do`. The user runs that themselves after seeing the ID.
- Do NOT add commentary or analysis beyond the table and the next-step line.
