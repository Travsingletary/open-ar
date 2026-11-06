from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import numpy as np

from open_ar.features import feature_vector
from open_ar.schema import AudioFeatures, CompMatch, CompTrack, Goal


def load_comps(path: str | Path | None = None) -> list[CompTrack]:
    if path is None:
        data_file = resources.files("open_ar").joinpath("data/seed_comps.json")
        raw = json.loads(data_file.read_text(encoding="utf-8"))
    else:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [CompTrack.model_validate(t) for t in raw["tracks"]]


def _why(features: AudioFeatures, comp: CompTrack) -> list[str]:
    reasons: list[str] = []
    cf = comp.features
    if abs(features.tempo_bpm - cf.tempo_bpm) <= 8:
        reasons.append(f"tempo near {cf.tempo_bpm:.0f} BPM")
    if abs(features.energy - cf.energy) <= 0.12:
        reasons.append("similar energy")
    if abs(features.danceability - cf.danceability) <= 0.12:
        reasons.append("similar groove feel")
    if abs(features.acousticness - cf.acousticness) <= 0.15:
        reasons.append("similar acoustic/electronic balance")
    if abs(features.duration_sec - cf.duration_sec) <= 25:
        reasons.append("comparable runtime")
    if not reasons:
        reasons.append("nearest overall feature distance")
    return reasons[:3]


def find_comps(
    features: AudioFeatures,
    goal: Goal,
    comps: list[CompTrack] | None = None,
    k: int = 8,
) -> list[CompMatch]:
    comps = comps or load_comps()
    query = feature_vector(features)

    scored: list[tuple[float, CompTrack]] = []
    for comp in comps:
        dist = float(np.linalg.norm(query - feature_vector(comp.features)))
        # Soft prefer comps tagged for the requested goal.
        if goal.value in comp.goal_tags:
            dist *= 0.85
        scored.append((dist, comp))

    scored.sort(key=lambda x: x[0])
    matches: list[CompMatch] = []
    for dist, comp in scored[:k]:
        matches.append(CompMatch(comp=comp, distance=round(dist, 4), why=_why(features, comp)))
    return matches
