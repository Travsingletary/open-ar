from __future__ import annotations

from open_ar.schema import AudioFeatures, CompMatch, FitScore, Gap, Goal, Play


def score_fit(features: AudioFeatures, goal: Goal, comps: list[CompMatch]) -> FitScore:
    rationale: list[str] = []
    score = 0.5

    goal_comps = [c for c in comps if goal.value in c.comp.goal_tags]
    if not comps:
        rationale.append("no verified comparison catalog; fit does not use reference tracks")
    elif goal_comps:
        avg_dist = sum(c.distance for c in goal_comps[:3]) / max(len(goal_comps[:3]), 1)
        proximity = max(0.0, 1.0 - avg_dist)
        score = 0.35 + 0.65 * proximity
        rationale.append(f"avg distance to top {goal.value} comps: {avg_dist:.3f}")
    else:
        rationale.append(f"verified catalog has no tracks tagged {goal.value}")

    if goal in (Goal.playlist, Goal.lead_single):
        if 150 <= features.duration_sec <= 210:
            score += 0.05
            rationale.append("runtime in common streaming single window")
        if features.hook_verified and features.hook_onset_sec is not None:
            if features.hook_onset_sec <= 25:
                score += 0.05
                rationale.append("verified hook arrives within 25s")
            else:
                score -= 0.08
                rationale.append("verified hook arrives after 25s")
        else:
            rationale.append("hook timing unavailable; onset peak is not scored as a hook")

    if goal == Goal.club:
        if features.danceability >= 0.7 and features.energy >= 0.7:
            score += 0.08
            rationale.append("energy/danceability in club band")
        else:
            score -= 0.1
            rationale.append("energy or groove below typical club comps")

    if goal == Goal.sync:
        if features.dynamic_range >= 0.55:
            score += 0.06
            rationale.append("dynamics leave room for picture")
        if features.speechiness <= 0.2:
            score += 0.04
            rationale.append("low speech density helps underscoring")

    if goal == Goal.cult:
        # Cult rewards distance from mainstream playlist comps.
        playlistish = [c for c in comps if "playlist" in c.comp.goal_tags]
        if playlistish and playlistish[0].distance > 0.35:
            score += 0.08
            rationale.append("stands apart from playlist-shaped comps")

    return FitScore(goal=goal, score=float(max(0.0, min(1.0, score))), rationale=rationale)


def detect_gaps(features: AudioFeatures, goal: Goal, comps: list[CompMatch]) -> list[Gap]:
    gaps: list[Gap] = []

    if (
        goal in (Goal.playlist, Goal.lead_single)
        and features.hook_verified
        and features.hook_onset_sec is not None
        and features.hook_onset_sec > 30
    ):
        gaps.append(
            Gap(
                code="late_hook",
                severity="high",
                message=f"Verified hook at {features.hook_onset_sec:.0f}s — consider moving the motif earlier.",
            )
        )
    elif goal in (Goal.playlist, Goal.lead_single) and not features.hook_verified:
        peak = features.novelty_peak_sec
        where = f" at {peak:.1f}s" if peak is not None else ""
        gaps.append(
            Gap(
                code="hook_unverified",
                severity="high",
                message=(
                    f"No verified hook. Strongest onset peak{where} is not a hook "
                    "and is not a cut point."
                ),
            )
        )

    if goal in (Goal.playlist, Goal.lead_single) and features.duration_sec > 240:
        gaps.append(
            Gap(
                code="long_runtime",
                severity="medium",
                message=f"Runtime {features.duration_sec/60:.1f}m is long for a lead streaming cut — consider a radio edit.",
            )
        )

    if goal == Goal.club and features.energy < 0.65:
        gaps.append(
            Gap(
                code="low_club_energy",
                severity="high",
                message=(
                    f"Energy proxy {features.energy:.2f} is below 0.65. "
                    "The proxy is mean RMS times 8, clipped at 1. It is not LUFS."
                ),
            )
        )

    if goal == Goal.sync and features.dynamic_range < 0.4:
        gaps.append(
            Gap(
                code="crushed_dynamics",
                severity="medium",
                message="Dynamics look crushed for picture — deliver a less-limited stem pack.",
            )
        )

    if not comps:
        gaps.append(
            Gap(
                code="comps_unavailable",
                severity="info",
                message="No verified comparison catalog. Fixture examples are not recommendations.",
            )
        )
    elif comps[0].distance > 0.55:
        gaps.append(
            Gap(
                code="weak_comp_neighborhood",
                severity="low",
                message="Far from the supplied comparison tracks. That is distance, not a chart position.",
            )
        )

    return gaps


def build_plays(
    features: AudioFeatures,
    goal: Goal,
    fit: FitScore,
    gaps: list[Gap],
    comps: list[CompMatch],
) -> list[Play]:
    plays: list[Play] = []
    gap_codes = {g.code for g in gaps}
    top = comps[:3]
    pitch_list = [f"{c.comp.title} — {c.comp.artist} ({c.comp.outcome})" for c in top]
    comp_action = (
        f"Sounds-similar references, not a quality or popularity ranking: {', '.join(pitch_list)}."
        if pitch_list
        else "No compatible permission-cleared comparison library. Do not cite fixture artists."
    )

    if goal in (Goal.playlist, Goal.lead_single):
        if "late_hook" in gap_codes or "long_runtime" in gap_codes:
            cut_action = (
                "Cut a streaming edit under ~3:30. Hook placement is unverified, so this does not mark a cut."
                if not features.hook_verified
                else "Cut a streaming edit: verified hook by ~0:20, total under ~3:30."
            )
            plays.append(
                Play(
                    primary=True,
                    title="Hold wide release — ship a shorter cut first",
                    actions=[
                        "Duration or a verified late hook is the reason. Do not cut at an onset peak.",
                        cut_action,
                        "Re-run open-ar on the edit before pitching.",
                    ],
                    evidence=[g.message for g in gaps if g.code in {"late_hook", "long_runtime"}],
                )
            )
            plays.append(
                Play(
                    primary=False,
                    title="Alternate: soft launch to owned audience",
                    actions=[
                        "Drop to mailing list / Discord first; measure completion rate.",
                        "Use early listeners to validate hook timing before playlist pitch.",
                    ],
                    evidence=["Fit score under playlist pressure with structure gaps."],
                )
            )
        elif "hook_unverified" in gap_codes:
            plays.append(
                Play(
                    primary=True,
                    title="Hook unverified — do not trim to the onset peak",
                    actions=[
                        "No intro cut is proposed. An onset peak is not a hook mark.",
                        comp_action,
                        "Add a verified hook mark before asking for an edit.",
                    ],
                    evidence=[g.message for g in gaps if g.code == "hook_unverified"],
                )
            )
        else:
            plays.append(
                Play(
                    primary=True,
                    title="Release path from measured signals",
                    actions=[
                        "Package one-sheet with the measured tempo estimate, key estimate, and LUFS if present.",
                        comp_action,
                        "Do not schedule the pitch around an unverified onset peak.",
                    ],
                    evidence=fit.rationale[:3],
                )
            )
            plays.append(
                Play(
                    primary=False,
                    title="Feature / remix lane",
                    actions=[
                        "If first-week velocity stalls, commission a dance or regional remix.",
                        "Keep original as album cut; remix as DSP single.",
                    ],
                    evidence=["Insurance path when editorial adds are slow."],
                )
            )

    elif goal == Goal.club:
        if "low_club_energy" in gap_codes:
            plays.append(
                Play(
                    primary=True,
                    title="Remix before club push",
                    actions=[
                        "Commission a DJ/extended mix (intro/outro for blending).",
                        "Target 120–128 BPM feel or half-time trap club lane explicitly.",
                        "Service DJs with WAV + stamped cue points.",
                    ],
                    evidence=[g.message for g in gaps if g.code == "low_club_energy"],
                )
            )
        else:
            plays.append(
                Play(
                    primary=True,
                    title="DJ service + club playlist push",
                    actions=[
                        "Deliver extended mix + radio edit.",
                        comp_action,
                        "Seed with 10–20 DJs before DSP push.",
                    ],
                    evidence=fit.rationale[:3],
                )
            )
        plays.append(
            Play(
                primary=False,
                title="Retarget to playlist/lead if remix budget is zero",
                actions=["Re-analyze with --goal playlist and judge the streaming edit path."],
                evidence=["Club lane needs production/mix commitment."],
            )
        )

    elif goal == Goal.sync:
        plays.append(
            Play(
                primary=True,
                title="Sync packaging",
                actions=[
                    "Export instrumental, no-lead-vocal, and 30/60s cuts.",
                    "Tag mood/BPM/key clearly; avoid crushed masters for picture.",
                    "Pitch to libraries/supervisors with scene uses (drive, resolve, tension).",
                ],
                evidence=fit.rationale[:3] + [g.message for g in gaps],
            )
        )
        plays.append(
            Play(
                primary=False,
                title="Consumer release still fine",
                actions=["Release normally but keep stem pack ready for inbound sync."],
                evidence=["Sync and consumer paths are not mutually exclusive."],
            )
        )

    else:  # cult
        plays.append(
            Play(
                primary=True,
                title="Cult / community path",
                actions=[
                    "Lean into difference in artwork and narrative — do not sand edges for playlist norms.",
                    "Release with lore, limited merch, or visual world-building.",
                    "Measure saves/comments depth over raw skip-rate.",
                ],
                evidence=fit.rationale[:3],
            )
        )
        plays.append(
            Play(
                primary=False,
                title="Selective remix bridge",
                actions=["One accessible edit for outsiders; keep album version weird."],
                evidence=["Optional bridge without abandoning identity."],
            )
        )

    # Ensure exactly one primary.
    if plays and not any(p.primary for p in plays):
        plays[0].primary = True
    return plays
