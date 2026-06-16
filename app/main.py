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

_started_at: float = 0.0


def _init_mvp():
    try:
        from app.mvp_backend.db.session import init_db as mvp_init_db, engine as mvp_engine
        from app.mvp_backend.registry import seed_blocks
        from sqlmodel import Session
        mvp_init_db()
        with Session(mvp_engine) as session:
            n = seed_blocks(session)
            logger.info("MVP: seeded %d blocks", n)
    except Exception as e:
        logger.warning("MVP init skipped: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _started_at
    await init_db()
    from app.services.git_service import clone_all_repos
    await clone_all_repos()
    _init_mvp()
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

# Mount block-chat MVP sub-app at /mvp
try:
    from app.mvp_backend.main import app as mvp_app
    app.mount("/mvp", mvp_app)
    logger.info("MVP sub-app mounted at /mvp")
except Exception as _e:
    logger.warning("MVP sub-app not available: %s", _e)


@app.get("/health")
async def health():
    return {"status": "ok", "started_at": _started_at}


@app.get("/mvp")
async def mvp_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/mvp/", status_code=301)


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    if full_path.startswith("api/") or full_path == "health" or full_path.startswith("mvp/"):
        from fastapi import HTTPException
        raise HTTPException(404)
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))
