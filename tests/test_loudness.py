import numpy as np
import pytest

from open_ar.loudness import integrated_lufs


def test_stereo_1khz_matches_bs1770_anchor():
    sample_rate = 48000
    seconds = 8.0
    time = np.arange(int(sample_rate * seconds)) / sample_rate
    amplitude = 10 ** (-23 / 20)
    tone = amplitude * np.sin(2 * np.pi * 1000 * time)
    stereo = integrated_lufs(np.column_stack([tone, tone]), sample_rate)
    mono = integrated_lufs(tone, sample_rate)
    assert stereo == pytest.approx(-23.0, abs=0.1)
    assert mono == pytest.approx(stereo - 3.0103, abs=0.2)


def test_short_or_wide_signal_stays_null():
    assert integrated_lufs(np.zeros(100), 48000) is None
    too_many = np.zeros((48000, 6))
    assert integrated_lufs(too_many, 48000) is None
