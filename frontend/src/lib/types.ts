export interface Channel {
  id: number
  name: string
  niche: string
  language: string
  videos_per_day: number
  yt_channel_id: string | null
  yt_subscriber_count: number | null
  yt_video_count: number | null
  yt_view_count: number | null
  yt_thumbnail: string | null
  yt_country: string | null
  yt_stats_fetched_at: string | null
  privacy: string
  active: boolean
  created_at: string
}

export interface Video {
  id: number
  channel_id: number
  topic: string
  niche: string
  title: string
  status: string
  language: string
  duration_seconds: number
  yt_video_id: string | null
  thumbnail_path: string | null
  file_path: string | null
  scheduled_at: string | null
  published_at: string | null
  error: string | null
  attempts: number
  created_at: string
  tags: string[]
  hashtags: string[]
  categories: string[]
  show_captions?: boolean | null
  show_watermark?: boolean | null
  show_subscribe_endcard?: boolean | null
  show_subscribe_badge?: boolean | null
  // v1.4 monetization
  hook_score?: number | null
  copyright_check_passed?: boolean | null
  copyright_check_score?: number | null
  predicted_ctr?: number | null
  parent_video_id?: number | null
  is_short?: boolean
}

export interface RenderProgress {
  pct: number
  stage: string
}

export interface DashboardSummary {
  channels: number
  videos_total: number
  videos_by_status: Record<string, number>
  rendering_now: Record<string, RenderProgress>
  queue: { queued: number; running: number; dead: number }
  system: {
    cpu_pct: number
    ram_pct: number
    ram_used_gb: number
    ram_total_gb: number
    disk_total_gb: number
    disk_used_gb: number
    uptime_min: number
  }
  storage: Record<string, number>
  capabilities: {
    services: Record<string, string>
    ffmpeg: string
    keys: Record<string, string>
    youtube_dry_run: boolean
    checked_at: string
  }
  scheduler: { id: string; next_run: string | null; trigger: string }[]
  recent_activity: LogEntry[]
}

export interface LogEntry {
  id?: number
  ts: string
  level: string
  source: string
  message: string
}

export interface Job {
  id: number
  type: string
  status: string
  attempts: number
  max_attempts: number
  run_at: string
  last_error: string | null
  payload: Record<string, unknown>
  created_at: string
}

export interface AnalyticsSummary {
  videos: number
  views: number
  watch_minutes: number
  subs_gained: number
  avg_retention: number
  avg_ctr: number
  likes: number
  comments: number
  shares: number
  // Live YouTube channel stats (may be null when not connected)
  channel_name?: string | null
  yt_channel_id?: string | null
  yt_thumbnail?: string | null
  yt_subscriber_count?: number | null
  yt_total_views?: number | null
  yt_video_count?: number | null
  yt_stats_fetched_at?: string | null
  yt_country?: string | null
  connected?: boolean
  live_fetched_at?: string | null
  metrics_source?: 'youtube' | 'simulated' | 'mixed' | 'none'
  metrics_are_live?: boolean
  simulation_allowed?: boolean
}

export interface LeaderboardRow {
  video_id: number
  title: string
  views: number
  retention_pct: number
  ctr_pct: number
  subs_gained: number
}

export interface StrategyProfile {
  niche_weights: Record<string, number>
  hook_weights: Record<string, number>
  title_patterns: Record<string, number>
  publish_hours: number[]
  insights: string[]
  updated_at?: string | null
}

export interface SettingsView {
  app: Record<string, string | number | boolean>
  options: {
    resolutions: string[]
    aspects: string[]
    voices: string[]
    languages: { code: string; label: string }[]
    niches: string[]
    privacy: string[]
    length_modes: { value: string; label: string }[]
    regions: string[]
  }
  capabilities: Record<string, string>
  keys_masked: Record<string, string>
  ffmpeg: string
  voices: Record<string, string>
  note: string
}

export interface TrendingVideo {
  id: number
  yt_video_id: string
  title: string
  niche: string
  channel_title: string
  view_count: number
  like_count: number
  comment_count: number
  duration_seconds: number
  published_at: string | null
  tags: string[]
  thumbnail: string | null
  region: string
  fetched_at: string
  analyzed: boolean
}

export interface LearnedInsight {
  id: number
  niche: string
  insight_type: string
  content: string
  meta: Record<string, unknown>
  source_video_id: string | null
  score: number
  created_at: string
}

export interface MonitorStats {
  trending_count: number
  insights_count: number
  min_views: number
  daily_quota: number
}

export interface ScheduledSlot {
  id: number
  channel_id: number
  hour: number
  minute: number
  categories: string[]
  length_mode: string
  target_seconds: number | null
  aspect: string | null
  language: string | null
  youtube_category_id: string | null
  enabled: boolean
  last_fired_at: string | null
  last_video_id: number | null
  created_at: string
}

export interface OAuthStatus {
  channel_id: number
  connected: boolean
  has_secrets: boolean
  credential_type?: string
  auth_method?: string
  needs_reauth?: boolean
  yt_channel_id: string | null
  yt_channel_name: string
  yt_thumbnail: string | null
  yt_subscriber_count: number | null
  yt_video_count: number | null
  yt_view_count: number | null
  yt_stats_fetched_at: string | null
  dry_run: boolean
}

export interface OAuthStartResponse {
  auth_url: string
  state: string
  channel_id: number
  redirect_uri: string
}

export interface YouTubeCategory {
  id: string
  title: string
  assignable: boolean
}

// v1.4 monetization types
export interface UploadTimeSlot {
  hour: number
  score: number
  videos?: number
  avg_views?: number
  reason?: string
}

export interface UploadTimeSuggestion {
  weekdays: Record<string, UploadTimeSlot[]>
  overall_best: { weekday: string; hour: number; score: number }[]
  source: 'analytics' | 'strategy' | 'default'
  data_points: number
}

export interface NextUploadTime {
  hour: number
  weekday: string
  score: number
  source: string
  reasoning: string
}

export interface HookAnalysis {
  score: number
  curiosity: number
  clarity: number
  stakes: number
  pacing: number
  weaknesses: string[]
  alternatives: string[]
  engine: string
}

export interface CopyrightCheckResult {
  checked: boolean
  clean: boolean
  score: number
  matches: { score: number; title: string; artist: string; release: string }[]
  audio_path: string
  reason: string
}

export interface ThumbnailVariant {
  index: number
  path: string
  ctr_score?: number | null
  rationale?: string
}

export interface ShortClip {
  id: number
  topic: string
  file_path: string
  duration_seconds: number
  status: string
}
