"""Project Phoenix AI — FastAPI application entry point.

Serves the REST API + websocket, runs crash recovery on boot, starts the
automation scheduler, and (in production) serves the built dashboard.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import APP_NAME, __version__
from .api import (
    routes_analytics, routes_channels, routes_compliance, routes_dashboard,
    routes_growth, routes_jobs, routes_monetization, routes_monitor,
    routes_revenue, routes_scheduler, routes_settings, routes_safety, routes_v18,
    routes_v19, routes_v20, routes_v21, routes_videos, ws,
)
from .config import settings
from .core.logging import get_logger
from .database import init_db, session_scope
from .models import Channel, StrategyProfile

log = get_logger("main")


def ensure_default_channel() -> None:
    with session_scope() as db:
        if db.query(Channel).count() == 0:
            ch = Channel(
                name=settings.channel_name,
                niche=settings.channel_niche,
                language=settings.channel_language,
                videos_per_day=settings.videos_per_day,
                privacy=settings.video_privacy,
            )
            db.add(ch)
            db.flush()
            db.add(StrategyProfile(channel_id=ch.id))
            log.info("created default channel '%s' (niche=%s)", ch.name, ch.niche)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_default_channel()

    from .pipeline.recovery import recover_interrupted_work
    from .pipeline.scheduler import start as start_scheduler

    recovery = recover_interrupted_work()
    sched = start_scheduler()
    log.info("%s v%s ready — recovery=%s, scheduler jobs=%d",
             APP_NAME, __version__, recovery, len(sched.get_jobs()))
    yield
    if sched.running:
        sched.shutdown(wait=False)
        log.info("scheduler stopped")


app = FastAPI(title=APP_NAME, version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                   "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
    routes_dashboard.router, routes_channels.router, routes_videos.router,
    routes_jobs.router, routes_analytics.router, routes_settings.router,
    routes_monitor.router, routes_scheduler.router,
    routes_monetization.router, routes_revenue.router,
    routes_growth.router, routes_compliance.router, routes_safety.router,
    routes_compliance.trend_router, routes_v18.router,
    routes_v19.router, routes_v20.router, routes_v21.router, ws.router,
):
    app.include_router(r)


@app.get("/api")
def root():
    return {"name": APP_NAME, "version": __version__, "docs": "/docs"}


# ----------------------------------------------------------------- OAuth callback
@app.get("/api/oauth/callback")
async def oauth_callback(request: Request,
                         code: str | None = Query(default=None),
                         state: str | None = Query(default=None),
                         error: str | None = Query(default=None)):
    """Google redirects here after the user grants consent.

    On success, exchanges the code for a token and caches it under the channel
    that started the flow (looked up by `state`). Shows a friendly result page
    that auto-closes the popup.
    """
    from .services.uploader import complete_web_oauth_flow

    if error:
        return HTMLResponse(_oauth_result_page(
            ok=False, message=f"Google returned an error: {error}"), status_code=400)

    if not code or not state:
        return HTMLResponse(_oauth_result_page(
            ok=False, message="Missing authorization code or state."), status_code=400)

    try:
        channel_id = complete_web_oauth_flow(code=code, state=state)
    except RuntimeError as exc:
        return HTMLResponse(_oauth_result_page(ok=False, message=str(exc)),
                            status_code=400)
    except Exception as exc:
        log.exception("OAuth callback failed: %s", exc)
        return HTMLResponse(_oauth_result_page(
            ok=False, message=f"OAuth exchange failed: {exc}"), status_code=500)

    log.info("OAuth completed for channel %d", channel_id)
    return HTMLResponse(_oauth_result_page(
        ok=True,
        message=f"YouTube channel connected! You can close this tab and return to the dashboard.",
        channel_id=channel_id,
    ))


def _oauth_result_page(ok: bool, message: str, channel_id: int | None = None) -> str:
    color = "#10b981" if ok else "#ef4444"
    icon = "✓" if ok else "✕"
    title = "Connected" if ok else "Failed"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>YouTube OAuth — {title}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         background: #0a0a0c; color: #e4e4e7; margin: 0;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; }}
  .card {{ background: #141418; border: 1px solid #2e2e36; border-radius: 16px;
          padding: 40px; max-width: 480px; text-align: center; }}
  .icon {{ font-size: 64px; color: {color}; margin-bottom: 16px; }}
  h1 {{ margin: 0 0 12px; font-size: 24px; }}
  p  {{ color: #a1a1aa; line-height: 1.5; margin: 0 0 24px; }}
  .meta {{ font-size: 12px; color: #52525b; }}
</style></head>
<body>
  <div class="card">
    <div class="icon">{icon}</div>
    <h1>{title}</h1>
    <p>{message}</p>
    <div class="meta">channel_id: {channel_id or "—"}</div>
    <script>
      // Try to close the popup (works when opened as a popup from the dashboard).
      setTimeout(function() {{
        try {{ window.close(); }} catch(e) {{}}
      }}, 2500);
    </script>
  </div>
</body></html>"""


# Serve the built dashboard when frontend/dist exists (production mode).
# The custom fallback is required for direct SPA URLs such as /safety and
# /analytics; API routes are registered above and continue to win first.
class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and scope.get("method") == "GET":
                return await super().get_response("index.html", scope)
            raise


_dist = settings.path("frontend", "dist")
if _dist.exists():
    app.mount("/", SPAStaticFiles(directory=str(_dist), html=True), name="dashboard")
