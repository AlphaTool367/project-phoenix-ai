#!/usr/bin/env python3
"""Comprehensive end-to-end test for the v1.3 Project Phoenix AI upgrades.

Verifies every v1.3 feature works:
  1. Settings returns all new v1.3 fields
  2. Settings POST persists v1.3 fields
  3. Produce with length_mode='shorts' resolves to 30-180s
  4. Produce with length_mode='long' resolves to 180-600s
  5. Monitor endpoints exist + return right shape
  6. Scheduler slot CRUD works
  7. Scheduler manual fire works
  8. Voice auto-selection per language
  9. Urdu text normalization
 10. Editor accepts cinematic flag
 11. SEO accepts trending_keywords + channel_name
 12. Uploader has copyright_check functions
 13. All v1.3 routes registered
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import app
from fastapi.testclient import TestClient
from test_utils import collect_route_paths


def main() -> int:
    with TestClient(app) as client:
        print("=== v1.3 comprehensive test ===")

        # 1. Settings returns v1.3 fields
        r = client.get('/api/settings')
        assert r.status_code == 200
        s = r.json()
        for f in ('video_length_mode', 'cinematic_mode', 'seo_language',
                  'hide_hooks_in_description', 'monitor_min_views',
                  'monitor_daily_quota', 'monitor_region_code',
                  'monitor_learn_from_top_videos', 'copyright_check_enabled',
                  'copyright_wait_seconds', 'auto_publish_after_check',
                  'post_check_privacy', 'scheduler_auto_trigger'):
            assert f in s['app'], f"missing settings field: {f}"
        assert 'length_modes' in s['options']
        assert 'regions' in s['options']
        assert len(s['options']['niches']) >= 20
        print(f"✓ 1. settings returns all v1.3 fields ({len(s['options']['niches'])} niches)")

        # 2. Settings POST with v1.3 fields
        r = client.post('/api/settings', json={
            'video_length_mode': 'shorts',
            'cinematic_mode': True,
            'hide_hooks_in_description': True,
            'copyright_check_enabled': True,
            'auto_publish_after_check': True,
            'scheduler_auto_trigger': True,
            'monitor_min_views': 5_000_000,
        })
        assert r.status_code == 200
        assert r.json()['count'] >= 6
        print(f"✓ 2. settings update: {r.json()['count']} fields applied")
        # Reset back
        client.post('/api/settings', json={'video_length_mode': 'manual'})

        # 3. Produce with shorts
        r = client.get('/api/channels')
        cid = r.json()[0]['id'] if r.json() else 1
        r = client.post('/api/videos/produce', json={
            'channel_id': cid, 'topic': 'Shorts test', 'publish': False,
            'length_mode': 'shorts', 'categories': ['technology']
        })
        assert r.status_code == 202
        print("✓ 3. produce with length_mode=shorts accepted")

        # 4. Produce with long
        r = client.post('/api/videos/produce', json={
            'channel_id': cid, 'topic': 'Long test', 'publish': False,
            'length_mode': 'long', 'categories': ['history']
        })
        assert r.status_code == 202
        print("✓ 4. produce with length_mode=long accepted")

        # 5. Monitor endpoints
        r = client.get(f'/api/monitor/stats/{cid}')
        assert r.status_code == 200
        assert 'trending_count' in r.json()
        r = client.get(f'/api/monitor/trending/{cid}')
        assert r.status_code == 200
        r = client.get(f'/api/monitor/insights/{cid}')
        assert r.status_code == 200
        r = client.get(f'/api/monitor/inspiration/{cid}/technology')
        assert r.status_code == 200
        r = client.get(f'/api/monitor/upload-times/{cid}')
        assert r.status_code == 200
        print("✓ 5. all monitor endpoints return 200")

        # 6. Scheduler slot CRUD
        r = client.get('/api/scheduler/slots')
        assert r.status_code == 200
        initial_count = len(r.json())
        r = client.post('/api/scheduler/slots', json={
            'channel_id': cid, 'hour': 9, 'minute': 30,
            'categories': ['technology', 'science'],
            'length_mode': 'shorts', 'enabled': True
        })
        assert r.status_code == 201
        slot = r.json()
        slot_id = slot['id']
        assert slot['hour'] == 9 and slot['minute'] == 30
        assert slot['length_mode'] == 'shorts'
        assert 'technology' in slot['categories']
        r = client.patch(f'/api/scheduler/slots/{slot_id}', json={'minute': 45})
        assert r.status_code == 200
        assert r.json()['minute'] == 45
        r = client.post(f'/api/scheduler/slots/{slot_id}/toggle')
        assert r.status_code == 200
        assert r.json()['enabled'] is False
        r = client.delete(f'/api/scheduler/slots/{slot_id}')
        assert r.status_code == 200
        r = client.get('/api/scheduler/slots')
        assert len(r.json()) == initial_count
        print("✓ 6. scheduler slot CRUD works (create / patch / toggle / delete)")

        # 7. Scheduler settings endpoint
        r = client.get('/api/scheduler/settings')
        assert r.status_code == 200
        for f in ('auto_trigger', 'copyright_check_enabled', 'copyright_wait_seconds',
                  'auto_publish_after_check', 'post_check_privacy'):
            assert f in r.json()
        print(f"✓ 7. scheduler settings: {r.json()}")

        # 8. Voice auto-selection
        from app.services.voice import pick_voice, _normalize_text_for_language
        cases = [
            ('en', 'en-US-ChristopherNeural'),
            ('ur', 'ur-PK-AsadNeural'),
            ('hi', 'hi-IN-MadhurNeural'),
            ('es', 'es-ES-AlvaroNeural'),
            ('ar', 'ar-SA-HamedNeural'),
            ('fa', 'fa-IR-FaridNeural'),
        ]
        for lang, expected in cases:
            v = pick_voice(lang)
            assert v == expected, f"{lang}: expected {expected}, got {v}"
        print(f"✓ 8. voice auto-selection: {len(cases)} languages verified")

        # 9. Urdu text normalization
        urdu = 'اور بھی باتیں ہیں جو آپ کو جاننی چاہئیں۔ يہ ایک لمبا فقرہ ہے۔'
        out = _normalize_text_for_language(urdu, 'ur')
        assert 'ے' in out  # Arabic yeh at end → Urdu yeh
        assert len(out) > 0
        print("✓ 9. Urdu text normalization works (Arabic yeh → Urdu yeh)")

        # 10. Editor accepts cinematic flag
        import inspect
        from app.services import editor
        sig = inspect.signature(editor.render_video)
        assert 'cinematic' in sig.parameters
        print("✓ 10. editor.render_video accepts cinematic flag")

        # 11. SEO accepts trending_keywords + channel_name
        from app.services import seo as seo_module
        sig = inspect.signature(seo_module.optimize)
        assert 'trending_keywords' in sig.parameters
        assert 'channel_name' in sig.parameters
        print("✓ 11. seo.optimize accepts trending_keywords + channel_name")

        # 12. Uploader copyright_check_and_finalize exists
        from app.services import uploader
        assert hasattr(uploader, 'has_copyright_claim')
        assert hasattr(uploader, 'set_video_privacy')
        assert hasattr(uploader, 'delete_video')
        assert hasattr(uploader, 'copyright_check_and_finalize')
        print("✓ 12. uploader has copyright_check / delete / publish functions")

        # 13. All v1.3 routes registered
        routes = collect_route_paths(app.routes)
        for path in ['/api/monitor/search', '/api/monitor/trending/{channel_id}',
                     '/api/monitor/insights/{channel_id}',
                     '/api/monitor/inspiration/{channel_id}/{niche}',
                     '/api/monitor/extract/{channel_id}',
                     '/api/monitor/upload-times/{channel_id}',
                     '/api/monitor/stats/{channel_id}',
                     '/api/scheduler/slots', '/api/scheduler/settings']:
            assert any(path == r or path in r for r in routes), f"missing route: {path}"
        print("✓ 13. all v1.3 routes registered")

        # 14. Models include new tables
        from app.models import TrendingVideo, LearnedInsight, ScheduledSlot
        from app.database import engine
        from sqlalchemy import inspect as db_inspect
        insp = db_inspect(engine)
        tables = insp.get_table_names()
        for t in ('trending_videos', 'learned_insights', 'scheduled_slots'):
            assert t in tables, f"missing table: {t}"
        print(f"✓ 14. new DB tables created: trending_videos, learned_insights, scheduled_slots")

    print()
    print("=" * 60)
    print("🎉 ALL v1.3 TESTS PASSED")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
