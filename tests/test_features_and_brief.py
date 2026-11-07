from pathlib import Path

import numpy as np
import soundfile as sf

import json

from open_ar.brief import build_brief
from open_ar.comps import load_catalog
from open_ar.features import extract_features
from open_ar.schema import Goal


def _write_tone(path: Path, seconds: float = 12.0, sr: int = 22050, bpm: float = 120.0) -> Path:
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    # Pulse-ish tone so onset/beat trackers have something to grab.
    beat_hz = bpm / 60.0
    amp = 0.35 + 0.35 * (np.sin(2 * np.pi * beat_hz * t) > 0).astype(float)
    y = amp * np.sin(2 * np.pi * 220.0 * t)
    # Louder section after 3s to create a novelty peak.
    y[int(3 * sr) :] *= 1.4
    sf.write(path, y.astype(np.float32), sr)
    return path


def test_extract_features_from_wav(tmp_path: Path):
    wav = _write_tone(tmp_path / "tone.wav")
    feats = extract_features(wav)
    assert feats.duration_sec > 10
    assert 60 < feats.tempo_bpm < 180
    assert 0.0 <= feats.energy <= 1.0
    assert feats.key is not None
    assert feats.hook_verified is False
    assert feats.hook_onset_sec is None
    assert feats.integrated_lufs is not None
    assert feats.integrated_lufs < 0
    assert feats.rms_rel_peak_db is not None
    assert feats.mean_rms_dbfs is not None


def test_build_brief_excludes_fixture_comps(tmp_path: Path):
    wav = _write_tone(tmp_path / "song.wav", seconds=14.0)
    brief = build_brief(wav, goal=Goal.playlist)
    payload = brief.to_pretty_dict()
    assert payload["goal"] == "playlist"
    assert payload["comps_status"] == "unavailable"
    assert payload["comps"] == []
    assert "Seed Artist" not in payload["comps_reason"]
    assert "fixture" in payload["comps_reason"]
    dumped = brief.model_dump_json()
    assert "Seed Artist" not in dumped
    assert len(payload["plays"]) >= 1
    assert any(p["primary"] for p in payload["plays"])
    assert payload["features"]["hook_verified"] is False


def test_only_a_verified_catalog_is_used(tmp_path: Path):
    wav = _write_tone(tmp_path / "song.wav", seconds=12.0)
    features = {
        "duration_sec": 180,
        "tempo_bpm": 100,
        "energy": 0.5,
        "danceability": 0.5,
        "brightness": 0.4,
        "acousticness": 0.3,
        "speechiness": 0.1,
        "dynamic_range": 0.5,
    }
    verified = tmp_path / "verified.json"
    verified.write_text(
        json.dumps(
            {
                "kind": "verified",
                "verified": True,
                "tracks": [
                    {
                        "id": "ref-1",
                        "title": "Reference Cut",
                        "artist": "Known Act",
                        "genre": "pop",
                        "goal_tags": ["playlist"],
                        "outcome": "in_house_reference",
                        "measurement_source": "open_ar",
                        "permission_cleared": True,
                        "permission_note": "Reference file supplied by the catalog owner.",
                        "features": features,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    brief = build_brief(wav, goal=Goal.playlist, comps_path=verified)
    assert brief.comps_status == "ok"
    assert brief.comps[0].comp.artist == "Known Act"

    relabeled = tmp_path / "fixture.json"
    seed = load_catalog()
    relabeled.write_text(
        json.dumps(
            {
                "kind": "fixture",
                "verified": True,
                "tracks": [
                    {
                        "id": track.id,
                        "title": track.title,
                        "artist": track.artist,
                        "genre": track.genre,
                        "goal_tags": track.goal_tags,
                        "outcome": track.outcome,
                        "features": track.features.model_dump(),
                    }
                    for track in seed.tracks[:1]
                ],
            }
        ),
        encoding="utf-8",
    )
    excluded = build_brief(wav, goal=Goal.playlist, comps_path=relabeled)
    assert excluded.comps_status == "unavailable"
    assert excluded.comps == []
    assert excluded.questions["currently_popular"]["status"] == "unavailable"
    assert excluded.questions["currently_popular"]["items"] == []
