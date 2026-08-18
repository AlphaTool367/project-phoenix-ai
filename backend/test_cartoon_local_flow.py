#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.services import cartoon_downloader
from app.core.utils import ffprobe_bin

SOURCE = Path('data/output/v8_final.mp4')

async def main() -> None:
    assert SOURCE.exists() and SOURCE.stat().st_size > 1000, SOURCE
    result = await cartoon_downloader.process_cartoon_to_shorts(
        str(SOURCE), max_shorts=1, short_duration=15, channel_id=1)
    assert result.get('success'), result
    assert result.get('shorts') and Path(result['shorts'][0]['path']).exists(), result
    out = result['shorts'][0]['path']
    probe = subprocess.run([
        ffprobe_bin(), '-v', 'error', '-show_streams', '-of', 'json', out
    ], capture_output=True, text=True, check=True)
    streams = json.loads(probe.stdout)['streams']
    video = next(s for s in streams if s['codec_type'] == 'video')
    audio = next(s for s in streams if s['codec_type'] == 'audio')
    assert (video['width'], video['height']) == (1080, 1920), video
    assert audio['codec_name'] == 'aac', audio
    print(json.dumps({
        'cartoon_local_flow': True,
        'path': out,
        'shorts': result['count'],
        'resolution': [video['width'], video['height']],
        'audio': audio['codec_name'],
        'copyright_checked': result['shorts'][0]['copyright_check'].get('checked'),
    }))

asyncio.run(main())
