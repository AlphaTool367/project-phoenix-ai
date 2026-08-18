# Project Phoenix AI — API and YouTube Setup

This guide covers the API providers used by the sanitized Project Phoenix AI repository. Create keys only in the official provider dashboards and keep all credentials in the project-root `.env` file. Never commit `.env`, OAuth JSON, tokens, databases, generated media, or logs.

## Official provider links

| Provider | Key or app page | Documentation | Environment variable |
|---|---|---|---|
| Pexels | https://www.pexels.com/api/ | https://www.pexels.com/api/documentation/ | `PEXELS_API_KEY` |
| Pixabay | https://pixabay.com/api/docs/ | https://pixabay.com/api/docs/ | `PIXABAY_API_KEY` |
| Jamendo | https://devportal.jamendo.com/ | https://developer.jamendo.com/v3.0 | `JAMENDO_CLIENT_ID` |
| OpenRouter | https://openrouter.ai/keys | https://openrouter.ai/docs/quickstart | `OPENROUTER_API_KEY` |
| Gemini | https://aistudio.google.com/api-keys | https://ai.google.dev/gemini-api/docs/api-key | `GEMINI_API_KEY` |
| Grok/xAI | https://console.x.ai/ | https://docs.x.ai/developers/quickstart | `GROK_API_KEY` |

Pexels and Pixabay provide stock image/video search. Jamendo provides music catalog access. OpenRouter, Gemini, and Grok/xAI provide AI model access. Provider quotas, free tiers, billing, and availability are controlled by the providers; Phoenix does not claim unlimited usage.

## Environment file

Create this file beside `run.sh`:

```text
project-phoenix-ai/.env
```

Use the following variable names:

```dotenv
OPENROUTER_API_KEY=your_real_value
GEMINI_API_KEY=your_real_value
GROK_API_KEY=your_real_value
PEXELS_API_KEY=your_real_value
PIXABAY_API_KEY=your_real_value
JAMENDO_CLIENT_ID=your_real_value
```

At least one AI key is recommended. If a provider key is absent, Phoenix uses a clearly labelled fallback where supported. The dashboard shows masked configured status; it never displays raw key values.

If you already have a local environment file, merge it safely from the project root:

```bash
python backend/cli.py import-env /path/to/your/.env
```

Windows PowerShell:

```powershell
python backend\cli.py import-env C:\path\to\your\.env
```

The command imports only non-empty values, creates a timestamped backup, and refuses an empty or redacted source file. Restart the backend after changing `.env`.

## YouTube OAuth

Create a Google Cloud project, enable YouTube Data API v3 and YouTube Analytics API, configure the OAuth consent screen, and create OAuth credentials. Save the downloaded file as:

```text
project-phoenix-ai/secrets/client_secret.json
```

Keep `YOUTUBE_DRY_RUN=true` while testing. Connect the channel from the dashboard, verify the real channel data, and only then consider live publishing. Analytics remain live-only; Phoenix does not invent views, subscribers, retention, or revenue.

## Dependencies

The repository includes `requirements.txt` for the Python backend and `frontend/package.json` for the React frontend. The recommended setup is:

```bash
cd project-phoenix-ai
./run.sh
```

For the manual two-terminal developer setup, see [`GITHUB_RUN_COMMANDS.md`](GITHUB_RUN_COMMANDS.md). The exact requested command blocks are included there for Windows backend and frontend terminals.

## Security checklist

Before pushing to GitHub, confirm that `.env`, `secrets/client_secret.json`, token files, SQLite databases, generated videos, audio, thumbnails, logs, virtual environments, and frontend `node_modules` are not staged. The repository `.gitignore` excludes these paths. The public distribution is sanitized and contains documentation, source code, tests, `requirements.txt`, and safe dashboard screenshots only.
