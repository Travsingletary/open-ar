from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np

from open_ar.schema import AudioFeatures

# Pitch-class → rough key label (major assumed when mode unclear).
_KEY_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _clamp01(x: float) -> float:
    return float(np.clip(x, 0.0, 1.0))


def _estimate_hook_onset(y: np.ndarray, sr: int) -> float:
    """First strong novelty peak after a short intro window — proxy for hook entry."""
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    times = librosa.times_like(onset_env, sr=sr)
    if len(onset_env) < 8:
        return 0.0
    # Ignore first ~8s as cold open / spoken intro territory.
    mask = times >= 8.0
    if not np.any(mask):
        return float(times[int(np.argmax(onset_env))])
    local = onset_env.copy()
    local[~mask] = 0.0
    peak_idx = int(np.argmax(local))
    return float(times[peak_idx])


def _estimate_key_mode(y: np.ndarray, sr: int) -> tuple[str | None, str | None]:
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_mean = chroma.mean(axis=1)
    root = int(np.argmax(chroma_mean))
    # Crude major/minor: compare major vs minor triad energy relative to root.
    major_idx = [(root + i) % 12 for i in (0, 4, 7)]
    minor_idx = [(root + i) % 12 for i in (0, 3, 7)]
    major_e = float(chroma_mean[major_idx].sum())
    minor_e = float(chroma_mean[minor_idx].sum())
    mode = "major" if major_e >= minor_e else "minor"
    return _KEY_NAMES[root], mode


def extract_features(path: str | Path) -> AudioFeatures:
    """Extract local audio features from a file. No Spotify API required."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    y, sr = librosa.load(path, sr=22050, mono=True)
    duration_sec = float(librosa.get_duration(y=y, sr=sr))

    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    tempo_bpm = float(np.atleast_1d(tempo)[0])

    rms = librosa.feature.rms(y=y)[0]
    energy = _clamp01(float(np.mean(rms) * 8.0))

    # Danceability proxy: tempo in common dance bands + beat strength.
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    beat_strength = float(np.mean(onset_env) / (np.max(onset_env) + 1e-9))
    tempo_fit = 1.0 - min(abs(tempo_bpm - 120.0), abs(tempo_bpm - 100.0), abs(tempo_bpm - 140.0)) / 60.0
    danceability = _clamp01(0.55 * beat_strength + 0.45 * max(tempo_fit, 0.0))

    centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
    brightness = _clamp01(float(np.mean(centroid) / 4000.0))

    # Acousticness proxy: high spectral flatness + lower high-band energy → more acoustic-ish.
    flatness = librosa.feature.spectral_flatness(y=y)[0]
    acousticness = _clamp01(1.0 - float(np.mean(flatness)) * 4.0)

    zcr = librosa.feature.zero_crossing_rate(y)[0]
    speechiness = _clamp01(float(np.mean(zcr) * 6.0))

    # Dynamic range: percentile spread of RMS in dB, normalized.
    rms_safe = np.maximum(rms, 1e-8)
    loud_db = librosa.amplitude_to_db(rms_safe, ref=np.max)
    dr = float(np.percentile(loud_db, 95) - np.percentile(loud_db, 10))
    dynamic_range = _clamp01(dr / 40.0)
    loudness_db = float(np.mean(loud_db))

    hook_onset_sec = _estimate_hook_onset(y, sr)
    key, mode = _estimate_key_mode(y, sr)

    return AudioFeatures(
        duration_sec=duration_sec,
        tempo_bpm=tempo_bpm,
        energy=energy,
        danceability=danceability,
        brightness=brightness,
        acousticness=acousticness,
        speechiness=speechiness,
        dynamic_range=dynamic_range,
        hook_onset_sec=hook_onset_sec,
        loudness_db=loudness_db,
        key=key,
        mode=mode,
    )


FEATURE_VECTOR_KEYS = (
    "tempo_bpm",
    "energy",
    "danceability",
    "brightness",
    "acousticness",
    "speechiness",
    "dynamic_range",
    "duration_sec",
    "hook_onset_sec",
)


def feature_vector(features: AudioFeatures) -> np.ndarray:
    """Normalized vector for nearest-neighbor comps."""
    raw = np.array(
        [
            features.tempo_bpm / 200.0,
            features.energy,
            features.danceability,
            features.brightness,
            features.acousticness,
            features.speechiness,
            features.dynamic_range,
            features.duration_sec / 360.0,
            features.hook_onset_sec / 60.0,
        ],
        dtype=float,
    )
    return raw
