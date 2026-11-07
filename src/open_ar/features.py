from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

from open_ar.loudness import integrated_lufs
from open_ar.schema import AudioFeatures

# Pitch-class → rough key label (major assumed when mode unclear).
_KEY_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _clamp01(x: float) -> float:
    return float(np.clip(x, 0.0, 1.0))


def _onset_peak_sec(y: np.ndarray, sr: int) -> float | None:
    """Time of the strongest onset after 8s. This is not a hook."""
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    times = librosa.times_like(onset_env, sr=sr)
    if len(onset_env) < 8:
        return None
    mask = times >= 8.0
    local = onset_env.copy()
    if np.any(mask):
        local[~mask] = 0.0
    peak_idx = int(np.argmax(local))
    if local[peak_idx] <= 0.0:
        return None
    return float(times[peak_idx])


def _estimate_key_mode(y: np.ndarray, sr: int) -> tuple[str | None, str | None, float | None, float | None]:
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_mean = chroma.mean(axis=1)
    total = float(np.sum(chroma_mean)) + 1e-9
    order = np.argsort(chroma_mean)
    root = int(order[-1])
    key_margin = float((chroma_mean[order[-1]] - chroma_mean[order[-2]]) / total)
    major_idx = [(root + i) % 12 for i in (0, 4, 7)]
    minor_idx = [(root + i) % 12 for i in (0, 3, 7)]
    major_e = float(chroma_mean[major_idx].sum())
    minor_e = float(chroma_mean[minor_idx].sum())
    mode = "major" if major_e >= minor_e else "minor"
    mode_margin = float(abs(major_e - minor_e) / (major_e + minor_e + 1e-9))
    return _KEY_NAMES[root], mode, key_margin, mode_margin


def _beat_regularity_from_frames(beats: np.ndarray, sr: int) -> float | None:
    times = librosa.frames_to_time(np.atleast_1d(beats), sr=sr)
    if len(times) < 4:
        return None
    intervals = np.diff(times)
    median = float(np.median(intervals))
    if median <= 0:
        return None
    regularity = 1.0 - float(np.std(intervals) / median)
    return float(np.clip(regularity, 0.0, 1.0))


def _measure_lufs(path: Path) -> tuple[float | None, int | None, str | None]:
    try:
        audio, sample_rate = sf.read(path, always_2d=True, dtype="float64")
    except Exception:
        return None, None, "could not read file channels for LUFS"
    channels = int(audio.shape[1])
    if channels > 5:
        return None, channels, "more than 5 channels; BS.1770 weights are not applied"
    try:
        value = integrated_lufs(audio, int(sample_rate))
    except Exception:
        return None, channels, "BS.1770 meter failed"
    if value is None:
        return None, channels, "signal shorter than one 400 ms block or below the loudness gate"
    return value, channels, None


def extract_features(path: str | Path) -> AudioFeatures:
    """Extract local audio features from a file. No Spotify API required."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    y, sr = librosa.load(path, sr=22050, mono=True)
    duration_sec = float(librosa.get_duration(y=y, sr=sr))

    tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
    tempo_bpm = float(np.atleast_1d(tempo)[0])
    beat_interval_regularity = _beat_regularity_from_frames(beats, sr)

    rms = librosa.feature.rms(y=y)[0]
    mean_rms = float(np.mean(rms))
    energy_raw = mean_rms * 8.0
    energy_saturated = energy_raw >= 1.0
    energy = _clamp01(energy_raw)
    mean_rms_dbfs = float(20.0 * np.log10(max(mean_rms, 1e-12)))

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
    novelty_peak_sec = _onset_peak_sec(y, sr)
    key, mode, key_margin, mode_margin = _estimate_key_mode(y, sr)
    lufs, lufs_channels, lufs_note = _measure_lufs(path)

    return AudioFeatures(
        duration_sec=duration_sec,
        tempo_bpm=tempo_bpm,
        energy=energy,
        danceability=danceability,
        brightness=brightness,
        acousticness=acousticness,
        speechiness=speechiness,
        dynamic_range=dynamic_range,
        hook_onset_sec=None,
        hook_verified=False,
        novelty_peak_sec=novelty_peak_sec,
        loudness_db=loudness_db,
        rms_rel_peak_db=loudness_db,
        mean_rms_dbfs=mean_rms_dbfs,
        energy_saturated=energy_saturated,
        integrated_lufs=lufs,
        lufs_channels=lufs_channels,
        lufs_note=lufs_note,
        tempo_octave_ambiguous=True,
        beat_interval_regularity=beat_interval_regularity,
        key_margin=key_margin,
        mode_margin=mode_margin,
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
            (features.hook_onset_sec or 0.0) / 60.0 if features.hook_verified else 0.0,
        ],
        dtype=float,
    )
    return raw
