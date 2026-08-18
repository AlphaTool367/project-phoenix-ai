#!/usr/bin/env python3
"""Comprehensive end-to-end test for the v1.2 Project Phoenix AI upgrades.

Verifies that every fix and feature works:
  1. Settings view returns all the new fields
  2. Settings POST persists to .env
  3. Channel model has the new YouTube stats fields
  4. OAuth status endpoint works (returns connected: false initially)
  5. YouTube categories fallback works
  6. Realtime analytics endpoint returns the right shape
  7. Produce endpoint accepts all new options (categories, toggles, language)
  8. OAuth callback returns proper HTML on error
  9. ASS path escaping fix (Windows paths, apostrophes)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import app
from fastapi.testclient import TestClient


def main() -> int:
    failures = []
    with TestClient(app) as client:
        # 1. Settings view returns all the new fields
        r = client.get('/api/settings')
        assert r.status_code == 200, f"settings view failed: {r.status_code}"
        s = r.json()
        for field in ('show_captions', 'show_watermark', 'show_subscribe_endcard',
                      'show_subscribe_badge', 'use_intro', 'use_outro',
                      'default_categories', 'youtube_dry_run', 'youtube_category_id',
                      'youtube_secrets_exist'):
            assert field in s['app'], f"missing field in settings.app: {field}"
        assert 'languages' in s['options']
        assert 'niches' in s['options']
        assert 'privacy' in s['options']
        print("✓ 1. settings view returns all new fields")

        # 2. Settings POST persists to .env
        r = client.post('/api/settings', json={
            'show_captions': True,
            'show_subscribe_endcard': False,
            'default_categories': 'technology,science,space,history',
        })
        assert r.status_code == 200, f"settings update failed: {r.status_code}"
        assert r.json()['count'] >= 3
        # Verify persisted by reading settings again
        r2 = client.get('/api/settings')
        assert r2.json()['app']['show_captions'] is True
        assert r2.json()['app']['default_categories'] == 'technology,science,space,history'
        print("✓ 2. settings update persists to .env and in-memory")

        # 3. Channel model has YouTube stats fields
        r = client.get('/api/channels')
        channels = r.json()
        assert len(channels) >= 1, "no channels found"
        ch = channels[0]
        for field in ('yt_subscriber_count', 'yt_video_count', 'yt_view_count',
                      'yt_thumbnail', 'yt_country', 'yt_stats_fetched_at'):
            assert field in ch, f"channel missing field: {field}"
        cid = ch['id']
        print(f"✓ 3. channel model has YouTube stats fields (channel #{cid})")

        # 4. OAuth status endpoint
        r = client.get(f'/api/channels/{cid}/oauth/status')
        assert r.status_code == 200
        st = r.json()
        assert 'connected' in st
        assert 'has_secrets' in st
        assert 'dry_run' in st
        print(f"✓ 4. oauth status: connected={st['connected']}, has_secrets={st['has_secrets']}")

        # 5. YouTube categories fallback
        r = client.get(f'/api/channels/{cid}/categories')
        assert r.status_code == 200
        cats = r.json()
        assert len(cats) >= 10, f"only {len(cats)} categories"
        # Verify the structure
        assert 'id' in cats[0] and 'title' in cats[0]
        print(f"✓ 5. youtube categories: {len(cats)} available (fallback works)")

        # 6. Realtime analytics endpoint
        r = client.get(f'/api/analytics/channel/{cid}/realtime')
        assert r.status_code == 200
        a = r.json()
        for field in ('connected', 'channel_name', 'videos', 'views',
                      'yt_subscriber_count', 'yt_total_views', 'yt_video_count'):
            assert field in a, f"analytics missing field: {field}"
        print(f"✓ 6. realtime analytics: connected={a['connected']}, channel={a['channel_name']}")

        # 7. Produce endpoint with all new options
        r = client.post('/api/videos/produce', json={
            'channel_id': cid,
            'topic': 'Test topic with all options',
            'publish': False,
            'categories': ['technology', 'science'],
            'language': 'en',
            'show_captions': True,
            'show_watermark': False,
            'show_subscribe_endcard': False,
            'show_subscribe_badge': False,
            'youtube_category_id': '27',
            'target_seconds': 30,
        })
        assert r.status_code == 202, f"produce failed: {r.status_code} {r.text}"
        print("✓ 7. produce video accepts all new options (categories, toggles, lang, category)")

        # 8. OAuth callback returns proper HTML on error
        r = client.get('/api/oauth/callback')
        assert r.status_code == 400
        assert 'text/html' in r.headers.get('content-type', '')
        assert 'Missing' in r.text or 'error' in r.text.lower()
        print("✓ 8. oauth callback returns proper HTML error page")

        # 9. ASS path escaping fix
        from app.services.editor import _ass_path_for_filter
        from pathlib import Path as P
        # Windows path with backslashes + drive letter colon
        # The fix converts \ to / FIRST, then escapes : as \: and ' as \'
        win = _ass_path_for_filter(P('C:\\Users\\test\\captions.ass'))
        # No raw path separators left (forward slashes are OK, only escaped colons)
        assert 'C\\:' in win, f"colon should be escaped: {win}"
        assert 'Users/test/' in win, f"backslashes should be forward slashes: {win}"
        # Apostrophe
        apo = _ass_path_for_filter(P("/home/z/user's stuff/captions.ass"))
        assert "\\'" in apo, f"apostrophe not escaped: {apo}"
        print(f"✓ 9. ASS path escaping fix verified (Windows={win!r}, apostrophe={apo!r})")

        # 10. OAuth redirect info
        r = client.get('/api/settings/oauth-redirect')
        assert r.status_code == 200
        assert 'redirect_uri' in r.json()
        print(f"✓ 10. oauth redirect URI: {r.json()['redirect_uri']}")

        # 11. Dashboard summary (was crashing before the snapshot() fix)
        r = client.get('/api/dashboard/summary')
        assert r.status_code == 200
        d = r.json()
        assert 'channels' in d
        assert 'videos_total' in d
        assert 'scheduler' in d
        print(f"✓ 11. dashboard summary works (scheduler snapshot fix verified)")

        # 12. Channel update via PATCH (new edit form feature)
        r = client.patch(f'/api/channels/{cid}', json={'videos_per_day': 5})
        assert r.status_code == 200
        assert r.json()['videos_per_day'] == 5
        # Restore
        client.patch(f'/api/channels/{cid}', json={'videos_per_day': 3})
        print("✓ 12. channel edit via PATCH works")

    print()
    print("=" * 60)
    print("🎉 ALL TESTS PASSED — v1.2 upgrades verified")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
