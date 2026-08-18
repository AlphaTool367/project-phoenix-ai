"""Routes for all v2.0 hard features."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import Channel, Video
from ..services import (hard_animate, hard_auth, hard_infra, hard_ml,
                        hard_voice)
from .deps import get_db

router = APIRouter(prefix="/api/v20", tags=["v2.0"])


# ----------------------------------------------------- voice cloning

class CloneRequest(BaseModel):
    text: str
    voice_sample_path: str = ""
    voice_id: str = ""


@router.get("/voice-clone/available")
def voice_clone_available():
    return {"coqui": hard_voice.coqui_available(),
            "elevenlabs": hard_voice.elevenlabs_available()}


@router.post("/voice-clone/coqui")
async def clone_coqui(body: CloneRequest):
    from pathlib import Path
    out = Path("data/output/cloned_voice.mp3")
    return await hard_voice.clone_voice_coqui(body.text, body.voice_sample_path, out)


@router.post("/voice-clone/elevenlabs")
async def clone_elevenlabs(body: CloneRequest):
    from pathlib import Path
    out = Path("data/output/elevenlabs_voice.mp3")
    return await hard_voice.clone_voice_elevenlabs(body.text, body.voice_id, out)


# ----------------------------------------------------- lip-sync

@router.get("/lip-sync/available")
def lip_sync_available():
    return {"available": hard_voice.wav2lip_available()}


@router.post("/lip-sync")
async def lip_sync(video_path: str, audio_path: str):
    return await hard_voice.lip_sync_video(video_path, audio_path)


# ----------------------------------------------------- animated explainer

@router.get("/manim/available")
def manim_available():
    return {"available": hard_animate.manim_available()}


@router.post("/manim/explainer")
async def manim_explainer(topic: str, key_points: str):
    from pathlib import Path
    out = Path("data/output/animated_explainer.mp4")
    points = [p.strip() for p in key_points.split(",") if p.strip()]
    return await hard_animate.generate_animated_explainer(topic, points, out)


# ----------------------------------------------------- live stream highlights

@router.post("/highlights/detect")
async def detect_highlights(stream_path: str, max_highlights: int = 5):
    return {"highlights": await hard_animate.detect_highlight_moments(
        stream_path, max_highlights=max_highlights)}


@router.post("/highlights/clip")
async def clip_highlights(stream_path: str, highlights_json: str):
    import json
    from pathlib import Path
    highlights = json.loads(highlights_json)
    out_dir = Path("data/output/highlights")
    results = await hard_animate.clip_highlights(stream_path, highlights, out_dir)
    return {"clips": results, "count": len(results)}


# ----------------------------------------------------- multi-user auth

class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=4, max_length=100)
    role: str = "editor"


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/register")
def register(body: UserCreate):
    return hard_auth.create_user(body.username, body.password, body.role)


@router.post("/auth/login")
def login(body: LoginRequest):
    return hard_auth.authenticate(body.username, body.password)


@router.get("/auth/verify")
def verify(token: str):
    user = hard_auth.verify_token(token)
    if not user:
        raise HTTPException(401, "invalid token")
    return user


@router.get("/auth/users")
def users():
    return {"users": hard_auth.list_users()}


@router.delete("/auth/users/{username}")
def remove_user(username: str):
    return hard_auth.delete_user(username)


# ----------------------------------------------------- team chat

@router.get("/chat/{video_id}")
def chat_history(video_id: int, limit: int = 50):
    return {"messages": hard_auth.get_chat_history(video_id, limit)}


@router.post("/chat/{video_id}")
def post_chat(video_id: int, username: str, message: str,
              timestamp_sec: float | None = None):
    return hard_auth.add_chat_message(video_id, username, message, timestamp_sec)


@router.websocket("/ws/chat/{video_id}")
async def ws_chat(websocket: WebSocket, video_id: int):
    """WebSocket for real-time team chat on a video."""
    await websocket.accept()
    hard_auth.register_chat_client(video_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            msg = hard_auth.add_chat_message(
                video_id, data.get("username", "anonymous"),
                data.get("message", ""),
                data.get("timestamp_sec"))
            await websocket.send_json(msg)
    except WebSocketDisconnect:
        hard_auth.unregister_chat_client(video_id, websocket)


# ----------------------------------------------------- Docker

@router.post("/docker/generate")
def docker_generate():
    return hard_infra.generate_docker_files()


@router.get("/cloud-render/available")
def cloud_available():
    return {"available": hard_infra.cloud_rendering_available()}


# ----------------------------------------------------- predictive ML

@router.post("/ml/train/{channel_id}")
def train_model(channel_id: int, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return hard_ml.train_topic_model(channel_id)


@router.post("/ml/predict")
def predict(niche: str, title: str, channel_id: int = 1,
            hook_style: str = "", is_short: bool = False):
    return hard_ml.predict_topic_potential(channel_id, niche, title,
                                            hook_style, is_short)


# ----------------------------------------------------- multi-camera

@router.post("/multi-angle")
async def multi_angle(clip_paths: str, duration: float = 10.0):
    from pathlib import Path
    paths = [p.strip() for p in clip_paths.split(",") if p.strip()]
    out_dir = Path("data/output/multi_angle")
    return await hard_ml.render_multi_angle(paths, out_dir, duration)


# ----------------------------------------------------- 360 video

@router.post("/360/inject")
async def inject_360(video_path: str):
    return await hard_ml.inject_360_metadata(video_path)


# ----------------------------------------------------- interactive

class InteractiveRequest(BaseModel):
    video_id: int
    choices: list[dict]


@router.post("/interactive/endscreen")
def interactive_endscreen(body: InteractiveRequest):
    return hard_ml.generate_interactive_endscreen(body.video_id, body.choices)
