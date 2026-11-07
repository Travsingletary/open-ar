from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import numpy as np

from open_ar.features import feature_vector
from open_ar.schema import AudioFeatures, CompMatch, CompTrack, Goal, SongRatings

FIXTURE_EXCLUDED = "Bundled examples are fixtures, not artist or chart comparisons."
UNVERIFIED_CATALOG = "Comparison catalog is not marked kind=verified and verified=true."
POPULARITY_UNAVAILABLE = (
    "No free popularity source is configured. Soundcharts is paid and is not called. "
    "A popularity number in the catalog is ignored."
)
ACOUSTICBRAINZ_HELD = (
    "AcousticBrainz measurements are CC0 historical descriptors. Collection stopped in 2022. "
    "They are not on the Open A&R scale, so they are not similarity comps."
)
ESSENTIA_HELD = "Essentia models are not used. Commercial licensing has not been checked."


@dataclass(frozen=True)
class Catalog:
    tracks: list[CompTrack]
    kind: str
    verified: bool
    reason: str
    source: str


def load_catalog(path: str | Path | None = None) -> Catalog:
    if path is None:
        data_file = resources.files("open_ar").joinpath("data/seed_comps.json")
        raw = json.loads(data_file.read_text(encoding="utf-8"))
        source = "seed_comps.json"
    else:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        source = str(path)
    tracks = [CompTrack.model_validate(track) for track in raw.get("tracks", [])]
    kind = str(raw.get("kind") or "unspecified")
    verified = raw.get("verified") is True and kind == "verified"
    if verified:
        reason = ""
    elif kind == "fixture":
        reason = FIXTURE_EXCLUDED
    else:
        reason = UNVERIFIED_CATALOG
    return Catalog(tracks=tracks, kind=kind, verified=verified, reason=reason, source=source)


def load_comps(path: str | Path | None = None) -> list[CompTrack]:
    """Return catalog tracks. Fixture tracks are not production recommendations."""
    return load_catalog(path).tracks


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


def _mbid_problem(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    try:
        uuid.UUID(value)
    except ValueError:
        return "musicbrainz_recording_mbid is not a UUID"
    return None


def similarity_problem(track: CompTrack) -> str | None:
    """Why this track cannot answer 'sounds similar'. None means it can."""
    mbid_problem = _mbid_problem(track.musicbrainz_recording_mbid)
    if mbid_problem:
        return mbid_problem
    if not track.permission_cleared:
        return "no permission clearance"
    source = track.measurement_source
    if source == "acousticbrainz":
        return ACOUSTICBRAINZ_HELD
    if source == "essentia":
        return ESSENTIA_HELD
    if source != "open_ar":
        return "measurement_source is not open_ar, so the reference is not compatible with this brief"
    return None


def complete_ratings(track: CompTrack) -> SongRatings | None:
    ratings = track.ratings
    if ratings is None or not ratings.rater.strip():
        return None
    if None in (ratings.drum_impact, ratings.hook, ratings.conviction):
        return None
    return ratings


def split_catalog(tracks: list[CompTrack]) -> tuple[list[CompTrack], list[dict]]:
    usable: list[CompTrack] = []
    held: list[dict] = []
    for track in tracks:
        problem = similarity_problem(track)
        if problem:
            held.append({"id": track.id, "title": track.title, "reason": problem})
        else:
            usable.append(track)
    return usable, held


def build_questions(
    *,
    catalog_verified: bool,
    catalog_reason: str,
    tracks: list[CompTrack],
    matches: list[CompMatch],
    held: list[dict],
) -> dict:
    """Keep sounds-similar, good-song, and currently-popular in separate objects."""
    if not catalog_verified:
        sounds_similar = {
            "status": "unavailable",
            "reason": catalog_reason,
            "method": None,
            "items": [],
            "held": held,
        }
        good_song = {
            "status": "unavailable",
            "reason": catalog_reason,
            "scale": "1-5 listener rating",
            "items": [],
        }
    else:
        if matches:
            sounds_similar = {
                "status": "ok",
                "reason": None,
                "method": "open_ar feature distance",
                "items": [
                    {
                        "id": match.comp.id,
                        "title": match.comp.title,
                        "artist": match.comp.artist,
                        "distance": match.distance,
                        "why": match.why[:3],
                        "musicbrainz_recording_mbid": match.comp.musicbrainz_recording_mbid,
                    }
                    for match in matches
                ],
                "held": held,
            }
        else:
            reason = held[0]["reason"] if len(held) == 1 else (
                "no compatible, permission-cleared Open A&R references"
            )
            sounds_similar = {
                "status": "unavailable",
                "reason": reason,
                "method": None,
                "items": [],
                "held": held,
            }
        rated = []
        for track in tracks:
            if similarity_problem(track) in {
                "no permission clearance",
                "musicbrainz_recording_mbid is not a UUID",
            }:
                continue
            ratings = complete_ratings(track)
            if ratings is None:
                continue
            rated.append(
                {
                    "id": track.id,
                    "title": track.title,
                    "artist": track.artist,
                    "musicbrainz_recording_mbid": track.musicbrainz_recording_mbid,
                    "drum_impact": ratings.drum_impact,
                    "hook": ratings.hook,
                    "conviction": ratings.conviction,
                    "rater": ratings.rater,
                    "scale": "1-5",
                }
            )
        if rated:
            good_song = {
                "status": "rated",
                "reason": None,
                "scale": "1-5 listener rating",
                "items": rated,
            }
        else:
            good_song = {
                "status": "unavailable",
                "reason": "No complete listener ratings for drum impact, hook, and conviction.",
                "scale": "1-5 listener rating",
                "items": [],
            }
    return {
        "sounds_similar": sounds_similar,
        "good_song": good_song,
        "currently_popular": {
            "status": "unavailable",
            "reason": POPULARITY_UNAVAILABLE,
            "source": None,
            "items": [],
        },
    }


def find_comps(
    features: AudioFeatures,
    goal: Goal,
    comps: list[CompTrack],
    k: int = 8,
) -> list[CompMatch]:
    """Nearest neighbors inside a catalog the caller already chose to trust."""
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
