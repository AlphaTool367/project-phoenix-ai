"""Central configuration.

Every setting comes from the environment / .env file. A service whose key is
missing automatically runs in MOCK MODE — the pipeline still works end-to-end.

Video resolution / aspect ratio:
  VIDEO_RESOLUTION supports 480p, 720p, 1080p, 1440p, 4k.
  VIDEO_ASPECT supports landscape (16:9), square (1:1), portrait (9:16) —
  this lets the user pick the output shape (YouTube long-form vs Shorts).

Visual toggles (set in .env or via the Settings page):
  SHOW_CAPTIONS            burn subtitles into the video (default true)
  SHOW_WATERMARK           overlay logo.png in the top-right corner (default false)
  SHOW_SUBSCRIBE_ENDCARD   show a subscribe call-to-action card at the end
                           (default false — green-screen subscribe bug fix)
  SHOW_SUBSCRIBE_BADGE     small persistent "Subscribe" pill in corner through
                           the whole video (default false)
  YOUTUBE_CATEGORY_ID      default YouTube category (default 27 = Education)
  DEFAULT_CATEGORIES       comma-separated niches used by the topic discovery
                           (default: technology,science,space)
"""
from __future__ import annotations

import os
import shutil
import time
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]  # project-phoenix-ai/

# Resolution -> (width, height)@landscape; aspect variants are derived.
_RESOLUTION_PRESETS: dict[str, tuple[int, int]] = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "4k": (3840, 2160),
}

# Aspect ratio multiplier (relative to base landscape dimensions).
_ASPECT_MULTIPLIERS: dict[str, tuple[float, float]] = {
    "landscape": (1.0, 1.0),   # 16:9
    "square": (1.0, 1.0),      # square is computed from height
    "portrait": (9 / 16, 1.0), # 9:16 (Shorts / TikTok / Reels)
}


# Allow override via env var (used when running outside the project dir).
_ENV_FILE = os.environ.get("PHOENIX_ENV_FILE")
if _ENV_FILE:
    _ENV_FILE_PATH = _ENV_FILE
else:
    _ENV_FILE_PATH = str(ROOT_DIR / ".env")


def merge_nonempty_env_file(source_path: str | Path, target_path: str | Path) -> tuple[list[str], str | None]:
    """Merge non-empty values from a user-provided .env without blank overwrites.

    This is intentionally conservative for uploaded/shared .env files: empty
    lines are ignored, at least one provider credential must be present, and a
    timestamped backup is made before the target is changed.
    """
    from dotenv import dotenv_values

    source = Path(source_path).expanduser().resolve()
    target = Path(target_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"source .env not found: {source}")

    values = dotenv_values(source)
    provider_keys = {
        "OPENROUTER_API_KEY", "GEMINI_API_KEY", "GROK_API_KEY",
        "PEXELS_API_KEY", "PIXABAY_API_KEY", "JAMENDO_CLIENT_ID",
    }
    cleaned = {
        str(key): str(value).strip()
        for key, value in values.items()
        if key and value is not None and str(value).strip()
    }
    if not any(key in cleaned for key in provider_keys):
        raise ValueError(
            "source .env contains no non-empty provider API key; refusing to overwrite configuration"
        )

    existing = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    positions: dict[str, int] = {}
    for index, line in enumerate(existing):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in cleaned:
            positions[key] = index

    for key, value in cleaned.items():
        new_line = f"{key}={value}"
        if key in positions:
            existing[positions[key]] = new_line
        else:
            existing.append(new_line)

    backup: str | None = None
    if target.exists():
        backup_path = target.with_name(f"{target.name}.backup-{int(time.time())}")
        shutil.copy2(target, backup_path)
        backup = str(backup_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    temp_path.write_text("\n".join(existing) + "\n", encoding="utf-8")
    os.replace(temp_path, target)
    return sorted(cleaned), backup


# Pre-load the project .env into the process environment so that values
# defined there take precedence over a parent .env file (e.g. when the
# project is run from inside another project that has its own .env).
def _preload_env() -> None:
    try:
        from dotenv import dotenv_values
        vals = dotenv_values(_ENV_FILE_PATH)
        for k, v in vals.items():
            if v is None:
                continue
            # v1.7: strip surrounding quotes + whitespace that users often
            # accidentally add when pasting API keys.
            cleaned = v.strip()
            if (cleaned.startswith('"') and cleaned.endswith('"')) or \
               (cleaned.startswith("'") and cleaned.endswith("'")):
                cleaned = cleaned[1:-1].strip()
            # Force-set so our project .env wins over inherited env vars.
            os.environ[k] = cleaned
    except Exception:
        pass  # missing dotenv or .env -> fall back to defaults


_preload_env()


# ----------------------------------------------------------------- env writer
def _coerce_str(v) -> str:
    """Coerce any python value to an .env-safe string."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v)
    return str(v)


def _update_env_file(updates: dict[str, object]) -> None:
    """Persist a set of key/value pairs back into the project .env file.

    Preserves comments and ordering; only changes the lines whose key matches.
    Adds new keys at the end if they don't exist yet.
    """
    env_path = Path(_ENV_FILE_PATH)
    try:
        existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    except Exception:
        existing = ""

    lines = existing.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    pending_newline = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={_coerce_str(updates[key])}")
                seen.add(key)
                continue
        out.append(line)

    # Append any keys that didn't already exist in the file.
    if seen != set(updates.keys()):
        if out and out[-1].strip():
            out.append("")
        out.append("# ---- updated via Settings page ----")
        for k, v in updates.items():
            if k not in seen:
                out.append(f"{k}={_coerce_str(v)}")

    try:
        env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    except Exception:
        pass  # read-only filesystems etc — silently ignore


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE_PATH, env_file_encoding="utf-8", extra="ignore"
    )

    # ---- LLM providers ----
    openrouter_api_key: str = ""
    # Default to a cheap, capable model — avoids the 402 "more credits" error.
    openrouter_model: str = "meta-llama/llama-3.1-8b-instruct"
    gemini_api_key: str = ""
    # gemini-2.0-flash is the current free-tier model (1.5-flash was deprecated).
    gemini_model: str = "gemini-2.0-flash"
    grok_api_key: str = ""
    # grok-2-latest is the correct model name (grok-beta / "grok 2.0" are invalid).
    grok_model: str = "grok-2-latest"
    # Comma-separated OpenRouter model fallbacks tried after the primary model.
    openrouter_fallback_models: str = ""
    # Provider request controls. Retries are only used for transient failures.
    llm_request_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_retry_backoff_seconds: float = 1.5

    # ---- Stock media ----
    pexels_api_key: str = ""
    pixabay_api_key: str = ""

    # ---- Music ----
    jamendo_client_id: str = ""

    # ---- v1.4 Copyright / AI / Affiliate APIs --------------------------------
    # AcoustID: pre-upload audio fingerprint matching (free, 3 req/sec).
    #   https://acoustid.org/api
    acoustid_api_key: str = ""
    # Path to fpcalc.exe (chromaprint). On Windows, download from
    # https://acoustid.org/chromaprint and set this to the full path.
    # Leave empty to auto-detect from PATH.
    fpcalc_path: str = ""
    # Hugging Face: free ML models (thumbnail CTR prediction, sentiment, etc.).
    #   https://huggingface.co/settings/tokens
    huggingface_token: str = ""
    # Amazon Associates + Product Advertising API (affiliate link auto-insert).
    #   https://affiliate-program.amazon.com/
    amazon_affiliate_tag: str = ""
    amazon_pa_api_key: str = ""
    amazon_pa_secret: str = ""
    amazon_pa_host: str = "webservices.amazon.com"  # or your locale host
    amazon_pa_region: str = "us-east-1"
    # Reddit API (free, 60 req/min) — used for trend discovery.
    #   https://www.reddit.com/prefs/apps
    reddit_client_id: str = ""
    reddit_secret: str = ""
    reddit_user_agent: str = "ProjectPhoenixAI/1.4"
    # NewsAPI.org (free, 100 req/day) — used for breaking-news topic discovery.
    news_api_key: str = ""

    # ---- v1.6 Mock/Real toggles (override auto-detection) -------------------
    # When True, the API is FORCED into mock mode even if the key is set.
    # When False (default), the API auto-detects based on key presence.
    force_mock_llm: bool = False
    force_mock_pexels: bool = False
    force_mock_pixabay: bool = False
    force_mock_jamendo: bool = False
    force_mock_youtube: bool = False
    force_mock_acoustid: bool = False
    force_mock_huggingface: bool = False
    force_mock_amazon: bool = False
    force_mock_reddit: bool = False
    force_mock_news: bool = False

    # ---- YouTube ----
    google_client_secrets_file: str = "secrets/client_secret.json"
    youtube_token_dir: str = "data/tokens"
    youtube_dry_run: bool = True
    youtube_category_id: str = "27"  # Education
    # OAuth redirect URL the browser uses after Google consent.
    # Defaults to the local dev server; override for production.
    oauth_redirect_uri: str = "http://localhost:8000/api/oauth/callback"
    # Local Remix speech-to-text model. `tiny` is quickest; `base` is more accurate.
    whisper_model: str = "base"

    # ---- Channel defaults ----
    channel_name: str = "Project Phoenix"
    channel_niche: str = "technology"
    channel_language: str = "en"
    videos_per_day: int = 3
    video_target_seconds: int = 150
    video_resolution: str = "1080p"  # 480p | 720p | 1080p | 1440p | 4k
    video_aspect: str = "landscape"   # landscape | square | portrait
    video_privacy: str = "private"

    # ---- Visual toggles (the fixes the user asked for) ----
    show_captions: bool = True           # subtitles burned in
    show_watermark: bool = False         # logo.png overlay
    show_subscribe_endcard: bool = False # big end-of-video subscribe card
    show_subscribe_badge: bool = False   # small persistent subscribe pill
    use_intro: bool = False              # prepend assets/intro.mp4 if it exists
    use_outro: bool = False              # append assets/outro.mp4 if it exists
    default_categories: str = "technology,science,space"

    # ---- v1.3 production mode -----------------------------------------
    # video_length_mode: 'manual' = use video_target_seconds as-is
    #                   'shorts'  = random 30s-180s (YouTube Shorts / Reels)
    #                   'long'    = random 180s-600s (long-form)
    video_length_mode: str = "manual"
    # Cinematic mode: stronger color grading, slower zooms, longer crossfades,
    # letterbox bars on landscape, dramatic music ducking.
    cinematic_mode: bool = True
    # SEO language: descriptions / tags are ALWAYS written in this language
    # regardless of the video's narration language. English maximises reach.
    seo_language: str = "en"
    # Hide hooks in description: when True, the description tells viewers what
    # the video is about WITHOUT restating the hook line — so competitors can't
    # reverse-engineer the retention hook from the description.
    hide_hooks_in_description: bool = True

    # ---- v1.3 YouTube monitor -----------------------------------------
    # Minimum view count for a video to be considered "winning" by the
    # monitor. The monitor searches YouTube for top videos in the channel's
    # niches and learns from those above this threshold.
    monitor_min_views: int = 2_000_000
    # How many top videos the monitor analyzes per niche per day.
    monitor_daily_quota: int = 50
    # Region code for YouTube trending searches (ISO 3166-1 alpha-2).
    monitor_region_code: str = "US"
    # When True, the monitor also fetches each top video's tags / description
    # and stores them as LearnedInsight rows for the learning loop.
    monitor_learn_from_top_videos: bool = True

    # ---- v1.3 upload safety -------------------------------------------
    # When True: videos upload as 'unlisted', wait copyright_wait_seconds,
    # then check for copyright claims via the Data API. If a claim exists,
    # the video is deleted automatically. If clean, it's switched to the
    # channel's privacy setting (private/unlisted/public).
    copyright_check_enabled: bool = True
    copyright_wait_seconds: int = 150   # 2.5 minutes — lets YouTube process
    auto_publish_after_check: bool = True
    # Final privacy status after copyright check passes.
    post_check_privacy: str = "unlisted"

    # ---- v1.3 scheduling ----------------------------------------------
    # When True, the scheduler auto-fires scheduled slots at their time.
    # When False, slots are queued but a manual button must trigger them.
    scheduler_auto_trigger: bool = True

    # ---- v1.4 monetization features -----------------------------------
    # Pre-upload copyright check via AcoustID. Fingerprint the rendered
    # audio and look it up before uploading. If a match with a high score
    # is found, the video is flagged so the user can swap the music.
    pre_upload_copyright_check: bool = True
    # Score threshold (0-1) above which a fingerprint match is flagged.
    copyright_score_threshold: float = 0.85

    # AI Thumbnail A/B testing — generate N variants per video and let
    # the dashboard pick / test them. Each variant has a different
    # background color + text placement + emoji.
    thumbnail_variant_count: int = 5
    # When True, the LLM also predicts a CTR score (0-100) for each variant
    # so the dashboard can suggest the best one.
    thumbnail_ctr_prediction: bool = True

    # First-30-second hook analyzer. Uses LLM + word timings to score the
    # hook on curiosity, clarity, stakes, and pacing. Returns a 0-100 score
    # and concrete suggestions.
    hook_analyzer_enabled: bool = True

    # Best upload time AI. Uses the channel's historical analytics to find
    # the best 3 publish hours per weekday. Falls back to the strategy
    # profile's publish_hours when not enough data.
    upload_time_ai_enabled: bool = True

    # Long → Shorts auto-clipper. When a long video finishes, automatically
    # detect the 3-5 most engaging moments and produce Shorts from them.
    shorts_auto_clip: bool = True
    shorts_per_long: int = 3          # how many Shorts to clip per long video
    shorts_min_duration: int = 15     # seconds
    shorts_max_duration: int = 60     # seconds

    # ---- Voice ----
    tts_voice: str = "en-US-ChristopherNeural"
    tts_rate: str = "+0%"
    # Urdu narration is intentionally slower for clearer pronunciation.
    urdu_tts_rate: str = "-8%"
    tts_pitch: str = "+0Hz"
    # Final MP4 duration must be measured, not inferred from scene estimates.
    duration_tolerance_seconds: float = 3.0
    duration_tolerance_ratio: float = 0.08

    # ---- Tracking truthfulness ---------------------------------------
    # Synthetic analytics are opt-in. Live tracking never invents numbers.
    allow_simulated_metrics: bool = False

    # ---- Safety Pack ----------------------------------------------
    # Automatic mode is the default. Critical gates (OAuth, dry-run,
    # copyright/policy failures and missing artifacts) still block publishing.
    approval_required: bool = False
    notifications_enabled: bool = True
    backup_retention_days: int = 14
    youtube_daily_quota_units: int = 10000

    # ---- App ----
    database_url: str = "sqlite:///data/phoenix.db"
    data_dir: str = "data"
    assets_dir: str = "assets"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    secret_key: str = "change-me"
    log_level: str = "INFO"

    # -------------------------------------------------- helpers
    def path(self, *parts: str) -> Path:
        """Absolute path under the project root; creates parent dirs.

        If the first part is already an absolute path (e.g. an Android
        /storage/emulated/0/... path), we still keep it absolute and just
        make sure the parent dir exists.
        """
        if len(parts) == 1 and Path(parts[0]).is_absolute():
            p = Path(parts[0])
        else:
            p = ROOT_DIR.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def data_path(self) -> Path:
        return self.path(self.data_dir)

    @property
    def assets_path(self) -> Path:
        return self.path(self.assets_dir)

    @property
    def resolution(self) -> tuple[int, int]:
        """Final (width, height) of rendered videos, accounting for aspect."""
        base_w, base_h = _RESOLUTION_PRESETS.get(
            self.video_resolution.lower(), (1920, 1080)
        )
        mult = _ASPECT_MULTIPLIERS.get(self.video_aspect.lower(), (1.0, 1.0))
        if self.video_aspect.lower() == "square":
            # square derived from height
            side = base_h
            return (side, side)
        if self.video_aspect.lower() == "portrait":
            # 9:16 (Shorts)
            return (base_h * 9 // 16, base_h)
        # landscape
        return (base_w, base_h)

    @property
    def resolution_label(self) -> str:
        w, h = self.resolution
        return f"{w}x{h}"

    @property
    def categories_list(self) -> list[str]:
        return [c.strip() for c in (self.default_categories or "").split(",") if c.strip()]

    def set_video_options(self, resolution: str | None = None,
                          aspect: str | None = None,
                          target_seconds: int | None = None) -> None:
        """Runtime override used by the API when a user submits a produce
        request with custom video size / aspect / length."""
        if resolution:
            self.video_resolution = resolution.lower()
        if aspect:
            self.video_aspect = aspect.lower()
        if target_seconds:
            self.video_target_seconds = max(15, min(int(target_seconds), 3600))

    def resolve_target_seconds(self, mode: str | None = None) -> int:
        """Resolve the final target duration in seconds based on the length mode.

        - 'manual' (or None): use settings.video_target_seconds as-is
        - 'shorts': random 30s - 180s (YouTube Shorts / Reels / TikTok)
        - 'long':   random 180s - 600s (long-form YouTube videos)

        Returns the resolved seconds. The caller should also override the
        aspect ratio to 'portrait' for shorts when mode='shorts'.
        """
        import random as _r
        m = (mode or self.video_length_mode or "manual").lower()
        if m == "shorts":
            return _r.randint(30, 180)
        if m == "long":
            return _r.randint(180, 600)
        # manual
        return self.video_target_seconds

    def apply_updates(self, updates: dict) -> dict:
        """Apply & persist a dict of setting updates from the Settings page.

        Returns a summary of what changed (key -> new value).
        Only known, scalar fields are written; everything else is ignored.
        """
        # Mapping of API field name -> (env_var_name, attr_name, type_cast)
        field_map = {
            "channel_name":          ("CHANNEL_NAME",          "channel_name",          str),
            "channel_niche":         ("CHANNEL_NICHE",         "channel_niche",         str),
            "channel_language":      ("CHANNEL_LANGUAGE",      "channel_language",      str),
            "videos_per_day":        ("VIDEOS_PER_DAY",        "videos_per_day",        int),
            "video_target_seconds":  ("VIDEO_TARGET_SECONDS",  "video_target_seconds",  int),
            "video_resolution":      ("VIDEO_RESOLUTION",      "video_resolution",      str),
            "video_aspect":          ("VIDEO_ASPECT",          "video_aspect",          str),
            "video_privacy":         ("VIDEO_PRIVACY",         "video_privacy",         str),
            "show_captions":         ("SHOW_CAPTIONS",         "show_captions",         bool),
            "show_watermark":        ("SHOW_WATERMARK",        "show_watermark",        bool),
            "show_subscribe_endcard":("SHOW_SUBSCRIBE_ENDCARD","show_subscribe_endcard",bool),
            "show_subscribe_badge":  ("SHOW_SUBSCRIBE_BADGE",  "show_subscribe_badge",  bool),
            "use_intro":             ("USE_INTRO",             "use_intro",             bool),
            "use_outro":             ("USE_OUTRO",             "use_outro",             bool),
            "default_categories":    ("DEFAULT_CATEGORIES",    "default_categories",    str),
            "youtube_dry_run":       ("YOUTUBE_DRY_RUN",       "youtube_dry_run",       bool),
            "youtube_category_id":   ("YOUTUBE_CATEGORY_ID",   "youtube_category_id",   str),
            "whisper_model":         ("WHISPER_MODEL",         "whisper_model",         str),
            "tts_voice":             ("TTS_VOICE",             "tts_voice",             str),
            "tts_rate":              ("TTS_RATE",              "tts_rate",              str),
            "urdu_tts_rate":          ("URDU_TTS_RATE",          "urdu_tts_rate",          str),
            "tts_pitch":             ("TTS_PITCH",             "tts_pitch",             str),
            "duration_tolerance_seconds": ("DURATION_TOLERANCE_SECONDS", "duration_tolerance_seconds", float),
            "duration_tolerance_ratio":   ("DURATION_TOLERANCE_RATIO",   "duration_tolerance_ratio",   float),
            # v1.3 additions
            "video_length_mode":            ("VIDEO_LENGTH_MODE",            "video_length_mode",            str),
            "cinematic_mode":               ("CINEMATIC_MODE",               "cinematic_mode",               bool),
            "seo_language":                 ("SEO_LANGUAGE",                 "seo_language",                 str),
            "hide_hooks_in_description":    ("HIDE_HOOKS_IN_DESCRIPTION",    "hide_hooks_in_description",    bool),
            "monitor_min_views":            ("MONITOR_MIN_VIEWS",            "monitor_min_views",            int),
            "monitor_daily_quota":          ("MONITOR_DAILY_QUOTA",          "monitor_daily_quota",          int),
            "monitor_region_code":          ("MONITOR_REGION_CODE",          "monitor_region_code",          str),
            "monitor_learn_from_top_videos":("MONITOR_LEARN_FROM_TOP_VIDEOS","monitor_learn_from_top_videos",bool),
            "copyright_check_enabled":      ("COPYRIGHT_CHECK_ENABLED",      "copyright_check_enabled",      bool),
            "copyright_wait_seconds":       ("COPYRIGHT_WAIT_SECONDS",       "copyright_wait_seconds",       int),
            "auto_publish_after_check":     ("AUTO_PUBLISH_AFTER_CHECK",     "auto_publish_after_check",     bool),
            "post_check_privacy":           ("POST_CHECK_PRIVACY",           "post_check_privacy",           str),
            "scheduler_auto_trigger":       ("SCHEDULER_AUTO_TRIGGER",       "scheduler_auto_trigger",       bool),
            # v1.4 additions
            "pre_upload_copyright_check":   ("PRE_UPLOAD_COPYRIGHT_CHECK",   "pre_upload_copyright_check",   bool),
            "copyright_score_threshold":    ("COPYRIGHT_SCORE_THRESHOLD",    "copyright_score_threshold",    float),
            "thumbnail_variant_count":      ("THUMBNAIL_VARIANT_COUNT",      "thumbnail_variant_count",      int),
            "thumbnail_ctr_prediction":     ("THUMBNAIL_CTR_PREDICTION",     "thumbnail_ctr_prediction",     bool),
            "hook_analyzer_enabled":        ("HOOK_ANALYZER_ENABLED",        "hook_analyzer_enabled",        bool),
            "upload_time_ai_enabled":       ("UPLOAD_TIME_AI_ENABLED",       "upload_time_ai_enabled",       bool),
            "shorts_auto_clip":             ("SHORTS_AUTO_CLIP",             "shorts_auto_clip",             bool),
            "shorts_per_long":              ("SHORTS_PER_LONG",              "shorts_per_long",              int),
            "shorts_min_duration":          ("SHORTS_MIN_DURATION",          "shorts_min_duration",          int),
            "shorts_max_duration":          ("SHORTS_MAX_DURATION",          "shorts_max_duration",          int),
            # v1.6 mock/real toggles
            "force_mock_llm":               ("FORCE_MOCK_LLM",               "force_mock_llm",               bool),
            "force_mock_pexels":            ("FORCE_MOCK_PEXELS",            "force_mock_pexels",            bool),
            "force_mock_pixabay":           ("FORCE_MOCK_PIXABAY",           "force_mock_pixabay",           bool),
            "force_mock_jamendo":           ("FORCE_MOCK_JAMENDO",           "force_mock_jamendo",           bool),
            "force_mock_youtube":           ("FORCE_MOCK_YOUTUBE",           "force_mock_youtube",           bool),
            "force_mock_acoustid":          ("FORCE_MOCK_ACOUSTID",          "force_mock_acoustid",          bool),
            "force_mock_huggingface":       ("FORCE_MOCK_HUGGINGFACE",       "force_mock_huggingface",       bool),
            "force_mock_amazon":            ("FORCE_MOCK_AMAZON",            "force_mock_amazon",            bool),
            "force_mock_reddit":            ("FORCE_MOCK_REDDIT",            "force_mock_reddit",            bool),
            "force_mock_news":              ("FORCE_MOCK_NEWS",              "force_mock_news",              bool),
            "fpcalc_path":                  ("FPCALC_PATH",                  "fpcalc_path",                  str),
            "openrouter_fallback_models":    ("OPENROUTER_FALLBACK_MODELS",    "openrouter_fallback_models",    str),
            "llm_request_timeout_seconds":   ("LLM_REQUEST_TIMEOUT_SECONDS",   "llm_request_timeout_seconds",   float),
            "llm_max_retries":               ("LLM_MAX_RETRIES",               "llm_max_retries",               int),
            "llm_retry_backoff_seconds":     ("LLM_RETRY_BACKOFF_SECONDS",     "llm_retry_backoff_seconds",     float),
            "allow_simulated_metrics":       ("ALLOW_SIMULATED_METRICS",       "allow_simulated_metrics",       bool),
            "approval_required":              ("APPROVAL_REQUIRED",              "approval_required",              bool),
            "notifications_enabled":          ("NOTIFICATIONS_ENABLED",          "notifications_enabled",          bool),
            "backup_retention_days":          ("BACKUP_RETENTION_DAYS",          "backup_retention_days",          int),
            "youtube_daily_quota_units":      ("YOUTUBE_DAILY_QUOTA_UNITS",      "youtube_daily_quota_units",      int),
        }

        env_writes: dict[str, object] = {}
        applied: dict[str, object] = {}
        for key, value in updates.items():
            if key not in field_map:
                continue
            env_name, attr, cast = field_map[key]
            try:
                if cast is bool:
                    if isinstance(value, str):
                        clean = value.strip().lower() in ("1", "true", "yes", "on")
                    else:
                        clean = bool(value)
                elif cast is int:
                    clean = int(value)
                else:
                    clean = str(value)
                setattr(self, attr, clean)
                env_writes[env_name] = clean
                applied[key] = clean
            except (TypeError, ValueError):
                continue

        if env_writes:
            _update_env_file(env_writes)
            # Also push to os.environ so subprocesses / libraries pick it up.
            for k, v in env_writes.items():
                os.environ[k] = _coerce_str(v)
        return applied

    # mock-mode flags ------------------------------------------------
    @property
    def llm_available(self) -> bool:
        return (bool(self.openrouter_api_key or self.gemini_api_key or self.grok_api_key)
                and not self.force_mock_llm)

    @property
    def pexels_available(self) -> bool:
        return bool(self.pexels_api_key) and not self.force_mock_pexels

    @property
    def pixabay_available(self) -> bool:
        return bool(self.pixabay_api_key) and not self.force_mock_pixabay

    @property
    def jamendo_available(self) -> bool:
        return bool(self.jamendo_client_id) and not self.force_mock_jamendo

    @property
    def youtube_available(self) -> bool:
        """True only when dry-run is OFF and the secrets file exists."""
        if self.youtube_dry_run or self.force_mock_youtube:
            return False
        p = Path(self.google_client_secrets_file)
        if not p.is_absolute():
            p = ROOT_DIR / self.google_client_secrets_file
        return p.exists()

    @property
    def youtube_secrets_exist(self) -> bool:
        """True when OAuth client secrets file exists (regardless of dry-run)."""
        p = Path(self.google_client_secrets_file)
        if not p.is_absolute():
            p = ROOT_DIR / self.google_client_secrets_file
        return p.exists()

    # ---- v1.4 capability flags -------------------------------------------
    @property
    def acoustid_available(self) -> bool:
        return bool(self.acoustid_api_key) and not self.force_mock_acoustid

    @property
    def huggingface_available(self) -> bool:
        return bool(self.huggingface_token) and not self.force_mock_huggingface

    @property
    def amazon_affiliate_available(self) -> bool:
        return (bool(self.amazon_affiliate_tag and self.amazon_pa_api_key
                     and self.amazon_pa_secret) and not self.force_mock_amazon)

    @property
    def reddit_available(self) -> bool:
        return bool(self.reddit_client_id and self.reddit_secret) and not self.force_mock_reddit

    @property
    def news_available(self) -> bool:
        return bool(self.news_api_key) and not self.force_mock_news

    def capability_report(self) -> dict[str, str]:
        """Used by the API health panel to show live/mock per service."""
        return {
            "llm": "live" if self.llm_available else "mock (template engine)",
            "openrouter": "configured" if self.openrouter_api_key and not self.force_mock_llm else "not configured",
            "gemini": "configured" if self.gemini_api_key and not self.force_mock_llm else "not configured",
            "grok": "configured" if self.grok_api_key and not self.force_mock_llm else "not configured",
            "pexels": "live" if self.pexels_available else "mock (generated clips)",
            "pixabay": "live" if self.pixabay_available else "mock (generated clips)",
            "jamendo": "live" if self.jamendo_available else "mock (synth music)",
            "voice": "live (Edge-TTS, keyless)",
            "youtube": "live" if self.youtube_available else ("mock (forced)" if self.force_mock_youtube else "dry-run (manifest only)"),
            "analytics": "synthetic (opt-in)" if self.allow_simulated_metrics else "live-only (no invented metrics)",
            # v1.4
            "acoustid": "live" if self.acoustid_available else "off (pre-upload check disabled)",
            "huggingface": "live" if self.huggingface_available else "off (CTR prediction disabled)",
            "amazon_affiliate": "live" if self.amazon_affiliate_available else "off (no affiliate links)",
            "reddit": "live" if self.reddit_available else "off (no reddit trends)",
            "news": "live" if self.news_available else "off (no news trends)",
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
