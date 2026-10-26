import asyncio
import os
import re
from pathlib import Path

from wrench.commands.parser import parse_command
from wrench.exceptions import GitHubError, WrenchError
from wrench.github_client.code_reader import CodeReader
from wrench.github_client.service import GitHubService
from wrench.llm.prompts import SYSTEM_CODE_ANALYST, SYSTEM_IMPLEMENTER, SYSTEM_PR_REVIEWER, SYSTEM_PR_REVIEWER_FOLLOWUP
from wrench.llm.router import LLMRouter


def _make_service(repo_override: str | None) -> GitHubService:
    token = os.environ["GITHUB_TOKEN"]
    if repo_override and "/" in repo_override:
        owner, repo = repo_override.split("/", 1)
    else:
        owner = os.environ["GITHUB_OWNER"]
        repo = repo_override or os.environ["GITHUB_REPO"]
    return GitHubService(owner=owner, repo=repo, token=token)


_WRENCH_MD = Path(__file__).resolve().parents[3] / "WRENCH.md"


def _load_project_context() -> str:
    path = Path(os.getenv("WRENCH_CONTEXT_FILE", str(_WRENCH_MD)))
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def dispatch(text: str, say, client, router: LLMRouter) -> None:
    intent = parse_command(text)
    try:
        service = _make_service(intent.get("repo"))
    except Exception as exc:
        say(f"❌ Could not connect to GitHub: {exc}")
        return

    say("⏳ Working on it…")

    try:
        _route(intent, text, service, router, say)
    except WrenchError as exc:
        say(
            f"❌ Something went wrong\n*Command:* {text}\n*Error:* {exc}"
        )
    except Exception as exc:
        say(
            f"❌ Something went wrong\n*Command:* {text}\n*Error:* {exc}"
        )


def _route(intent: dict, raw: str, service: GitHubService, router: LLMRouter, say) -> None:
    name = intent["intent"]
    if name == "create_branch":
        handle_create_branch(intent, service, say)
    elif name == "describe_code":
        asyncio.run(handle_describe_code(intent, service, router, say))
    elif name == "implement":
        asyncio.run(handle_implement(intent, service, router, say))
    elif name == "review_pr":
        asyncio.run(handle_review_pr(intent, service, router, say))
    elif name == "open_pr":
        handle_open_pr(intent, service, say)
    elif name == "status":
        asyncio.run(handle_status(router, say))
    else:
        say(f"🤔 I don't understand that command. Try `/wrench status` to check if I'm alive.")


def handle_create_branch(intent: dict, service: GitHubService, say) -> None:
    branch = intent.get("branch")
    if not branch:
        desc = intent.get("description", "feature")
        prefix = "fix" if "fix" in desc or "bug" in desc else "feat"
        branch = f"{prefix}/{_slug(desc)}"

    base = intent.get("base", "main")
    result = service.create_branch(branch, base=base)
    owner_repo = f"{service.owner}/{service.repo_name}"

    say(
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"✅ *Branch created*\n"
                        f"Branch: `{result['branch']}`   Repo: {owner_repo}   Base: {base}"
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View on GitHub ↗"},
                        "url": result["url"],
                        "action_id": "view_branch",
                    }
                ],
            },
        ]
    )


async def handle_describe_code(
    intent: dict, service: GitHubService, router: LLMRouter, say
) -> None:
    reader = CodeReader(service)
    path_hint = intent.get("path") or intent.get("description") or ""
    context = reader.build_context(
        repo=f"{service.owner}/{service.repo_name}", path_hint=path_hint
    )
    prompt = f"Describe the following code:\n\n{context}"
    response = await router.ask(SYSTEM_CODE_ANALYST, prompt)
    text = response.text[:3000]
    say(f"{text}\n\n_Answered by {response.provider}_")


async def handle_implement(
    intent: dict, service: GitHubService, router: LLMRouter, say
) -> None:
    reader = CodeReader(service)
    description = intent.get("description", "")

    say("🔍 Reading codebase…")
    context = reader.build_context(
        repo=f"{service.owner}/{service.repo_name}", path_hint=description
    )

    say("🤖 Planning changes…")
    prompt = f"Task: {description}\n\nExisting code:\n{context}"
    result = await router.ask_json(SYSTEM_IMPLEMENTER, prompt, thinking=True)

    files = result.get("files")
    if not files:
        say("❌ LLM returned no files to change.")
        return

    branch = intent.get("branch")
    if not branch:
        branch = f"feat/{_slug(description)}"
        service.create_branch(branch)

    say(f"💾 Committing {len(files)} file(s)…")
    commit = service.commit_files(branch, files, result.get("commit_message", "chore: automated change"))

    say("📬 Opening PR…")
    pr = service.open_pr(
        branch=branch,
        base=service.repo.default_branch,
        title=result.get("pr_title", description[:72]),
        body=result.get("pr_body", ""),
    )

    response_provider = result.get("provider", "llm")
    say(
        f"✅ Done! PR #{pr['number']}: <{pr['url']}|{pr['title']}>\n"
        f"_Implemented by {response_provider}_"
    )


async def handle_review_pr(
    intent: dict, service: GitHubService, router: LLMRouter, say
) -> None:
    pr_number = intent.get("pr_number")
    if not pr_number:
        say("❌ Please specify a PR, e.g. `@wrench https://github.com/owner/repo/pull/42`")
        return

    say(f"🔍 Reviewing PR #{pr_number}…")
    reader = CodeReader(service)
    context = reader.build_pr_context(pr_number)

    project_context = _load_project_context()
    if project_context:
        context = f"--- Project Context ---\n{project_context}\n\n{context}"

    # pass 1 — full review
    import json as _json
    result = await router.ask_json(SYSTEM_PR_REVIEWER, context, thinking=True)

    # pass 2 — self-critique to catch missed issues and validate verdict
    say("🔎 Double-checking review…")
    followup_prompt = f"Here is the context:\n{context}\n\nHere is your initial review:\n{_json.dumps(result, indent=2)}"
    try:
        result = await router.ask_json(SYSTEM_PR_REVIEWER_FOLLOWUP, followup_prompt, thinking=True)
    except Exception:
        pass  # keep pass-1 result if pass-2 fails

    verdict = result.get("verdict", "COMMENT")
    badge = {"APPROVE": "✅ APPROVED", "REQUEST_CHANGES": "🔴 CHANGES REQUESTED"}.get(
        verdict, "💬 COMMENT"
    )

    inline = result.get("inline_comments", [])
    suggestions = result.get("suggestions", [])

    event_map = {"APPROVE": "APPROVE", "REQUEST_CHANGES": "REQUEST_CHANGES", "COMMENT": "COMMENT"}
    service.create_review(
        pr_number=pr_number,
        body=result.get("summary", ""),
        event=event_map.get(verdict, "COMMENT"),
        comments=inline,
    )

    score = result.get("score")
    score_text = f"  Score: *{score}/10*" if score is not None else ""

    categories = result.get("categories", {})
    cat_emoji = {"pass": "✅", "warn": "⚠️", "fail": "🔴"}
    cat_lines = "  ".join(
        f"{cat_emoji.get(v.get('rating', 'pass'), '❓')} {k}"
        for k, v in categories.items()
    )

    blocking = result.get("blocking_issues", [])
    blocking_text = ""
    if blocking:
        blocking_text = "\n*🚨 Blocking issues:*\n" + "\n".join(f"• {b}" for b in blocking)

    suggestions = result.get("suggestions", [])
    suggestion_text = ""
    if suggestions:
        suggestion_text = "\n*💡 Suggestions:*\n" + "\n".join(f"• {s}" for s in suggestions)

    praise = result.get("praise", [])
    praise_text = ""
    if praise:
        praise_text = "\n*👏 What's good:*\n" + "\n".join(f"• {p}" for p in praise)

    say(
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{badge} — PR #{pr_number}{score_text}\n"
                        f"{result.get('summary', '')}\n"
                        f"{cat_lines}\n"
                        f"_{len(inline)} inline comment(s)_"
                        f"{blocking_text}{suggestion_text}{praise_text}"
                    ),
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_Reviewed by Wrench via {result.get('provider', 'llm')}_",
                    }
                ],
            },
        ]
    )


def handle_open_pr(intent: dict, service: GitHubService, say) -> None:
    branch = intent.get("branch")
    base = intent.get("base") or service.repo.default_branch
    title = intent.get("title") or f"PR from {branch}"

    if not branch:
        say("❌ Please specify a branch, e.g. `/wrench open pr from fix/my-branch to main`")
        return

    pr = service.open_pr(branch=branch, base=base, title=title, body="")
    owner_repo = f"{service.owner}/{service.repo_name}"

    say(
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"📬 <{pr['url']}|PR #{pr['number']}: {pr['title']}>",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "action_id": "approve_pr",
                        "value": f"{owner_repo}/{pr['number']}",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Request changes"},
                        "style": "danger",
                        "action_id": "request_changes",
                        "value": f"{owner_repo}/{pr['number']}",
                    },
                ],
            },
        ]
    )


async def handle_status(router: LLMRouter, say) -> None:
    statuses = await router.health_check_all()
    _icons = {
        "healthy": "✅",
        "unhealthy": "🔴",
        "not_configured": "⚪",
    }
    lines = []
    for name, status in statuses.items():
        if status.startswith("circuit_open:"):
            remaining = status.split(":")[1]
            lines.append(f"⚠️ {name} _(circuit open, retry in {remaining})_")
        else:
            icon = _icons.get(status, "❓")
            suffix = " _(no API key)_" if status == "not_configured" else ""
            lines.append(f"{icon} {name}{suffix}")
    say(f"🔧 *Wrench — Provider Status*\n" + "   ".join(lines))
