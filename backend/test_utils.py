"""Small helpers shared by the integration scripts."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def collect_route_paths(routes: Iterable[Any]) -> list[str]:
    """Return paths from regular and nested FastAPI/Starlette route objects.

    FastAPI versions can expose included routers as private wrapper objects
    without a direct ``path`` attribute. The public route objects are still
    available through ``original_router.routes``; walking both shapes keeps the
    integration checks framework-version-safe.
    """
    paths: list[str] = []
    seen: set[int] = set()

    def walk(items: Iterable[Any]) -> None:
        for route in items:
            identity = id(route)
            if identity in seen:
                continue
            seen.add(identity)

            path = getattr(route, "path", None)
            if isinstance(path, str):
                paths.append(path)
                continue

            nested = getattr(route, "routes", None)
            if nested is None:
                original = getattr(route, "original_router", None)
                nested = getattr(original, "routes", None)
            if nested:
                walk(nested)

    walk(routes)
    return paths
