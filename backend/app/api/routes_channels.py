"""Multi-channel management + YouTube OAuth flow + live channel stats."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..models import Channel, StrategyProfile
from ..schemas import ChannelCreate, ChannelOut, ChannelUpdate, OAuthStartResponse
from ..services import uploader
from .deps import get_db

router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.get("", response_model=list[ChannelOut])
def list_channels(db: Session = Depends(get_db)):
    return db.query(Channel).order_by(Channel.id).all()


@router.post("", response_model=ChannelOut, status_code=201)
def create_channel(body: ChannelCreate, db: Session = Depends(get_db)):
    if db.query(Channel).filter_by(name=body.name).first():
        raise HTTPException(409, "channel name already exists")
    ch = Channel(**body.model_dump())
    db.add(ch)
    db.flush()
    db.add(StrategyProfile(channel_id=ch.id))
    db.commit()
    db.refresh(ch)
    return ch


@router.get("/{channel_id}", response_model=ChannelOut)
def get_channel(channel_id: int, db: Session = Depends(get_db)):
    ch = db.get(Channel, channel_id)
    if not ch:
        raise HTTPException(404, "channel not found")
    return ch


@router.patch("/{channel_id}", response_model=ChannelOut)
def update_channel(channel_id: int, body: ChannelUpdate, db: Session = Depends(get_db)):
    ch = db.get(Channel, channel_id)
    if not ch:
        raise HTTPException(404, "channel not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(ch, k, v)
    db.commit()
    db.refresh(ch)
    return ch


@router.get("/{channel_id}/strategy")
def channel_strategy(channel_id: int, db: Session = Depends(get_db)):
    sp = db.query(StrategyProfile).filter_by(channel_id=channel_id).first()
    if not sp:
        return {"niche_weights": {}, "hook_weights": {}, "title_patterns": {},
                "publish_hours": [13, 17, 21], "insights": []}
    return {
        "niche_weights": sp.niche_weights, "hook_weights": sp.hook_weights,
        "title_patterns": sp.title_patterns, "publish_hours": sp.publish_hours,
        "insights": sp.insights, "updated_at": sp.updated_at.isoformat() if sp.updated_at else None,
    }


@router.get("/{channel_id}/oauth/status")
def oauth_status(channel_id: int, db: Session = Depends(get_db)):
    """Tell the dashboard whether this channel is connected to YouTube."""
    ch = db.get(Channel, channel_id)
    if not ch:
        raise HTTPException(404, "channel not found")
    cred_type = uploader.detect_credential_type()
    connected = uploader.is_oauth_connected(channel_id)
    # v1.7: check if the cached token has the new force-ssl scope.
    # If not, the user needs to re-authenticate.
    needs_reauth = False
    if connected:
        try:
            creds = uploader.get_credentials(channel_id)
            if creds and creds.scopes:
                required = "https://www.googleapis.com/auth/youtube.force-ssl"
                if required not in creds.scopes:
                    needs_reauth = True
        except Exception:
            pass
    return {
        "channel_id": channel_id,
        "connected": connected,
        "has_secrets": uploader._secrets_path().exists(),
        "credential_type": cred_type,  # 'desktop' | 'web' | 'unknown'
        "auth_method": "cli" if cred_type == "desktop" else "web",
        "needs_reauth": needs_reauth,  # v1.7: scopes changed, re-auth needed
        "yt_channel_id": ch.yt_channel_id,
        "yt_channel_name": ch.name,
        "yt_thumbnail": ch.yt_thumbnail,
        "yt_subscriber_count": ch.yt_subscriber_count,
        "yt_video_count": ch.yt_video_count,
        "yt_view_count": ch.yt_view_count,
        "yt_stats_fetched_at": ch.yt_stats_fetched_at.isoformat() if ch.yt_stats_fetched_at else None,
        "dry_run": __import__("app.config", fromlist=["settings"]).settings.youtube_dry_run,
    }


@router.post("/{channel_id}/oauth/cli")
async def oauth_cli(channel_id: int, background: BackgroundTasks,
                    db: Session = Depends(get_db)):
    """Start CLI-style OAuth (works with Desktop app credentials, no redirect URI).

    This runs `run_console_auth_flow` in a background thread. The user's
    browser opens automatically, they consent, and the token is cached.
    The dashboard polls /oauth/status to detect when it's done.
    """
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    if not uploader._secrets_path().exists():
        raise HTTPException(400, "OAuth secrets file not found. "
                            "Place your client_secret.json in secrets/.")
    background.add_task(uploader.run_cli_auth_async, channel_id)
    return {
        "started": True,
        "channel_id": channel_id,
        "message": ("Browser should open automatically. Complete Google consent, "
                    "then this page will detect the connection."),
        "credential_type": uploader.detect_credential_type(),
    }


@router.post("/{channel_id}/oauth/start", response_model=OAuthStartResponse)
def oauth_start(channel_id: int, db: Session = Depends(get_db)):
    """Begin a web-based YouTube OAuth flow. Returns the Google consent URL."""
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    try:
        return uploader.start_web_oauth_flow(channel_id)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"OAuth start failed: {exc}") from exc


@router.post("/{channel_id}/oauth/refresh")
def oauth_refresh(channel_id: int, db: Session = Depends(get_db)):
    """Force-refresh the cached YouTube channel info (subs, views, thumbnail)."""
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    if not uploader.is_oauth_connected(channel_id):
        raise HTTPException(400, "YouTube not connected. Start OAuth first.")
    live = uploader.fetch_live_channel_stats(channel_id)
    if live is None:
        raise HTTPException(400, "Could not fetch live stats — token may be invalid.")
    db.commit()  # persist the cache update from the session inside uploader
    db.expire_all()
    ch = db.get(Channel, channel_id)
    return {
        "channel_id": channel_id,
        "yt_channel_name": ch.name,
        "yt_channel_id": ch.yt_channel_id,
        "yt_thumbnail": ch.yt_thumbnail,
        "yt_subscriber_count": ch.yt_subscriber_count,
        "yt_video_count": ch.yt_video_count,
        "yt_view_count": ch.yt_view_count,
        "live": live,
    }


@router.get("/{channel_id}/yt-info")
def channel_yt_info(channel_id: int, db: Session = Depends(get_db)):
    """Fetch and persist the real YouTube channel name + id (auto-detect)."""
    ch = db.get(Channel, channel_id)
    if not ch:
        raise HTTPException(404, "channel not found")
    if not uploader.is_oauth_connected(channel_id):
        raise HTTPException(
            400, "YouTube not connected. Click 'Connect YouTube' to start OAuth.")
    info = uploader.fetch_channel_info(channel_id)
    if info is None:
        raise HTTPException(
            400, "Could not fetch channel info — token may be invalid. Re-connect.")
    db.expire_all()
    ch = db.get(Channel, channel_id)
    return {
        "channel_id": channel_id,
        "yt_channel_name": ch.name,
        "yt_channel_id": ch.yt_channel_id,
        "yt_thumbnail": ch.yt_thumbnail,
        "yt_subscriber_count": ch.yt_subscriber_count,
        "yt_video_count": ch.yt_video_count,
        "yt_view_count": ch.yt_view_count,
        "fetched": info,
    }


@router.get("/{channel_id}/categories")
def channel_yt_categories(channel_id: int, db: Session = Depends(get_db)):
    """List YouTube video categories (uses the connected channel's token)."""
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return uploader.list_youtube_categories(channel_id)
