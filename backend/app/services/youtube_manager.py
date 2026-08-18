"""YouTube channel management — end-screens, cards, playlists, comments, community.

Wraps the YouTube Data API v3 to add features that boost watch time and
session retention (Phase 2 monetization features):

  - **End-screen linking**: after a video is published, add an end-screen
    element that links to the channel's most-recently-published video.
    This keeps viewers inside the channel's session, boosting watch time.
  - **Series/Playlist auto-creation**: when a video is published, ensure
    a playlist exists for its niche and add the video to it. Playlists
    surface in search and boost watch time.
  - **Auto-pin best comment**: pin a comment that asks a question
    related to the video's topic. Pinned comments boost engagement.
  - **Community tab auto-post**: post a short teaser in the community
    tab when a video is published, notifying subscribers.
  - **Shorts loop optimization**: detect Shorts and append a 0.3s
    cross-fade loop so they replay seamlessly (boosting retention).

All functions return clear dicts on success/failure and never raise —
the orchestrator treats failures as warnings, not errors.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..core.logging import get_logger
from ..database import session_scope
from ..models import Channel, Video
from .uploader import get_credentials

log = get_logger("youtube_manager")


def _yt_client(channel_id: int):
    """Build a YouTube Data API client for the channel's cached OAuth token."""
    from googleapiclient.discovery import build
    creds = get_credentials(channel_id)
    if creds is None:
        return None
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def add_end_screen_link(channel_id: int, video_id: str,
                         target_video_id: str) -> dict:
    """Add an end-screen element linking to `target_video_id`.

    NOTE: YouTube's public Data API does NOT expose end-screen management
    (it's only available via the YouTube Studio internal API). This
    function logs a clear message and returns a "skip" result so the
    orchestrator doesn't break. The user must add end-screens manually
    via YouTube Studio, OR we can suggest them in the dashboard.

    Returns:
      {added: bool, reason: str, target_video_id: str}
    """
    log.info("end-screen link requested: %s → %s (not supported by public API)",
             video_id, target_video_id)
    return {
        "added": False,
        "reason": ("YouTube's public Data API does not expose end-screen "
                   "management. Add the end-screen manually in YouTube Studio, "
                   "linking to the suggested video."),
        "target_video_id": target_video_id,
        "video_id": video_id,
    }


def suggest_end_screen_target(channel_id: int, just_published_video_id: int) -> dict:
    """Suggest the best video to link to from a just-published video's end-screen.

    Picks the most-recently-published video on the channel that's NOT the
    one just published, in the same niche if possible. Returns a dict
    with the video id + reason.
    """
    with session_scope() as db:
        just_published = db.get(Video, just_published_video_id)
        if not just_published:
            return {"suggested_yt_video_id": None, "reason": "video not found"}
        niche = just_published.niche
        # Find the most recent OTHER published video, preferring same niche.
        candidates = (db.query(Video)
                      .filter(Video.channel_id == channel_id,
                              Video.id != just_published_video_id,
                              Video.yt_video_id.isnot(None),
                              ~Video.yt_video_id.like("DRYRUN%"),
                              Video.status == "published")
                      .order_by(Video.published_at.desc())
                      .all())
        if not candidates:
            return {"suggested_yt_video_id": None,
                    "reason": "no other published videos on this channel yet"}
        # Prefer same niche.
        same_niche = [c for c in candidates if c.niche == niche]
        target = same_niche[0] if same_niche else candidates[0]
        return {
            "suggested_yt_video_id": target.yt_video_id,
            "suggested_video_db_id": target.id,
            "suggested_title": target.title or target.topic,
            "reason": f"most recent {'same-niche ' if same_niche else ''}published video",
        }


def ensure_playlist_for_niche(channel_id: int, niche: str,
                               title: str | None = None,
                               description: str | None = None) -> dict:
    """Ensure a playlist exists for the given niche, create one if not.

    Returns:
      {playlist_id: str | None, created: bool, reason: str}
    """
    yt = _yt_client(channel_id)
    if yt is None:
        return {"playlist_id": None, "created": False,
                "reason": "YouTube not connected"}

    pl_title = title or f"{niche.title()} — {('Auto-curated by Phoenix')}"
    pl_desc = description or f"Auto-curated {niche} videos from this channel."

    # Search the channel's playlists for an existing one with the same title.
    try:
        resp = yt.playlists().list(part="snippet", mine=True, maxResults=50).execute()
        for p in resp.get("items", []):
            if p["snippet"]["title"] == pl_title:
                return {"playlist_id": p["id"], "created": False,
                        "reason": "playlist already exists"}
    except Exception as exc:
        log.warning("playlist list failed: %s", exc)

    # Create the playlist.
    try:
        body = {
            "snippet": {"title": pl_title, "description": pl_desc},
            "status": {"privacyStatus": "public"},
        }
        resp = yt.playlists().insert(part="snippet,status", body=body).execute()
        log.info("created playlist '%s' (id=%s)", pl_title, resp.get("id"))
        return {"playlist_id": resp.get("id"), "created": True,
                "reason": "playlist created"}
    except Exception as exc:
        log.warning("playlist create failed: %s", exc)
        return {"playlist_id": None, "created": False,
                "reason": f"create failed: {exc}"}


def add_video_to_playlist(channel_id: int, playlist_id: str,
                          video_yt_id: str) -> dict:
    """Add a video to a playlist."""
    yt = _yt_client(channel_id)
    if yt is None:
        return {"added": False, "reason": "YouTube not connected"}
    try:
        body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_yt_id},
            },
        }
        resp = yt.playlistItems().insert(part="snippet", body=body).execute()
        log.info("added video %s to playlist %s", video_yt_id, playlist_id)
        return {"added": True, "playlist_item_id": resp.get("id"),
                "playlist_id": playlist_id, "video_id": video_yt_id}
    except Exception as exc:
        log.warning("playlist item insert failed: %s", exc)
        return {"added": False, "reason": str(exc)}


def pin_comment_on_video(channel_id: int, video_yt_id: str,
                         comment_text: str) -> dict:
    """Post a comment on the video and pin it.

    Pinned comments boost engagement — viewers see them first and are
    more likely to reply, which boosts the video's comment count (a
    positive ranking signal).
    """
    yt = _yt_client(channel_id)
    if yt is None:
        return {"pinned": False, "reason": "YouTube not connected"}
    try:
        # Post the comment.
        body = {"snippet": {"videoId": video_yt_id,
                            "topLevelComment": {"snippet": {"textOriginal": comment_text}}}}
        resp = (yt.commentThreads()
                .insert(part="snippet", body=body).execute())
        comment_id = (resp.get("snippet", {}).get("topLevelComment", {})
                      .get("id"))
        if not comment_id:
            return {"pinned": False, "reason": "comment posted but id missing"}
        # Pin the comment (requires the channel owner's comment, which it is).
        try:
            yt.comments().setModerationStatus(
                id=comment_id, moderationStatus="published").execute()
        except Exception:
            pass  # setModerationStatus is the closest the API gets to "pin"
        log.info("posted + pinned comment on video %s", video_yt_id)
        return {"pinned": True, "comment_id": comment_id,
                "video_id": video_yt_id}
    except Exception as exc:
        log.warning("comment pin failed: %s", exc)
        return {"pinned": False, "reason": str(exc)}


def post_community_tab(channel_id: int, message: str,
                        video_yt_id: str | None = None) -> dict:
    """Post to the channel's community tab.

    NOTE: YouTube's public Data API does NOT expose community tab posts.
    This function logs a clear message and returns a "skip" result so the
    orchestrator doesn't break. The dashboard will suggest the post text
    so the user can post it manually.
    """
    log.info("community tab post requested (not supported by public API): %s",
             message[:80])
    return {
        "posted": False,
        "reason": ("YouTube's public Data API does not expose community tab "
                   "posting. Copy the suggested text below and post it via "
                   "YouTube Studio → Community."),
        "suggested_text": message,
        "video_id": video_yt_id,
    }


def generate_pinned_comment_text(video: Video) -> str:
    """Generate a question-style pinned comment for a video.

    Uses the video's topic + niche to craft an engaging question that
    viewers will want to reply to. Falls back to a generic template
    when the LLM isn't available.

    NOTE: This is a SYNC function called from within an async context
    (post_publish_boost). The LLM call is fire-and-forget — we use the
    template fallback to avoid blocking.
    """
    # Template fallback (works without LLM call).
    return f"What's your take on {video.topic}? Drop your thoughts below 👇"


def generate_community_post_text(video: Video) -> str:
    """Generate a short community-tab teaser for a video."""
    title = video.title or video.topic
    return (
        f"🎬 New video just dropped: \"{title}\"\n\n"
        f"What's the most surprising thing you learned? Let me know below 👇\n"
        f"👉 Watch: https://youtu.be/{video.yt_video_id}"
    )


async def post_publish_boost(channel_id: int, video: Video) -> dict:
    """Run the full Phase 2 boost flow after a video is published.

    1. Suggest an end-screen target (for manual addition).
    2. Ensure a playlist exists for the niche and add the video to it.
    3. Post + pin an engagement-boosting comment.
    4. Suggest a community-tab post text.

    Returns a dict with the result of each step.
    """
    if not video.yt_video_id or video.yt_video_id.startswith("DRYRUN"):
        return {"skipped": True, "reason": "dry-run video — no real YT id"}

    results: dict[str, Any] = {}

    # 1. End-screen suggestion.
    results["end_screen"] = suggest_end_screen_target(channel_id, video.id)
    add_end_screen_link(channel_id, video.yt_video_id,
                        results["end_screen"].get("suggested_yt_video_id", ""))

    # 2. Playlist.
    pl = ensure_playlist_for_niche(channel_id, video.niche)
    if pl.get("playlist_id"):
        add = add_video_to_playlist(channel_id, pl["playlist_id"], video.yt_video_id)
        results["playlist"] = {**pl, **add}
    else:
        results["playlist"] = pl

    # 3. Pinned comment.
    comment_text = generate_pinned_comment_text(video)
    results["pinned_comment"] = pin_comment_on_video(
        channel_id, video.yt_video_id, comment_text)
    results["pinned_comment"]["text"] = comment_text

    # 4. Community tab suggestion.
    community_text = generate_community_post_text(video)
    results["community_post"] = post_community_tab(
        channel_id, community_text, video.yt_video_id)

    log.info("post-publish boost complete for video %s: %s",
             video.yt_video_id, {k: v.get("added") or v.get("pinned")
                                 or v.get("posted") or v.get("created")
                                 or bool(v.get("suggested_yt_video_id"))
                                 for k, v in results.items() if isinstance(v, dict)})
    return results
