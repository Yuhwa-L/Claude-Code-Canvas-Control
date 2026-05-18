---
description: Full workflow — research, draft, review, preview, and (with confirmation) submit a Canvas assignment.
argument-hint: <assignment_id> [course_id]
allowed-tools: Task, mcp__canvas__list_assignments, mcp__canvas__save_draft, mcp__canvas__prepare_submission, mcp__canvas__submit_assignment, AskUserQuestion
---

The user wants you to do the full workflow on a Canvas assignment. Arguments: `$ARGUMENTS`.

## Parse the arguments

The first argument is the `assignment_id`. The second (optional) is `course_id`.

- If only `assignment_id` was given, call `mcp__canvas__list_assignments` with no course_id and find the matching row to recover `course_id`. If you can't find it, ask the user for the course_id.

## Workflow — execute in order, do NOT skip steps

### Step 1: Research
Spawn the `canvas-researcher` subagent via the Task tool. Pass it a short prompt like:

> "Produce a research brief for Canvas assignment_id=<X>, course_id=<Y>. Use the get_assignment tool to load it, read every attachment from its local_path, and return the brief in the structured format you're trained on."

Receive the brief. Show it to the user as a brief inline summary (no pause — do NOT wait for user input here), then immediately proceed to Step 2.

### Step 2: Draft
Spawn the `canvas-writer` subagent via the Task tool. Pass it the full brief from Step 1. Receive the draft.

### Step 3: Review
Spawn the `canvas-reviewer` subagent via the Task tool. Pass it both the brief and the draft. Receive APPROVED or REVISE.

- If APPROVED: go to Step 4.
- If REVISE with blocking items: spawn `canvas-writer` again with the brief + the previous draft + the reviewer's revision list, and get a new draft. Then re-review. Max 2 revision cycles — after that, show the latest draft and the outstanding issues to the user and ask whether to proceed anyway, revise once more, or cancel.

### Step 4: Show + first confirm
Show the user the final draft IN FULL in chat. Below it, call `AskUserQuestion`:

- Question: "Ready to prepare this submission?"
- Options: "Yes, prepare it" / "Let me edit it first" / "Cancel"

If Cancel: stop. If Edit: ask what to change, then loop back to Step 2 with the user's notes appended to the brief.

### Step 5: Prepare
Call `mcp__canvas__prepare_submission(assignment_id, course_id, body=<the draft>)`. This returns a `confirm_token` and a preview.

### Step 6: Save draft to Canvas + inspection pause
Call `mcp__canvas__save_draft(assignment_id, course_id, body=<the same draft>)`. This puts the draft into the Canvas assignment text-entry box (auto-save mechanism) so the user can preview rendering in the real UI before committing.

Show the user the `assignment_url` returned and ask them to open it in their browser to inspect the draft as Canvas will render it. Then call `AskUserQuestion`:

- Question: "Does the draft look right in Canvas?"
- Options: "Yes, looks good — submit" / "Looks broken — let me edit" / "Cancel"

If "Looks broken": ask what to change and loop back to Step 2.
If "Cancel": stop.
If "Yes": continue to Step 7.

If `save_draft` fails (some institutions disable the submission_drafts endpoint), report the error and ask whether to skip straight to submit or cancel. Do NOT silently fall through.

### Step 7: Final confirm + submit
Show the user the preview returned by `prepare_submission` (word count + first/last chars) and call `AskUserQuestion`:

- Question: "Submit this to Canvas now?"
- Options: "Submit" / "Cancel"

ONLY if the user picks Submit: call `mcp__canvas__submit_assignment(assignment_id, confirm_token=<the token>)`.

### Step 8: Report
Show the user the submission result — whether ok, the submission_id, the html_url to view it on Canvas, and the audit log line.

## Rules

- NEVER call `submit_assignment` without going through `prepare_submission` first AND getting the user's "Submit" answer at Step 7.
- The `prepare_submission` token expires in 10 minutes. If the user takes a long time inspecting the Canvas draft at Step 6, the token may expire; re-call `prepare_submission` before `submit_assignment` if so.
- If any step fails, stop and report the error. Do not silently retry on submissions.
- Drafts live in the conversation only. Do not write them to disk.
