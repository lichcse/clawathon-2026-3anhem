import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.api import users, repos, chat, webhooks, worldcup, admin

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# Epoch seconds when this container finished startup — used by deploy.sh to
# confirm the new container (not old) is serving before restoring data.
_started_at: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _started_at
    await init_db()
    # Re-clone any repos that are not ready on startup (parallel, max 3 min)
    from app.services.git_service import clone_all_repos
    await clone_all_repos()
    _started_at = time.time()
    logger.info("3 ANH EM agent started (started_at=%.0f)", _started_at)
    yield
    logger.info("3 ANH EM agent stopping")


app = FastAPI(title="3 ANH EM — Code Review Agent", lifespan=lifespan)

app.include_router(users.router, prefix="/api")
app.include_router(repos.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(webhooks.router, prefix="/api")
app.include_router(worldcup.router, prefix="/api")
app.include_router(admin.router, prefix="/api")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
async def health():
    return {"status": "ok", "started_at": _started_at}


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    # Don't catch API routes
    if full_path.startswith("api/") or full_path == "health":
        from fastapi import HTTPException
        raise HTTPException(404)
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))
