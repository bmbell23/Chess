import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .routes.achievements import router as achievements_router
from .routes.analysis import router as analysis_router
from .routes.charts import router as charts_router
from .routes.insights import router as insights_router
from .routes.sync import router as sync_router
from .routes.training import router as training_router

settings = get_settings()

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = None
    if settings.enable_schedulers:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        from apscheduler.triggers.cron import CronTrigger

        from .services.sync import SyncService

        def _daily_sync() -> None:
            service = SyncService()
            try:
                result = service.run_full_sync()
                logging.getLogger(__name__).info("daily sync: %s", result)
            finally:
                service.client.close()

        scheduler = AsyncIOScheduler(timezone=settings.tz)
        scheduler.add_job(_daily_sync, CronTrigger(hour=3, minute=0), id="daily_sync")
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(sync_router)
app.include_router(charts_router)
app.include_router(analysis_router)
app.include_router(insights_router)
app.include_router(training_router)
app.include_router(achievements_router)


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name, "player": settings.chesscom_username}


def _page_ctx(player: str | None):
    from .services.sync import normalize_username

    username = normalize_username(player)
    is_default = username == settings.chesscom_username.strip().lower()
    return {
        "settings": settings,
        "player": username,
        "is_default": is_default,
        "search_value": "" if is_default else username,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request, player: str | None = None):
    from .services.sync import sync_status

    ctx = _page_ctx(player)
    return templates.TemplateResponse(
        request, "index.html", {**ctx, "status": sync_status(ctx["player"]), "active": "overview"}
    )


@app.get("/achievements", response_class=HTMLResponse)
def achievements_page(request: Request, player: str | None = None):
    ctx = _page_ctx(player)
    return templates.TemplateResponse(
        request, "achievements.html", {**ctx, "active": "achievements"}
    )
