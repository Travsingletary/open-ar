from pathlib import Path

import numpy as np
import soundfile as sf

from open_ar.brief import build_brief
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


def test_build_brief_json_roundtrip(tmp_path: Path):
    wav = _write_tone(tmp_path / "song.wav", seconds=14.0)
    brief = build_brief(wav, goal=Goal.playlist)
    payload = brief.to_pretty_dict()
    assert payload["goal"] == "playlist"
    assert payload["fit"]["score"] >= 0
    assert len(payload["comps"]) >= 3
    assert len(payload["plays"]) >= 1
    assert any(p["primary"] for p in payload["plays"])
