"""Routes for v2.1 — Cartoon Downloader + AI Story + Video Remix."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import func
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import Channel
from ..services import ai_story, cartoon_downloader, video_remix
from .deps import get_db

router = APIRouter(prefix="/api/v21", tags=["v2.1"])


# ----------------------------------------------------- cartoon downloader

class CartoonDownloadRequest(BaseModel):
    url: str = Field(min_length=5)
    quality: str = "1080p"  # 1080p | 720p | 480p


class CartoonSearchRequest(BaseModel):
    query: str = Field(min_length=2)
    max_results: int = Field(default=10, ge=1, le=50)


class CartoonProcessRequest(BaseModel):
    source_path: str
    max_shorts: int = Field(default=3, ge=1, le=10)
    short_duration: int = Field(default=60, ge=15, le=180)
    channel_id: int = 1
    auto_upload: bool = True
    niche: str = "entertainment"
    language: str = "en"


@router.get("/cartoon/ytdlp-available")
def ytdlp_status():
    return {"available": cartoon_downloader.ytdlp_available()}


@router.post("/cartoon/search")
async def search_cartoons(body: CartoonSearchRequest):
    results = await cartoon_downloader.search_cartoons(body.query, body.max_results)
    return {"results": results, "count": len(results)}


@router.post("/cartoon/download")
async def download_cartoon(body: CartoonDownloadRequest):
    result = await cartoon_downloader.download_cartoon(body.url, quality=body.quality)
    return result


@router.post("/cartoon/process")
async def process_cartoon(body: CartoonProcessRequest):
    """Full flow: detect moments → clip → modify → copyright check → AUTO UPLOAD."""
    from ..services.auto_upload import auto_upload_cartoon_shorts
    result = await cartoon_downloader.process_cartoon_to_shorts(
        body.source_path, body.max_shorts, body.short_duration, body.channel_id)
    if not result.get("success"):
        return result
    # Auto-upload all clean shorts.
    if body.auto_upload and result.get("shorts"):
        upload_results = await auto_upload_cartoon_shorts(
            result["shorts"], body.channel_id, body.niche, body.language)
        result["uploads"] = upload_results
        result["uploaded"] = sum(1 for r in upload_results if r.get("success"))
    return result


@router.post("/cartoon/full-flow")
async def cartoon_full_flow(url: str, channel_id: int = 1,
                             max_shorts: int = 3, short_duration: int = 60,
                             quality: str = "1080p",
                             niche: str = "entertainment",
                             language: str = "en",
                             auto_upload: bool = True):
    """One-call flow: download cartoon → clip → modify → copyright check → upload.

    This is the simplest endpoint — give it a YouTube URL and it does everything.
    """
    from ..services.auto_upload import auto_upload_cartoon_shorts
    # Step 1: download.
    dl = await cartoon_downloader.download_cartoon(url, quality=quality)
    if not dl.get("success"):
        return {"success": False, "step": "download", "reason": dl.get("reason")}
    # Step 2: process (clip + modify + copyright check).
    proc = await cartoon_downloader.process_cartoon_to_shorts(
        dl["path"], max_shorts, short_duration, channel_id)
    if not proc.get("success"):
        return {"success": False, "step": "process", "reason": proc.get("reason"),
                "download": dl}
    # Step 3: auto-upload.
    if auto_upload and proc.get("shorts"):
        uploads = await auto_upload_cartoon_shorts(
            proc["shorts"], channel_id, niche, language)
        proc["uploads"] = uploads
        proc["uploaded"] = sum(1 for u in uploads if u.get("success"))
    proc["download"] = dl
    return proc


@router.post("/cartoon/clip-and-modify")
async def clip_and_modify(source_path: str, start: float, end: float,
                           color_shift: bool = True, speed_change: float = 1.03,
                           mirror: bool = False, crop_shift: bool = True):
    from pathlib import Path
    out = Path("data/output/cartoon_short_modified.mp4")
    result = await cartoon_downloader.clip_and_modify_short(
        source_path, start, end, out,
        modifications={"color_shift": color_shift, "speed_change": speed_change,
                       "mirror": mirror, "crop_shift": crop_shift})
    return result


# ----------------------------------------------------- AI Story Generator

class StoryRequest(BaseModel):
    prompt: str = Field(min_length=3)
    genre: str = "kids_fairy_tale"
    scene_count: int = Field(default=5, ge=3, le=12)
    target_seconds: int = Field(default=60, ge=15, le=300)
    language: str = "en"
    music_path: str | None = None
    auto_upload: bool = True
    channel_id: int = 1


@router.get("/story/genres")
def list_genres():
    return {"genres": list(ai_story.STORY_GENRES.keys()),
            "descriptions": ai_story.STORY_GENRES}


@router.post("/story/generate")
async def generate_story_video(body: StoryRequest, db: Session = Depends(get_db)):
    """Generate a complete AI story video from a prompt → AUTO UPLOAD."""
    from ..models import Video
    from ..services.auto_upload import auto_upload_video
    if not db.get(Channel, body.channel_id):
        raise HTTPException(404, "channel not found")
    video_id = (db.query(func.max(Video.id)).scalar() or 0) + 1
    result = await ai_story.create_ai_story_video(
        body.prompt, body.genre, body.scene_count, body.target_seconds,
        body.language, body.music_path, video_id)
    if not result.get("success"):
        return result
    # Auto-upload.
    if body.auto_upload and result.get("path"):
        story_title = result.get("story", {}).get("title", body.prompt[:50])
        upload = await auto_upload_video(
            file_path=result["path"],
            channel_id=body.channel_id,
            topic=story_title,
            niche="entertainment",
            language=body.language,
            is_short=body.target_seconds <= 180,
            youtube_category_id="24",  # Entertainment
            auto_publish=True,
        )
        result["upload"] = upload
    return result


# ----------------------------------------------------- Video Remix

class RemixRequest(BaseModel):
    source_path: str
    language: str = "en"
    music_path: str | None = None
    auto_upload: bool = False
    channel_id: int = 1


@router.post("/remix/analyze")
async def analyze_video(source_path: str, language: str = "en"):
    """Extract transcript + analyze structure from an uploaded video."""
    transcript_result = await video_remix.extract_transcript(source_path, language)
    if not transcript_result.get("transcript"):
        return {"success": False, "reason": transcript_result.get("reason", "no transcript"),
                "duration": transcript_result.get("duration")}
    analysis = await video_remix.analyze_video_structure(
        transcript_result["transcript"], transcript_result.get("duration", 60))
    return {"success": True, "analysis": analysis, **transcript_result}


@router.post("/remix/create")
async def remix_video(body: RemixRequest, db: Session = Depends(get_db)):
    """Full remix: transcript → analysis → original story → rendered video."""
    from ..models import Video
    if not db.get(Channel, body.channel_id):
        raise HTTPException(404, "channel not found")
    if not __import__("pathlib").Path(body.source_path).exists():
        raise HTTPException(400, "uploaded source video not found")
    # Do not fabricate a remix when speech-to-text is unavailable.
    transcript_check = await video_remix.extract_transcript(body.source_path, body.language)
    if not transcript_check.get("transcript"):
        return {
            "success": False,
            "reason": transcript_check.get("reason", "No transcript could be extracted."),
            "transcript_method": transcript_check.get("method", "none"),
            "next_step": "Install openai-whisper or faster-whisper, then retry.",
        }
    video_id = (db.query(func.max(Video.id)).scalar() or 0) + 1
    result = await video_remix.remix_video(
        body.source_path, video_id, body.language, body.music_path,
        transcript_result=transcript_check)
    if result.get("success") and body.auto_upload and result.get("path"):
        from ..services.auto_upload import auto_upload_video
        title = result.get("story", {}).get("title", "Original remix")
        result["upload"] = await auto_upload_video(
            file_path=result["path"], channel_id=body.channel_id,
            topic=title, niche="entertainment", language=body.language,
            is_short=True, youtube_category_id="24", auto_publish=True,
        )
    return result


@router.post("/remix/upload")
async def upload_for_remix(file: UploadFile = File(...)):
    """Upload a video file for remixing."""
    from pathlib import Path
    uploads_dir = Path("data/uploads")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "upload.mp4").name
    if not safe_name.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".avi")):
        raise HTTPException(400, "unsupported video file extension")
    out_path = uploads_dir / safe_name
    with open(out_path, "wb") as f:
        content = await file.read()
        f.write(content)
    return {"uploaded": True, "path": str(out_path),
            "size_mb": round(out_path.stat().st_size / 1e6, 1)}
