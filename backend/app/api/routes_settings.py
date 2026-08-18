"""Settings & capability view (keys always masked) + editable settings."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..schemas import SettingsUpdate
from ..services import health
from ..services.voice import VOICE_MAP

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings_view():
    h = health.api_health()
    return {
        "app": {
            "channel_name": settings.channel_name,
            "channel_niche": settings.channel_niche,
            "channel_language": settings.channel_language,
            "videos_per_day": settings.videos_per_day,
            "video_target_seconds": settings.video_target_seconds,
            "video_resolution": settings.video_resolution,
            "video_aspect": settings.video_aspect,
            "resolution_label": settings.resolution_label,
            "video_privacy": settings.video_privacy,
            "show_captions": settings.show_captions,
            "show_watermark": settings.show_watermark,
            "show_subscribe_endcard": settings.show_subscribe_endcard,
            "show_subscribe_badge": settings.show_subscribe_badge,
            "use_intro": settings.use_intro,
            "use_outro": settings.use_outro,
            "default_categories": settings.default_categories,
            "youtube_dry_run": settings.youtube_dry_run,
            "youtube_category_id": settings.youtube_category_id,
            "youtube_secrets_exist": settings.youtube_secrets_exist,
            "tts_voice": settings.tts_voice,
            "tts_rate": settings.tts_rate,
            "urdu_tts_rate": settings.urdu_tts_rate,
            "tts_pitch": settings.tts_pitch,
            "duration_tolerance_seconds": settings.duration_tolerance_seconds,
            "duration_tolerance_ratio": settings.duration_tolerance_ratio,
            # v1.3 production-mode settings
            "video_length_mode": settings.video_length_mode,
            "cinematic_mode": settings.cinematic_mode,
            "seo_language": settings.seo_language,
            "hide_hooks_in_description": settings.hide_hooks_in_description,
            # v1.3 monitor settings
            "monitor_min_views": settings.monitor_min_views,
            "monitor_daily_quota": settings.monitor_daily_quota,
            "monitor_region_code": settings.monitor_region_code,
            "monitor_learn_from_top_videos": settings.monitor_learn_from_top_videos,
            # v1.3 copyright safety
            "copyright_check_enabled": settings.copyright_check_enabled,
            "copyright_wait_seconds": settings.copyright_wait_seconds,
            "auto_publish_after_check": settings.auto_publish_after_check,
            "post_check_privacy": settings.post_check_privacy,
            # v1.3 scheduling
            "scheduler_auto_trigger": settings.scheduler_auto_trigger,
            # v1.4 monetization
            "pre_upload_copyright_check": settings.pre_upload_copyright_check,
            "copyright_score_threshold": settings.copyright_score_threshold,
            "thumbnail_variant_count": settings.thumbnail_variant_count,
            "thumbnail_ctr_prediction": settings.thumbnail_ctr_prediction,
            "hook_analyzer_enabled": settings.hook_analyzer_enabled,
            "upload_time_ai_enabled": settings.upload_time_ai_enabled,
            "shorts_auto_clip": settings.shorts_auto_clip,
            "shorts_per_long": settings.shorts_per_long,
            "shorts_min_duration": settings.shorts_min_duration,
            "shorts_max_duration": settings.shorts_max_duration,
            # v1.4 API availability (read-only — set keys in .env)
            "acoustid_available": settings.acoustid_available,
            "huggingface_available": settings.huggingface_available,
            "amazon_affiliate_available": settings.amazon_affiliate_available,
            "reddit_available": settings.reddit_available,
            "news_available": settings.news_available,
            # v1.6 Mock/Real toggles
            "force_mock_llm": settings.force_mock_llm,
            "force_mock_pexels": settings.force_mock_pexels,
            "force_mock_pixabay": settings.force_mock_pixabay,
            "force_mock_jamendo": settings.force_mock_jamendo,
            "force_mock_youtube": settings.force_mock_youtube,
            "force_mock_acoustid": settings.force_mock_acoustid,
            "force_mock_huggingface": settings.force_mock_huggingface,
            "force_mock_amazon": settings.force_mock_amazon,
            "force_mock_reddit": settings.force_mock_reddit,
            "force_mock_news": settings.force_mock_news,
            # v1.6 chromaprint status
            "fpcalc_path": settings.fpcalc_path,
            "fpcalc_available": __import__("app.services.copyright_check",
                                            fromlist=["fpcalc_available"]).fpcalc_available(),
            "credential_type": __import__("app.services.uploader",
                                           fromlist=["detect_credential_type"]).detect_credential_type(),
            # Reliability and truthful-data controls
            "openrouter_model": settings.openrouter_model,
            "openrouter_fallback_models": settings.openrouter_fallback_models,
            "llm_request_timeout_seconds": settings.llm_request_timeout_seconds,
            "llm_max_retries": settings.llm_max_retries,
            "llm_retry_backoff_seconds": settings.llm_retry_backoff_seconds,
            "allow_simulated_metrics": settings.allow_simulated_metrics,
            "approval_required": settings.approval_required,
            "notifications_enabled": settings.notifications_enabled,
            "backup_retention_days": settings.backup_retention_days,
            "youtube_daily_quota_units": settings.youtube_daily_quota_units,
        },
        "options": {
            "resolutions": ["480p", "720p", "1080p", "1440p", "4k"],
            "aspects": ["landscape", "square", "portrait"],
            "voices": list(VOICE_MAP.keys()),
            "languages": [
                {"code": "en", "label": "English"},
                {"code": "en-gb", "label": "English (UK)"},
                {"code": "ur", "label": "Urdu / اردو"},
                {"code": "hi", "label": "Hindi / हिंदी"},
                {"code": "es", "label": "Spanish / Español"},
                {"code": "ar", "label": "Arabic / العربية"},
                {"code": "de", "label": "German / Deutsch"},
                {"code": "fr", "label": "French / Français"},
                {"code": "pt", "label": "Portuguese / Português"},
                {"code": "tr", "label": "Turkish / Türkçe"},
                {"code": "ru", "label": "Russian / Русский"},
                {"code": "id", "label": "Indonesian"},
                {"code": "ja", "label": "Japanese / 日本語"},
                {"code": "ko", "label": "Korean / 한국어"},
                {"code": "zh", "label": "Chinese / 中文"},
                {"code": "fa", "label": "Persian / فارسی"},
            ],
            "niches": ["technology", "finance", "health", "space",
                       "history", "science", "education", "entertainment",
                       "gaming", "lifestyle", "news", "music",
                       "travel", "food", "fitness", "sports",
                       "automotive", "diy", "art", "business",
                       "psychology", "philosophy", "politics", "fashion"],
            "privacy": ["private", "unlisted", "public"],
            "length_modes": [
                {"value": "manual", "label": "Manual — use exact target seconds"},
                {"value": "shorts", "label": "Shorts — random 30s–3min (portrait)"},
                {"value": "long", "label": "Long — random 3–10min (landscape)"},
            ],
            "regions": ["US", "GB", "IN", "PK", "AE", "CA", "AU", "DE", "FR",
                        "BR", "JP", "KR", "ID", "TR", "SA"],
        },
        "capabilities": h["services"],
        "keys_masked": h["keys"],
        "ffmpeg": h["ffmpeg"],
        "voices": VOICE_MAP,
        "note": ("Settings are saved to the .env file and applied instantly. "
                 "API keys are never exposed through this API — edit them "
                 "directly in the .env file or use the API key field below."),
    }


@router.post("")
def update_settings_view(body: SettingsUpdate):
    """Persist setting updates to .env + the in-memory Settings object."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "no settings to update")
    applied = settings.apply_updates(updates)
    if not applied:
        raise HTTPException(400, "no recognised settings in payload")
    return {"applied": applied, "count": len(applied)}


@router.get("/oauth-redirect")
def oauth_redirect_info():
    """Tell the dashboard what redirect URI to register in Google Cloud."""
    return {
        "redirect_uri": settings.oauth_redirect_uri,
        "instructions": (
            "Add this exact URI to your Google Cloud Console OAuth client's "
            "'Authorized redirect URIs' list."
        ),
    }
