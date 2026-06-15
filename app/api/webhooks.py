import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Repository, WebhookEvent
from app.config import get_settings

router = APIRouter()
settings = get_settings()


def _verify_signature(body: bytes, signature: str, secret: str) -> bool:
    if not signature or not secret:
        return not secret  # no secret = accept all
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _is_agent_commit(commit: dict) -> bool:
    msg = commit.get("message", "")
    return msg.startswith(settings.AGENT_COMMIT_PREFIX)


@router.post("/webhooks/{repo_id}")
async def handle_webhook(
    repo_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()

    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(404, "Repository not found")

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(body, signature, repo.webhook_secret or ""):
        raise HTTPException(401, "Invalid webhook signature")

    event_type = request.headers.get("X-GitHub-Event", "")
    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    if event_type == "push":
        ref = payload.get("ref", "")
        main_ref = f"refs/heads/{repo.main_branch}"
        pusher_login = payload.get("pusher", {}).get("name", "")

        if pusher_login == settings.AGENT_BOT_LOGIN:
            return {"status": "skipped", "reason": "agent push"}

        commits = payload.get("commits", [])
        # Anti-loop: skip if ALL commits are agent commits
        if commits and all(_is_agent_commit(c) for c in commits):
            return {"status": "skipped", "reason": "all agent commits"}

        # Review commits on ANY branch (not just main)
        if repo.review_on_commit:
            for commit in commits:
                if _is_agent_commit(commit):
                    continue
                commit_sha = commit.get("id", "")
                if not commit_sha:
                    continue

                existing = await db.execute(
                    select(WebhookEvent).where(
                        WebhookEvent.repo_id == repo_id,
                        WebhookEvent.event_id == commit_sha,
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                event = WebhookEvent(
                    repo_id=repo_id,
                    event_type="push",
                    event_id=commit_sha,
                    sender_login=pusher_login,
                )
                db.add(event)
                await db.flush()
                from app.services.github_service import process_push_event
                background_tasks.add_task(process_push_event, repo_id, event.id, commit)

        # Auto-update docs only on main branch
        if repo.auto_update_docs and ref == main_ref:
            from app.services.github_service import process_docs_update
            background_tasks.add_task(process_docs_update, repo_id, payload)

        await db.commit()

    elif event_type == "pull_request":
        action = payload.get("action", "")
        if action not in ("opened", "synchronize", "reopened"):
            return {"status": "skipped", "reason": f"action={action}"}

        if not repo.review_on_mr:
            return {"status": "skipped", "reason": "review_on_mr disabled"}

        pr = payload.get("pull_request", {})
        pr_number = pr.get("number")
        pr_sha = pr.get("head", {}).get("sha", "")
        event_id = f"pr-{pr_number}-{pr_sha[:8]}"

        existing = await db.execute(
            select(WebhookEvent).where(
                WebhookEvent.repo_id == repo_id,
                WebhookEvent.event_id == event_id,
            )
        )
        if not existing.scalar_one_or_none():
            event = WebhookEvent(
                repo_id=repo_id,
                event_type="pull_request",
                event_id=event_id,
                sender_login=payload.get("sender", {}).get("login", ""),
            )
            db.add(event)
            await db.flush()
            from app.services.github_service import process_pr_event
            background_tasks.add_task(process_pr_event, repo_id, event.id, payload)
            await db.commit()

    return {"status": "accepted"}
