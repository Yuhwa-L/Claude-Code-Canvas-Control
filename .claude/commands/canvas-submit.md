---
description: Submit user-provided text to a Canvas assignment (skips the research/draft workflow).
argument-hint: <assignment_id> [course_id]
allowed-tools: mcp__canvas__list_assignments, mcp__canvas__prepare_submission, mcp__canvas__submit_assignment, AskUserQuestion
---

The user has already written the submission text themselves and wants to submit it. Arguments: `$ARGUMENTS`.

## Parse arguments

First arg is `assignment_id`. Second (optional) is `course_id`. If course_id missing, look it up via `mcp__canvas__list_assignments`.

## Workflow

1. Ask the user (via AskUserQuestion or just in chat — your choice) for the body of the submission. Accept it as plain text or markdown. If they already pasted it in the same message, use that.

2. Call `mcp__canvas__prepare_submission(assignment_id, course_id, body=<text>)`. Get the `confirm_token` and preview.

3. Show the user the preview (word count, first/last chars) and call `AskUserQuestion`:
   - Question: "Submit this to Canvas now?"
   - Options: "Submit" / "Cancel"

4. If Submit: call `mcp__canvas__submit_assignment(assignment_id, confirm_token=<token>)`. Report the result.

If Cancel: stop. The token will expire on its own.

## Rules

- Never call `submit_assignment` without the user's explicit "Submit" choice.
- Do NOT spawn the researcher/writer/reviewer agents — the user already wrote the work.
- Do NOT modify or "improve" the user's text. Submit it verbatim.
