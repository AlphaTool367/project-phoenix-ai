"""All SQLAlchemy models for Project Phoenix AI."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    niche: Mapped[str] = mapped_column(String(80), default="technology")
    language: Mapped[str] = mapped_column(String(10), default="en")
    videos_per_day: Mapped[int] = mapped_column(Integer, default=3)
    yt_channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    privacy: Mapped[str] = mapped_column(String(16), default="private")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Cached YouTube stats — refreshed after OAuth + on demand.
    yt_subscriber_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yt_video_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yt_view_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yt_thumbnail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    yt_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    yt_country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    yt_stats_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    videos: Mapped[list["Video"]] = relationship(back_populates="channel")
    strategy: Mapped["StrategyProfile | None"] = relationship(back_populates="channel")


class Video(Base):
    """One video through the whole pipeline."""

    STATUSES = [
        "planned", "researching", "scripted", "voiced", "media_ready",
        "rendering", "rendered", "uploading", "checking", "published",
        "scheduled", "failed", "cancelled",
        "short_ready",   # v1.4: a Short has been clipped, awaiting upload
        "awaiting_review",  # Safety Pack: human approval required before publish
        "rejected",         # Safety Pack: review rejected the video
    ]

    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"))
    topic: Mapped[str] = mapped_column(String(255))
    niche: Mapped[str] = mapped_column(String(80), default="")
    title: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="planned", index=True)
    # Safety Pack approval workflow. ``pending`` is the safe default for videos
    # that are intended for publishing; dry-run/demo videos may remain neutral.
    review_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    review_notes: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en")

    script_json: Mapped[dict] = mapped_column(JSON, default=dict)
    seo_json: Mapped[dict] = mapped_column(JSON, default=dict)
    strategy_context: Mapped[dict] = mapped_column(JSON, default=dict)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    # Per-video overrides (None = use global setting)
    show_captions: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    show_watermark: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    show_subscribe_endcard: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    show_subscribe_badge: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # v1.4 monetization fields -------------------------------------------
    # Hook analysis (0-100 score + breakdown stored in seo_json.hook_analysis).
    hook_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Pre-upload copyright check result.
    copyright_check_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    copyright_check_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    copyright_check_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    # Predicted CTR for the active thumbnail (0-100).
    predicted_ctr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Parent video for Shorts clipped from a long video.
    parent_video_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    is_short: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    thumbnail_variants: Mapped[list] = mapped_column(JSON, default=list)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0)
    yt_video_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    channel: Mapped[Channel] = relationship(back_populates="videos")
    analytics: Mapped[list["AnalyticsSnapshot"]] = relationship(back_populates="video")


class TrendReport(Base):
    __tablename__ = "trend_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), nullable=True)
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    topics: Mapped[list] = mapped_column(JSON, default=list)   # scored topic list
    winning_niche: Mapped[str] = mapped_column(String(80), default="")
    source: Mapped[str] = mapped_column(String(160), default="template_fallback")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Asset(Base):
    """Downloaded / generated media files (clips, music, voice)."""

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(24))  # clip|voice|music|image
    provider: Mapped[str] = mapped_column(String(24), default="mock")
    query: Mapped[str] = mapped_column(String(255), default="")
    path: Mapped[str] = mapped_column(String(500))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id"), nullable=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    views: Mapped[int] = mapped_column(Integer, default=0)
    watch_minutes: Mapped[float] = mapped_column(Float, default=0)
    avg_view_duration: Mapped[float] = mapped_column(Float, default=0)
    retention_pct: Mapped[float] = mapped_column(Float, default=0)
    ctr_pct: Mapped[float] = mapped_column(Float, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    subs_gained: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(16), default="mock")

    video: Mapped[Video | None] = relationship(back_populates="analytics")


class StrategyProfile(Base):
    """Learned per-channel weights — the 'brain' of the self-learning loop."""

    __tablename__ = "strategy_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), unique=True)
    niche_weights: Mapped[dict] = mapped_column(JSON, default=dict)
    hook_weights: Mapped[dict] = mapped_column(JSON, default=dict)
    title_patterns: Mapped[dict] = mapped_column(JSON, default=dict)
    publish_hours: Mapped[list] = mapped_column(JSON, default=[13, 17, 21])
    insights: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    channel: Mapped[Channel] = relationship(back_populates="strategy")


class Job(Base):
    """Durable background job queue (retry + crash recovery)."""

    STATUSES = ["queued", "running", "done", "failed", "dead"]

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40), index=True)  # produce_video|upload|analytics...
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ActivityLog(Base):
    """Everything the AI does, streamed live to the dashboard."""

    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    source: Mapped[str] = mapped_column(String(32), default="system")
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict] = mapped_column(JSON, default=dict)


class ProviderUsage(Base):
    """One provider request's measured usage metadata.

    Token counts and cost are recorded only when the provider response reports
    them. Missing cost remains NULL/unknown rather than being estimated.
    """

    __tablename__ = "provider_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str] = mapped_column(String(32), index=True)
    model: Mapped[str] = mapped_column(String(160), default="")
    request_count: Mapped[int] = mapped_column(Integer, default=1)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reported_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_source: Mapped[str] = mapped_column(String(32), default="unknown")
    status: Mapped[str] = mapped_column(String(16), default="success")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class TrendingVideo(Base):
    """A top YouTube video discovered by the monitor — used to learn from.

    Stored once per (video_id, channel_id); the monitor refreshes the
    view_count / like_count periodically. Insights (extracted hooks / tags /
    description patterns) are kept in LearnedInsight rows that reference
    back to this row.
    """

    __tablename__ = "trending_videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), nullable=True, index=True)
    yt_video_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(500))
    niche: Mapped[str] = mapped_column(String(80), default="")
    channel_title: Mapped[str] = mapped_column(String(200), default="")
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    thumbnail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    region: Mapped[str] = mapped_column(String(8), default="US")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    analyzed: Mapped[bool] = mapped_column(Boolean, default=False)


class LearnedInsight(Base):
    """A pattern the monitor extracted from a trending video.

    Types: 'hook' (opening line style), 'tag_cluster' (group of related tags),
    'description_pattern' (structural pattern), 'title_pattern', 'thumbnail_style',
    'duration_band' (which length performs best in this niche).
    """

    __tablename__ = "learned_insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), nullable=True, index=True)
    niche: Mapped[str] = mapped_column(String(80), default="", index=True)
    insight_type: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    source_video_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)  # weighted by views
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ScheduledSlot(Base):
    """A user-defined production slot — fires automatically at the set time.

    Each slot specifies: channel, time (hour:minute), categories, length mode,
    target seconds, aspect, and an 'enabled' flag. The scheduler picks due
    slots and produces one video per slot per day.
    """

    __tablename__ = "scheduled_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    hour: Mapped[int] = mapped_column(Integer)         # 0-23 UTC
    minute: Mapped[int] = mapped_column(Integer, default=0)  # 0-59
    categories: Mapped[list] = mapped_column(JSON, default=list)
    length_mode: Mapped[str] = mapped_column(String(16), default="manual")
    target_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aspect: Mapped[str | None] = mapped_column(String(16), nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    youtube_category_id: Mapped[str | None] = mapped_column(String(8), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_video_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ----------------------------------------------------------------- v1.5 Phase 4

class CompetitorChannel(Base):
    """A competitor YouTube channel the user is tracking."""

    __tablename__ = "competitor_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    yt_channel_id: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(120), default="")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CompetitorVideo(Base):
    """A video from a competitor channel — cached for analysis."""

    __tablename__ = "competitor_videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitor_channels.id"), index=True)
    yt_video_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(500))
    channel_title: Mapped[str] = mapped_column(String(200), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ABTest(Base):
    """An A/B test for a video's title or thumbnail.

    status: 'running' / 'completed' / 'applied'
    winner_variant: index of the winning variant (or null if no winner)
    """

    __tablename__ = "ab_tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), index=True)
    test_type: Mapped[str] = mapped_column(String(16))  # 'title' | 'thumbnail'
    variants: Mapped[list] = mapped_column(JSON, default=list)  # [{text_or_path, predicted_ctr}]
    active_variant: Mapped[int] = mapped_column(Integer, default=0)
    winner_variant: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ends_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RevenueSnapshot(Base):
    """Daily revenue snapshot for a channel (real or estimated)."""

    __tablename__ = "revenue_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    period_days: Mapped[int] = mapped_column(Integer, default=30)
    total_revenue_usd: Mapped[float] = mapped_column(Float, default=0)
    ad_revenue_usd: Mapped[float] = mapped_column(Float, default=0)
    views: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    monetized_playbacks: Mapped[int] = mapped_column(Integer, default=0)
    rpm_usd: Mapped[float] = mapped_column(Float, default=0)
    cpm_usd: Mapped[float] = mapped_column(Float, default=0)
    monetized: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(24), default="estimated")


class BrandDeal(Base):
    """A brand sponsorship deal — from pitch to completion."""

    __tablename__ = "brand_deals"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    brand_name: Mapped[str] = mapped_column(String(200))
    product: Mapped[str] = mapped_column(String(300), default="")
    contact_email: Mapped[str] = mapped_column(String(200), default="")
    rate_usd: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pitched")  # pitched|negotiating|confirmed|completed|rejected
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class NotificationLog(Base):
    """Log of alerts sent (email, milestone, anomaly)."""

    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    notification_type: Mapped[str] = mapped_column(String(40))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
