"""Best upload time AI.

Uses the channel's historical analytics to find the best 3 publish hours
per weekday. The "best" hour is the one where the channel's videos have
historically received the highest first-24-hour views.

Data sources:
  1. AnalyticsSnapshot table (per-video views captured over time)
  2. Video.published_at + first-snapshot views
  3. StrategyProfile.publish_hours (fallback when not enough data)

Falls back gracefully:
  - < 5 videos: use the strategy profile's publish_hours
  - no strategy profile: use [13, 17, 21] (afternoon/evening defaults)

Returns a dict per weekday:
  {
    "0": [{"hour": 13, "score": 0.9, "videos": 3}, ...],  # Monday
    "1": [...],                                            # Tuesday
    ...
    "6": [...],                                            # Sunday
  }
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from ..core.logging import get_logger
from ..database import session_scope
from ..models import AnalyticsSnapshot, StrategyProfile, Video

log = get_logger("upload_time_ai")

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday"]

DEFAULT_HOURS = [13, 17, 21]


def suggest_best_hours(channel_id: int, top_n: int = 3) -> dict:
    """Return the top-N best publish hours per weekday for a channel.

    Returns:
      {
        "weekdays": {
          "0": [{"hour": 13, "score": 0.92, "videos": 3, "avg_views": 1500}],
          ...
        },
        "overall_best": [{"hour": 17, "score": 0.95, "reason": "..."}],
        "source": "analytics" | "strategy" | "default",
        "data_points": int,
      }
    """
    with session_scope() as db:
        # Pull every published video with its first-snapshot views.
        rows = (db.query(Video, AnalyticsSnapshot)
                .join(AnalyticsSnapshot, AnalyticsSnapshot.video_id == Video.id)
                .filter(Video.channel_id == channel_id,
                        Video.published_at.isnot(None))
                .order_by(AnalyticsSnapshot.captured_at)
                .all())

        # Group first-snapshot views by (weekday, hour).
        per_slot: dict[tuple[int, int], list[int]] = defaultdict(list)
        for v, snap in rows:
            if not v.published_at or snap.views is None:
                continue
            wd = v.published_at.weekday()
            hr = v.published_at.hour
            per_slot[(wd, hr)].append(snap.views)

        strategy = (db.query(StrategyProfile)
                    .filter_by(channel_id=channel_id).first())

    if sum(len(v) for v in per_slot.values()) >= 5:
        # Enough data — compute average views per (weekday, hour) slot,
        # then rank hours within each weekday.
        per_weekday: dict[int, list[dict]] = defaultdict(list)
        for (wd, hr), views_list in per_slot.items():
            avg = sum(views_list) / len(views_list)
            per_weekday[wd].append({
                "hour": hr,
                "score": round(min(avg / 5000.0, 1.0), 2),  # normalize
                "videos": len(views_list),
                "avg_views": int(avg),
            })
        for wd in per_weekday:
            per_weekday[wd].sort(key=lambda x: x["score"], reverse=True)
            per_weekday[wd] = per_weekday[wd][:top_n]
        # Fill missing weekdays with the overall best.
        all_scores = sorted(
            ({x["hour"], x["score"]} for slots in per_weekday.values() for x in slots),
            key=lambda d: d["score"], reverse=True
        ) if False else []
        overall_best = []
        for wd in range(7):
            if wd in per_weekday and per_weekday[wd]:
                overall_best.append({
                    "weekday": WEEKDAY_NAMES[wd],
                    "hour": per_weekday[wd][0]["hour"],
                    "score": per_weekday[wd][0]["score"],
                })
        return {
            "weekdays": {str(wd): per_weekday.get(wd, []) for wd in range(7)},
            "overall_best": overall_best,
            "source": "analytics",
            "data_points": sum(len(v) for v in per_slot.values()),
        }

    # Fall back to the strategy profile.
    if strategy and strategy.publish_hours:
        hours = strategy.publish_hours[:top_n]
        return {
            "weekdays": {str(wd): [{"hour": h, "score": 1.0, "videos": 0,
                                     "avg_views": 0, "reason": "channel learning"}
                                    for h in hours] for wd in range(7)},
            "overall_best": [{"weekday": WEEKDAY_NAMES[wd],
                              "hour": hours[0] if hours else 13,
                              "score": 1.0} for wd in range(7)],
            "source": "strategy",
            "data_points": sum(len(v) for v in per_slot.values()),
        }

    # Last-resort defaults.
    return {
        "weekdays": {str(wd): [{"hour": h, "score": 1.0, "videos": 0,
                                 "avg_views": 0, "reason": "default"}
                                for h in DEFAULT_HOURS[:top_n]]
                     for wd in range(7)},
        "overall_best": [{"weekday": WEEKDAY_NAMES[wd], "hour": 13, "score": 1.0}
                         for wd in range(7)],
        "source": "default",
        "data_points": 0,
    }


def suggest_next_upload_time(channel_id: int, now: datetime | None = None) -> dict:
    """Suggest the single best next upload time given the current time.

    Returns:
      {
        "hour": int,
        "weekday": str,
        "score": float,
        "source": str,
        "reasoning": str,
      }
    """
    now = now or datetime.utcnow()
    data = suggest_best_hours(channel_id, top_n=3)
    today_wd = now.weekday()
    today_slots = data["weekdays"].get(str(today_wd), [])
    if not today_slots:
        return {
            "hour": 13, "weekday": WEEKDAY_NAMES[today_wd], "score": 0.5,
            "source": data["source"],
            "reasoning": "no data — using afternoon default",
        }
    best = today_slots[0]
    return {
        "hour": best["hour"],
        "weekday": WEEKDAY_NAMES[today_wd],
        "score": best.get("score", 0.5),
        "source": data["source"],
        "reasoning": (
            f"based on {data['data_points']} published videos — "
            f"avg first-snapshot views in this slot: {best.get('avg_views', 'n/a')}"
        ),
    }
