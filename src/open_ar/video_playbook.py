from __future__ import annotations

from open_ar.schema import (
    AudioFeatures,
    Gap,
    Play,
    VideoFeatures,
    VideoFitScore,
    VideoGoal,
)


def score_video_fit(video: VideoFeatures, audio: AudioFeatures, goal: VideoGoal) -> VideoFitScore:
    rationale: list[str] = []
    score = 0.5

    if goal == VideoGoal.youtube_mv:
        if video.aspect == "horizontal":
            score += 0.08
            rationale.append("horizontal frame suits YouTube MV")
        else:
            score -= 0.05
            rationale.append("non-horizontal — consider a 16:9 master for YouTube")
        if video.opening_15s_energy >= 0.25 or (video.first_cut_sec is not None and video.first_cut_sec <= 8):
            score += 0.07
            rationale.append("opening has motion / early cut for retention")
        else:
            score -= 0.1
            rationale.append("opening looks static — YouTube drop-off risk in first 15s")
        if video.audio_sync_basis == "verified_hook" and video.audio_hook_visual_sync >= 0.6:
            score += 0.08
            rationale.append("visual peak/cut near a verified audio hook")
        elif video.audio_sync_basis == "verified_hook":
            score -= 0.06
            rationale.append("picture peak is off the verified audio hook")
        else:
            rationale.append("hook sync not scored; an onset peak is not a verified hook")

    elif goal == VideoGoal.short_form:
        if video.aspect == "vertical":
            score += 0.1
            rationale.append("vertical frame fits Shorts/Reels/TikTok")
        else:
            score -= 0.08
            rationale.append("horizontal master — need a vertical crop/reframe")
        if video.opening_3s_energy >= 0.3 or (video.first_cut_sec is not None and video.first_cut_sec <= 2.5):
            score += 0.1
            rationale.append("fast open — good for short-form cold start")
        else:
            score -= 0.12
            rationale.append("first 3s too quiet visually for short-form")
        if audio.hook_verified and audio.hook_onset_sec is not None and audio.hook_onset_sec <= 12:
            score += 0.05
            rationale.append("verified audio hook is early enough to land in a 15–30s cut")
        elif not audio.hook_verified:
            rationale.append("hook timing unavailable for the short-form cut")

    elif goal == VideoGoal.premiere:
        if video.duration_sec >= 150:
            score += 0.05
            rationale.append("runtime supports a premiere event")
        if video.cuts_per_minute >= 4:
            score += 0.05
            rationale.append("cut density keeps a premiere audience watching")
        if video.opening_15s_energy < 0.2:
            score -= 0.08
            rationale.append("premiere cold open needs a stronger first beat of picture")

    else:  # visualizer
        if video.scene_cut_count <= 3 and video.visual_energy <= 0.45:
            score += 0.1
            rationale.append("low cut density fits visualizer / waveform lane")
        else:
            score -= 0.05
            rationale.append("cutty edit — may be overbuilt for a simple visualizer drop")

    rationale.append(f"cuts/min={video.cuts_per_minute:.1f}, visual_energy={video.visual_energy:.2f}")
    return VideoFitScore(goal=goal, score=float(max(0.0, min(1.0, score))), rationale=rationale)


def detect_video_gaps(video: VideoFeatures, audio: AudioFeatures, goal: VideoGoal) -> list[Gap]:
    gaps: list[Gap] = []

    if goal in (VideoGoal.youtube_mv, VideoGoal.premiere) and video.opening_15s_energy < 0.2:
        gaps.append(
            Gap(
                code="dull_open",
                severity="high",
                message="First 15s look static — front-load a cut, lyric, or performer move.",
            )
        )

    if goal == VideoGoal.short_form and video.aspect != "vertical":
        gaps.append(
            Gap(
                code="wrong_aspect",
                severity="high",
                message=f"Aspect is {video.aspect} ({video.width}x{video.height}) — cut a 9:16 for short-form.",
            )
        )

    if goal == VideoGoal.short_form and video.opening_3s_energy < 0.25:
        gaps.append(
            Gap(
                code="slow_short_open",
                severity="high",
                message="First 3s lack visual punch — short-form viewers bail before the hook.",
            )
        )

    if video.audio_sync_basis == "verified_hook" and video.audio_hook_visual_sync < 0.45:
        hook_at = audio.hook_onset_sec if audio.hook_onset_sec is not None else 0.0
        gaps.append(
            Gap(
                code="hook_picture_mismatch",
                severity="medium",
                message=(
                    f"Verified audio hook ~{hook_at:.0f}s vs peak picture ~{video.peak_visual_sec:.0f}s."
                ),
            )
        )
    elif video.audio_sync_basis != "verified_hook":
        peak = audio.novelty_peak_sec
        where = f" Onset peak at {peak:.1f}s is not a hook." if peak is not None else ""
        gaps.append(
            Gap(
                code="hook_unverified",
                severity="info",
                message=f"Picture sync was not scored against a hook.{where}",
            )
        )

    if goal == VideoGoal.youtube_mv and video.duration_sec > 0 and video.cuts_per_minute < 2:
        gaps.append(
            Gap(
                code="static_edit",
                severity="low",
                message="Very few scene cuts — fine for performance film, risky for algorithm retention.",
            )
        )

    if goal == VideoGoal.youtube_mv and video.aspect == "vertical":
        gaps.append(
            Gap(
                code="vertical_on_youtube",
                severity="medium",
                message="Vertical master on YouTube MV — also publish a 16:9 crop or letterbox intentionally.",
            )
        )

    return gaps


def suggest_clip_windows(video: VideoFeatures, audio: AudioFeatures) -> list[dict]:
    """Suggest short-form windows anchored on hook / peak visual."""
    anchor, basis = audio.timing_anchor()
    peak = video.peak_visual_sec
    if anchor is None:
        center = peak
        anchor_note = "hook unavailable"
    else:
        center = anchor if abs(anchor - peak) < 8 else peak
        anchor_note = (
            f"verified hook {anchor:.0f}s"
            if basis == "verified_hook"
            else f"onset peak {anchor:.0f}s (not a verified hook)"
        )
    windows = []
    for length, label in ((15.0, "15s short"), (30.0, "30s short"), (60.0, "1-min cut")):
        start = max(0.0, center - length * 0.35)
        end = min(video.duration_sec, start + length)
        start = max(0.0, end - length)
        windows.append(
            {
                "label": label,
                "start_sec": round(start, 2),
                "end_sec": round(end, 2),
                "why": f"centered near {anchor_note} / peak picture ({peak:.0f}s)",
            }
        )
    # Thumbnail / still suggestion
    thumb_t = peak if peak > 1 else max(anchor or 0.0, 3.0)
    windows.append(
        {
            "label": "thumbnail still",
            "start_sec": round(thumb_t, 2),
            "end_sec": round(thumb_t, 2),
            "why": "highest visual motion. Not a verified hook frame.",
        }
    )
    return windows


def build_video_plays(
    video: VideoFeatures,
    audio: AudioFeatures,
    goal: VideoGoal,
    fit: VideoFitScore,
    gaps: list[Gap],
    clip_windows: list[dict],
) -> list[Play]:
    gap_codes = {g.code for g in gaps}
    short = next((w for w in clip_windows if w["label"] == "15s short"), None)
    thumb = next((w for w in clip_windows if w["label"] == "thumbnail still"), None)

    plays: list[Play] = []

    if goal == VideoGoal.youtube_mv:
        if "dull_open" in gap_codes or "hook_picture_mismatch" in gap_codes:
            plays.append(
                Play(
                    primary=True,
                    title="Re-edit before wide YouTube push",
                    actions=[
                        "Move a strong visual hit onto the audio hook / first chorus.",
                        "Replace the cold open with title card + performer / lyric in under 5s.",
                        f"Test thumbnail frame near {thumb['start_sec']:.0f}s." if thumb else "A/B two thumbnails.",
                        "Ship Shorts/Reels cut from the suggested 15s window the same day as the MV.",
                    ],
                    evidence=[g.message for g in gaps] + fit.rationale[:2],
                )
            )
            plays.append(
                Play(
                    primary=False,
                    title="Soft premiere while edit finishes",
                    actions=[
                        "Premiere to owned audience / Discord with feedback form.",
                        "Use comments to pick the short-form moment before public push.",
                    ],
                    evidence=["Preserve momentum without locking a weak open on YouTube."],
                )
            )
        else:
            plays.append(
                Play(
                    primary=True,
                    title="YouTube MV release package",
                    actions=[
                        "Schedule premiere; pin comment with streaming links + credits.",
                        f"Export thumbnail around {thumb['start_sec']:.0f}s and one alternate." if thumb else "Export 2 thumbnails.",
                        f"Cut vertical short {short['start_sec']:.0f}–{short['end_sec']:.0f}s for Shorts/Reels." if short else "Cut a 15s vertical.",
                        "End screen: next video + subscribe; chapters at verse/chorus if story-driven.",
                    ],
                    evidence=fit.rationale[:3],
                )
            )
            plays.append(
                Play(
                    primary=False,
                    title="Paid boost only after organic retention check",
                    actions=[
                        "Watch first 24h audience retention; if first 30s holds, then boost.",
                        "Do not spend until cold-open drop-off is acceptable.",
                    ],
                    evidence=["Spend follows retention evidence, not upload day hype."],
                )
            )

    elif goal == VideoGoal.short_form:
        plays.append(
            Play(
                primary=True,
                title="Short-form cut + post pack",
                actions=[
                    f"Export 9:16 from {short['start_sec']:.0f}–{short['end_sec']:.0f}s." if short else "Export a 15s 9:16.",
                    "First frame must have motion or text — no logo hold.",
                    "Post 3 variants (hook-first, lyric-first, face-first) across 72 hours.",
                    "CTA in caption: full MV / streaming link — not in the first 1s of audio.",
                ],
                evidence=fit.rationale[:3] + [g.message for g in gaps],
            )
        )
        plays.append(
            Play(
                primary=False,
                title="If vertical reframe is weak",
                actions=[
                    "Shoot a one-take vertical performance for the hook instead of cropping the MV.",
                    "Use MV as B-roll only.",
                ],
                evidence=["Cropping a wide narrative MV often kills composition."],
            )
        )

    elif goal == VideoGoal.premiere:
        plays.append(
            Play(
                primary=True,
                title="Premiere event playbook",
                actions=[
                    "Announce 48–72h ahead with countdown sticker / community post.",
                    "Host live chat; drop merch or streaming link at chorus #1.",
                    "Clip the chat-highlight moment into a Short within an hour after premiere.",
                ],
                evidence=fit.rationale[:3],
            )
        )
        plays.append(
            Play(
                primary=False,
                title="If open is soft",
                actions=["Start premiere with a 10s teaser montage, then roll the full MV."],
                evidence=[g.message for g in gaps if g.code == "dull_open"],
            )
        )

    else:  # visualizer
        plays.append(
            Play(
                primary=True,
                title="Visualizer / audio-first YouTube",
                actions=[
                    "Keep picture simple; optimize title/thumbnail for the song search terms.",
                    "Chapters optional; focus on Content ID / official audio SEO.",
                    "Still cut one vertical hook clip for discovery — visualizer alone rarely spreads.",
                ],
                evidence=fit.rationale[:3],
            )
        )
        plays.append(
            Play(
                primary=False,
                title="Upgrade path",
                actions=["If the short-form clip outperforms, greenlight a real performance MV."],
                evidence=["Let distribution data fund the next video budget."],
            )
        )

    if plays and not any(p.primary for p in plays):
        plays[0].primary = True
    return plays
