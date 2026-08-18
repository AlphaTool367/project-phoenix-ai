#!/usr/bin/env python3
"""Verify the two publish-policy modes without performing a real upload."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as client:
    before = client.get('/api/settings').json()['app']
    original = bool(before.get('approval_required', True))

    automatic = client.post('/api/settings', json={'approval_required': False})
    assert automatic.status_code == 200, automatic.text
    after_automatic = client.get('/api/settings').json()['app']
    assert after_automatic['approval_required'] is False

    manual = client.post('/api/settings', json={'approval_required': True})
    assert manual.status_code == 200, manual.text
    after_manual = client.get('/api/settings').json()['app']
    assert after_manual['approval_required'] is True

    restored = client.post('/api/settings', json={'approval_required': original})
    assert restored.status_code == 200, restored.text
    final = client.get('/api/settings').json()['app']
    assert bool(final['approval_required']) == original

print('UPLOAD POLICY MODE TEST PASSED: automatic -> manual -> restored')
