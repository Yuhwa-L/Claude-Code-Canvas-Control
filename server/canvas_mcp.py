"""Canvas LMS MCP server.

Five tools: list_courses, list_assignments, get_assignment,
prepare_submission, submit_assignment.

Submission safety: submit_assignment requires a confirm_token issued by
prepare_submission. The token binds to (assignment_id, body) so the body
cannot be swapped between prepare and submit. Tokens expire after 10 min
or after first use.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

CANVAS_URL = os.environ["CANVAS_API_URL"].rstrip("/")
CANVAS_TOKEN = os.environ.get("CANVAS_API_TOKEN") or None
CANVAS_COOKIE = os.environ.get("CANVAS_COOKIE") or None

if not CANVAS_TOKEN and not CANVAS_COOKIE:
    raise SystemExit(
        "Auth missing. Set either CANVAS_API_TOKEN or CANVAS_COOKIE in .env. "
        "See README.md for instructions."
    )

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ATTACHMENT_DIR = PROJECT_ROOT / "attachments"
ATTACHMENT_DIR.mkdir(exist_ok=True)
SUBMISSIONS_LOG = PROJECT_ROOT / "submissions.log"


def _build_headers() -> dict:
    if CANVAS_TOKEN:
        return {"Authorization": f"Bearer {CANVAS_TOKEN}"}
    # Cookie auth fallback (used when institution blocks PATs).
    headers = {
        "Cookie": CANVAS_COOKIE,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
    }
    m = re.search(r"_csrf_token=([^;]+)", CANVAS_COOKIE or "")
    if m:
        headers["X-CSRF-Token"] = urllib.parse.unquote(m.group(1))
    return headers


_client = httpx.Client(headers=_build_headers(), timeout=30.0)

_pending: dict[str, dict] = {}
_TOKEN_TTL_SEC = 600

mcp = FastMCP("canvas")


class _HTMLStripper(HTMLParser):
    _BLOCK = {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip = True
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = False
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def _strip_html(s: str) -> str:
    if not s:
        return ""
    p = _HTMLStripper()
    try:
        p.feed(s)
    except Exception:
        return s
    text = "".join(p.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return html.unescape(text).strip()


_FILE_LINK_RE = re.compile(r"/(?:courses/\d+/)?files/(\d+)")


def _extract_file_ids(s: str) -> list[int]:
    if not s:
        return []
    return sorted({int(m) for m in _FILE_LINK_RE.findall(s)})


def _paginate(url: str, params: Optional[dict] = None, cap: int = 500) -> list:
    out: list = []
    next_url: Optional[str] = url
    next_params = dict(params or {})
    next_params.setdefault("per_page", 50)
    while next_url:
        r = _client.get(next_url, params=next_params)
        r.raise_for_status()
        out.extend(r.json())
        next_url = None
        next_params = {}
        link = r.headers.get("Link", "")
        for part in link.split(","):
            if 'rel="next"' in part:
                m = re.search(r"<([^>]+)>", part)
                if m:
                    next_url = m.group(1)
                break
        if len(out) >= cap:
            break
    return out


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120]


def _download_file(file_id: int) -> dict:
    r = _client.get(f"{CANVAS_URL}/api/v1/files/{file_id}")
    r.raise_for_status()
    meta = r.json()
    name = meta.get("display_name") or meta.get("filename") or f"file_{file_id}"
    local = ATTACHMENT_DIR / f"{file_id}_{_safe_name(name)}"
    if not local.exists():
        dl = httpx.get(meta["url"], follow_redirects=True, timeout=60.0)
        dl.raise_for_status()
        local.write_bytes(dl.content)
    return {
        "file_id": file_id,
        "name": name,
        "mime": meta.get("content-type") or meta.get("mime_class"),
        "size": meta.get("size"),
        "local_path": str(local),
    }


@mcp.tool()
def list_courses() -> list[dict]:
    """List your active Canvas courses.

    Returns compact rows: id, name, course_code, term.
    Use this to resolve a course name to an id for list_assignments.
    """
    raw = _paginate(
        f"{CANVAS_URL}/api/v1/courses",
        params={"enrollment_state": "active", "include[]": "term"},
    )
    return [
        {
            "id": c["id"],
            "name": c.get("name"),
            "course_code": c.get("course_code"),
            "term": (c.get("term") or {}).get("name"),
        }
        for c in raw
        if not c.get("access_restricted_by_date")
    ]


@mcp.tool()
def list_assignments(
    course_id: Optional[int] = None,
    only_pending: bool = True,
    limit: Optional[int] = None,
) -> list[dict]:
    """List assignments.

    If course_id is provided, scoped to that course; otherwise iterates all
    active courses.

    only_pending=True (default) returns assignments the user has NOT yet
    submitted (any due date, including overdue). Set False to include
    submitted/graded assignments too.

    limit=N returns at most N rows (the N earliest-due). Use this when you
    only need the next-due assignment(s) instead of the full list.

    Returns compact rows. Descriptions are NOT included to save tokens;
    use get_assignment for full detail.
    """
    if course_id is not None:
        course_ids = [course_id]
        course_names: dict[int, str] = {}
        try:
            r = _client.get(f"{CANVAS_URL}/api/v1/courses/{course_id}")
            if r.status_code == 200:
                course_names[course_id] = r.json().get("name")
        except httpx.HTTPError:
            pass
    else:
        courses = list_courses()
        course_ids = [c["id"] for c in courses]
        course_names = {c["id"]: c["name"] for c in courses}

    rows: list[dict] = []
    for cid in course_ids:
        params: dict = {"include[]": "submission", "order_by": "due_at"}
        try:
            items = _paginate(
                f"{CANVAS_URL}/api/v1/courses/{cid}/assignments",
                params=params,
            )
        except httpx.HTTPStatusError as e:
            # Surface failures (esp. 401 from expired cookies) instead of returning [].
            raise RuntimeError(
                f"Canvas API {e.response.status_code} for course {cid} "
                f"({course_names.get(cid)}): {e.response.text[:200]}"
            ) from e
        for a in items:
            sub = a.get("submission") or {}
            if only_pending and sub.get("workflow_state") in ("submitted", "graded"):
                continue
            rows.append(
                {
                    "id": a["id"],
                    "course_id": cid,
                    "course_name": course_names.get(cid),
                    "name": a.get("name"),
                    "due_at": a.get("due_at"),
                    "points": a.get("points_possible"),
                    "submission_types": a.get("submission_types") or [],
                    "html_url": a.get("html_url"),
                }
            )
    rows.sort(key=lambda r: (r["due_at"] is None, r["due_at"] or ""))
    if limit is not None and limit >= 0:
        rows = rows[:limit]
    return rows


@mcp.tool()
def get_assignment(assignment_id: int, course_id: int) -> dict:
    """Full detail for one assignment + auto-downloaded attachments.

    Description HTML is stripped to plain text. If >8000 chars it is
    truncated with a marker and the full HTML saved to
    attachments/desc_<id>.html for fallback reading.

    File links referenced in the description are downloaded to
    attachments/<file_id>_<name> and their local paths returned.
    """
    r = _client.get(
        f"{CANVAS_URL}/api/v1/courses/{course_id}/assignments/{assignment_id}",
        params={"include[]": "rubric"},
    )
    r.raise_for_status()
    a = r.json()

    raw_html = a.get("description") or ""
    text = _strip_html(raw_html)
    truncated = False
    if len(text) > 8000:
        fallback = ATTACHMENT_DIR / f"desc_{assignment_id}.html"
        fallback.write_text(raw_html, encoding="utf-8")
        text = text[:8000] + f"\n\n[... truncated. Full HTML at {fallback} ...]"
        truncated = True

    attachments: list[dict] = []
    for fid in _extract_file_ids(raw_html):
        try:
            attachments.append(_download_file(fid))
        except Exception as e:
            attachments.append({"file_id": fid, "error": str(e)})

    return {
        "id": a["id"],
        "course_id": course_id,
        "name": a.get("name"),
        "due_at": a.get("due_at"),
        "points_possible": a.get("points_possible"),
        "submission_types": a.get("submission_types") or [],
        "html_url": a.get("html_url"),
        "description": text,
        "description_truncated": truncated,
        "rubric": a.get("rubric"),
        "attachments": attachments,
    }


@mcp.tool()
def save_draft(assignment_id: int, course_id: int, body: str) -> dict:
    """Save a text-entry draft to Canvas WITHOUT submitting.

    The draft becomes the auto-saved content of the assignment's text-entry
    box, visible when the user opens the assignment in the Canvas UI. Same
    storage mechanism the rich-text editor uses for auto-save.

    Use this before submit_assignment so the user can preview rendering
    (markdown, line breaks, special chars) in the actual Canvas UI and
    catch formatting issues before committing to a real submission.

    Returns the assignment_url for the user to open and inspect.
    """
    body = body or ""
    if not body.strip():
        return {"error": "empty_body", "message": "Cannot save an empty draft."}

    # Need submission_id + next attempt number for the drafts endpoint.
    r = _client.get(
        f"{CANVAS_URL}/api/v1/courses/{course_id}/assignments/"
        f"{assignment_id}/submissions/self"
    )
    if r.status_code >= 400:
        return {
            "ok": False,
            "error": "submission_lookup_failed",
            "status": r.status_code,
            "message": r.text[:500],
        }
    sub = r.json()
    submission_id = sub["id"]
    attempt = (sub.get("attempt") or 0) + 1

    # Canvas's REST /api/v1/submission_drafts endpoint is disabled at some
    # institutions (SMC included). The React assignment UI uses the GraphQL
    # createSubmissionDraft mutation, which works everywhere the modern UI
    # does. Use that instead.
    mutation = """
    mutation CreateSubmissionDraft(
      $submissionId: ID!,
      $activeSubmissionType: DraftableSubmissionType!,
      $attempt: Int!,
      $body: String
    ) {
      createSubmissionDraft(input: {
        submissionId: $submissionId,
        activeSubmissionType: $activeSubmissionType,
        attempt: $attempt,
        body: $body
      }) {
        submissionDraft { _id body }
        errors { attribute message }
      }
    }
    """
    r = _client.post(
        f"{CANVAS_URL}/api/graphql",
        json={
            "query": mutation,
            "variables": {
                "submissionId": str(submission_id),
                "activeSubmissionType": "online_text_entry",
                "attempt": attempt,
                "body": body,
            },
        },
    )
    if r.status_code >= 400:
        return {
            "ok": False,
            "error": "canvas_error",
            "status": r.status_code,
            "message": r.text[:500],
        }

    payload = r.json()
    gql_errors = payload.get("errors")
    if gql_errors:
        return {
            "ok": False,
            "error": "graphql_error",
            "message": json.dumps(gql_errors)[:500],
        }
    mutation_errors = (
        payload.get("data", {})
        .get("createSubmissionDraft", {})
        .get("errors")
    )
    if mutation_errors:
        return {
            "ok": False,
            "error": "mutation_error",
            "message": json.dumps(mutation_errors)[:500],
        }
    draft = (
        payload.get("data", {})
        .get("createSubmissionDraft", {})
        .get("submissionDraft")
    )

    return {
        "ok": True,
        "assignment_url": f"{CANVAS_URL}/courses/{course_id}/assignments/{assignment_id}",
        "draft_id": draft.get("_id") if draft else None,
        "submission_id": submission_id,
        "attempt": attempt,
        "char_count": len(body),
        "word_count": len(body.split()),
    }


@mcp.tool()
def prepare_submission(
    assignment_id: int, course_id: int, body: str
) -> dict:
    """Stage a text-entry submission and return a preview + one-time confirm_token.

    The confirm_token is REQUIRED to call submit_assignment. The token binds
    to (assignment_id, course_id, body) so the body cannot be swapped before
    submit. Tokens expire after 10 minutes or after first use.

    ALWAYS show the preview to the user via AskUserQuestion before calling
    submit_assignment.
    """
    body = body or ""
    if not body.strip():
        return {"error": "empty_body", "message": "Cannot prepare an empty submission."}
    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    token = hashlib.sha256(
        f"{assignment_id}:{course_id}:{body_hash}:{time.time()}".encode()
    ).hexdigest()[:24]
    _pending[token] = {
        "assignment_id": assignment_id,
        "course_id": course_id,
        "body": body,
        "body_hash": body_hash,
        "expires_at": time.time() + _TOKEN_TTL_SEC,
    }
    if len(body) <= 600:
        preview = body
    else:
        preview = body[:400] + "\n\n[... middle omitted ...]\n\n" + body[-200:]
    return {
        "confirm_token": token,
        "char_count": len(body),
        "word_count": len(body.split()),
        "preview": preview,
        "expires_in_seconds": _TOKEN_TTL_SEC,
    }


@mcp.tool()
def submit_assignment(assignment_id: int, confirm_token: str) -> dict:
    """Submit a prepared text entry to Canvas.

    REQUIRES a confirm_token from prepare_submission. Rejects if the token
    is unknown, expired, already used, or bound to a different assignment.

    Appends a line to submissions.log on success.
    """
    pending = _pending.pop(confirm_token, None)
    if pending is None:
        return {
            "ok": False,
            "error": "invalid_or_used_token",
            "message": "No pending submission for this token. Call prepare_submission first.",
        }
    if pending["assignment_id"] != assignment_id:
        _pending[confirm_token] = pending
        return {
            "ok": False,
            "error": "assignment_mismatch",
            "message": "Token was issued for a different assignment.",
        }
    if time.time() > pending["expires_at"]:
        return {
            "ok": False,
            "error": "expired",
            "message": "Token expired. Call prepare_submission again.",
        }

    course_id = pending["course_id"]
    body = pending["body"]

    r = _client.post(
        f"{CANVAS_URL}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions",
        data={
            "submission[submission_type]": "online_text_entry",
            "submission[body]": body,
        },
    )
    if r.status_code >= 400:
        return {
            "ok": False,
            "error": "canvas_error",
            "status": r.status_code,
            "message": r.text[:500],
        }

    sub = r.json()
    with SUBMISSIONS_LOG.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "assignment_id": assignment_id,
                    "course_id": course_id,
                    "body_hash": pending["body_hash"],
                    "char_count": len(body),
                    "submission_id": sub.get("id"),
                    "attempt": sub.get("attempt"),
                    "status": r.status_code,
                }
            )
            + "\n"
        )

    return {
        "ok": True,
        "submission_id": sub.get("id"),
        "attempt": sub.get("attempt"),
        "body_hash": pending["body_hash"],
        "submitted_at": sub.get("submitted_at"),
        "preview_url": sub.get("preview_url"),
        "html_url": sub.get("html_url"),
    }


if __name__ == "__main__":
    mcp.run()
