from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..logs import setup_logging
from .jobs import resume_interrupted_jobs
from .local_recorder import shutdown_local_recorder, start_local_recorder
from .routes import router
from .teams_watcher import start_watcher

app = FastAPI(title="keepmeet-ai")


@app.on_event("startup")
def _startup():
    setup_logging()
    resume_interrupted_jobs()
    start_watcher()
    start_local_recorder()


@app.on_event("shutdown")
def _shutdown():
    shutdown_local_recorder()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5670"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _no_cache_api(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(router)

dist_dir = Path("frontend/dist")
if dist_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(dist_dir / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        file_path = dist_dir / full_path
        if full_path and file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(dist_dir / "index.html")
