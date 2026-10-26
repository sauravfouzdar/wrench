import os

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from wrench.github_client.service import GitHubService
from wrench.llm.router import create_router
from wrench.slack.handlers import dispatch


def create_slack_app() -> App:
    app = App(
        token=os.environ["SLACK_BOT_TOKEN"],
        signing_secret=os.environ["SLACK_SIGNING_SECRET"],
    )
    router = create_router()

    @app.command("/wrench")
    def wrench_command(ack, command, say, client):
        ack()
        dispatch(command["text"], say, client, router)

    @app.event("app_mention")
    def app_mention(event, say, client):
        dispatch(event["text"], say, client, router)

    @app.action("approve_pr")
    def approve_pr(ack, action, say, client):
        ack()
        value = action["value"]
        parts = value.rsplit("/", 1)
        if len(parts) != 2:
            say("❌ Could not parse PR reference.")
            return
        owner_repo, pr_number_str = parts
        owner, repo = owner_repo.split("/", 1)
        pr_number = int(pr_number_str)
        token = os.environ["GITHUB_TOKEN"]
        service = GitHubService(owner=owner, repo=repo, token=token)
        service.create_review(pr_number=pr_number, body="Approved via Wrench.", event="APPROVE", comments=[])
        say(f"✅ PR #{pr_number} approved.")

    @app.action("request_changes")
    def request_changes(ack, action, say, client):
        ack()
        value = action["value"]
        parts = value.rsplit("/", 1)
        if len(parts) != 2:
            say("❌ Could not parse PR reference.")
            return
        owner_repo, pr_number_str = parts
        owner, repo = owner_repo.split("/", 1)
        pr_number = int(pr_number_str)
        token = os.environ["GITHUB_TOKEN"]
        service = GitHubService(owner=owner, repo=repo, token=token)
        service.create_review(
            pr_number=pr_number,
            body="Changes requested via Wrench.",
            event="REQUEST_CHANGES",
            comments=[],
        )
        say(f"🔴 Changes requested on PR #{pr_number}.")

    return app


def start():
    app = create_slack_app()
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
