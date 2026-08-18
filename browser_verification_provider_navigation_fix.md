# Browser verification — provider status and same-tab navigation

Date: 2026-08-17

## Dashboard API status

Live route `/?build=provider-nav-fix` rendered the **System & API Health** card with a separate **API provider status** section. It showed OpenRouter, Gemini and Grok/xAI independently, masked key state, and the truthful `not configured` state in this sandbox. The same card continued to show `analytics live`, `youtube dry-run`, `voice live`, and other service states without claiming provider success or fake quota.

## Same-tab navigation

Clicking the sidebar Videos item changed the current URL from `/` to `/videos` in the same browser session. Clicking Channels then its internal `analytics →` action changed the current URL to `/analytics?channel=1` in the same tab. The raw internal analytics anchor was replaced with a React Router `Link`; the internal generated-file download no longer has `target=_blank`.

External YouTube/watch links and the Google OAuth authorization popup remain intentionally separate because they leave the Phoenix app or require external authorization. They are not internal page navigation.
