from __future__ import annotations

from pathlib import Path

from open_ar.comps import find_comps, load_comps
from open_ar.features import extract_features
from open_ar.playbook import build_plays, detect_gaps, score_fit
from open_ar.schema import ARBrief, AudioFeatures, Goal


def build_brief(
    track_path: str | Path,
    goal: Goal | str = Goal.playlist,
    comps_path: str | Path | None = None,
    features: AudioFeatures | None = None,
) -> ARBrief:
    goal = Goal(goal) if isinstance(goal, str) else goal
    track_path = Path(track_path)
    feats = features or extract_features(track_path)
    comps_catalog = load_comps(comps_path) if comps_path else load_comps()
    matches = find_comps(feats, goal, comps=comps_catalog)
    fit = score_fit(feats, goal, matches)
    gaps = detect_gaps(feats, goal, matches)
    plays = build_plays(feats, goal, fit, gaps, matches)
    return ARBrief(
        track_path=str(track_path),
        goal=goal,
        features=feats,
        comps=matches,
        fit=fit,
        gaps=gaps,
        plays=plays,
    )
