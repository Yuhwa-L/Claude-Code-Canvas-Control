# Claude-Code-Canvas-Control

A project-scoped Canvas LMS integration for Claude Code. Let Claude check your assignments, read descriptions + attachments, draft the work with a researcher/writer/reviewer pipeline, and submit text-entry assignments — **always** pausing for your confirmation before anything is sent to Canvas.

The MCP server, agents, and slash commands all live inside this repo. They only activate when you `cd` into this directory, so they cost zero tokens in unrelated projects.

## Setup

### 1. Authenticate

You need ONE of two auth methods. Pick whichever works for your account.

#### Option A — Personal Access Token (preferred when available)

In Canvas: **Account → Settings → New Access Token**. Copy the token immediately — Canvas only shows it once.

If the "New Access Token" button is grayed out, your institution has blocked PATs. Use Option B.

#### Option B — Session cookie (works when PATs are blocked)

**Do NOT use `document.cookie` in the Console.** The Canvas session cookie (`canvas_session`) is `HttpOnly` and invisible to JavaScript by design — you'd copy only analytics cookies and your requests will 401. Use the Network tab instead.

1. Log into Canvas in your browser.
2. Open DevTools — `F12` on Windows/Linux, `Cmd+Opt+I` on macOS. Go to the **Network** tab.
3. In Canvas, click around so a request fires (or just reload the page). Make sure the Network panel is recording.
4. Click any request to your Canvas host (e.g. `online.smc.edu`).
5. Right-click the request → **Copy** → **Copy as cURL**.
6. Paste somewhere scratch. Find the `-H 'Cookie: …'` segment (Safari/Firefox may use `-b '…'`). Copy the value **between the single quotes** — it will look like:
   ```
   _csrf_token=…; canvas_session=…; log_session_id=…; _ga=…; …
   ```
7. You'll paste this whole string into `.env` in the next step.

**Alternative (browser extension):** Install "Cookie-Editor" (Chrome/Firefox), open it on a Canvas tab, click **Export → Header String**, paste into `.env`. Same result, no DevTools.

**Caveats for cookie auth:**
- The cookie expires when you log out of Canvas in that browser. When you start getting 401 errors, repeat the steps above to refresh.
- **The MCP server reads `.env` only at startup.** After updating the cookie, restart Claude Code (or kill the `canvas_mcp.py` process and reconnect via `/mcp`) so the new value takes effect.
- At minimum the cookie string must include `canvas_session` and `_csrf_token`. Including `log_session_id` is recommended.
- Use the same browser you're actively logged into. Don't share the cookie — it's equivalent to your password for that session.
- Submissions (POST requests) *should* work because the server also extracts and sends the CSRF token from the cookie. If submissions fail with a 422 or CSRF error, file an issue — we may need a Playwright fallback for the submit step.

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:
- `CANVAS_API_URL` — your Canvas base URL (e.g. `https://canvas.instructure.com` or `https://your-school.instructure.com`)
- Fill in EITHER `CANVAS_API_TOKEN` (Option A) OR `CANVAS_COOKIE` (Option B) — not both. If both are set, the token is used.

`.env` is gitignored — never commit it. Especially important for the cookie, which grants full account access.

### 3. Install Python dependencies

```bash
python3 -m pip install -r server/requirements.txt
```

If you prefer a venv:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
```
(If using a venv, point `.mcp.json`'s `command` to `.venv/bin/python` instead of `python3`.)

### 4. Restart Claude Code in this directory

The first time Claude Code opens this project it will detect `.mcp.json` and ask to enable the `canvas` server. Approve it. Verify with `/mcp` — you should see `canvas` listed with 6 tools.

## Usage

| Command | What it does |
|---------|-------------|
| `/canvas-check` | List all pending assignments across your courses |
| `/canvas-check <course-name>` | Same, filtered to one course (substring match on course name or code) |
| `/canvas-next` | Show only the **single** next-due pending assignment (across all courses) — useful when you don't want to scroll a long list |
| `/canvas-next <course-name>` | Same, scoped to one course |
| `/canvas-do <assignment_id>` | Research → draft → review → in-chat preview → save draft to Canvas → visual inspection in browser → confirm → submit |
| `/canvas-submit <assignment_id>` | Submit your own text (skips the draft workflow) |

## How submission safety works

`/canvas-do` walks through three checkpoints before a real submission is created on Canvas:

1. **In-chat draft review.** After the writer/reviewer pipeline approves a draft, the full text is shown in chat with a Yes / Edit / Cancel prompt.
2. **Canvas-UI inspection.** The draft is written to the assignment's text-entry box via `save_draft` (NOT submitted yet — Canvas treats it as the auto-saved draft, the same as if you'd typed it). You open the assignment URL in your browser, verify the rendering, line breaks, bold, spacing, and any special characters, then answer a Looks good / Edit / Cancel prompt. This step catches HTML/formatting issues before they're locked into a graded submission.
3. **MCP token gate.** Even after both prompts, the `submit_assignment` tool requires a `confirm_token` issued by `prepare_submission`. The token is bound to (assignment_id, body hash), expires after 10 minutes, and is invalidated on first use. A misbehaving agent cannot blind-submit — and cannot swap the body between prepare and submit either.

`/canvas-submit` (the bring-your-own-text path) keeps checkpoints 1 and 3 but skips the Canvas-UI inspection step.

Every successful submission is appended to `submissions.log` (gitignored) with timestamp, assignment ID, body hash, and Canvas response info.

## Body formatting

Canvas renders `online_text_entry` submission bodies as **HTML**, not markdown. The `/canvas-do` writer drafts in HTML using `<p>`, `<strong>`, `<em>`, and `<p>&nbsp;</p>` for visible spacing between sections. If you write your own body via `/canvas-submit`, use HTML for anything you want rendered — markdown like `**bold**` will appear as literal asterisks in the submitted view.

## Architecture

- **`server/canvas_mcp.py`** — FastMCP server exposing 6 tools: `list_courses`, `list_assignments`, `get_assignment`, `save_draft`, `prepare_submission`, `submit_assignment`. Direct httpx calls to Canvas API, no ORM.
  - `list_assignments` does NOT use Canvas's `bucket=unsubmitted` filter (that filter silently excludes overdue work). It fetches all assignments and filters client-side on `submission.workflow_state` so past-due unsubmitted items show up.
  - `save_draft` uses Canvas's GraphQL `createSubmissionDraft` mutation at `/api/graphql` — the same call the modern React assignment UI makes when you type in the text box. The REST endpoint `/api/v1/submission_drafts` is disabled at some institutions (including SMC), so the GraphQL path is more portable.
- **`.claude/agents/`** — three subagents (`canvas-researcher`, `canvas-writer`, `canvas-reviewer`) that run in isolated contexts so heavy reading (attachments, rubrics) doesn't pollute the main conversation.
- **`.claude/commands/`** — three slash commands that orchestrate the agents and MCP tools.
- **`.mcp.json`** — registers the server in this project only.
- **`.claude/settings.json`** — auto-allows the read-only tools (`list_courses`, `list_assignments`, `get_assignment`) plus `prepare_submission` (which only stages locally, no Canvas write). `save_draft` and `submit_assignment` are NOT in the allow list and will prompt on every call — `save_draft` because it writes to Canvas's draft store, `submit_assignment` because it creates a permanent attempt. If you find the `save_draft` prompt noisy, you can add it to `permissions.allow` at your own discretion; the workflow always shows the assignment URL afterward regardless.
- **`scripts/probe_draft.py`** — diagnostic script that probes every known draft-save mechanism (REST flat, REST nested, REST JSON, assignment-scoped REST, GraphQL) against your Canvas instance and reports which work. Run when `save_draft` starts failing or when porting this repo to a new institution: `python3 scripts/probe_draft.py`.

## Token discipline

- List endpoints return only IDs, names, dates, points — never descriptions.
- `get_assignment` strips HTML to text and truncates at 8KB (full HTML saved to `attachments/desc_<id>.html` for fallback).
- Attachments cached once in `./attachments/` and reused.
- Researcher runs in a subagent — main thread only sees the ~500-word brief.
- Drafts live in conversation memory; not written to disk.

## Troubleshooting

- **`/mcp` doesn't show `canvas`** — make sure you approved the project MCP server when prompted, and that `.env` has `CANVAS_API_URL` plus either `CANVAS_API_TOKEN` or `CANVAS_COOKIE`. Restart Claude Code.
- **`Auth missing` on startup** — `.env` has neither token nor cookie set.
- **401 from Canvas** — token is wrong/expired (Option A), or your session cookie has expired or is missing `canvas_session` (Option B). For Option B, refresh the cookie via DevTools → Network → Copy as cURL (see Setup §1) and **restart Claude Code** so the MCP server reloads `.env`. Quick sanity check: `curl -H "Cookie: $CANVAS_COOKIE" $CANVAS_API_URL/api/v1/users/self` should return 200.
- **422 / CSRF error on submit (cookie auth only)** — Canvas is rejecting the POST. Try grabbing a fresh cookie. If it persists, the institution may require a real-browser POST; we can add a Playwright fallback for the submit step.
- **Overdue assignment not in `/canvas-check`** — this was a real bug, now fixed. Canvas's `bucket=unsubmitted` filter excludes past-due items by design; the server used to apply that filter and silently hide overdue work. The current code skips the bucket filter and filters client-side, so overdue unsubmitted assignments DO show up. If something is still missing, verify it's genuinely unsubmitted (`only_pending=false` will include submitted/graded too).
- **`/canvas-check` returns `[]` when it shouldn't** — the MCP server used to swallow HTTP errors with `except httpx.HTTPStatusError: continue`, which made auth failures look like "no assignments." The server now re-raises with a `RuntimeError` containing the status code and Canvas error body. If you see a real error message, that's the fix. If you still see an empty list, the API genuinely returned no rows.
- **`save_draft` fails with 404 / `"Unexpected error, ID: unknown"`** — your institution disables the REST `/api/v1/submission_drafts` endpoint. The shipped `save_draft` already uses the GraphQL mutation as a workaround, which works at SMC. If you still see 404s, your Canvas may have disabled GraphQL too. Run `python3 scripts/probe_draft.py` to see which endpoints respond, and file an issue with the probe output.
- **Mid-session 401 after several successful calls** — the cookie session expired or rotated. Refresh `CANVAS_COOKIE` in `.env` and run `/mcp` to reconnect. Note: any in-flight `confirm_token` from `prepare_submission` is lost when the MCP server restarts and you'll need to re-prepare.

## What this does NOT do

- File-upload submissions (PDFs, docs) — text entry only.
- Quizzes, discussions, or graded peer reviews.
- Group assignments with special workflows.
- Automatic / scheduled runs. No background polling. Nothing happens unless you invoke a command.
