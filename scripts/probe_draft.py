"""Probe Canvas API to find a working save-draft mechanism for SMC.

Tries multiple known endpoints/methods and reports which works.
Run from project root: python3 scripts/probe_draft.py
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse

import httpx
from dotenv import load_dotenv

load_dotenv()

CANVAS_URL = os.environ["CANVAS_API_URL"].rstrip("/")
TOKEN = os.environ.get("CANVAS_API_TOKEN") or None
COOKIE = os.environ.get("CANVAS_COOKIE") or None

ASSIGNMENT_ID = 2146560
COURSE_ID = 81646
TEST_BODY = "PROBE TEST DRAFT — please ignore. Will be overwritten."


def build_headers() -> dict:
    if TOKEN:
        return {"Authorization": f"Bearer {TOKEN}"}
    headers = {
        "Cookie": COOKIE,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
    }
    m = re.search(r"_csrf_token=([^;]+)", COOKIE or "")
    if m:
        headers["X-CSRF-Token"] = urllib.parse.unquote(m.group(1))
    return headers


client = httpx.Client(headers=build_headers(), timeout=30.0)


def banner(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def report(r: httpx.Response, label: str) -> None:
    print(f"\n[{label}] {r.request.method} {r.request.url}")
    print(f"  status: {r.status_code}")
    body = r.text
    if len(body) > 400:
        body = body[:400] + "..."
    print(f"  body:   {body}")


# ---------------------------------------------------------------------
# Step 1: confirm auth + get submission_id
# ---------------------------------------------------------------------
banner("Step 1: GET submission for self (need submission_id)")
r = client.get(
    f"{CANVAS_URL}/api/v1/courses/{COURSE_ID}/assignments/"
    f"{ASSIGNMENT_ID}/submissions/self"
)
report(r, "submission")
if r.status_code != 200:
    raise SystemExit("Auth or submission lookup broken — fix first.")
sub = r.json()
SUBMISSION_ID = sub["id"]
ATTEMPT = (sub.get("attempt") or 0) + 1
USER_ID = sub.get("user_id")
print(f"\n  -> submission_id={SUBMISSION_ID}, next_attempt={ATTEMPT}, user_id={USER_ID}")


# ---------------------------------------------------------------------
# Step 2: REST attempts at /api/v1/submission_drafts
# ---------------------------------------------------------------------
banner("Step 2: REST /api/v1/submission_drafts variants")

# A — flat params (what we tried first)
r = client.post(
    f"{CANVAS_URL}/api/v1/submission_drafts",
    data={
        "submission_id": SUBMISSION_ID,
        "submission_attempt": ATTEMPT,
        "submission_type": "online_text_entry",
        "body": TEST_BODY,
    },
)
report(r, "REST flat")

# B — nested under submission_draft[...]
r = client.post(
    f"{CANVAS_URL}/api/v1/submission_drafts",
    data={
        "submission_id": SUBMISSION_ID,
        "submission_draft[active_submission_type]": "online_text_entry",
        "submission_draft[submission_attempt]": ATTEMPT,
        "submission_draft[body]": TEST_BODY,
    },
)
report(r, "REST nested")

# C — JSON body
r = client.post(
    f"{CANVAS_URL}/api/v1/submission_drafts",
    json={
        "submission_id": SUBMISSION_ID,
        "submission_draft": {
            "active_submission_type": "online_text_entry",
            "submission_attempt": ATTEMPT,
            "body": TEST_BODY,
        },
    },
)
report(r, "REST JSON nested")


# ---------------------------------------------------------------------
# Step 3: try assignment-scoped endpoint
# ---------------------------------------------------------------------
banner("Step 3: Assignment-scoped REST")

r = client.post(
    f"{CANVAS_URL}/api/v1/courses/{COURSE_ID}/assignments/"
    f"{ASSIGNMENT_ID}/submissions/self/draft",
    data={
        "submission[submission_type]": "online_text_entry",
        "submission[body]": TEST_BODY,
    },
)
report(r, "assignment-scoped /draft")

# Alternative: maybe POST without /draft suffix creates a draft if no submission_type
r = client.put(
    f"{CANVAS_URL}/api/v1/courses/{COURSE_ID}/assignments/"
    f"{ASSIGNMENT_ID}/submissions/{USER_ID}",
    data={"submission[body]": TEST_BODY},
)
report(r, "PUT submission body only")


# ---------------------------------------------------------------------
# Step 4: GraphQL mutation
# ---------------------------------------------------------------------
banner("Step 4: GraphQL createSubmissionDraft mutation")

# Canvas GraphQL endpoint - try both common paths
for gql_path in ["/api/graphql", "/api/v1/graphql", "/graphql"]:
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
        submissionDraft {
          _id
          body
        }
        errors {
          attribute
          message
        }
      }
    }
    """
    r = client.post(
        f"{CANVAS_URL}{gql_path}",
        json={
            "query": mutation,
            "variables": {
                "submissionId": str(SUBMISSION_ID),
                "activeSubmissionType": "online_text_entry",
                "attempt": ATTEMPT,
                "body": TEST_BODY,
            },
        },
    )
    report(r, f"GraphQL {gql_path}")
    if r.status_code == 200:
        try:
            payload = r.json()
            print(f"  parsed: {json.dumps(payload, indent=2)[:600]}")
        except Exception:
            pass
        break


# ---------------------------------------------------------------------
# Step 5: confirm by re-fetching submission to see if draft is set
# ---------------------------------------------------------------------
banner("Step 5: re-fetch submission to check for draft")
r = client.get(
    f"{CANVAS_URL}/api/v1/courses/{COURSE_ID}/assignments/"
    f"{ASSIGNMENT_ID}/submissions/self",
    params={"include[]": "submission_history"},
)
report(r, "submission re-check")
if r.status_code == 200:
    sub = r.json()
    print(f"  body field: {repr((sub.get('body') or '')[:200])}")
    print(f"  workflow_state: {sub.get('workflow_state')}")
    print(f"  has 'submission_drafts': {'submission_drafts' in sub}")
