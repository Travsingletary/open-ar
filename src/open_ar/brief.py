from __future__ import annotations

from pathlib import Path

from open_ar.comps import build_questions, find_comps, load_catalog, split_catalog
from open_ar.evidence import load_attention_evidence
from open_ar.features import extract_features
from open_ar.marketing import load_marketing_notes
from open_ar.playbook import build_plays, detect_gaps, score_fit
from open_ar.schema import ARBrief, AudioFeatures, Goal


def build_brief(
    track_path: str | Path,
    goal: Goal | str = Goal.playlist,
    comps_path: str | Path | None = None,
    features: AudioFeatures | None = None,
    marketing_path: str | Path | None = None,
    trends_path: str | Path | None = None,
    analytics_path: str | Path | None = None,
) -> ARBrief:
    goal = Goal(goal) if isinstance(goal, str) else goal
    track_path = Path(track_path)
    feats = features or extract_features(track_path)
    catalog = load_catalog(comps_path)
    if catalog.verified:
        usable, held = split_catalog(catalog.tracks)
        matches = find_comps(feats, goal, comps=usable) if usable else []
        if matches:
            comps_status = "ok"
            comps_reason = None
        else:
            comps_status = "unavailable"
            comps_reason = (
                held[0]["reason"]
                if len(held) == 1
                else "no compatible, permission-cleared Open A&R references"
            )
    else:
        matches = []
        held = []
        comps_status = "unavailable"
        comps_reason = catalog.reason
    questions = build_questions(
        catalog_verified=catalog.verified,
        catalog_reason=catalog.reason,
        tracks=catalog.tracks if catalog.verified else [],
        matches=matches,
        held=held,
    )
    fit = score_fit(feats, goal, matches)
    gaps = detect_gaps(feats, goal, matches)
    plays = build_plays(feats, goal, fit, gaps, matches)
    # Notes and attention rows are attached after fit, distance, comps, and ratings are fixed.
    marketing_notes = load_marketing_notes(marketing_path)
    attention_evidence = load_attention_evidence(trends_path, analytics_path)
    return ARBrief(
        track_path=str(track_path),
        goal=goal,
        features=feats,
        comps=matches,
        comps_status=comps_status,
        comps_reason=comps_reason,
        comparison_held=held,
        questions=questions,
        marketing_notes=marketing_notes,
        attention_evidence=attention_evidence,
        fit=fit,
        gaps=gaps,
        plays=plays,
    )
