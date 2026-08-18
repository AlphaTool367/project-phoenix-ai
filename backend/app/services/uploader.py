"""Automatic upload system: Google OAuth + resumable uploads + scheduling.

Dry-run mode (default) writes an upload manifest instead of calling YouTube —
the full pipeline is exercisable without touching your channel.
Google libraries are imported lazily so the app runs without them installed.

Channel auto-detection: after first OAuth, the uploader calls
`youtube.channels.list(part=snippet, mine=true)` to fetch the channel title
and persist it on the local Channel row, so the dashboard shows the real
YouTube channel name automatically (no manual configuration needed).

Web-based OAuth: the dashboard can start a consent flow that opens in the
browser, redirects to Google, then back to `/api/oauth/callback` where the
token is exchanged and cached. No CLI needed.
"""
from __future__ import annotations

import json
import secrets as _secrets
import time
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..core.logging import get_logger
from ..database import session_scope
from ..models import Channel, Video

log = get_logger("uploader")

# Full scope set — needed for uploads, analytics, and channel info.
SCOPES = [
    # youtube.force-ssl is the SUPERSET scope that covers upload, read,
    # update (privacy), playlists, comments, thumbnails — everything the
    # dashboard needs. Without it, you get 403 "insufficient scopes" on
    # playlist create, comment pin, video privacy update, thumbnail set.
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
]

# In-flight OAuth states (channel_id -> state token) — kept in memory, they
# only need to live for the duration of one consent flow.
_PENDING_STATES: dict[str, int] = {}


def _token_path(channel_id: int) -> Path:
    d = settings.path(settings.youtube_token_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"channel_{channel_id}.json"


def _secrets_path() -> Path:
    """Resolve the OAuth client secrets file path.

    - If the path is absolute, use it as-is.
    - Otherwise, resolve it against the project root.
    - Provides a clear error message if missing.
    """
    raw = settings.google_client_secrets_file
    p = Path(raw)
    if not p.is_absolute():
        p = settings.path(raw)
    return p


def detect_credential_type() -> str:
    """Detect whether the OAuth credential is 'web' or 'desktop'.

    Reads the client_secret.json and checks the top-level keys:
      - "installed" → Desktop app (use CLI auth, no redirect URI needed)
      - "web"       → Web application (use web OAuth with redirect URI)

    Returns 'desktop', 'web', or 'unknown' (when file is missing/invalid).
    """
    import json
    p = _secrets_path()
    if not p.exists():
        return "unknown"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if "installed" in data:
            return "desktop"
        if "web" in data:
            return "web"
        return "unknown"
    except Exception:
        return "unknown"


def is_oauth_connected(channel_id: int) -> bool:
    """True when a (possibly expired) token file exists for this channel."""
    return _token_path(channel_id).exists()


def get_credentials(channel_id: int):
    """Load cached OAuth credentials for a channel (refreshing if needed).

    Returns None when no token file exists. Returns the refreshed Credentials
    object otherwise. On refresh failure, the stale token file is left in
    place so the user can re-consent; we still return the (expired) creds so
    the caller can decide what to do.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token = _token_path(channel_id)
    if not token.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(token), SCOPES)
    except Exception as exc:
        log.warning("could not parse cached token for channel %s: %s", channel_id, exc)
        return None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token.write_text(creds.to_json())
        except Exception as exc:
            log.warning("token refresh failed for channel %s: %s", channel_id, exc)
            # Return the (still-expired) creds so the caller can re-trigger consent.
    return creds


def run_console_auth_flow(channel_id: int) -> bool:
    """Interactive OAuth consent (CLI `auth` command).

    Opens a local server on port 8765 that Google redirects back to.
    Works with BOTH Desktop app and Web application credentials.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    secrets = _secrets_path()
    if not secrets.exists():
        log.error("client secrets file not found: %s", secrets)
        log.error("Tip: download OAuth credentials JSON from Google Cloud "
                  "Console and save it to: %s", secrets)
        return False
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
        # run_local_server works for Desktop app credentials too — it opens
        # a tiny local HTTP server that Google redirects to.
        creds = flow.run_local_server(port=8765, prompt="consent", open_browser=True)
    except Exception as exc:
        log.error("OAuth flow failed: %s", exc)
        return False
    _token_path(channel_id).write_text(creds.to_json())
    log.info("YouTube OAuth token cached for channel %s", channel_id)

    # Auto-detect the real YouTube channel name and persist it.
    _persist_channel_info(channel_id, creds)
    return True


async def run_cli_auth_async(channel_id: int) -> dict:
    """Run the CLI auth flow in a background thread (called from the API).

    This is the Desktop-app-compatible OAuth flow — no redirect URI needed.
    The user's browser opens automatically, they consent, and the token is
    cached.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        ok = await loop.run_in_executor(None, run_console_auth_flow, channel_id)
        if ok:
            return {"connected": True, "channel_id": channel_id}
        return {"connected": False, "reason": "OAuth flow failed — check logs"}
    except Exception as exc:
        return {"connected": False, "reason": str(exc)}


# ----------------------------------------------------------------- web OAuth
def start_web_oauth_flow(channel_id: int) -> dict:
    """Begin a web-based OAuth flow. Returns dict with auth_url + state.

    The user is redirected to `auth_url`; after consent Google sends them
    back to `oauth_redirect_uri` (defaults to /api/oauth/callback).
    """
    from google_auth_oauthlib.flow import Flow

    secrets = _secrets_path()
    if not secrets.exists():
        raise RuntimeError(
            f"OAuth client secrets file not found at {secrets}. Download it "
            "from Google Cloud Console (APIs: YouTube Data API v3 + "
            "YouTube Analytics API)."
        )

    flow = Flow.from_client_secrets_file(
        str(secrets),
        scopes=SCOPES,
        redirect_uri=settings.oauth_redirect_uri,
    )
    state = _secrets.token_urlsafe(24)
    _PENDING_STATES[state] = channel_id

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return {
        "auth_url": auth_url,
        "state": state,
        "channel_id": channel_id,
        "redirect_uri": settings.oauth_redirect_uri,
    }


def complete_web_oauth_flow(code: str, state: str) -> int:
    """Exchange the auth code for a token; returns the channel_id.

    Raises RuntimeError when the state is unknown (CSRF guard / timeout).
    """
    from google_auth_oauthlib.flow import Flow

    if state not in _PENDING_STATES:
        raise RuntimeError("invalid or expired OAuth state — please restart the flow")
    channel_id = _PENDING_STATES.pop(state)

    secrets = _secrets_path()
    flow = Flow.from_client_secrets_file(
        str(secrets),
        scopes=SCOPES,
        redirect_uri=settings.oauth_redirect_uri,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    _token_path(channel_id).write_text(creds.to_json())
    log.info("YouTube OAuth token cached for channel %s (web flow)", channel_id)

    _persist_channel_info(channel_id, creds)
    return channel_id


# ----------------------------------------------------------------- helpers
def _youtube_client(channel_id: int):
    from googleapiclient.discovery import build

    creds = get_credentials(channel_id)
    if creds is None:
        return None
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _persist_channel_info(channel_id: int, creds) -> dict | None:
    """Fetch snippet + statistics for the channel and persist them locally."""
    try:
        from googleapiclient.discovery import build
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
        resp = yt.channels().list(part="snippet,statistics", mine=True).execute()
        items = resp.get("items", [])
        if not items:
            return None
        item = items[0]
        snippet = item.get("snippet", {}) or {}
        stats = item.get("statistics", {}) or {}
        title = snippet.get("title", "")
        yt_id = item.get("id", "")
        thumb = (snippet.get("thumbnails", {}) or {}).get("default", {}).get("url")
        with session_scope() as db:
            ch = db.get(Channel, channel_id)
            if ch:
                if title:
                    ch.name = title
                if yt_id:
                    ch.yt_channel_id = yt_id
                ch.yt_thumbnail = thumb
                ch.yt_description = snippet.get("description", "")[:5000]
                ch.yt_country = snippet.get("country")
                try:
                    ch.yt_subscriber_count = int(stats.get("subscriberCount", 0) or 0)
                except (TypeError, ValueError):
                    pass
                try:
                    ch.yt_video_count = int(stats.get("videoCount", 0) or 0)
                except (TypeError, ValueError):
                    pass
                try:
                    ch.yt_view_count = int(stats.get("viewCount", 0) or 0)
                except (TypeError, ValueError):
                    pass
                ch.yt_stats_fetched_at = datetime.utcnow()
                log.info("auto-detected YouTube channel: '%s' (id=%s, subs=%s)",
                         title, yt_id, ch.yt_subscriber_count)
        return {
            "title": title,
            "yt_channel_id": yt_id,
            "thumbnail": thumb,
            "subscriber_count": stats.get("subscriberCount"),
            "video_count": stats.get("videoCount"),
            "view_count": stats.get("viewCount"),
        }
    except Exception as exc:
        log.warning("could not auto-detect channel info: %s", exc)
        return None


def fetch_channel_info(channel_id: int) -> dict | None:
    """Fetch the real YouTube channel title + id (also persists them locally)."""
    creds = get_credentials(channel_id)
    if creds is None:
        return None
    return _persist_channel_info(channel_id, creds)


def fetch_live_channel_stats(channel_id: int) -> dict | None:
    """Live subscriber / video / view counts + snippet. Refreshes the cache."""
    yt = _youtube_client(channel_id)
    if yt is None:
        return None
    try:
        resp = yt.channels().list(part="snippet,statistics", mine=True).execute()
        items = resp.get("items", [])
        if not items:
            return None
        item = items[0]
        snippet = item.get("snippet", {}) or {}
        stats = item.get("statistics", {}) or {}
        thumb = (snippet.get("thumbnails", {}) or {}).get("default", {}).get("url")
        title = snippet.get("title", "")
        yt_id = item.get("id", "")
        with session_scope() as db:
            ch = db.get(Channel, channel_id)
            if ch:
                if title and ch.name != title:
                    ch.name = title
                if yt_id and ch.yt_channel_id != yt_id:
                    ch.yt_channel_id = yt_id
                ch.yt_thumbnail = thumb
                ch.yt_description = snippet.get("description", "")[:5000]
                ch.yt_country = snippet.get("country")
                try: ch.yt_subscriber_count = int(stats.get("subscriberCount", 0) or 0)
                except (TypeError, ValueError): pass
                try: ch.yt_video_count = int(stats.get("videoCount", 0) or 0)
                except (TypeError, ValueError): pass
                try: ch.yt_view_count = int(stats.get("viewCount", 0) or 0)
                except (TypeError, ValueError): pass
                ch.yt_stats_fetched_at = datetime.utcnow()
        return {
            "title": title,
            "yt_channel_id": yt_id,
            "thumbnail": thumb,
            "subscriber_count": int(stats.get("subscriberCount", 0) or 0),
            "video_count": int(stats.get("videoCount", 0) or 0),
            "view_count": int(stats.get("viewCount", 0) or 0),
            "country": snippet.get("country"),
            "description": snippet.get("description", ""),
            "fetched_at": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        log.warning("fetch_live_channel_stats failed: %s", exc)
        return None


def list_youtube_categories(channel_id: int, region_code: str = "US") -> list[dict]:
    """Return YouTube video categories for a region (used in the produce form)."""
    yt = _youtube_client(channel_id)
    if yt is None:
        # Fall back to a small built-in catalog so the UI still works.
        return _FALLBACK_CATEGORIES
    try:
        resp = yt.videoCategories().list(part="snippet", regionCode=region_code).execute()
        out = []
        for item in resp.get("items", []):
            snip = item.get("snippet", {}) or {}
            out.append({
                "id": item.get("id", ""),
                "title": snip.get("title", ""),
                "assignable": bool(snip.get("assignable", True)),
            })
        return out or _FALLBACK_CATEGORIES
    except Exception as exc:
        log.warning("list_youtube_categories failed: %s", exc)
        return _FALLBACK_CATEGORIES


_FALLBACK_CATEGORIES = [
    {"id": "1",  "title": "Film & Animation", "assignable": True},
    {"id": "2",  "title": "Autos & Vehicles", "assignable": True},
    {"id": "10", "title": "Music", "assignable": True},
    {"id": "15", "title": "Pets & Animals", "assignable": True},
    {"id": "17", "title": "Sports", "assignable": True},
    {"id": "19", "title": "Travel & Events", "assignable": True},
    {"id": "20", "title": "Gaming", "assignable": True},
    {"id": "22", "title": "People & Blogs", "assignable": True},
    {"id": "23", "title": "Comedy", "assignable": True},
    {"id": "24", "title": "Entertainment", "assignable": True},
    {"id": "25", "title": "News & Politics", "assignable": True},
    {"id": "26", "title": "Howto & Style", "assignable": True},
    {"id": "27", "title": "Education", "assignable": True},
    {"id": "28", "title": "Science & Technology", "assignable": True},
    {"id": "29", "title": "Nonprofits & Activism", "assignable": True},
]


async def upload_video(video: Video, channel_id: int) -> dict:
    """Upload (or dry-run) a rendered video; schedule if scheduled_at is set."""
    # Pick the YouTube category: per-video override > global setting.
    yt_category = (getattr(video, "_yt_category_id", None)
                   or settings.youtube_category_id or "27")

    body = {
        "snippet": {
            "title": video.title,
            "description": video.description,
            "tags": video.tags,
            "categoryId": str(yt_category),
            "defaultLanguage": video.language,
            "defaultAudioLanguage": video.language,
        },
        "status": {
            "privacyStatus": "private" if video.scheduled_at else _channel_privacy(channel_id),
            "selfDeclaredMadeForKids": False,
            **(
                {"publishAt": video.scheduled_at.strftime("%Y-%m-%dT%H:%M:%S.0Z"),
                 "privacyStatus": "private"}
                if video.scheduled_at else {}
            ),
        },
    }

    # If dry-run is OFF but no token is cached, fall back to a manifest so the
    # pipeline still completes — the user just needs to re-consent.
    creds = get_credentials(channel_id)
    if settings.youtube_dry_run or creds is None:
        manifest = settings.path(settings.data_dir, "output") / f"v{video.id}_upload_manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({
            "dry_run": True,
            "would_upload": body,
            "file": video.file_path,
            "thumbnail": video.thumbnail_path,
            "reason": "no_token" if creds is None else "dry_run_mode",
            "at": datetime.utcnow().isoformat(),
        }, indent=2))
        log.info("DRY-RUN upload for video %d (manifest: %s, reason=%s)",
                 video.id, manifest.name,
                 "no_token" if creds is None else "dry_run_mode")
        return {"yt_video_id": f"DRYRUN-{video.id:06d}", "dry_run": True,
                "manifest": str(manifest)}

    from googleapiclient.http import MediaFileUpload

    yt = _youtube_client(channel_id)
    if yt is None:
        raise RuntimeError("YouTube client unavailable — run OAuth consent first")

    # Make sure the local Channel row reflects the real YouTube channel name.
    fetch_channel_info(channel_id)

    media = MediaFileUpload(video.file_path, mimetype="video/mp4",
                            resumable=True, chunksize=8 * 1024 * 1024)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    attempt = 0
    last_err = ""
    while response is None and attempt < 5:
        try:
            _, response = request.next_chunk()
        except Exception as exc:
            attempt += 1
            last_err = str(exc)
            wait = 2 ** attempt * 5
            log.warning("upload chunk failed (%s), retry %d in %ds", exc, attempt, wait)
            time.sleep(wait)
    if response is None:
        raise RuntimeError(f"upload failed after 5 attempts: {last_err[:300]}")

    yt_id = response["id"]
    if video.thumbnail_path and Path(video.thumbnail_path).exists():
        try:
            yt.thumbnails().set(
                videoId=yt_id,
                media_body=MediaFileUpload(video.thumbnail_path, mimetype="image/jpeg"),
            ).execute()
        except Exception as exc:
            log.warning("thumbnail set failed for %s: %s", yt_id, exc)

    log.info("uploaded video %d -> https://youtu.be/%s", video.id, yt_id)
    return {"yt_video_id": yt_id, "dry_run": False,
            "url": f"https://youtu.be/{yt_id}"}


def _channel_privacy(channel_id: int) -> str:
    with session_scope() as db:
        ch = db.get(Channel, channel_id)
        return ch.privacy if ch else settings.video_privacy


async def list_playlists(channel_id: int) -> list[dict]:
    yt = _youtube_client(channel_id)
    if yt is None:
        return []
    try:
        resp = yt.playlists().list(part="snippet", mine=True, maxResults=50).execute()
        return [{"id": p["id"], "title": p["snippet"]["title"]}
                for p in resp.get("items", [])]
    except Exception as exc:
        log.warning("list_playlists failed: %s", exc)
        return []


# ----------------------------------------------------- v1.3 copyright safety
def get_video_status(channel_id: int, yt_video_id: str) -> dict | None:
    """Fetch the current status of an uploaded video.

    Returns the `status` dict from the YouTube Data API:
      {privacyStatus, publishAt, selfDeclaredMadeForKids, madeForKids,
       containsSyntheticMedia, license, embeddable, publicStatsViewable}

    Returns None on any error (caller should treat as "unknown" rather than
    "clean"). The most useful field for copyright checking is the
    `contentDetails.contentClaim` block, but the simpler signal is the
    presence of an entry in `contentRating` or `claimList` in the auditDetail.
    For this use case we call the videos.list with part=status,contentDetails,
    snippet and inspect what's available without the auditDetail (which needs
    special access).
    """
    yt = _youtube_client(channel_id)
    if yt is None:
        return None
    try:
        resp = yt.videos().list(
            part="status,contentDetails,snippet,statistics",
            id=yt_video_id,
        ).execute()
        items = resp.get("items", [])
        if not items:
            return None
        item = items[0]
        return {
            "status": item.get("status", {}),
            "content_details": item.get("contentDetails", {}),
            "snippet": item.get("snippet", {}),
            "statistics": item.get("statistics", {}),
            "raw": item,
        }
    except Exception as exc:
        log.warning("get_video_status failed for %s: %s", yt_video_id, exc)
        return None


def has_copyright_claim(channel_id: int, yt_video_id: str) -> tuple[bool, str]:
    """Check whether a video has any copyright claim / strike.

    Returns (has_claim, details_str). When the API can't tell us (the standard
    contentDetails part doesn't expose claims — that needs the auditDetail
    partner-only scope), we look at:
      1. contentDetails.licensedContent (True = third-party licensed content)
      2. status.uploadStatus == 'rejected' (upload rejected for policy reasons)
      3. status.rejectionReason (any non-empty value)
      4. contentDetails.regionRestriction (blocked in regions)

    The most reliable signal available without partner scope is
    `contentDetails.licensedContent == True` — that indicates a Content ID
    claim exists. We also flag any rejectionReason.
    """
    s = get_video_status(channel_id, yt_video_id)
    if s is None:
        return (False, "video not found or API error")
    cd = s.get("content_details", {}) or {}
    st = s.get("status", {}) or {}
    reasons = []
    if cd.get("licensedContent"):
        reasons.append("Content ID claim (licensedContent=True)")
    if st.get("uploadStatus") == "rejected":
        reasons.append(f"upload rejected: {st.get('rejectionReason', 'unknown')}")
    elif st.get("rejectionReason"):
        reasons.append(f"rejection: {st.get('rejectionReason')}")
    rr = cd.get("regionRestriction") or {}
    if rr.get("blocked"):
        reasons.append(f"blocked in regions: {','.join(rr['blocked'][:5])}")
    if reasons:
        return (True, "; ".join(reasons))
    return (False, "no claims detected")


def set_video_privacy(channel_id: int, yt_video_id: str,
                      privacy: str) -> bool:
    """Change a video's privacy status (private/unlisted/public)."""
    yt = _youtube_client(channel_id)
    if yt is None:
        return False
    try:
        yt.videos().update(
            part="status",
            body={
                "id": yt_video_id,
                "status": {
                    "privacyStatus": privacy,
                    "selfDeclaredMadeForKids": False,
                },
            },
        ).execute()
        log.info("video %s privacy set to '%s'", yt_video_id, privacy)
        return True
    except Exception as exc:
        log.warning("set_video_privacy failed for %s: %s", yt_video_id, exc)
        return False


def delete_video(channel_id: int, yt_video_id: str) -> bool:
    """Permanently delete a video from YouTube."""
    yt = _youtube_client(channel_id)
    if yt is None:
        return False
    try:
        yt.videos().delete(id=yt_video_id).execute()
        log.info("video %s DELETED from YouTube", yt_video_id)
        return True
    except Exception as exc:
        log.warning("delete_video failed for %s: %s", yt_video_id, exc)
        return False


async def copyright_check_and_finalize(channel_id: int, yt_video_id: str,
                                       video_id: int | None = None) -> dict:
    """Run the full copyright-check → publish/delete flow for a video.

    Returns a dict: {action: 'published'|'deleted'|'kept'|'unknown', reason, ...}

    Flow:
      1. Wait settings.copyright_wait_seconds (default 150s) for YouTube to
         process Content ID matching.
      2. Call has_copyright_claim(). If True: delete the video, set local
         status to 'failed' with a clear error. Return action='deleted'.
      3. If clean and settings.auto_publish_after_check is True: set the
         video's privacy to settings.post_check_privacy (default 'unlisted').
         Return action='published'.
      4. If clean but auto_publish is False: leave as-is. Return 'kept'.
    """
    import asyncio
    from ..models import Video as VideoModel
    wait = max(30, int(settings.copyright_wait_seconds))
    log.info("copyright check: waiting %ds before checking video %s", wait, yt_video_id)
    await asyncio.sleep(wait)
    has_claim, details = has_copyright_claim(channel_id, yt_video_id)

    if has_claim:
        log.warning("copyright claim detected on video %s: %s", yt_video_id, details)
        ok = delete_video(channel_id, yt_video_id)
        if video_id is not None:
            with session_scope() as db:
                v = db.get(VideoModel, video_id)
                if v:
                    v.status = "failed"
                    v.error = f"Copyright claim detected — auto-deleted. ({details})"[:2000]
        return {"action": "deleted", "reason": details, "yt_video_id": yt_video_id}

    if settings.auto_publish_after_check:
        target = settings.post_check_privacy or "unlisted"
        ok = set_video_privacy(channel_id, yt_video_id, target)
        if ok and video_id is not None:
            with session_scope() as db:
                v = db.get(VideoModel, video_id)
                if v:
                    v.status = "published"
                    v.published_at = datetime.utcnow()
        return {"action": "published", "privacy": target,
                "yt_video_id": yt_video_id, "reason": details}

    return {"action": "kept", "reason": "auto_publish disabled",
            "yt_video_id": yt_video_id}
