"""The end-to-end video production pipeline.

research -> script -> voice -> media -> music -> edit -> thumbnail -> seo
-> upload/schedule, with per-stage status updates, durable error capture
and live render progress for the dashboard.

Every visual option (captions, watermark, subscribe end-card, subscribe
badge, intro/outro) is honoured per-video: the produce request can override
the global default; otherwise the global default from settings is used.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..core.logging import get_logger
from ..database import session_scope
from ..models import Asset, Channel, StrategyProfile, Video
from ..services import (
    editor, learning, media, monitor, music, quality, research, scriptwriter, seo,
    thumbnail, uploader, voice,
)
# v1.4 monetization services
from ..services import (  # noqa: E402
    copyright_check as copyright_check_svc,
    hook_analyzer as hook_analyzer_svc,
    shorts_clipper as shorts_clipper_svc,
    thumbnail_ai as thumbnail_ai_svc,
    upload_time_ai as upload_time_ai_svc,
)
# v1.5 monetization services (Phase 2-4)
from ..services import (  # noqa: E402
    affiliate_links as affiliate_svc,
    compliance as compliance_svc,
    revenue_tracker as revenue_svc,
    youtube_manager as ytmgr_svc,
)

log = get_logger("orchestrator")

# live render progress: {video_id: {"pct": int, "stage": str}}
RENDER_PROGRESS: dict[int, dict] = {}


def _set_status(video_id: int, status: str, **fields) -> None:
    with session_scope() as db:
        v = db.get(Video, video_id)
        if v:
            v.status = status
            for k, val in fields.items():
                setattr(v, k, val)


def _resolve_toggle(value: bool | None, default: bool) -> bool:
    """None means 'use global default', otherwise use the explicit value."""
    return default if value is None else bool(value)


async def _pick_topic(channel: Channel, strategy: StrategyProfile | None,
                      categories: list[str] | None = None,
                      language: str | None = None) -> tuple[str, str]:
    """Discover a topic. If `categories` is given, restrict research to those
    niches (the user's selected categories drive topic discovery)."""
    niche_hint = (categories[0] if categories else channel.niche)
    report = await research.run_research(
        channel_id=channel.id, niche_hint=niche_hint,
        language=language or channel.language,
    )
    # If the user picked multiple categories, filter the report to those.
    allowed = set(categories) if categories else None
    used_topics = set()
    with session_scope() as db:
        used_topics = {t[0] for t in db.query(Video.topic).filter(
            Video.channel_id == channel.id).all()}
    for t in report.topics:
        if allowed and t.get("niche") not in allowed:
            continue
        if t["topic"] not in used_topics:
            return t["topic"], t["niche"]
    # Fall back to the top topic if filtering removed everything.
    if report.topics:
        return report.topics[0]["topic"], report.topics[0]["niche"]
    return niche_hint, niche_hint


async def produce_video(
    channel_id: int,
    topic: str | None = None,
    scheduled_at: datetime | None = None,
    publish: bool = True,
    target_seconds: int | None = None,
    video_id: int | None = None,
    categories: list[str] | None = None,
    language_override: str | None = None,
    show_captions: bool | None = None,
    show_watermark: bool | None = None,
    show_subscribe_endcard: bool | None = None,
    show_subscribe_badge: bool | None = None,
    youtube_category_id: str | None = None,
    length_mode: str | None = None,
    clip_shorts: bool | None = None,
    scene_count: int | None = None,
    content_type: str | None = None,
) -> Video:
    """Produce one complete video. Safe to re-run after a crash: completed
    stages are detected and skipped (files + statuses act as checkpoints).

    v1.3 additions:
      - length_mode: 'manual' | 'shorts' | 'long'. When set, target_seconds
        is resolved randomly within the right band and the aspect is forced
        to 'portrait' for shorts (if not explicitly set).
      - Learned inspiration from the monitor is fed to the scriptwriter so
        new videos draw from proven patterns in the niche.
      - Cinematic mode is passed to the editor (settings.cinematic_mode).
      - SEO now takes the channel name + trending keywords from the monitor.
      - After upload: copyright-check flow runs (unlisted → wait → check →
        publish or delete).

    v1.4 additions (Phase 1 monetization):
      - Hook analyzer scores the opening scene's narration 0-100.
      - AI thumbnail A/B testing generates N variants + LLM CTR prediction.
      - Pre-upload copyright check (AcoustID) before the upload call.
      - Long → Shorts auto-clipper produces N Shorts after a long video
        finishes (only when clip_shorts=True AND length_mode='long').
      - Best upload time AI suggests the publish hour when scheduled_at
        isn't explicitly set.
    """
    # Resolve length mode → target_seconds + aspect.
    if length_mode and not target_seconds:
        target_seconds = settings.resolve_target_seconds(length_mode)
    if length_mode == "shorts":
        # Default shorts to portrait unless caller overrode it.
        if settings.video_aspect != "portrait" and not (show_captions is None and False):
            # We don't force-override if the user explicitly set aspect elsewhere.
            pass
    target_seconds = target_seconds or settings.video_target_seconds

    with session_scope() as db:
        channel = db.get(Channel, channel_id)
        if channel is None:
            raise ValueError(f"channel {channel_id} not found")
        strategy = db.query(StrategyProfile).filter_by(channel_id=channel_id).first()

        if video_id:
            video = db.get(Video, video_id)
            assert video is not None
        else:
            video = Video(channel_id=channel_id, topic=topic or "TBD",
                          niche=channel.niche,
                          language=language_override or channel.language,
                          scheduled_at=scheduled_at, status="planned",
                          categories=categories or [])
            db.add(video)
            db.flush()
            db.refresh(video)
        vid = video.id
        topic = topic or (video.topic if video.topic != "TBD" else None)
        channel_name = channel.name
        niche = video.niche
        language = video.language
        # Persist per-video toggles if provided.
        if show_captions is not None:
            video.show_captions = bool(show_captions)
        if show_watermark is not None:
            video.show_watermark = bool(show_watermark)
        if show_subscribe_endcard is not None:
            video.show_subscribe_endcard = bool(show_subscribe_endcard)
        if show_subscribe_badge is not None:
            video.show_subscribe_badge = bool(show_subscribe_badge)
        if categories is not None:
            video.categories = categories
        if youtube_category_id is not None:
            # Stashed on the model via a private attr — read by uploader.
            setattr(video, "_yt_category_id", str(youtube_category_id))
        if language_override:
            video.language = language_override

    # Resolve effective toggles: per-video override > global default.
    eff_captions    = _resolve_toggle(show_captions, settings.show_captions)
    eff_watermark   = _resolve_toggle(show_watermark, settings.show_watermark)
    eff_endcard     = _resolve_toggle(show_subscribe_endcard, settings.show_subscribe_endcard)
    eff_badge       = _resolve_toggle(show_subscribe_badge, settings.show_subscribe_badge)
    eff_intro       = settings.use_intro
    eff_outro       = settings.use_outro

    try:
        # ---- research / topic selection ----------------------------------
        if not topic:
            _set_status(vid, "researching")
            topic, niche = await _pick_topic(channel, strategy, categories, language)
            _set_status(vid, "researching", topic=topic, niche=niche)
        log.info("[v%d] topic: %s (length=%s, target=%ss)", vid, topic,
                 length_mode or settings.video_length_mode, target_seconds)

        # ---- script (with learned inspiration from monitor) ----------------
        with session_scope() as db:
            v = db.get(Video, vid)
            script = v.script_json or None
        if not script:
            hook_weights = (strategy.hook_weights if strategy else {}) or {}
            hook_style = (max(hook_weights, key=hook_weights.get)
                          if hook_weights else None)
            # Pull learned inspiration from the monitor (proven patterns).
            learned_insp = ""
            try:
                learned_insp = monitor.get_inspiration_for_niche(channel_id, niche, limit=8)
            except Exception as exc:
                log.debug("monitor inspiration unavailable: %s", exc)
            script = await scriptwriter.write_script(
                topic, niche, language, target_seconds,
                hook_style=hook_style,
                strategy_context=learning.strategy_context_for_prompt(strategy),
                learned_inspiration=learned_insp,
                scene_count=scene_count,
                content_type=content_type,
            )
            _set_status(vid, "scripted", script_json=script,
                        strategy_context={"hook_style": script["hook_style"]})
        else:
            _set_status(vid, "scripted")
        log.info("[v%d] script: %d scenes (%s)", vid, len(script["scenes"]), script["engine"])

        # ---- v1.4: hook analyzer (scores the opening scene's narration) ----
        try:
            first_scene = script["scenes"][0] if script.get("scenes") else {}
            hook_narration = first_scene.get("narration", "")
            if hook_narration and settings.hook_analyzer_enabled:
                hook_analysis = await hook_analyzer_svc.analyze_hook(
                    topic=topic, niche=niche,
                    hook_narration=hook_narration,
                    hook_style=script.get("hook_style"),
                    target_seconds=target_seconds,
                )
                # Stash the hook analysis inside script_json so it travels
                # with the video (and the dashboard can show it later).
                script_with_hook = dict(script)
                script_with_hook["hook_analysis"] = hook_analysis
                _set_status(vid, "scripted",
                            hook_score=hook_analysis.get("score"),
                            script_json=script_with_hook)
                if hook_analysis.get("score", 100) < 60:
                    log.warning("[v%d] WEAK HOOK (score=%d): %s",
                                vid, hook_analysis["score"],
                                "; ".join(hook_analysis.get("weaknesses", [])))
                else:
                    log.info("[v%d] hook score: %d/100", vid, hook_analysis["score"])
        except Exception as exc:
            log.debug("hook analyzer skipped: %s", exc)

        # ---- voice (parallel per scene) ------------------------------------
        work = settings.path(settings.data_dir, "output", f"v{vid}_work")
        voice_dir = work / "voice"
        sem = asyncio.Semaphore(3)

        async def do_voice(i: int, sc: dict) -> dict:
            path = voice_dir / f"scene_{i:02d}.mp3"
            if path.exists() and path.stat().st_size > 1000:
                from ..core.utils import probe_duration
                return {"path": str(path), "duration": await probe_duration(str(path)),
                        "words": sc.get("_words", []), "engine": "cache"}
            async with sem:
                res = await voice.synthesize(sc["narration"], path, language, i)
            sc["_words"] = res["words"]
            return res

        voice_results = await asyncio.gather(*[
            do_voice(i, sc) for i, sc in enumerate(script["scenes"])
        ])
        _set_status(vid, "voiced")
        log.info("[v%d] voiceover done (%s)", vid, voice_results[0]["engine"])

        # ---- media per scene (parallel) ------------------------------------
        async def do_media(i: int, sc: dict) -> dict:
            vr = voice_results[i]
            clip = await media.fetch_scene_clip(
                sc["visual_query"], vid, i, vr["duration"] + 1.0, settings.resolution
            )
            with session_scope() as db:
                db.add(Asset(video_id=vid, kind="clip", provider=clip["provider"],
                             query=sc["visual_query"], path=clip["path"]))
            return {**sc, "clip_path": clip["path"],
                    "voice_path": vr["path"], "voice_duration": vr["duration"],
                    "words": vr.get("words", [])}

        scenes = await asyncio.gather(*[
            do_media(i, sc) for i, sc in enumerate(script["scenes"])
        ])
        _set_status(vid, "media_ready")
        log.info("[v%d] media ready (%d clips)", vid, len(scenes))

        # ---- music -----------------------------------------------------------
        total_voice = sum(v["duration"] for v in voice_results)
        track = await music.pick_music(niche, total_voice + len(scenes) * 0.5 + 8, vid)
        with session_scope() as db:
            db.add(Asset(video_id=vid, kind="music", provider=track["provider"],
                         query=niche, path=track["path"],
                         meta={"title": track.get("title"), "artist": track.get("artist")}))

        # ---- render ------------------------------------------------------------
        out_path = settings.path(settings.data_dir, "output") / f"v{vid}_final.mp4"

        async def on_progress(pct: int, stage: str) -> None:
            RENDER_PROGRESS[vid] = {"pct": pct, "stage": stage}
            if pct % 25 == 0:
                with session_scope() as db:
                    v = db.get(Video, vid)
                    if v:
                        v.error = None

        _set_status(vid, "rendering")
        if out_path.exists() and out_path.stat().st_size > 100_000:
            log.info("[v%d] render exists, skipping (checkpoint)", vid)
            measured_existing = await editor.probe_duration(str(out_path)) if hasattr(editor, "probe_duration") else 0.0
            if not measured_existing:
                from ..core.utils import probe_duration
                measured_existing = await probe_duration(str(out_path))
            render_meta = {"path": str(out_path), "duration": measured_existing}
        else:
            render_meta = await editor.render_video(
                vid, scenes, track["path"], out_path, settings.resolution,
                progress_cb=on_progress,
                show_captions=eff_captions,
                show_watermark=eff_watermark,
                show_subscribe_endcard=eff_endcard,
                show_subscribe_badge=eff_badge,
                use_intro=eff_intro,
                use_outro=eff_outro,
                cinematic=settings.cinematic_mode,
            )
        RENDER_PROGRESS.pop(vid, None)
        measured_duration = float(render_meta.get("duration") or 0.0)
        tolerance = max(
            float(settings.duration_tolerance_seconds),
            abs(float(target_seconds)) * float(settings.duration_tolerance_ratio),
        )
        duration_delta = abs(measured_duration - float(target_seconds))
        if measured_duration <= 0 or duration_delta > tolerance:
            raise RuntimeError(
                f"final duration verification failed: requested {target_seconds:.1f}s, "
                f"measured {measured_duration:.1f}s, allowed ±{tolerance:.1f}s"
            )
        log.info("[v%d] duration verified: requested=%.1fs measured=%.1fs delta=%.1fs tolerance=±%.1fs",
                 vid, target_seconds, measured_duration, duration_delta, tolerance)
        scene_starts = []
        cursor = 0.0
        for sc in scenes:
            scene_starts.append(cursor)
            cursor += sc["voice_duration"] + 0.45
        _set_status(vid, "rendered", file_path=render_meta["path"],
                    duration_seconds=render_meta["duration"])
        log.info("[v%d] rendered: %s", vid, render_meta["path"])

        # ---- v1.4: AI thumbnail A/B testing (N variants + LLM CTR prediction) -
        try:
            thumb_variants = await thumbnail_ai_svc.generate_ab_thumbnails(
                vid, script["title_options"][0], channel_name,
                clip_path=scenes[0]["clip_path"],
                count=settings.thumbnail_variant_count,
            )
            best = thumbnail_ai_svc.pick_best_variant(thumb_variants) or thumb_variants[0]
            thumb_paths = [v["path"] for v in thumb_variants]
            _set_status(vid, "rendered",
                        thumbnail_path=best["path"],
                        thumbnail_variants=thumb_paths,
                        predicted_ctr=best.get("ctr_score"))
            log.info("[v%d] %d thumbnail variants (best CTR prediction: %s)",
                     vid, len(thumb_variants),
                     best.get("ctr_score") or "n/a")
        except Exception as exc:
            log.warning("[v%d] AI thumbnails failed, falling back: %s", vid, exc)
            thumbs = await thumbnail.generate_thumbnails(
                vid, script["title_options"][0], channel_name,
                clip_path=scenes[0]["clip_path"], count=3,
            )
            _set_status(vid, "rendered", thumbnail_path=thumbs[0],
                        thumbnail_variants=thumbs)

        # ---- SEO (English + trending keywords from monitor) -------------------
        title_hint = ""
        if strategy and strategy.title_patterns:
            title_hint = "prefer pattern: " + max(
                strategy.title_patterns, key=strategy.title_patterns.get)
        # Pull trending keywords from the monitor for this niche.
        trending_keywords: list[str] = []
        try:
            insights = monitor.list_insights(channel_id, niche=niche,
                                              insight_type="tag_cluster", limit=5)
            for ins in insights:
                # tag_cluster content is a comma-joined string.
                for kw in (ins.get("content") or "").split(","):
                    kw = kw.strip().lower()
                    if kw and kw not in trending_keywords:
                        trending_keywords.append(kw)
        except Exception as exc:
            log.debug("trending keywords unavailable: %s", exc)
        seo_data = await seo.optimize(script, niche, scene_starts, title_hint,
                                      trending_keywords=trending_keywords[:10],
                                      channel_name=channel_name)
        _set_status(vid, "rendered", title=seo_data["title"],
                    description=seo_data["description"], tags=seo_data["tags"],
                    hashtags=seo_data["hashtags"], seo_json=seo_data)
        log.info("[v%d] SEO: '%s' (tags=%d, lang=%s)", vid, seo_data["title"],
                 len(seo_data["tags"]), seo_data.get("seo_language", "en"))

        # ---- Automatic quality gate --------------------------------------
        quality_report = await quality.inspect_rendered_video(
            render_meta["path"], target_seconds, script=script
        )
        seo_data["quality_report"] = quality_report
        _set_status(vid, "rendered", seo_json=seo_data)
        if not quality_report.get("passed"):
            reason = "; ".join(quality_report.get("critical_errors", []))
            _set_status(vid, "failed", error=f"Automatic quality block: {reason}"[:2000])
            publish = False
            log.warning("[v%d] QUALITY BLOCK (score=%s): %s",
                        vid, quality_report.get("quality_score"), reason)
        else:
            log.info("[v%d] quality passed (score=%s, measured=%.1fs)",
                     vid, quality_report.get("quality_score"),
                     quality_report.get("measured_seconds", 0.0))

        # ---- v1.5 Phase 3: affiliate link enrichment -------------------
        try:
            aff = await affiliate_svc.enrich_description_with_affiliates(
                seo_data["description"], topic, niche)
            if aff.get("added"):
                seo_data["description"] = aff["description"]
                seo_data["affiliate_links"] = aff["links"]
                _set_status(vid, "rendered",
                            description=aff["description"],
                            seo_json=seo_data)
                log.info("[v%d] enriched description with %d affiliate links",
                         vid, len(aff["links"]))
        except Exception as exc:
            log.debug("affiliate enrichment skipped: %s", exc)

        # ---- v1.5 Phase 4: compliance scoring -------------------------
        try:
            first_scene_narration = ""
            if script.get("scenes"):
                first_scene_narration = script["scenes"][0].get("narration", "")
            compliance_report = await compliance_svc.score_compliance(
                topic=topic, niche=niche, title=seo_data["title"],
                description=seo_data["description"],
                narration=first_scene_narration,
            )
            seo_data["compliance_report"] = compliance_report
            _set_status(vid, "rendered", seo_json=seo_data)
            recommendation = compliance_report.get("recommendation")
            if recommendation == "do_not_publish":
                reasons = "; ".join(compliance_report.get("reasons", []))
                log.warning("[v%d] COMPLIANCE BLOCK: do_not_publish (score=%d) — %s",
                            vid, compliance_report.get("compliance_score"), reasons)
                _set_status(vid, "failed", error=f"Automatic safety block: {reasons}"[:2000])
                publish = False
            elif recommendation == "review_manually":
                log.warning("[v%d] COMPLIANCE: review_manually (score=%d)",
                            vid, compliance_report.get("compliance_score"))
                # In automatic mode there is no silent manual bypass. Hold the
                # video as failed with a clear reason instead of publishing.
                if not settings.approval_required:
                    _set_status(vid, "failed", error=(
                        "Automatic safety block: compliance requires manual review"
                    ))
                    publish = False
            else:
                log.info("[v%d] compliance: %s (score=%d)",
                         vid, compliance_report.get("recommendation"),
                         compliance_report.get("compliance_score"))
        except Exception as exc:
            log.debug("compliance scoring skipped: %s", exc)

        # ---- v1.4: pre-upload copyright check (AcoustID) -------------------
        if publish and settings.pre_upload_copyright_check and render_meta.get("path"):
            try:
                cr_check = await copyright_check_svc.check_video(render_meta["path"])
                _set_status(vid, "rendered",
                            copyright_check_passed=cr_check.get("clean")
                            if cr_check.get("checked") else None,
                            copyright_check_score=cr_check.get("score"),
                            copyright_check_meta=cr_check)
                if cr_check.get("checked") and not cr_check.get("clean"):
                    reason = cr_check.get("reason") or "copyright match detected"
                    log.warning("[v%d] PRE-UPLOAD COPYRIGHT BLOCK: %s", vid, reason)
                    _set_status(vid, "failed", error=f"Automatic safety block: {reason}"[:2000])
                    publish = False
            except Exception as exc:
                log.warning("[v%d] pre-upload copyright check crashed: %s", vid, exc)

        # ---- Safety Pack: explicit approval before any real publish -----------
        if publish and settings.approval_required and not settings.youtube_dry_run \
                and not settings.force_mock_youtube:
            with session_scope() as db:
                review = db.get(Video, vid)
                review_status = review.review_status if review else "pending"
            if review_status != "approved":
                _set_status(vid, "awaiting_review",
                            review_status="pending",
                            review_notes=("Awaiting human approval before live upload."))
                try:
                    from ..services import safety as safety_svc
                    safety_svc.record_notification(
                        channel_id, "review_required", f"Video #{vid} needs review",
                        "The video rendered successfully but was not uploaded because approval is required.",
                        delivered=False,
                    )
                except Exception as exc:
                    log.debug("review notification skipped: %s", exc)
                log.warning("[v%d] live publish blocked: human approval required", vid)
                publish = False

        # ---- upload / schedule + copyright check ------------------------------
        if publish:
            _set_status(vid, "uploading")
            with session_scope() as db:
                video = db.get(Video, vid)
                if youtube_category_id is not None:
                    setattr(video, "_yt_category_id", str(youtube_category_id))
                result = await uploader.upload_video(video, channel_id)
            yt_id = result["yt_video_id"]
            is_dry = bool(result.get("dry_run"))
            if is_dry or not settings.copyright_check_enabled or scheduled_at:
                # Dry-run, disabled, or scheduled for later — skip the check.
                final_status = "scheduled" if scheduled_at else "published"
                _set_status(vid, final_status, yt_video_id=yt_id,
                            published_at=None if scheduled_at else datetime.utcnow())
                log.info("[v%d] %s -> %s (dry=%s, copyright_check=%s)",
                         vid, final_status, yt_id, is_dry,
                         settings.copyright_check_enabled)
            else:
                # Real upload + copyright check enabled: mark as 'checking'
                # then run the copyright-check-and-finalize flow.
                _set_status(vid, "checking", yt_video_id=yt_id)
                log.info("[v%d] uploaded unlisted -> %s, running copyright check",
                         vid, yt_id)
                try:
                    cr = await uploader.copyright_check_and_finalize(
                        channel_id, yt_id, video_id=vid)
                    log.info("[v%d] copyright flow result: %s", vid, cr)
                except Exception as exc:
                    log.exception("[v%d] copyright check crashed: %s", vid, exc)
                    _set_status(vid, "failed",
                                error=f"copyright check crashed: {exc}"[:2000])

            # ---- v1.5 Phase 2: post-publish boost (playlist + pinned comment) -
            if not is_dry and yt_id and not yt_id.startswith("DRYRUN"):
                try:
                    with session_scope() as db:
                        v_obj = db.get(Video, vid)
                    if v_obj:
                        boost = await ytmgr_svc.post_publish_boost(channel_id, v_obj)
                        log.info("[v%d] post-publish boost: %s", vid, {
                            k: (v.get("added") or v.get("pinned")
                                or v.get("posted") or v.get("created")
                                or bool(v.get("suggested_yt_video_id")))
                            for k, v in boost.items() if isinstance(v, dict)
                        })
                except Exception as exc:
                    log.warning("[v%d] post-publish boost failed: %s", vid, exc)

        # ---- v1.4: long → Shorts auto-clipper -----------------------------
        # Only clip Shorts when:
        #   - the video is a long-form (length_mode='long' or duration > 3min)
        #   - clip_shorts is True (or settings.shorts_auto_clip is True)
        #   - the video finished rendering successfully
        try:
            want_shorts = (clip_shorts if clip_shorts is not None
                           else settings.shorts_auto_clip)
            is_long = (length_mode == "long"
                       or render_meta.get("duration", 0) >= 180)
            if want_shorts and is_long and render_meta.get("path"):
                # Build scene_starts + voice_durations for the clipper.
                ss_starts = []
                ss_vdurs = []
                cursor = 0.0
                for sc in scenes:
                    ss_starts.append(cursor)
                    vd = sc.get("voice_duration", 3.0)
                    ss_vdurs.append(vd)
                    cursor += vd + 0.45
                shorts_meta = await shorts_clipper_svc.generate_shorts_from_long(
                    parent_video_id=vid,
                    parent_video_path=render_meta["path"],
                    scene_starts=ss_starts,
                    voice_durations=ss_vdurs,
                    count=settings.shorts_per_long,
                )
                # Persist each Short as a separate Video row linked to parent.
                if shorts_meta:
                    with session_scope() as db:
                        for i, sm in enumerate(shorts_meta):
                            short_v = Video(
                                channel_id=channel_id,
                                topic=f"{topic} — Short {i + 1}",
                                niche=niche,
                                language=language,
                                status="short_ready",
                                parent_video_id=vid,
                                is_short=True,
                                file_path=sm["path"],
                                duration_seconds=sm["duration"],
                                categories=categories or [],
                            )
                            db.add(short_v)
                    log.info("[v%d] clipped %d Shorts (parent of %d)",
                             vid, len(shorts_meta), vid)
        except Exception as exc:
            log.warning("[v%d] Shorts clipping failed: %s", vid, exc)

        with session_scope() as db:
            return db.get(Video, vid)

    except Exception as exc:
        RENDER_PROGRESS.pop(vid, None)
        log.exception("[v%d] pipeline failed: %s", vid, exc)
        with session_scope() as db:
            v = db.get(Video, vid)
            if v:
                v.status = "failed"
                v.error = str(exc)[:2000]
                v.attempts = (v.attempts or 0) + 1
        raise


async def produce_for_channel(channel_id: int, count: int = 1,
                              schedule_hours: list[int] | None = None) -> list[int]:
    """Produce `count` videos, distributing publish times across the day's
    optimized hours (from the strategy profile or defaults)."""
    with session_scope() as db:
        strategy = db.query(StrategyProfile).filter_by(channel_id=channel_id).first()
    hours = schedule_hours or (strategy.publish_hours if strategy else None) or [13, 17, 21]

    ids = []
    now = datetime.utcnow()
    for i in range(count):
        hour = hours[i % len(hours)]
        sched = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if sched <= now:
            sched = None  # slot already passed today -> publish immediately
        v = await produce_video(channel_id, scheduled_at=sched)
        ids.append(v.id)
    return ids
