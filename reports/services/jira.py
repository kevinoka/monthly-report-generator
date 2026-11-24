"""Jira Cloud client: incidents and service requests for one project and period."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import requests
from django.conf import settings
from django.utils.dateparse import parse_datetime

from core.models import Project


class JiraError(RuntimeError):
    pass


@dataclass
class Ticket:
    key: str
    created: datetime
    summary: str
    description: str
    reporter: str
    follow_up: str
    status: str


def adf_to_text(node) -> str:
    """Flatten Atlassian Document Format (rich text in API v3) to plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_text(n) for n in node)
    kind = node.get("type")
    if kind == "text":
        return node.get("text", "")
    if kind == "hardBreak":
        return "\n"
    if kind == "mention":
        return node.get("attrs", {}).get("text", "")
    inner = adf_to_text(node.get("content", []))
    if kind in {"paragraph", "heading", "listItem", "codeBlock", "blockquote"}:
        return inner.strip() + "\n"
    return inner


def clean_text(text: str, limit: int = 400) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _jql(project: Project, kind_jql: str, start: datetime, end: datetime) -> str:
    fmt = "%Y-%m-%d %H:%M"
    return (
        f"({project.jira_base_jql}) AND ({kind_jql}) "
        f'AND created >= "{start:{fmt}}" AND created < "{end:{fmt}}" ORDER BY created ASC'
    )


def _session() -> requests.Session:
    if not (settings.JIRA_BASE_URL and settings.JIRA_EMAIL and settings.JIRA_API_TOKEN):
        raise JiraError("JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN belum diset.")
    s = requests.Session()
    s.auth = (settings.JIRA_EMAIL, settings.JIRA_API_TOKEN)
    s.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    return s


def search(jql: str) -> list[dict]:
    """Enhanced JQL search (POST /rest/api/3/search/jql) with token pagination."""
    fields = ["summary", "description", "reporter", "status", "created", "comment"]
    if settings.JIRA_FOLLOWUP_FIELD:
        fields.append(settings.JIRA_FOLLOWUP_FIELD)
    url = settings.JIRA_BASE_URL.rstrip("/") + "/rest/api/3/search/jql"
    s = _session()
    issues: list[dict] = []
    token = None
    while True:
        body = {"jql": jql, "fields": fields, "maxResults": 100}
        if token:
            body["nextPageToken"] = token
        resp = s.post(url, json=body, timeout=settings.JIRA_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            raise JiraError(f"HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        issues.extend(data.get("issues", []))
        token = data.get("nextPageToken")
        if not token or data.get("isLast", True):
            return issues


def to_ticket(issue: dict) -> Ticket:
    f = issue["fields"]
    follow_up = ""
    if settings.JIRA_FOLLOWUP_FIELD and f.get(settings.JIRA_FOLLOWUP_FIELD):
        follow_up = adf_to_text(f[settings.JIRA_FOLLOWUP_FIELD])
    else:
        comments = (f.get("comment") or {}).get("comments") or []
        if comments:
            follow_up = adf_to_text(comments[-1].get("body"))
    return Ticket(
        key=issue["key"],
        created=parse_datetime(f["created"]),
        summary=clean_text(f.get("summary") or "", 200),
        description=clean_text(adf_to_text(f.get("description"))),
        reporter=(f.get("reporter") or {}).get("displayName", "-"),
        follow_up=clean_text(follow_up) or "-",
        status=(f.get("status") or {}).get("name", "-"),
    )


def fetch_tickets(project: Project, start: datetime, end: datetime) -> tuple[list[Ticket], list[Ticket]]:
    inc_jql = project.jira_incident_jql or settings.JIRA_DEFAULT_INCIDENT_JQL
    req_jql = project.jira_request_jql or settings.JIRA_DEFAULT_REQUEST_JQL
    incidents = [to_ticket(i) for i in search(_jql(project, inc_jql, start, end))]
    requests_ = [to_ticket(i) for i in search(_jql(project, req_jql, start, end))]
    return incidents, requests_
