"""GitHub API interactions: diff fetching, comment posting, docs push."""
import asyncio
import subprocess
from pathlib import Path

import httpx

from app.config import get_settings
from app.services.git_service import get_repo_path, read_file

settings = get_settings()


def _strip_json_fences(text: str) -> str:
    """Remove markdown code fences from LLM JSON response safely."""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
    return text


def _github_headers(token: str = None) -> dict:
    h = {"Accept": "application/vnd.github.v3+json"}
    if token:
        h["Authorization"] = f"token {token}"
    return h


def _parse_owner_repo(github_url: str) -> tuple[str, str]:
    parts = github_url.rstrip("/").replace(".git", "").split("/")
    return parts[-2], parts[-1]


async def get_commit_diff(github_url: str, sha: str, token: str = None) -> str:
    owner, repo = _parse_owner_repo(github_url)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}",
            headers=_github_headers(token),
        )
        if resp.status_code != 200:
            return f"Cannot fetch commit {sha}: HTTP {resp.status_code}"
        data = resp.json()
        parts = [f"Commit: {data.get('sha','')[:8]} — {data.get('commit',{}).get('message','')}"]
        for f in data.get("files", [])[:15]:
            parts.append(f"\nFile: {f['filename']} ({f['status']})")
            if f.get("patch"):
                parts.append(f['patch'][:2000])
        return "\n".join(parts)


async def get_pr_diff(github_url: str, pr_number: int, token: str = None) -> str:
    owner, repo = _parse_owner_repo(github_url)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files",
            headers=_github_headers(token),
        )
        if resp.status_code != 200:
            return f"Cannot fetch PR #{pr_number}: HTTP {resp.status_code}"
        files = resp.json()
        parts = [f"Pull Request #{pr_number} — {len(files)} file(s) changed"]
        for f in files[:15]:
            parts.append(f"\nFile: {f['filename']} ({f['status']})")
            if f.get("patch"):
                parts.append(f['patch'][:2000])
        return "\n".join(parts)


async def post_commit_comment(
    github_url: str, sha: str, body: str, token: str
) -> bool:
    owner, repo = _parse_owner_repo(github_url)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}/comments",
            headers=_github_headers(token),
            json={"body": body},
        )
        return resp.status_code == 201


async def post_pr_review(
    github_url: str, pr_number: int, body: str, token: str
) -> bool:
    owner, repo = _parse_owner_repo(github_url)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            headers=_github_headers(token),
            json={"body": body, "event": "COMMENT"},
        )
        return resp.status_code == 200


def create_pull_request_sync(
    github_url: str, title: str, body: str, head: str, base: str, token: str
) -> str:
    """Create a pull request via GitHub API (sync). Returns PR URL or error message."""
    owner, repo = _parse_owner_repo(github_url)
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            f"https://api.github.com/repos/{owner}/{repo}/pulls",
            headers=_github_headers(token),
            json={"title": title, "body": body, "head": head, "base": base},
        )
        if resp.status_code == 422:
            data = resp.json()
            errors = data.get("errors", [])
            msg = data.get("message", "Unprocessable Entity")
            if errors:
                msg += ": " + "; ".join(e.get("message", str(e)) for e in errors)
            return f"Failed to create PR: {msg}"
        if resp.status_code not in (200, 201):
            return f"Failed to create PR: HTTP {resp.status_code} — {resp.text[:300]}"
        data = resp.json()
        return f"PR #{data['number']} created: {data['html_url']}"


def _pull_latest(repo_path, branch: str = ""):
    """Pull latest changes so rule files are always up-to-date."""
    try:
        args = ["git", "-C", str(repo_path), "pull", "--rebase", "--autostash"]
        if branch:
            args += ["origin", branch]
        subprocess.run(args, capture_output=True, timeout=30)
    except Exception:
        pass


def _read_rule(repo_id: int, rule_path: str) -> str | None:
    """Read a rule file from the repo. Returns content if non-empty, None otherwise."""
    full = get_repo_path(repo_id) / rule_path
    if not full.exists():
        return None
    try:
        content = full.read_text(encoding="utf-8", errors="replace").strip()
        return content if content else None
    except Exception:
        return None


async def _generate_review(diff: str, context: str, rule: str = "") -> str:
    if not settings.LLM_API_KEY:
        return ""
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage

    llm = ChatOpenAI(
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
        model=settings.DEFAULT_MODEL,
        temperature=0.1,
    )

    if rule:
        system = (
            "You are a senior code reviewer. "
            "Review the provided diff STRICTLY following the project rules below. "
            "Do NOT apply generic criteria outside of these rules — the rules define exactly what to check.\n\n"
            f"PROJECT REVIEW RULES (follow EXACTLY):\n{rule}\n\n"
            "Format: concise markdown list. Be specific with file and line references."
        )
    else:
        system = (
            "You are a senior code reviewer. Analyze the provided diff and identify:\n"
            "1. Potential bugs or logic errors\n"
            "2. Security vulnerabilities (injection, hardcoded secrets, etc.)\n"
            "3. Performance concerns\n"
            "4. Code quality issues (naming, duplication, missing error handling)\n\n"
            "Format: concise markdown list. Be specific with file and line references."
        )
    user = f"Review this {context}:\n\n{diff[:6000]}"
    try:
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        draft = resp.content
    except Exception as e:
        return f"Review generation failed: {e}"

    # Verification pass: check draft is complete before posting
    criteria = rule if rule else (
        "1. Potential bugs or logic errors\n"
        "2. Security vulnerabilities (injection, hardcoded secrets, etc.)\n"
        "3. Performance concerns\n"
        "4. Code quality issues (naming, duplication, missing error handling)"
    )
    try:
        verify_system = (
            "You are a strict code review quality checker. "
            "Your job is to verify that a review is complete and fully covers all criteria.\n\n"
            f"REVIEW CRITERIA:\n{criteria}"
        )
        verify_user = (
            f"Here is the generated review:\n\n{draft}\n\n"
            "Does this review fully cover EVERY criterion listed above? "
            "If YES, reply with exactly: COMPLIANT\n"
            "If NO, reply with the COMPLETE corrected review that covers all missing criteria "
            "(not just the missing parts — the full review)."
        )
        v_resp = await llm.ainvoke([SystemMessage(content=verify_system), HumanMessage(content=verify_user)])
        verified = v_resp.content.strip()
        if not verified.upper().startswith("COMPLIANT"):
            draft = verified
    except Exception:
        pass  # use original draft if verification fails

    return f"🤖 **Automated Code Review by 3 ANH EM Code Agent - AI-powered code review & assistant**\n\n{draft}"


async def process_push_event(repo_id: int, event_id: int, commit: dict):
    from app.database import AsyncSessionLocal
    from app.models import Repository, WebhookEvent
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Repository).where(Repository.id == repo_id))
        repo = result.scalar_one_or_none()
        if not repo:
            return
        github_url = repo.github_url
        main_branch = repo.main_branch
        token = None
        if repo.github_token_encrypted:
            from app.crypto import decrypt_token
            token = decrypt_token(repo.github_token_encrypted)

    # Pull latest so rules files are fresh, then read rule (None → use default criteria)
    _pull_latest(get_repo_path(repo_id), main_branch)
    rule = _read_rule(repo_id, "rules/review.md")

    sha = commit.get("id", "")
    diff = await get_commit_diff(github_url, sha, token)
    review = await _generate_review(diff, "commit", rule)

    if review and token:
        await post_commit_comment(github_url, sha, review, token)

    async with AsyncSessionLocal() as db:
        ev_result = await db.execute(select(WebhookEvent).where(WebhookEvent.id == event_id))
        ev = ev_result.scalar_one_or_none()
        if ev:
            ev.processed = True
            ev.result = review[:500] if review else "no-token"
            await db.commit()


async def process_pr_event(repo_id: int, event_id: int, payload: dict):
    from app.database import AsyncSessionLocal
    from app.models import Repository, WebhookEvent
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Repository).where(Repository.id == repo_id))
        repo = result.scalar_one_or_none()
        if not repo:
            return
        github_url = repo.github_url
        main_branch = repo.main_branch
        token = None
        if repo.github_token_encrypted:
            from app.crypto import decrypt_token
            token = decrypt_token(repo.github_token_encrypted)

    # Pull latest so rules files are fresh, then read rule (None → use default criteria)
    _pull_latest(get_repo_path(repo_id), main_branch)
    rule = _read_rule(repo_id, "rules/review.md")

    pr_number = payload.get("pull_request", {}).get("number")
    diff = await get_pr_diff(github_url, pr_number, token)
    review = await _generate_review(diff, f"pull request #{pr_number}", rule)

    if review and token and pr_number:
        await post_pr_review(github_url, pr_number, review, token)

    async with AsyncSessionLocal() as db:
        ev_result = await db.execute(select(WebhookEvent).where(WebhookEvent.id == event_id))
        ev = ev_result.scalar_one_or_none()
        if ev:
            ev.processed = True
            ev.result = review[:500] if review else "no-token"
            await db.commit()


async def process_docs_update(repo_id: int, payload: dict):
    """Generate/update docs after a push to main branch, guided by rules/docs.md."""
    from app.database import AsyncSessionLocal
    from app.models import Repository
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Repository).where(Repository.id == repo_id))
        repo = result.scalar_one_or_none()
        if not repo or not repo.github_token_encrypted:
            return
        # Capture all needed values before the session closes to avoid DetachedInstanceError
        github_url = repo.github_url
        github_username = repo.github_username
        github_token_encrypted = repo.github_token_encrypted
        main_branch = repo.main_branch

    # Pull latest so rule files are fresh
    repo_path = get_repo_path(repo_id)
    _pull_latest(repo_path, main_branch)

    # Check rules/docs.md — skip if missing or empty
    rule_content = _read_rule(repo_id, "rules/docs.md")
    if rule_content is None:
        return

    if not settings.LLM_API_KEY:
        return

    # Gather changed files from the push (exclude rules/ and docs/ themselves).
    # Merge commits on GitHub typically have empty added/modified lists, so fall back
    # to git diff-tree to get the actual files touched by the HEAD commit.
    changed = []
    for commit in payload.get("commits", []):
        changed.extend(commit.get("added", []))
        changed.extend(commit.get("modified", []))
    changed = list({f for f in changed if not f.startswith("docs/") and not f.startswith("rules/")})[:10]

    if not changed:
        try:
            result_git = subprocess.run(
                ["git", "-C", str(repo_path), "diff-tree", "--no-commit-id", "-r", "--name-only", "HEAD"],
                capture_output=True, text=True,
            )
            changed = [
                f for f in result_git.stdout.splitlines()
                if f and not f.startswith("docs/") and not f.startswith("rules/")
            ][:10]
        except Exception:
            pass

    if not changed:
        return

    # Read changed files content
    file_summaries = []
    for f in changed:
        try:
            content = read_file(repo_id, f)
            file_summaries.append(f"### {f}\n```\n{content[:1500]}\n```")
        except Exception:
            pass

    if not file_summaries:
        return

    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage

    llm = ChatOpenAI(
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
        model=settings.DEFAULT_MODEL,
        temperature=0.2,
    )

    import json as _json

    system_content = (
        "You are a technical documentation writer. "
        "You MUST follow the DOCUMENTATION RULES below EXACTLY — match the structure, file path, format, and style as specified. "
        "Do NOT deviate from these rules.\n\n"
        f"DOCUMENTATION RULES (follow EXACTLY):\n{rule_content}\n\n"
        "RESPONSE FORMAT: You MUST respond with ONLY a valid JSON object, no markdown fences, no explanation:\n"
        '{"path": "relative/path/to/file.md", "content": "markdown content here"}\n'
        "The 'path' field MUST follow what the documentation rules specify (e.g. README.md, docs/API.md, etc.). "
        "If the rules do not specify a path, use \"docs/AUTO_GENERATED.md\"."
    )

    prompt = (
        "Write or update documentation for these changed files:\n\n"
        + "\n\n".join(file_summaries)
    )

    try:
        resp = await llm.ainvoke([
            SystemMessage(content=system_content),
            HumanMessage(content=prompt),
        ])
        raw = _strip_json_fences(resp.content.strip())
        parsed = _json.loads(raw)
        doc_path = parsed.get("path", "docs/AUTO_GENERATED.md").lstrip("/")
        doc_content = parsed.get("content", "")
    except Exception:
        return

    if not doc_content:
        return

    # Verification pass: check docs completeness against rules before pushing
    try:
        verify_system = (
            "You are a strict documentation quality checker. "
            "Verify that the generated documentation fully satisfies ALL requirements in the rules below.\n\n"
            f"DOCUMENTATION RULES:\n{rule_content}"
        )
        verify_user = (
            f"Generated documentation (file: {doc_path}):\n\n{doc_content}\n\n"
            "Does this documentation fully satisfy EVERY requirement in the rules? "
            "If YES, reply with exactly: COMPLIANT\n"
            "If NO, reply with a JSON object containing the COMPLETE corrected documentation "
            "(same format as before): "
            '{"path": "...", "content": "complete corrected content"}'
        )
        v_resp = await llm.ainvoke([SystemMessage(content=verify_system), HumanMessage(content=verify_user)])
        verified = v_resp.content.strip()
        if not verified.upper().startswith("COMPLIANT"):
            # Try to parse corrected JSON from verifier
            try:
                v_parsed = _json.loads(_strip_json_fences(verified))
                doc_path = v_parsed.get("path", doc_path).lstrip("/")
                doc_content = v_parsed.get("content", doc_content)
            except Exception:
                pass  # keep original if verifier response is not valid JSON
    except Exception:
        pass  # proceed with original if verification call fails

    try:
        from app.crypto import decrypt_token
        token = decrypt_token(github_token_encrypted)

        def _git_push():
            env = {
                **__import__("os").environ,
                "GIT_AUTHOR_NAME": settings.AGENT_BOT_LOGIN,
                "GIT_AUTHOR_EMAIL": "bot@3anhem.local",
                "GIT_COMMITTER_NAME": settings.AGENT_BOT_LOGIN,
                "GIT_COMMITTER_EMAIL": "bot@3anhem.local",
            }
            subprocess.run(["git", "-C", str(repo_path), "checkout", main_branch], capture_output=True, env=env)
            subprocess.run(
                ["git", "-C", str(repo_path), "pull", "--rebase", "origin", main_branch],
                capture_output=True, env=env,
            )
            # Write to the path the LLM determined from rules/docs.md
            out_file = repo_path / doc_path
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(doc_content)
            subprocess.run(["git", "-C", str(repo_path), "add", str(out_file.relative_to(repo_path))], check=True, env=env)
            commit_result = subprocess.run(
                ["git", "-C", str(repo_path), "commit", "-m",
                 f"{settings.AGENT_COMMIT_PREFIX} Update documentation"],
                capture_output=True, env=env,
            )
            if commit_result.returncode not in (0, 1):
                commit_result.check_returncode()
            if commit_result.returncode != 0:
                return
            remote = github_url
            if "https://" in remote and token:
                from urllib.parse import urlparse
                parsed_url = urlparse(remote)
                remote = remote.replace(f"{parsed_url.scheme}://", f"{parsed_url.scheme}://{github_username}:{token}@")
            subprocess.run(["git", "-C", str(repo_path), "push", remote, f"HEAD:{main_branch}"], check=True, env=env)

        await asyncio.get_event_loop().run_in_executor(None, _git_push)
    except Exception:
        pass
