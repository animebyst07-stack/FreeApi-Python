# FreeApi-Python

## Overview

Flask + SQLite web application for a Telegram-backed AI API platform. The frontend is a single-page app in `static/index.html`, with backend routes in `freeapi/routes.py` and persistence in `freeapi/database.py` / `freeapi/repositories.py`.

## Stack

- Python 3.11
- Flask 3
- SQLite
- Telethon
- Single-file HTML/CSS/JavaScript SPA

## Review System

- Public reviews are shown on the landing page.
- Authenticated non-admin users can create or update one review per account.
- Review score range is 1–10 and text length is validated server-side.
- One-review-per-user is enforced by application logic and a unique SQLite index.
- Temporary review bans are stored in `review_restrictions`.
- User review notifications are shown in the dashboard.

## Favorite AI Agent

- `freeapi/agent.py` runs the autonomous moderator.
- The agent uses the platform's existing Telegram-backed `run_chat()` flow through a selected internal API key.
- Admin settings `agent_enabled` and `agent_key_id` are initialized during DB startup.
- When enabled, new reviews are submitted as `pending` and the agent is triggered immediately.
- Agent actions:
  - `APPROVE`: publishes the review and optional public response.
  - `DELETE`: deletes the review, bans review access for 7 days, and notifies the user.
  - `FEEDBACK`: publishes the review with a public AI response and creates an admin notification.

## Admin Panel

- Hidden admin panel is available only to username `ReZero`.
- Admin can enable/disable Favorite AI Agent, choose the agent key, view admin notifications, approve reviews, and delete reviews/notifications.

## Final Polish Notes

- Sidebar now renders above the header on mobile and includes an explicit close button.
- Browser session handling uses persistent Flask sessions with credentialed frontend requests.
- Support chat clears duplicate renders, handles image messages more cleanly, and falls back to a keyword-based admin report when AI close-analysis is unavailable.

## April 18, 2026 Bugfix Batch

- `/api/chat/test` now records request history, updates monthly model stats, and uses dual-mode translation when a translator account is configured.
- Dual-mode and `/api/v1/chat` emit diagnostic logs with key/model/translator context.
- Telegram response joining now deduplicates replacement/expanded message parts and always filters promo-code service messages from answers.
- Test chat history is persisted per API key in browser storage and restored after switching keys or reopening the chat view.
- The sidebar includes an "Отзывы" shortcut, the landing empty-review copy points users to the reviews section, full API keys wrap visibly in key cards, and the context meter moved above the chat input.

## Autonomous Agent Mode (постоянная память)

- Project owner = `animebyst07-stack` (Termux user, Russian-only chat).
- Repo: `animebyst07-stack/FreeApi-Python` on GitHub. Main branch only.
- Workspace clone is at `/home/runner/workspace/freeapi-repo/` →
  symlink to the actual git repo `/home/runner/FreeApi-Python/`.
  Therefore writes via path `freeapi-repo/...` go straight to the repo.
- The agent works AUTONOMOUSLY at night while the user sleeps. The user
  has explicitly asked for this and granted a GitHub PAT for direct
  pushes via the Contents API. While in autonomous mode:
    * never wait for confirmation, never ask clarifying questions;
    * push every change to GitHub immediately (blob → tree → commit → ref);
    * keep `plan.txt` (in the repo AND mirrored to
      `/home/runner/workspace/plan.txt`) up to date — this is the only
      contract the user reads in the morning;
    * Russian-only in all comments / docs / log messages / commit msgs;
    * `git checkout` / `git reset` / destructive git ops are FORBIDDEN
      for the main agent — use `git fetch` + replay edits instead.
- Background workflows `artifacts/api-server` and `artifacts/mockup-sandbox`
  are unrelated Replit scaffolding and must NOT be touched. The Termux
  Flask app is started by the user manually on his phone, not by Replit.

## Validation Commands

- `PYTHONPATH=FreeApi-Python python -m compileall -q FreeApi-Python/freeapi FreeApi-Python/api.py`
- `DATABASE_PATH=/tmp/freeapi_review_test.db PYTHONPATH=FreeApi-Python python - <<'PY'`
  - initialize database
  - create Flask app
  - exercise review/admin routes with Flask test client
