"""Integrated loudness in LUFS, ITU-R BS.1770-4.

K-weighting coefficients follow Brecht De Man's formulation, the one
commonly used to satisfy the EBU R 128 stereo 1 kHz check. Channel
weights are the five BS.1770 weights. This is a measurement, not a master.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

_BLOCK_SEC = 0.400
_OVERLAP = 0.75
_ABSOLUTE_GATE_LUFS = -70.0
_CHANNEL_WEIGHTS = (1.0, 1.0, 1.0, 1.41, 1.41)


def integrated_lufs(samples: np.ndarray, sample_rate: int) -> float | None:
    """Return integrated LUFS, or None when the file cannot be gated.

    `samples` is mono `(n,)` or `(n, channels)` in channel order
    Left, Right, Center, Left surround, Right surround. More than five
    channels returns None.
    """
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1:
        audio = audio[:, None]
    if audio.ndim != 2 or audio.shape[1] < 1 or audio.shape[1] > 5:
        return None
    if sample_rate <= 0 or audio.shape[0] < int(_BLOCK_SEC * sample_rate):
        return None

    weighted = np.empty_like(audio)
    for channel in range(audio.shape[1]):
        weighted[:, channel] = _k_weight(audio[:, channel], sample_rate)

    powers = _block_mean_squares(weighted, sample_rate)
    if powers.size == 0:
        return None
    weights = np.asarray(_CHANNEL_WEIGHTS[: audio.shape[1]], dtype=np.float64)
    loudness = _block_loudness(powers, weights)
    absolute = np.flatnonzero(loudness >= _ABSOLUTE_GATE_LUFS)
    if absolute.size == 0:
        return None
    relative_gate = _sum_loudness(powers[absolute], weights) - 10.0
    kept = np.flatnonzero((loudness > relative_gate) & (loudness > _ABSOLUTE_GATE_LUFS))
    if kept.size == 0:
        return None
    value = _sum_loudness(powers[kept], weights)
    if not np.isfinite(value):
        return None
    return float(value)


def _k_weight(channel: np.ndarray, sample_rate: int) -> np.ndarray:
    shelf_b, shelf_a = _high_shelf(sample_rate)
    highpass_b, highpass_a = _high_pass(sample_rate)
    shelved = lfilter(shelf_b, shelf_a, channel)
    return lfilter(highpass_b, highpass_a, shelved)


def _high_shelf(sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
    frequency = 1681.9744509555319
    gain_db = 3.99984385397
    quality = 0.7071752369554193
    k = np.tan(np.pi * frequency / sample_rate)
    vh = 10.0 ** (gain_db / 20.0)
    vb = vh ** 0.499666774155
    a0 = 1.0 + k / quality + k * k
    b = np.array(
        [
            (vh + vb * k / quality + k * k) / a0,
            2.0 * (k * k - vh) / a0,
            (vh - vb * k / quality + k * k) / a0,
        ]
    )
    a = np.array([1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / quality + k * k) / a0])
    return b, a


def _high_pass(sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
    frequency = 38.13547087613982
    quality = 0.5003270373253953
    k = np.tan(np.pi * frequency / sample_rate)
    denominator = 1.0 + k / quality + k * k
    b = np.array([1.0, -2.0, 1.0])
    a = np.array([1.0, 2.0 * (k * k - 1.0) / denominator, (1.0 - k / quality + k * k) / denominator])
    return b, a


def _block_mean_squares(weighted: np.ndarray, sample_rate: int) -> np.ndarray:
    block = int(_BLOCK_SEC * sample_rate)
    step = int(_BLOCK_SEC * (1.0 - _OVERLAP) * sample_rate)
    if step < 1:
        step = 1
    blocks: list[np.ndarray] = []
    for start in range(0, weighted.shape[0] - block + 1, step):
        segment = weighted[start : start + block]
        blocks.append(np.mean(segment * segment, axis=0))
    if not blocks:
        return np.empty((0, weighted.shape[1]))
    return np.vstack(blocks)


def _block_loudness(powers: np.ndarray, weights: np.ndarray) -> np.ndarray:
    mixed = powers @ weights
    mixed = np.maximum(mixed, 1e-20)
    return -0.691 + 10.0 * np.log10(mixed)


def _sum_loudness(powers: np.ndarray, weights: np.ndarray) -> float:
    mean_power = np.mean(powers, axis=0)
    mixed = float(np.sum(weights * mean_power))
    if mixed <= 0.0:
        return float("-inf")
    return float(-0.691 + 10.0 * np.log10(mixed))
