"""Hard features Group 4 — Docker deployment + Cloud rendering.

  - Docker deployment: Dockerfile + docker-compose.yml for one-command
    deployment. Includes Python backend + Node frontend + SQLite volume.
  - Cloud rendering: submit render jobs to Render.com / Railway / Fly.io
    free tier instead of rendering locally (useful for slow machines).
"""
from __future__ import annotations

import os
from pathlib import Path

from ..config import settings, ROOT_DIR
from ..core.logging import get_logger

log = get_logger("hard_infra")


# ----------------------------------------------------- Docker

def generate_dockerfile() -> str:
    """Generate a Dockerfile for the project."""
    return """# Project Phoenix AI — Dockerfile
FROM python:3.12-slim

# System deps (ffmpeg, fpcalc, fonts).
RUN apt-get update && apt-get install -y \\
    ffmpeg \\
    chromaprint-tools \\
    fonts-dejavu \\
    fonts-noto-sans \\
    && rm -rf /var/lib/apt/lists/*

# Python deps.
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project.
COPY . .

# Build frontend.
RUN cd frontend && npm install && npm run build

# Expose port.
EXPOSE 8000

# Run.
CMD ["python", "backend/cli.py", "serve"]
"""


def generate_docker_compose() -> str:
    """Generate a docker-compose.yml for the project."""
    return """# Project Phoenix AI — docker-compose.yml
version: '3.8'

services:
  phoenix:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./secrets:/app/secrets
      - ./assets:/app/assets
    environment:
      - PHOENIX_ENV_FILE=/app/.env
    restart: unless-stopped
"""


def generate_docker_files() -> dict:
    """Write Dockerfile + docker-compose.yml to the project root."""
    dockerfile = ROOT_DIR / "Dockerfile"
    compose = ROOT_DIR / "docker-compose.yml"
    dockerfile.write_text(generate_dockerfile(), encoding="utf-8")
    compose.write_text(generate_docker_compose(), encoding="utf-8")
    log.info("Docker files generated: Dockerfile + docker-compose.yml")
    return {
        "generated": True,
        "files": [str(dockerfile), str(compose)],
        "instructions": (
            "To deploy with Docker:\n"
            "  docker-compose up -d\n"
            "  # Access at http://localhost:8000\n"
            "  # Stop: docker-compose down\n"
            "  # View logs: docker-compose logs -f"
        ),
    }


# ----------------------------------------------------- cloud rendering

def cloud_rendering_available() -> bool:
    """Check if cloud rendering is configured."""
    return bool(os.environ.get("CLOUD_RENDER_API_URL"))


async def submit_render_to_cloud(video_id: int, scenes: list[dict],
                                  music_path: str, out_path: str,
                                  size: tuple[int, int]) -> dict:
    """Submit a render job to a cloud rendering service.

    This sends the scene data + media paths to a remote render service
    (e.g. Render.com, Railway, or a custom GPU server). The service
    renders the video and returns the result URL.

    Configuration:
      CLOUD_RENDER_API_URL — the render service's API endpoint
      CLOUD_RENDER_API_KEY — authentication key (if needed)

    When not configured, returns a clear message.
    """
    api_url = os.environ.get("CLOUD_RENDER_API_URL", "")
    if not api_url:
        return {"submitted": False,
                "reason": ("Cloud rendering not configured. Set "
                           "CLOUD_RENDER_API_URL in .env to enable.\n\n"
                           "Free options:\n"
                           "  1. Render.com — free tier with 512MB RAM\n"
                           "  2. Railway.app — $5 free credit/month\n"
                           "  3. Fly.io — 3 free shared-cpu VMs\n"
                           "  4. Your own GPU server (cheapest long-term)\n\n"
                           "Deploy the Phoenix backend on the cloud service, "
                           "then set CLOUD_RENDER_API_URL to its URL.")}
    import httpx
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{api_url}/api/render",
                json={"video_id": video_id,
                      "scenes": [{"clip_path": s.get("clip_path"),
                                   "voice_path": s.get("voice_path"),
                                   "voice_duration": s.get("voice_duration"),
                                   "narration": s.get("narration", "")}
                                  for s in scenes],
                      "music_path": music_path,
                      "out_path": out_path,
                      "size": list(size)},
                headers={"Authorization": f"Bearer {os.environ.get('CLOUD_RENDER_API_KEY', '')}"},
            )
        if r.status_code != 200:
            return {"submitted": False,
                    "reason": f"cloud render HTTP {r.status_code}: {r.text[:200]}"}
        return {"submitted": True, **r.json()}
    except Exception as exc:
        log.warning("cloud render failed: %s", exc)
        return {"submitted": False, "reason": str(exc)}
