"""Import a user-supplied AcousticBrainz low-level JSON file.

AcousticBrainz low-level descriptors are CC0 historical measurements indexed
by a MusicBrainz recording MBID. Collection stopped in 2022. They are not on
the Open A&R scale. This importer stores identity plus a held historical
block. It does not call AcousticBrainz, MusicBrainz, or Essentia, and it does
not copy those numbers into the feature fields find_comps reads.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from open_ar.schema import AudioFeatures, CompTrack

DATASET_FROZEN = "2022"
LICENSE = "CC0"
SOURCE = "acousticbrainz"
_SCALAR_LIMIT = 50


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unused_features() -> AudioFeatures:
    """Placeholder features. None of these numbers come from the imported file."""
    return AudioFeatures(
        duration_sec=0.0,
        tempo_bpm=0.0,
        energy=0.0,
        danceability=0.0,
        brightness=0.0,
        acousticness=0.0,
        speechiness=0.0,
        dynamic_range=0.0,
        hook_onset_sec=None,
        hook_verified=False,
    )


def _as_list(value: object) -> list:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _first_text(value: object) -> str:
    for item in _as_list(value):
        if isinstance(item, str) and item.strip():
            return item.strip()
    return ""


def _recording_mbid(tags: dict) -> tuple[str | None, str | None]:
    raw = _first_text(tags.get("musicbrainz_recordingid"))
    if not raw:
        return None, "musicbrainz_recordingid was not in the file"
    try:
        parsed = uuid.UUID(raw)
    except ValueError:
        return None, "musicbrainz_recordingid in the file is not a UUID"
    return str(parsed), None


def _scalars(node: object, prefix: str, out: dict[str, object], arrays: list[str]) -> None:
    if len(out) >= _SCALAR_LIMIT or not isinstance(node, dict):
        return
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            out[path] = value
        elif isinstance(value, str) and len(value) <= 80:
            out[path] = value
        elif isinstance(value, dict):
            _scalars(value, path, out, arrays)
        elif isinstance(value, list):
            arrays.append(path)
        if len(out) >= _SCALAR_LIMIT:
            return


def import_lowlevel_json(path: str | Path) -> dict:
    """Read one local low-level JSON file and return a held catalog row."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"AcousticBrainz JSON not found: {file_path}")
    parsed = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("AcousticBrainz JSON must be an object.")
    lowlevel = parsed.get("lowlevel")
    if not isinstance(lowlevel, dict):
        raise ValueError(
            "Only a local AcousticBrainz low-level JSON is accepted. "
            "A file without a lowlevel object is not imported."
        )
    metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
    version = metadata.get("version") if isinstance(metadata.get("version"), dict) else {}
    tags = metadata.get("tags") if isinstance(metadata.get("tags"), dict) else {}
    essentia = version.get("essentia")
    extractor = version.get("extractor")
    essentia_version = essentia.strip() if isinstance(essentia, str) and essentia.strip() else None
    file_feature_version = extractor.strip() if isinstance(extractor, str) and extractor.strip() else None
    mbid, mbid_reason = _recording_mbid(tags)
    scalars: dict[str, object] = {}
    arrays: list[str] = []
    _scalars(lowlevel, "lowlevel", scalars, arrays)
    digest = _sha256(file_path)
    title = _first_text(tags.get("title")) or "AcousticBrainz low-level import"
    historical = {
        "source": SOURCE,
        "dataset_frozen": DATASET_FROZEN,
        "license": LICENSE,
        "file_feature_version": file_feature_version,
        "file_feature_version_reason": None
        if file_feature_version
        else "feature version was not in the file",
        "essentia_version": essentia_version,
        "essentia_version_reason": None if essentia_version else "essentia version was not in the file",
        "file_path": str(file_path.resolve()),
        "sha256": digest,
        "musicbrainz_recording_mbid": mbid,
        "recording_id_reason": mbid_reason,
        "tag_artist": _first_text(tags.get("artist")) or None,
        "scalar_descriptors": scalars,
        "arrays_omitted": bool(arrays),
        "scalars_truncated": len(scalars) >= _SCALAR_LIMIT,
        "note": (
            "Held historical block. These values are not Open A&R features and "
            "find_comps does not read them."
        ),
    }
    track = CompTrack(
        id=f"ab-{digest[:16]}",
        title=title,
        artist="Local import",
        genre="unspecified",
        goal_tags=[],
        outcome="held_historical",
        features=_unused_features(),
        notes=(
            "Imported from a local AcousticBrainz low-level JSON. "
            "Feature fields are unused placeholders. Not a similarity comp."
        ),
        musicbrainz_recording_mbid=mbid,
        measurement_source=SOURCE,
        permission_cleared=False,
        permission_note=(
            "CC0 covers the AcousticBrainz measurement, not a license to use the recording as a comp."
        ),
        feature_version=None,
        produced_by="acousticbrainz_import",
        historical=historical,
        ratings=None,
    )
    return track.model_dump(mode="json")


def add_to_catalog(lowlevel_path: str | Path, catalog_path: str | Path) -> dict:
    """Append or replace the held row in a local catalog. No network."""
    track = import_lowlevel_json(lowlevel_path)
    destination = Path(catalog_path)
    if destination.exists():
        raw = json.loads(destination.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Catalog must be a JSON object.")
    else:
        raw = {
            "kind": "verified",
            "verified": True,
            "note": (
                "Local catalog. AcousticBrainz imports are held historical measurements, "
                "not similarity comps. This file was written from a local JSON and did not "
                "call AcousticBrainz."
            ),
            "tracks": [],
        }
    tracks = raw.get("tracks")
    if not isinstance(tracks, list):
        raise ValueError("Catalog tracks must be a list.")
    replaced = False
    for index, existing in enumerate(tracks):
        if isinstance(existing, dict) and existing.get("id") == track["id"]:
            tracks[index] = track
            replaced = True
            break
    if not replaced:
        tracks.append(track)
    raw["tracks"] = tracks
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return {"track": track, "catalog": str(destination), "replaced": replaced, "held": True}
