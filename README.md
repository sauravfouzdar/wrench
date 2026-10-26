# Wrench 🔧

A 24/7 LLM Slack bot that fixes bugs, builds features, reviews PRs, and manages GitHub workflows — all from a single `/wrench` command.

## Quickstart

### 1. Prerequisites

- Python 3.11+
- A Slack workspace where you can install apps
- A GitHub personal access token with `repo` scope
- An API key for at least one LLM provider: Anthropic, OpenAI, DeepSeek, Gemini, or Groq

### 2. Create the Slack app

At https://api.slack.com/apps:

1. **Create New App → From scratch**, name it **Wrench**.
2. **OAuth & Permissions → Bot Token Scopes**: `chat:write`, `commands`, `app_mentions:read`, `channels:history`, `im:history`.
3. **Slash Commands**: create `/wrench`.
4. **Event Subscriptions**: subscribe to `app_mention` and `message.im`.
5. **Socket Mode**: enable it and generate an App-Level Token with `connections:write` scope.
6. **Interactivity & Shortcuts**: enable it (needed for the Approve / Request changes buttons).
7. **Install to Workspace**.

### 3. Install and configure

```bash
git clone <this-repo> wrench && cd wrench
python -m venv .venv && source .venv/bin/activate
pip install -e .

cp .env.example .env
```

Fill in `.env`:

| Variable | Description |
|---|---|
| `SLACK_BOT_TOKEN` | `xoxb-…` bot token (OAuth & Permissions) |
| `SLACK_SIGNING_SECRET` | from Basic Information |
| `SLACK_APP_TOKEN` | `xapp-…` App-Level Token (Socket Mode) |
| `GITHUB_TOKEN` | PAT with `repo` scope |
| `GITHUB_OWNER` / `GITHUB_REPO` | default repo when a command doesn't name one |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY` | set any you have — providers without a key are skipped |
| `LLM_PROVIDER_ORDER` | fallback priority, e.g. `anthropic,openai,deepseek,gemini,groq` |
| `WRENCH_CONTEXT_FILE` | optional path to a project context file (defaults to `WRENCH.md`) |

### 4. Run

Any of these work (with the virtualenv active):

```bash
wrench                     # console script installed by pip install -e .
python -m wrench.main      # run as a module
python src/wrench/main.py  # run the file directly
```

Socket Mode means no public URL or ngrok is needed. Check it's alive with `/wrench status` in Slack.

### 5. (Optional) Add project context

Edit [WRENCH.md](WRENCH.md) to describe your codebase's architecture, intentional patterns, and conventions. Wrench reads it before every PR review.

## Usage

Mention Wrench with a PR link to review it:

```
@wrench https://github.com/acme/api/pull/42
```

Other commands:

```
/wrench create branch fix/login-bug in acme/api
/wrench what does src/auth/middleware.py do in acme/api
/wrench fix the JWT refresh token not rotating on each request in acme/api on branch fix/jwt
/wrench open pr from fix/jwt to main in acme/api
/wrench review pr #42 in acme/api
/wrench status
```

All commands also work as `@Wrench <text>` mentions in any channel.
