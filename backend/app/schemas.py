"""Pydantic schemas for API requests/responses."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    niche: str = "technology"
    language: str = "en"
    videos_per_day: int = Field(default=3, ge=1, le=10)
    privacy: str = "private"


class ChannelUpdate(BaseModel):
    name: str | None = None
    niche: str | None = None
    language: str | None = None
    videos_per_day: int | None = Field(default=None, ge=1, le=10)
    privacy: str | None = None
    active: bool | None = None


class ChannelOut(BaseModel):
    id: int
    name: str
    niche: str
    language: str
    videos_per_day: int
    yt_channel_id: str | None
    yt_subscriber_count: int | None = None
    yt_video_count: int | None = None
    yt_view_count: int | None = None
    yt_thumbnail: str | None = None
    yt_country: str | None = None
    yt_stats_fetched_at: datetime | None = None
    privacy: str
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class VideoOut(BaseModel):
    id: int
    channel_id: int
    topic: str
    niche: str
    title: str
    status: str
    review_status: str = "pending"
    review_notes: str = ""
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    language: str
    duration_seconds: float
    yt_video_id: str | None
    thumbnail_path: str | None
    file_path: str | None = None
    scheduled_at: datetime | None
    published_at: datetime | None
    error: str | None
    attempts: int
    created_at: datetime
    tags: list = []
    hashtags: list = []
    categories: list = []
    # v1.4 monetization fields
    hook_score: int | None = None
    copyright_check_passed: bool | None = None
    copyright_check_score: float | None = None
    predicted_ctr: int | None = None
    parent_video_id: int | None = None
    is_short: bool = False

    class Config:
        from_attributes = True


class VideoDetail(VideoOut):
    description: str = ""
    script_json: dict = {}
    seo_json: dict = {}
    thumbnail_variants: list = []
    file_path: str | None = None
    show_captions: bool | None = None
    show_watermark: bool | None = None
    show_subscribe_endcard: bool | None = None
    show_subscribe_badge: bool | None = None
    copyright_check_meta: dict = {}


class ProduceRequest(BaseModel):
    channel_id: int
    topic: str | None = None
    publish: bool = True
    scheduled_at: datetime | None = None
    target_seconds: int | None = None
    resolution: str | None = None       # 480p | 720p | 1080p | 1440p | 4k
    aspect: str | None = None           # landscape | square | portrait (Shorts)
    categories: list[str] | None = None # niche filter for topic discovery
    language: str | None = None         # override channel language for this video
    show_captions: bool | None = None
    show_watermark: bool | None = None
    show_subscribe_endcard: bool | None = None
    show_subscribe_badge: bool | None = None
    youtube_category_id: str | None = None
    # v1.3: length mode — 'manual' | 'shorts' | 'long'. When set, overrides
    # target_seconds with a random value in the right band.
    length_mode: str | None = None
    # v1.4: clip Shorts from a long video after it renders.
    clip_shorts: bool | None = None
    # v1.7: manual scene count override (default: auto from target_seconds)
    scene_count: int | None = Field(default=None, ge=3, le=12)
    # v1.8: content type — explainer|tutorial|listicle|news|review|comparison|myth_busting|q_and_a|vlog
    content_type: str | None = None


class SettingsUpdate(BaseModel):
    """Partial settings update sent from the Settings page."""
    channel_name: str | None = None
    channel_niche: str | None = None
    channel_language: str | None = None
    videos_per_day: int | None = Field(default=None, ge=1, le=10)
    video_target_seconds: int | None = Field(default=None, ge=15, le=3600)
    video_resolution: str | None = None
    video_aspect: str | None = None
    video_privacy: str | None = None
    show_captions: bool | None = None
    show_watermark: bool | None = None
    show_subscribe_endcard: bool | None = None
    show_subscribe_badge: bool | None = None
    use_intro: bool | None = None
    use_outro: bool | None = None
    default_categories: str | None = None
    youtube_dry_run: bool | None = None
    youtube_category_id: str | None = None
    tts_voice: str | None = None
    tts_rate: str | None = None
    tts_pitch: str | None = None
    # v1.3 additions
    video_length_mode: str | None = None
    cinematic_mode: bool | None = None
    seo_language: str | None = None
    hide_hooks_in_description: bool | None = None
    monitor_min_views: int | None = Field(default=None, ge=0)
    monitor_daily_quota: int | None = Field(default=None, ge=1, le=500)
    monitor_region_code: str | None = None
    monitor_learn_from_top_videos: bool | None = None
    copyright_check_enabled: bool | None = None
    copyright_wait_seconds: int | None = Field(default=None, ge=30, le=3600)
    auto_publish_after_check: bool | None = None
    post_check_privacy: str | None = None
    scheduler_auto_trigger: bool | None = None
    # v1.4 additions
    pre_upload_copyright_check: bool | None = None
    copyright_score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    thumbnail_variant_count: int | None = Field(default=None, ge=1, le=10)
    thumbnail_ctr_prediction: bool | None = None
    hook_analyzer_enabled: bool | None = None
    upload_time_ai_enabled: bool | None = None
    shorts_auto_clip: bool | None = None
    shorts_per_long: int | None = Field(default=None, ge=0, le=10)
    shorts_min_duration: int | None = Field(default=None, ge=5, le=180)
    shorts_max_duration: int | None = Field(default=None, ge=10, le=180)
    # v1.6 mock/real toggles
    force_mock_llm: bool | None = None
    force_mock_pexels: bool | None = None
    force_mock_pixabay: bool | None = None
    force_mock_jamendo: bool | None = None
    force_mock_youtube: bool | None = None
    force_mock_acoustid: bool | None = None
    force_mock_huggingface: bool | None = None
    force_mock_amazon: bool | None = None
    force_mock_reddit: bool | None = None
    force_mock_news: bool | None = None
    fpcalc_path: str | None = None
    # LLM reliability and truthful analytics controls
    openrouter_fallback_models: str | None = None
    llm_request_timeout_seconds: float | None = Field(default=None, ge=5.0, le=300.0)
    llm_max_retries: int | None = Field(default=None, ge=0, le=5)
    llm_retry_backoff_seconds: float | None = Field(default=None, ge=0.1, le=10.0)
    allow_simulated_metrics: bool | None = None
    approval_required: bool | None = None
    notifications_enabled: bool | None = None
    backup_retention_days: int | None = Field(default=None, ge=1, le=365)
    youtube_daily_quota_units: int | None = Field(default=None, ge=1000, le=100000)


class ScheduledSlotCreate(BaseModel):
    """Create a scheduled production slot."""
    channel_id: int
    hour: int = Field(ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    categories: list[str] = Field(default_factory=list)
    length_mode: str = "manual"  # manual | shorts | long
    target_seconds: int | None = None
    aspect: str | None = None
    language: str | None = None
    youtube_category_id: str | None = None
    enabled: bool = True


class ScheduledSlotUpdate(BaseModel):
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)
    categories: list[str] | None = None
    length_mode: str | None = None
    target_seconds: int | None = None
    aspect: str | None = None
    language: str | None = None
    youtube_category_id: str | None = None
    enabled: bool | None = None


class ScheduledSlotOut(BaseModel):
    id: int
    channel_id: int
    hour: int
    minute: int
    categories: list
    length_mode: str
    target_seconds: int | None
    aspect: str | None
    language: str | None
    youtube_category_id: str | None
    enabled: bool
    last_fired_at: datetime | None
    last_video_id: int | None
    created_at: datetime

    class Config:
        from_attributes = True


class MonitorSearchRequest(BaseModel):
    """Search YouTube for top videos in a niche."""
    channel_id: int
    query: str | None = None       # free-text; overrides niche if given
    niches: list[str] = Field(default_factory=list)
    region_code: str | None = None
    min_views: int | None = None
    max_results: int = Field(default=20, ge=1, le=50)
    learn: bool = True              # extract insights from the top results


class TrendingVideoOut(BaseModel):
    id: int
    yt_video_id: str
    title: str
    niche: str
    channel_title: str
    view_count: int
    like_count: int
    comment_count: int
    duration_seconds: float
    published_at: datetime | None
    tags: list
    thumbnail: str | None
    region: str
    fetched_at: datetime

    class Config:
        from_attributes = True


class LearnedInsightOut(BaseModel):
    id: int
    niche: str
    insight_type: str
    content: str
    meta: dict
    source_video_id: str | None
    score: float
    created_at: datetime

    class Config:
        from_attributes = True


class JobOut(BaseModel):
    id: int
    type: str
    status: str
    attempts: int
    max_attempts: int
    run_at: datetime
    last_error: str | None
    payload: dict
    created_at: datetime

    class Config:
        from_attributes = True


class LogOut(BaseModel):
    id: int
    ts: datetime
    level: str
    source: str
    message: str

    class Config:
        from_attributes = True


class OAuthStartResponse(BaseModel):
    auth_url: str
    state: str
    channel_id: int
    redirect_uri: str


class YouTubeCategory(BaseModel):
    id: str
    title: str
    assignable: bool = True
