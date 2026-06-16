import os
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from .api import blocks, chat, runs, uploads, workflows
from .db.session import engine, init_db
from .registry import seed_blocks

STATIC_DIR = pathlib.Path(os.environ.get("MVB_STATIC_DIR", "/app/mvp-frontend"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with Session(engine) as session:
        n = seed_blocks(session)
        print(f"[startup] seeded {n} blocks from disk")
    yield


app = FastAPI(title="Block Chat", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(blocks.router)
app.include_router(chat.router)
app.include_router(runs.router)
app.include_router(uploads.router)
app.include_router(workflows.router)

_next_dir = STATIC_DIR / "_next"
if _next_dir.exists():
    app.mount("/_next", StaticFiles(directory=str(_next_dir)), name="mvp-next-assets")


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.get("/")
def mvp_index():
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return {"status": "mvp", "note": "frontend not built yet"}


@app.get("/{full_path:path}")
def mvp_spa_fallback(full_path: str):
    if full_path.startswith("api/") or full_path == "healthz":
        raise HTTPException(404)
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    raise HTTPException(404)
