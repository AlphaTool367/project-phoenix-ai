# Provider cards fix browser verification

Date: 2026-08-18

The cache-busting dashboard URL loaded successfully after the frontend rebuild and backend restart.

Visible API provider cards:

- OpenRouter — masked key — `configured · ready to try`
- Gemini — masked key — `configured · ready to try`
- Grok / xAI — masked key — `configured · ready to try`

The lower service grid now uses truthful labels instead of mapping every non-`live` state to `off/fallback`:

- `llm` — live
- `openrouter` — configured
- `gemini` — configured
- `grok` — configured
- `pexels`, `pixabay`, `jamendo` — live
- optional unconfigured providers — off

The live dashboard loaded on the same URL with no frontend error and API health remained HTTP 200.
