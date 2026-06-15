import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.database import get_db
from app.models import User, Repository
from app.crypto import encrypt_token, decrypt_token
from app.api.deps import get_current_user

router = APIRouter()


class RepoCreate(BaseModel):
    name: str
    github_url: str
    main_branch: str = "main"
    is_private: bool = False
    interact_with_source: bool = False
    github_username: Optional[str] = None
    github_token: Optional[str] = None
    auto_update_docs: bool = False
    review_on_mr: bool = False
    review_on_commit: bool = False
    is_shared: bool = False
    temp_clone_key: Optional[str] = None


def _repo_to_dict(repo: Repository, current_user_id: str) -> dict:
    return {
        "id": repo.id,
        "name": repo.name,
        "github_url": repo.github_url,
        "main_branch": repo.main_branch,
        "is_private": repo.is_private,
        "interact_with_source": repo.interact_with_source,
        "auto_update_docs": repo.auto_update_docs,
        "review_on_mr": repo.review_on_mr,
        "review_on_commit": repo.review_on_commit,
        "is_shared": repo.is_shared,
        "clone_status": repo.clone_status,
        "clone_error": repo.clone_error,
        "is_owner": repo.user_id == current_user_id,
        "created_at": repo.created_at,
    }


@router.get("/repos")
async def list_repos(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Repository).where(
            or_(
                Repository.user_id == current_user.id,
                Repository.is_shared == True,
            )
        ).order_by(Repository.created_at.desc())
    )
    repos = result.scalars().all()
    return [_repo_to_dict(r, current_user.id) for r in repos]


@router.post("/repos")
async def create_repo(
    body: RepoCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not body.name.strip():
        raise HTTPException(400, "Repo name is required")
    if not body.github_url.strip():
        raise HTTPException(400, "GitHub URL is required")
    if body.is_private and body.interact_with_source and not body.github_token:
        raise HTTPException(400, "GitHub token required for private repos with source interaction")

    encrypted_token = encrypt_token(body.github_token) if body.github_token else None
    webhook_secret = secrets.token_hex(32)

    repo = Repository(
        user_id=current_user.id,
        name=body.name.strip(),
        github_url=body.github_url.strip().rstrip("/"),
        main_branch=body.main_branch.strip(),
        is_private=body.is_private,
        interact_with_source=body.interact_with_source,
        github_username=body.github_username,
        github_token_encrypted=encrypted_token,
        auto_update_docs=body.auto_update_docs,
        review_on_mr=body.review_on_mr,
        review_on_commit=body.review_on_commit,
        is_shared=body.is_shared,
        webhook_secret=webhook_secret,
        clone_status="pending",
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)

    from app.services.git_service import clone_repo, promote_temp_clone
    if body.temp_clone_key and promote_temp_clone(body.temp_clone_key, repo.id):
        repo.clone_status = "ready"
        await db.commit()
    else:
        background_tasks.add_task(
            clone_repo,
            repo.id,
            repo.github_url,
            repo.main_branch,
            repo.github_username,
            repo.github_token_encrypted,
        )

    return {
        **_repo_to_dict(repo, current_user.id),
        "webhook_url": f"/api/webhooks/{repo.id}",
        "webhook_secret": webhook_secret,
    }


@router.get("/repos/{repo_id}")
async def get_repo(
    repo_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(404, "Repository not found")
    if repo.user_id != current_user.id and not repo.is_shared:
        raise HTTPException(403, "Access denied")
    return {
        **_repo_to_dict(repo, current_user.id),
        "github_username": repo.github_username,
        "webhook_url": f"/api/webhooks/{repo.id}",
        "webhook_secret": repo.webhook_secret if repo.user_id == current_user.id else None,
    }


@router.delete("/repos/{repo_id}")
async def delete_repo(
    repo_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(404, "Repository not found")
    if repo.user_id != current_user.id:
        raise HTTPException(403, "Only the owner can delete a repository")
    await db.delete(repo)
    await db.commit()
    return {"ok": True}


class ValidateUrlRequest(BaseModel):
    github_url: str
    main_branch: str = "main"
    github_username: Optional[str] = None
    github_token: Optional[str] = None


@router.post("/repos/validate-url")
async def validate_url(
    body: ValidateUrlRequest,
    current_user: User = Depends(get_current_user),
):
    from app.services.git_service import validate_repo, clone_to_temp
    from app.crypto import encrypt_token

    result = await validate_repo(body.github_url, body.main_branch, body.github_username, body.github_token)
    if not result.get("valid"):
        return result

    # GitHub check passed — now clone to temp dir
    try:
        encrypted = encrypt_token(body.github_token) if body.github_token else None
        temp_key = await clone_to_temp(body.github_url, body.main_branch, body.github_username, encrypted)
        result["temp_clone_key"] = temp_key
    except Exception as e:
        msg = str(e) or f"Clone thất bại: {type(e).__name__}"
        result["valid"] = False
        result["error"] = msg

    return result


@router.post("/repos/{repo_id}/validate")
async def validate_repository(
    repo_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(404, "Repository not found")
    if repo.user_id != current_user.id:
        raise HTTPException(403, "Access denied")

    token = decrypt_token(repo.github_token_encrypted) if repo.github_token_encrypted else None
    from app.services.git_service import validate_repo
    return await validate_repo(repo.github_url, repo.main_branch, repo.github_username, token)


@router.post("/repos/{repo_id}/pull")
async def pull_repo(
    repo_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(404, "Repository not found")
    if repo.user_id != current_user.id and not repo.is_shared:
        raise HTTPException(403, "Access denied")

    from app.services.git_service import pull_repo as git_pull
    branch, output = await git_pull(
        repo_id,
        repo.github_url,
        repo.github_username,
        repo.github_token_encrypted,
    )
    return {"ok": True, "branch": branch, "output": output}


@router.post("/repos/{repo_id}/reclone")
async def reclone_repo(
    repo_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(404, "Repository not found")
    if repo.user_id != current_user.id:
        raise HTTPException(403, "Access denied")

    from app.services.git_service import clone_repo
    background_tasks.add_task(
        clone_repo,
        repo.id,
        repo.github_url,
        repo.main_branch,
        repo.github_username,
        repo.github_token_encrypted,
    )
    return {"ok": True, "message": "Re-cloning started"}
