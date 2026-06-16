import asyncio
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings

settings = get_settings()


def get_repo_path(repo_id: int) -> Path:
    return Path(settings.REPOS_PATH) / str(repo_id)


def _temp_clone_dir() -> Path:
    return Path(settings.REPOS_PATH) / "temp"


def _temp_key(url: str, branch: str) -> str:
    return hashlib.md5(f"{url}::{branch}".encode()).hexdigest()


def get_temp_clone_path(temp_key: str) -> Path:
    return _temp_clone_dir() / temp_key


async def _set_clone_status(repo_id: int, status: str, error: str = None):
    from app.database import AsyncSessionLocal
    from app.models import Repository
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Repository).where(Repository.id == repo_id))
        repo = result.scalar_one_or_none()
        if repo:
            repo.clone_status = status
            repo.clone_error = error
            await db.commit()


async def clone_repo(
    repo_id: int,
    github_url: str,
    branch: str,
    username: str = None,
    encrypted_token: str = None,
):
    await _set_clone_status(repo_id, "cloning")
    repo_path = get_repo_path(repo_id)
    repo_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Only inject credentials for private repos that have both username and token
        clone_url = github_url
        if username and encrypted_token:
            from app.crypto import decrypt_token
            token = decrypt_token(encrypted_token)
            if clone_url.startswith("https://"):
                clone_url = clone_url.replace("https://", f"https://{username}:{token}@")

        if repo_path.exists():
            shutil.rmtree(repo_path)

        def _do_clone():
            result = subprocess.run(
                ["git", "clone", "--depth", "200", "--branch", branch, clone_url, str(repo_path)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                stdout = result.stdout.strip()
                # Produce a human-readable error
                # Check branch errors first (more specific)
                if "remote branch" in stderr.lower() or "could not find remote branch" in stderr.lower():
                    raise RuntimeError(f"Branch '{branch}' does not exist.\n{stderr}")
                if "repository" in stderr.lower() and "not found" in stderr.lower():
                    raise RuntimeError(f"Repository not found or access denied.\n{stderr}")
                if "authentication" in stderr.lower() or "403" in stderr or "401" in stderr:
                    raise RuntimeError(f"Authentication failed. Check your username and token.\n{stderr}")
                raise RuntimeError(stderr or stdout or f"git clone exited with code {result.returncode}")

        await asyncio.get_event_loop().run_in_executor(None, _do_clone)
        await _set_clone_status(repo_id, "ready")
    except RuntimeError as e:
        await _set_clone_status(repo_id, "error", str(e)[:1000])
    except Exception as e:
        await _set_clone_status(repo_id, "error", str(e)[:1000])


async def clone_to_temp(
    url: str,
    branch: str,
    username: str = None,
    encrypted_token: str = None,
) -> str:
    """Clone repo to a temp dir for validate-then-add flow. Returns temp_key."""
    temp_key = _temp_key(url, branch)
    temp_path = get_temp_clone_path(temp_key)
    temp_path.parent.mkdir(parents=True, exist_ok=True)

    clone_url = url
    if username and encrypted_token:
        from app.crypto import decrypt_token
        token = decrypt_token(encrypted_token)
        if clone_url.startswith("https://"):
            clone_url = clone_url.replace("https://", f"https://{username}:{token}@")

    if temp_path.exists():
        shutil.rmtree(temp_path)

    def _do_clone():
        result = subprocess.run(
            ["git", "clone", "--depth", "200", "--branch", branch, clone_url, str(temp_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            if "remote branch" in stderr.lower() or "could not find remote branch" in stderr.lower():
                raise RuntimeError(f"Branch '{branch}' does not exist.\n{stderr}")
            if "repository" in stderr.lower() and "not found" in stderr.lower():
                raise RuntimeError(f"Repository not found or access denied.\n{stderr}")
            if "authentication" in stderr.lower() or "403" in stderr or "401" in stderr:
                raise RuntimeError(f"Authentication failed. Check your username and token.\n{stderr}")
            raise RuntimeError(stderr or stdout or f"git clone exited with code {result.returncode}")

    await asyncio.get_event_loop().run_in_executor(None, _do_clone)
    return temp_key


def promote_temp_clone(temp_key: str, repo_id: int) -> bool:
    """Move temp clone to final repo path. Returns True if successful."""
    temp_path = get_temp_clone_path(temp_key)
    if not temp_path.exists():
        return False
    final_path = get_repo_path(repo_id)
    if final_path.exists():
        shutil.rmtree(final_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(temp_path), str(final_path))
    return True


async def clone_all_repos():
    """Re-clone any repos that are not ready on startup. Runs in parallel, waits up to 3 min."""
    from app.database import AsyncSessionLocal
    from app.models import Repository
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Repository))
        repos = result.scalars().all()
        tasks = []
        for repo in repos:
            path = get_repo_path(repo.id)
            if not path.exists() or repo.clone_status != "ready":
                tasks.append(
                    asyncio.ensure_future(
                        clone_repo(
                            repo.id,
                            repo.github_url,
                            repo.main_branch,
                            repo.github_username,
                            repo.github_token_encrypted,
                        )
                    )
                )
        if tasks:
            await asyncio.wait(tasks, timeout=180)


def read_file(repo_id: int, file_path: str) -> str:
    full = get_repo_path(repo_id) / file_path.lstrip("/")
    if not full.exists() or not full.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")
    content = full.read_text(encoding="utf-8", errors="replace")
    if len(content) > 12_000:
        content = content[:12_000] + "\n\n... [truncated — file is larger]"
    return content


def list_directory(repo_id: int, directory: str = "") -> list[dict]:
    base = get_repo_path(repo_id)
    target = (base / directory.lstrip("/")) if directory else base
    if not target.exists():
        return []
    items = []
    for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
        if item.name.startswith("."):
            continue
        items.append({
            "name": item.name,
            "path": str(item.relative_to(base)),
            "type": "directory" if item.is_dir() else "file",
        })
    return items


def search_code(repo_id: int, query: str) -> str:
    base = get_repo_path(repo_id)
    if not base.exists():
        return "Repository not cloned yet."
    try:
        result = subprocess.run(
            [
                "grep", "-r", "-n", "--include=*.py", "--include=*.js",
                "--include=*.ts", "--include=*.java", "--include=*.go",
                "--include=*.rs", "--include=*.md", "--include=*.yaml",
                "--include=*.json", "-l", query, str(base),
            ],
            capture_output=True, text=True, timeout=15,
        )
        files = [f for f in result.stdout.strip().split("\n") if f][:8]
        if not files:
            return "No matches found."
        lines_out = []
        for f in files:
            rel = str(Path(f).relative_to(base))
            lines_out.append(f"📄 {rel}")
            r2 = subprocess.run(
                ["grep", "-n", query, f],
                capture_output=True, text=True, timeout=5,
            )
            for line in r2.stdout.strip().split("\n")[:5]:
                lines_out.append(f"   {line}")
        return "\n".join(lines_out)
    except Exception as e:
        return f"Search error: {e}"


def get_tree(repo_id: int) -> str:
    base = get_repo_path(repo_id)
    if not base.exists():
        return "Repository not cloned yet."
    lines = []
    for root, dirs, files in os.walk(str(base)):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git", "venv", ".venv"))
        level = len(Path(root).relative_to(base).parts)
        if level > 4:
            dirs.clear()
            continue
        indent = "  " * level
        rel = Path(root).relative_to(base)
        if level > 0:
            lines.append(f"{indent}{rel.name}/")
        for f in sorted(files)[:30]:
            lines.append(f"{indent}  {f}")
    return "\n".join(lines[:300]) or "(empty)"


def create_branch(repo_id: int, branch_name: str, from_branch: str = "") -> str:
    """Create and checkout a new branch."""
    base = get_repo_path(repo_id)
    if not base.exists():
        return "Repository not cloned."
    try:
        if from_branch:
            r = subprocess.run(
                ["git", "-C", str(base), "checkout", from_branch],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                return f"Failed to checkout '{from_branch}': {r.stderr.strip()}"
        result = subprocess.run(
            ["git", "-C", str(base), "checkout", "-b", branch_name],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return f"Failed to create branch: {result.stderr.strip()}"
        return f"Branch '{branch_name}' created and checked out."
    except Exception as e:
        return f"Error: {e}"


def list_branches(repo_id: int) -> str:
    """List all local and remote branches."""
    base = get_repo_path(repo_id)
    if not base.exists():
        return "Repository not cloned."
    try:
        result = subprocess.run(
            ["git", "-C", str(base), "branch", "-a"],
            capture_output=True, text=True,
        )
        return result.stdout.strip() or "No branches found."
    except Exception as e:
        return f"Error: {e}"


def get_current_branch(repo_id: int) -> str:
    """Return the name of the currently checked-out branch."""
    base = get_repo_path(repo_id)
    if not base.exists():
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def write_repo_file(repo_id: int, file_path: str, content: str) -> str:
    """Write content to a file in the repository (create or overwrite)."""
    base = get_repo_path(repo_id)
    if not base.exists():
        return "Repository not cloned."
    try:
        target = (base / file_path.lstrip("/")).resolve()
        if not str(target).startswith(str(base.resolve())):
            return "Error: path traversal not allowed."
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"File '{file_path}' written ({len(content)} chars)."
    except Exception as e:
        return f"Error: {e}"


def commit_changes(repo_id: int, message: str) -> str:
    """Stage all changes and commit."""
    base = get_repo_path(repo_id)
    if not base.exists():
        return "Repository not cloned."
    try:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "3 ANH EM Agent",
            "GIT_AUTHOR_EMAIL": "bot@3anhem.local",
            "GIT_COMMITTER_NAME": "3 ANH EM Agent",
            "GIT_COMMITTER_EMAIL": "bot@3anhem.local",
        }
        subprocess.run(["git", "-C", str(base), "add", "-A"], check=True, env=env)
        result = subprocess.run(
            ["git", "-C", str(base), "commit", "-m", message],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            out = result.stderr.strip() or result.stdout.strip()
            if "nothing to commit" in out:
                return "Nothing to commit — no changes staged."
            return f"Commit failed: {out}"
        return f"Committed: {message}"
    except Exception as e:
        return f"Error: {e}"


def push_branch(repo_id: int, branch: str, github_url: str, username: str, encrypted_token: str) -> str:
    """Push a branch to remote."""
    base = get_repo_path(repo_id)
    if not base.exists():
        return "Repository not cloned."
    try:
        from app.crypto import decrypt_token
        token = decrypt_token(encrypted_token)
        push_url = github_url
        if push_url.startswith("https://") and username and token:
            push_url = push_url.replace("https://", f"https://{username}:{token}@")
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "3 ANH EM Agent",
            "GIT_AUTHOR_EMAIL": "bot@3anhem.local",
            "GIT_COMMITTER_NAME": "3 ANH EM Agent",
            "GIT_COMMITTER_EMAIL": "bot@3anhem.local",
        }
        result = subprocess.run(
            ["git", "-C", str(base), "push", push_url, f"HEAD:{branch}"],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            err = result.stderr.strip()
            if token:
                err = err.replace(token, "***")
            return f"Push failed: {err}"
        return f"Pushed to '{branch}' successfully."
    except Exception as e:
        return f"Error: {e}"


async def pull_repo(
    repo_id: int,
    github_url: str,
    username: str = None,
    encrypted_token: str = None,
) -> tuple[str, str]:
    """Git pull on the current branch. Returns (branch_name, output)."""
    base = get_repo_path(repo_id)
    if not base.exists():
        return ("", "Repository not cloned yet.")

    pull_url = github_url
    if username and encrypted_token:
        from app.crypto import decrypt_token
        token = decrypt_token(encrypted_token)
        if pull_url.startswith("https://"):
            pull_url = pull_url.replace("https://", f"https://{username}:{token}@")

    def _do_pull():
        # Get current branch
        br = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True,
        )
        branch = br.stdout.strip() or "unknown"

        result = subprocess.run(
            ["git", "-C", str(base), "pull", pull_url, branch, "--rebase"],
            capture_output=True, text=True,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            raise RuntimeError(output or f"git pull exited {result.returncode}")
        return branch, output or "Already up to date."

    try:
        branch, output = await asyncio.get_event_loop().run_in_executor(None, _do_pull)
        return branch, output
    except Exception as e:
        return ("", str(e))


async def validate_repo(
    github_url: str,
    branch: str,
    username: str = None,
    token: str = None,
) -> dict:
    try:
        import httpx
        parts = github_url.rstrip("/").replace(".git", "").split("/")
        owner, repo_name = parts[-2], parts[-1]

        headers = {"Accept": "application/vnd.github.v3+json"}
        if username and token:
            headers["Authorization"] = f"token {token}"

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo_name}",
                headers=headers,
            )
            if resp.status_code == 404:
                return {"valid": False, "error": "Repository not found. Make sure it is public or credentials are correct."}
            if resp.status_code == 401:
                return {"valid": False, "error": "Authentication failed. Check your username and token."}
            if resp.status_code != 200:
                return {"valid": False, "error": f"GitHub API returned {resp.status_code}"}

            data = resp.json()
            br, rules_dir, rules_docs, rules_review = await asyncio.gather(
                client.get(f"https://api.github.com/repos/{owner}/{repo_name}/branches/{branch}", headers=headers),
                client.get(f"https://api.github.com/repos/{owner}/{repo_name}/contents/rules", headers=headers),
                client.get(f"https://api.github.com/repos/{owner}/{repo_name}/contents/rules/docs.md", headers=headers),
                client.get(f"https://api.github.com/repos/{owner}/{repo_name}/contents/rules/review.md", headers=headers),
            )
            return {
                "valid": True,
                "repo_name": data.get("full_name"),
                "description": data.get("description"),
                "is_private": data.get("private"),
                "branch_exists": br.status_code == 200,
                "has_rules_folder": rules_dir.status_code == 200,
                "has_rules_docs": rules_docs.status_code == 200,
                "has_rules_review": rules_review.status_code == 200,
                "default_branch": data.get("default_branch"),
            }
    except Exception as e:
        msg = str(e)
        if not msg:
            msg = f"Lỗi không xác định: {type(e).__name__}"
        return {"valid": False, "error": msg}
