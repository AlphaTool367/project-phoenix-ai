"""Hard features Group 3 — Multi-user auth (JWT) + Team chat (WebSocket).

  - Multi-user accounts: JWT-based authentication with role-based access
    control (admin, editor, writer, reviewer). Each user can only see
    + act on what their role allows.
  - Team chat on videos: real-time WebSocket chat per video, so team
    members can discuss a video's progress with timestamps.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Any

from ..config import settings
from ..core.logging import get_logger
from ..database import session_scope
from ..models import ActivityLog

log = get_logger("hard_auth")

# In-memory user store (for simplicity — in production, use a DB table).
# In a real deployment, this would be a User model in the database.
_USERS: dict[str, dict] = {}
_SESSIONS: dict[str, str] = {}  # token -> username


def _hash_password(password: str) -> str:
    """Hash a password with a salt (simple HMAC — use bcrypt in production)."""
    import os
    salt = "phoenix_salt_v1"
    return hmac.new(salt.encode(), password.encode(), hashlib.sha256).hexdigest()


def create_user(username: str, password: str, role: str = "editor") -> dict:
    """Create a new user account.

    Roles:
      - admin: full access (create/delete users, manage channels, produce videos)
      - editor: produce + edit videos, view analytics
      - writer: write + edit scripts only
      - reviewer: view videos + comment only
    """
    if username in _USERS:
        return {"created": False, "reason": "username already exists"}
    if role not in ("admin", "editor", "writer", "reviewer"):
        return {"created": False, "reason": f"invalid role: {role}"}
    _USERS[username] = {
        "username": username,
        "password_hash": _hash_password(password),
        "role": role,
        "created_at": datetime.utcnow().isoformat(),
    }
    log.info("user created: %s (role=%s)", username, role)
    return {"created": True, "username": username, "role": role}


def authenticate(username: str, password: str) -> dict:
    """Authenticate a user and return a JWT-like token."""
    user = _USERS.get(username)
    if not user or user["password_hash"] != _hash_password(password):
        return {"authenticated": False, "reason": "invalid credentials"}
    # Generate a simple token (in production, use PyJWT).
    token = _generate_token(username)
    _SESSIONS[token] = username
    return {"authenticated": True, "token": token,
            "username": username, "role": user["role"]}


def _generate_token(username: str) -> str:
    """Generate a simple signed token."""
    payload = {"username": username, "exp": int(time.time()) + 86400}
    raw = json.dumps(payload)
    sig = hmac.new(settings.secret_key.encode(), raw.encode(),
                   hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def verify_token(token: str) -> dict | None:
    """Verify a token and return the user info, or None if invalid."""
    if token not in _SESSIONS:
        return None
    username = _SESSIONS[token]
    user = _USERS.get(username)
    if not user:
        return None
    return {"username": username, "role": user["role"]}


def check_permission(token: str, action: str) -> bool:
    """Check if the user's role allows the given action.

    Actions:
      - produce_video: admin, editor
      - edit_script: admin, editor, writer
      - delete_video: admin
      - view_analytics: admin, editor, reviewer
      - manage_users: admin
      - manage_channels: admin
    """
    user = verify_token(token)
    if not user:
        return False
    role = user["role"]
    permissions = {
        "admin": {"produce_video", "edit_script", "delete_video",
                   "view_analytics", "manage_users", "manage_channels"},
        "editor": {"produce_video", "edit_script", "view_analytics"},
        "writer": {"edit_script"},
        "reviewer": {"view_analytics"},
    }
    return action in permissions.get(role, set())


def list_users() -> list[dict]:
    """List all users (admin only — check in the route)."""
    return [{"username": u["username"], "role": u["role"],
             "created_at": u["created_at"]}
            for u in _USERS.values()]


def delete_user(username: str) -> dict:
    """Delete a user account."""
    if username not in _USERS:
        return {"deleted": False, "reason": "user not found"}
    del _USERS[username]
    # Clean up sessions.
    _SESSIONS.pop(username, None)
    return {"deleted": True, "username": username}


# ----------------------------------------------------- team chat (WebSocket)

# In-memory chat store: {video_id: [{username, message, timestamp}]}
_CHAT_STORE: dict[int, list[dict]] = {}
# Connected WebSocket clients per video: {video_id: set[WebSocket]}
_CHAT_CLIENTS: dict[int, set] = {}


def add_chat_message(video_id: int, username: str, message: str,
                     timestamp_sec: float | None = None) -> dict:
    """Add a chat message to a video's chat room."""
    msg = {
        "username": username,
        "message": message,
        "timestamp_sec": timestamp_sec,
        "sent_at": datetime.utcnow().isoformat(),
    }
    if video_id not in _CHAT_STORE:
        _CHAT_STORE[video_id] = []
    _CHAT_STORE[video_id].append(msg)
    # Notify connected clients.
    import asyncio
    for ws in _CHAT_CLIENTS.get(video_id, set()):
        try:
            asyncio.create_task(ws.send_json(msg))
        except Exception:
            pass
    return msg


def get_chat_history(video_id: int, limit: int = 50) -> list[dict]:
    """Get chat history for a video."""
    history = _CHAT_STORE.get(video_id, [])
    return history[-limit:]


def register_chat_client(video_id: int, websocket) -> None:
    """Register a WebSocket client for a video's chat room."""
    if video_id not in _CHAT_CLIENTS:
        _CHAT_CLIENTS[video_id] = set()
    _CHAT_CLIENTS[video_id].add(websocket)


def unregister_chat_client(video_id: int, websocket) -> None:
    """Unregister a WebSocket client."""
    if video_id in _CHAT_CLIENTS:
        _CHAT_CLIENTS[video_id].discard(websocket)
