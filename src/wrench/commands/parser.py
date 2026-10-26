import os
import re

from wrench.exceptions import ParseError

_SOURCE_EXTENSIONS = {".py", ".js", ".ts", ".go", ".rb", ".java", ".rs", ".cs", ".cpp"}

_INTENT_PATTERNS = [
    ("create_branch", r"create branch|new branch"),
    ("describe_code", r"describe|explain|what does|understand"),
    ("implement", r"\bfix\b|\bbuild\b|\bimplement\b|add feature|\bresolve\b"),
    ("open_pr", r"open pr|create pr|pull request"),
    ("review_pr", r"review pr|check pr"),
    ("status", r"\bstatus\b|\bhealth\b|\bproviders\b"),
]


_PR_URL_RE = re.compile(
    r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/(\d+)", re.IGNORECASE
)


def _clean_slack_text(text: str) -> str:
    # drop user mentions like <@U123ABC>
    text = re.sub(r"<@[A-Z0-9]+>", "", text)
    # unwrap Slack links: <url|label> or <url> → url
    text = re.sub(r"<(https?://[^|>]+)(?:\|[^>]*)?>", r"\1", text)
    return text.strip()


def _parse_pr_url(text: str) -> dict | None:
    m = _PR_URL_RE.search(text)
    if not m:
        return None
    owner, repo, number = m.groups()
    return {"intent": "review_pr", "repo": f"{owner}/{repo}", "pr_number": int(number)}


def _extract_repo(text: str) -> str | None:
    m = re.search(r"in\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", text)
    if m:
        return m.group(1)
    m = re.search(r"repo:([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?)", text)
    if m:
        name = m.group(1)
        if "/" not in name:
            owner = os.getenv("GITHUB_OWNER", "")
            name = f"{owner}/{name}" if owner else name
        return name
    owner = os.getenv("GITHUB_OWNER", "")
    repo = os.getenv("GITHUB_REPO", "")
    if owner and repo:
        return f"{owner}/{repo}"
    return None


def _extract_branch(text: str) -> str | None:
    m = re.search(r"(?:branch|on)\s+([A-Za-z0-9_/.-]+)", text)
    return m.group(1) if m else None


def _extract_pr_number(text: str) -> int | None:
    m = re.search(r"(?:pr|#)\s*(\d+)", text)
    return int(m.group(1)) if m else None


def _extract_path(text: str) -> str | None:
    tokens = text.split()
    for tok in tokens:
        if "/" in tok:
            return tok
        _, ext = os.path.splitext(tok)
        if ext in _SOURCE_EXTENSIONS:
            return tok
    return None


def _strip_tokens(text: str, *tokens: str | None) -> str:
    result = text
    for tok in tokens:
        if tok:
            result = result.replace(tok, "")
    return re.sub(r"\s+", " ", result).strip()


def parse_command(text: str) -> dict:
    text = _clean_slack_text(text)

    # a GitHub PR link anywhere in the message means "review this PR"
    pr_from_url = _parse_pr_url(text)
    if pr_from_url:
        return pr_from_url

    lower = text.lower()

    intent = "unknown"
    for name, pattern in _INTENT_PATTERNS:
        if re.search(pattern, lower):
            intent = name
            break

    repo = _extract_repo(lower)
    branch = _extract_branch(lower)
    pr_number = _extract_pr_number(lower)
    path = _extract_path(lower)

    # strip extracted tokens to get remaining description
    stripped = _strip_tokens(
        lower,
        repo,
        f"in {repo}" if repo else None,
        f"branch {branch}" if branch else None,
        f"on {branch}" if branch else None,
        f"pr {pr_number}" if pr_number else None,
        f"#{pr_number}" if pr_number else None,
        path,
    )
    # remove the matched verb
    for _, pattern in _INTENT_PATTERNS:
        stripped = re.sub(pattern, "", stripped).strip()

    result: dict = {"intent": intent, "repo": repo}

    if intent == "create_branch":
        result["branch"] = branch
        result["base"] = "main"
        result["description"] = stripped

    elif intent == "describe_code":
        result["path"] = path
        result["description"] = stripped

    elif intent == "implement":
        result["branch"] = branch
        result["description"] = stripped

    elif intent == "open_pr":
        result["branch"] = branch
        result["base"] = "main"
        result["title"] = stripped or f"PR from {branch}"

    elif intent == "review_pr":
        result["pr_number"] = pr_number

    elif intent == "unknown":
        result["raw"] = text

    return result
