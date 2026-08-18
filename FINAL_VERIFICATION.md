# Project Phoenix AI — Final Package and Folder Verification

**تاریخ:** 16 اگست 2026  
**Source:** `/home/ubuntu/work_youtube_tracker/project-phoenix-ai/`

## Audit result

پرانے uploaded archive `/home/ubuntu/upload/4_5766895121400339815.zip` کے ساتھ موجودہ project کا side-by-side audit کیا گیا۔ پرانی ZIP میں runtime `.gitkeep` folders، `.env` اور `secrets/client_secret.json` موجود تھے، جبکہ پہلے sanitized distribution میں data اور secrets intentionally exclude ہونے کی وجہ سے folders نظر نہیں آ رہے تھے۔ اب دونوں استعمال کے لیے واضح bundles بنائے گئے ہیں۔

## Restored runtime layout

| Path | استعمال |
|---|---|
| `data/uploads/` | Browser سے upload ہونے والی source videos، خاص طور پر Remix inputs |
| `data/cartoons/` | Cartoon search/download staging |
| `data/output/` | Final MP4 files اور per-job working folders |
| `data/media/` | Reusable downloaded/generated media |
| `data/music/` | Background music |
| `data/thumbnails/` | Thumbnail variants |
| `data/logs/` | Application اور workflow logs |
| `data/backups/` | Safety Pack database/config backups |
| `data/tokens/` | Private YouTube OAuth tokens |
| `secrets/` | Private Google OAuth client JSON |

ہر runtime folder میں `.gitkeep` شامل ہے، اس لیے ZIP extract کرنے کے فوراً بعد folders دکھائی دیں گے۔ `run.sh` بھی startup پر تمام folders recreate کرتا ہے، اس لیے اگر user انہیں delete کر دے تب بھی application silently fail نہیں کرے گی۔

## OAuth and configuration

Sanitized package میں `secrets/client_secret.json.example` shape-only template، `secrets/README.md` اور `.env.example` موجود ہیں۔ Private complete bundle میں پرانی upload سے اصل `.env` اور `secrets/client_secret.json` restore کیے گئے ہیں، اور نئے Phoenix safety/reliability settings بھی merged ہیں۔ Private bundle کو public repository یا کسی غیر مجاز شخص کے ساتھ share نہ کریں۔

`.env` میں کم از کم یہ paths درست ہونے چاہییں:

```text
GOOGLE_CLIENT_SECRETS_FILE=secrets/client_secret.json
YOUTUBE_TOKEN_DIR=data/tokens
DATA_DIR=data
DATABASE_URL=sqlite:///data/phoenix.db
```

نئے reliability controls بھی `.env.example` میں documented ہیں: `POLLINATIONS_CONCURRENCY`، `POLLINATIONS_MIN_INTERVAL`، `POLLINATIONS_RETRIES` اور `TTS_TIMEOUT_SECONDS`۔

## Verified bundles

| Bundle | Contents | Security handling |
|---|---|---|
| `project-phoenix-ai-sanitized-complete.zip` | Source، production frontend، tests، `.env.example`، runtime folders، OAuth example، README، `run.sh` | Real `.env`، OAuth JSON، database، generated media، logs اور tokens excluded |
| `project-phoenix-ai-complete-private.zip` | Sanitized contents کے ساتھ original `.env` اور `secrets/client_secret.json` | Confidential; public sharing یا GitHub upload نہ کریں |

Both ZIPs passed `unzip -t` integrity validation. Structure parser نے required folders، `.env` keys اور OAuth JSON shape validate کیا۔

## Post-restore verification

| Check | Result |
|---|---|
| `bash -n run.sh` | Passed |
| `./run.sh` duplicate protection | Exit 0; existing server detected cleanly |
| Runtime directories after launcher | All 9 folders present |
| Live health | `analytics: live-only (no invented metrics)`, `ffmpeg: ok`, `youtube_dry_run: true` |
| All-section smoke test | Passed; all pages/APIs 200; Remix real output through faster-whisper |
| Safety Pack test | Passed |
| Reliability test | Passed |
| Cartoon local flow | Passed; 1080×1920 portrait MP4 with AAC audio |
| ZIP structure and secret scan | Passed |

## Startup

Extract the desired bundle, enter the project directory, and run:

```bash
./run.sh
```

Then open `http://localhost:8000`. For YouTube connection, place the private OAuth file at `secrets/client_secret.json`, keep `YOUTUBE_DRY_RUN=true` during the first verification, connect the channel from the Channels page, and only disable dry-run after reviewing one complete render.

## Truthful limitations

Live provider quotas are controlled by OpenRouter, Google, YouTube and the relevant third-party services; the application cannot truthfully guarantee unlimited AI. If provider keys are absent, labelled template fallback is used and the dashboard reports that state. YouTube dry-run and approval settings remain safety controls, not fake publish confirmations. AcoustID copyright lookup remains unavailable until `ACOUSTID_API_KEY` is configured, and the application reports it as unavailable instead of inventing a result.


## API setup documentation

The project now includes `API_SETUP_GUIDE_ROMAN_URDU.md`. It documents the required Google OAuth JSON and YouTube Data/Analytics APIs first, followed by OpenRouter, Gemini, Grok/xAI, Pexels, Pixabay and Jamendo. Amazon, Reddit, NewsAPI and other integrations are marked optional. The guide includes exact `.env` names, OAuth scopes, redirect URI, test-user email steps, Web/Installed JSON shapes, security warnings and common errors.


## Expanded setup details

The Roman Urdu guide now separately explains that the Google OAuth JSON contains application credentials, while API enablement happens in Google Cloud API Library and permissions come from OAuth scopes. It documents YouTube Data API v3 and YouTube Analytics API as the essential YouTube services, explains that `status.privacyStatus` controls private/unlisted/public rather than a separate JSON permission, and records the Google upload/audit limitation for unverified API projects. It also adds exact Python 3.12/3.11 guidance, Node 20/22 guidance, FFmpeg/ffprobe/fpcalc requirements, platform install commands and the one-command launcher flow.


## Long-video quality upgrade

The long-form pipeline now measures the final MP4 duration with `ffprobe` after muxing instead of trusting an intermediate estimate. The orchestrator compares the measured artifact against the requested target and records a clear failure when the result falls outside the configured tolerance (`max(3 seconds, 8% of target)` by default). Existing render checkpoints are also re-probed before they are accepted.

Script generation now uses a language-aware speech budget, carries explicit `purpose` and `takeaways` metadata, and expands non-explainer fallback formats for long targets. Urdu narration automatically selects `ur-PK-AsadNeural`, uses a slower configurable `URDU_TTS_RATE=-8%` default for clearer pronunciation, and keeps Edge-TTS timeout/fallback behavior.

The new `backend/test_long_video_quality.py` passed with a measured 30.0-second MP4 for a 30-second request, Urdu voice `ur-PK-AsadNeural`, purpose metadata present, and script-duration scaling verified. The existing `backend/test_media_sections.py` also passed after these changes.


## Automatic quality and safety mode

The default upload policy is now automatic (`APPROVAL_REQUIRED=false`). Script generation, voice, media assembly, measured duration validation, metadata, quality inspection, compliance scoring, copyright checks, scheduling and upload proceed without a manual approval click when the required providers are configured.

Automatic mode is not a blind bypass. The final artifact quality gate blocks missing/corrupt media, missing audio/video streams and out-of-tolerance duration. Compliance recommendations `do_not_publish` and `review_manually` block automatic publication. A confirmed pre-upload copyright flag also blocks publication. Missing OAuth, dry-run mode, provider limits and upload/API failures remain non-publish conditions and are logged truthfully.

Special Cartoon and AI Story auto-upload flows now run the same artifact-quality and compliance gates before upload. The new `backend/app/services/quality.py` produces a persisted quality report with measured duration, stream presence, purpose/takeaway metadata, script word budget and a score.

Regression status after automatic-mode changes: `test_reliability.py`, `test_long_video_quality.py`, `test_media_sections.py`, Python compile checks and frontend build checks passed. The HTTPX/Starlette deprecation warning is non-fatal and does not represent an application runtime error.


## Live automatic-mode verification

After restarting the project server with the updated source, the live settings API returned `approval_required=false`, `duration_tolerance_seconds=3.0`, `duration_tolerance_ratio=0.08`, `urdu_tts_rate=-8%`, and `youtube_dry_run=true`. The live health endpoint returned HTTP 200 and reported analytics as `live-only (no invented metrics)`. The Settings browser page displayed the Automatic quality controls panel with `3s / 8%`, Urdu rate `-8%`, and Critical safety gates `ON`.


## Features 1, 12 and 13 — final verification (17 August 2026)

### Feature 1 — real 10–20 minute long-video verifier

`backend/cli.py verify-long` is implemented with a strict `600..1200` second range. It generates a real artifact, does not publish, measures the final MP4 with `ffprobe`, validates audio/video streams, checks duration tolerance, validates purpose/takeaway metadata and emits a quality report. The command help was verified live after server restart:

```text
usage: phoenix verify-long [-h] [--seconds 600..1200] [--topic TOPIC]
```

The existing quality test passed with a measured 30-second artifact for the test target, and the verifier is intentionally not run on startup because a real 10–20 minute render is CPU/disk intensive. A successful verifier run is not a fake upload confirmation; it is a local quality result with `publish=False`.

### Feature 12 — actual provider usage and cost dashboard

`ProviderUsage` is persisted in SQLite. OpenRouter, Gemini and Grok response metadata records request count and provider-reported prompt/completion/total tokens. Cost is recorded only when the provider response supplies cost metadata. The `/api/safety/provider-usage?days=1` endpoint and Safety Center panel were verified with no configured live provider key: the endpoint returned an empty usage list and the truthful note that token/cost values are provider-response data only. The UI showed unknown balance rather than an invented balance or estimated price, while YouTube local quota remained separate.

The focused `test_research_usage.py`, reliability tests and Safety Pack tests passed. A temporary provider-usage test row was removed after validation; the final clean endpoint state reports no provider response usage in the sandbox.

### Feature 13 — automatic topic research with provenance

The Monitor page now exposes `POST /api/monitor/research/{channel_id}` and `GET /api/monitor/research/latest/{channel_id}`. The research service prefers Google Trends through `pytrends`, public Reddit signals, optional NewsAPI, and connected YouTube data when credentials are available. Every report carries source/provenance labels. With no live keys and Google Trends rate limiting in the sandbox, the live page correctly displayed `source: template_fallback` and each topic as `template_fallback_not_live_trend`; it did not claim those topics were live trends. The live endpoint returned HTTP 200 and the research report was available.

### Regression and live checks

| Check | Result |
|---|---|
| Python compile checks for new backend files | Passed |
| `test_research_usage.py` | Passed |
| `test_reliability.py` | Passed |
| `test_safety_pack.py` | Passed |
| `test_upload_policy_mode.py` | Passed |
| `test_long_video_quality.py` | Passed previously and retained |
| `test_media_sections.py` | Passed previously and retained |
| Frontend TypeScript/Vite production build | Passed |
| Live `/api/dashboard/health` | HTTP 200; `analytics: live-only (no invented metrics)` |
| Live `verify-long --help` | Passed; strict 600–1200 range visible |
| Live Monitor browser verification | Passed; research panel and labelled fallback visible |
| Live Safety Center browser verification | Passed; actual usage and unknown-balance states visible |

The Safety Center still contains historical FFmpeg failure records for Videos #29, #23, #19 and #18 from earlier test artifacts. No new failure was created during the final Features 1/12/13 verification; these records are retained history and were not silently deleted.

### Honest operational limitations

The sandbox had no live OpenRouter/Gemini/Grok credentials, so provider usage remained empty and provider cost remained unknown. Google Trends returned a sandbox rate-limit response, so the research UI used the explicitly labelled fallback. These are truthful runtime states, not implementation failures and not evidence of unlimited provider access. Actual provider quotas and pricing remain controlled by the provider accounts and are never estimated by Phoenix.


## Final rebuilt distribution bundles

After the Features 1/12/13 changes and documentation updates, both distribution archives were rebuilt from clean staging trees. Generated database/media/logs and virtualenv were excluded; runtime `.gitkeep` folders remain. The sanitized archive excludes `.env` and `secrets/client_secret.json`. The private archive includes the local `.env` and original OAuth client JSON and must be treated as confidential.

| File | Approximate size | Verification |
|---|---:|---|
| `project-phoenix-ai-sanitized-complete.zip` | approximately 589 KB before final compression metadata | `unzip -tq` passed; exact SHA-256 is in the external checksum file |
| `project-phoenix-ai-complete-private.zip` | approximately 593 KB before final compression metadata | `unzip -tq` passed; exact SHA-256 is in the external checksum file |

Both archives passed `unzip -tq`. Required Feature 1/12/13 source files and the updated final verification report were confirmed inside both archives. Exact hashes are intentionally kept outside the archives in `/home/ubuntu/work_youtube_tracker/project-phoenix-ai-bundles.sha256`, avoiding a self-referential checksum inside a file that is itself packaged.


## API provider status and same-tab navigation fix (17 August 2026)

The Dashboard health card now has a dedicated **API provider status** section for OpenRouter, Gemini and Grok/xAI. The backend capability report exposes each provider independently, while the dashboard shows only masked key state and truthful runtime labels such as `configured · ready to try` or `not configured`. It does not display raw API keys, invent provider connectivity, or claim a provider quota is unlimited. The existing generic service panel remains available for ffmpeg, YouTube dry-run, analytics and other capabilities.

The navigation audit found that the sidebar already used React Router `NavLink`. The actual internal new-tab causes were raw internal anchors: Channels → analytics and the generated video-file download. Channels analytics is now a router `Link`, and the internal file link no longer uses `target=_blank`. Live browser verification changed `/` to `/videos`, then `/channels` to `/analytics?channel=1`, in the same browser tab. External YouTube links and the Google OAuth authorization popup remain intentionally separate because they leave the app or require external authorization.

| Fix check | Result |
|---|---|
| Python compile checks | Passed |
| Reliability test | Passed |
| Safety Pack test | Passed |
| Upload policy mode test | Passed |
| Frontend TypeScript/Vite production build | Passed |
| Live dashboard health | HTTP 200 |
| Provider status payload | OpenRouter/Gemini/Grok shown independently; no keys configured in sandbox |
| Dashboard browser rendering | Passed; API provider status cards visible |
| Sidebar `/` → `/videos` | Passed; same-tab URL change |
| Channels analytics `/channels` → `/analytics?channel=1` | Passed; same-tab URL change |
| Internal raw `target=_blank` routes | Removed |


## API key disappearance diagnosis and protection (18 August 2026)

The user-provided `.env` attachment contained the correct provider variable names but empty values for `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `GROK_API_KEY`, `PEXELS_API_KEY`, `PIXABAY_API_KEY` and `JAMENDO_CLIENT_ID`. The project-root `.env` also contained empty values. Therefore the backend correctly reported `not configured` and mock states; no API key was silently fabricated or exposed. The upload artifact appears to have arrived without credential values, so it could not restore live providers.

A safe `python backend/cli.py import-env /path/to/.env` command was added. It merges only non-empty settings, requires at least one non-empty provider credential, creates a timestamped backup before changing the target, and refuses an empty/redacted source. The test confirmed that blank Gemini values do not overwrite an existing value, non-empty provider values merge correctly, and an all-blank source exits with an explicit `ENV IMPORT BLOCKED` message.

`run.sh` now prints provider names only and never prints credential values. If no non-empty provider key exists at the project root, it logs a clear warning explaining why the dashboard will show mock/not-configured. After a real `.env` is imported, the backend must be restarted because a running process does not reload credentials automatically.

| Protection check | Result |
|---|---|
| Uploaded `.env` variable audit | Correct names; all six provider values empty |
| Existing project `.env` audit | All six provider values empty |
| Blank import overwrite protection | Passed; source rejected with exit code 2 |
| Non-empty merge and timestamped backup | Passed in isolated test |
| `bash -n run.sh` | Passed |
| Permanent `backend/test_env_import.py` | Passed |
| Live restart through `run.sh` | Passed; HTTP 200 |
| Live launcher warning | Passed; provider values hidden |
| Live provider status | Truthfully remains not configured until real values are present |


## Provider cards visibility fix (18 August 2026)

The live backend payload contained all six provider key names and reported OpenRouter, Gemini and Grok/xAI as `configured`, but the dashboard lower capability grid mapped every non-`live` state to `off/fallback`, which was misleading. The HealthPanel was corrected so the three primary provider cards are always rendered—even when a key is absent—and the lower grid preserves truthful states such as `configured`, `live`, `mock/fallback`, `not configured` and `off`.

After a production frontend rebuild and backend restart, cache-busting browser verification showed masked OpenRouter, Gemini and Grok/xAI cards with `configured · ready to try`. The lower grid showed `openrouter configured`, `gemini configured`, `grok configured`, while Pexels, Pixabay and Jamendo showed `live`. The live dashboard remained healthy with HTTP 200.
