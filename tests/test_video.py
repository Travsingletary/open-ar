from pathlib import Path

import numpy as np
import soundfile as sf

from open_ar.schema import VideoGoal
from open_ar.video_brief import build_video_brief
from open_ar.video_playbook import detect_video_gaps, score_video_fit, suggest_clip_windows
from open_ar.schema import AudioFeatures, VideoFeatures


def _make_test_mp4(path: Path, seconds: float = 8.0) -> Path:
    """Generate a tiny mp4 with a mid-point scene change via ffmpeg."""
    import subprocess

    # Two color segments so scene detect fires.
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s=640x360:d={seconds/2}",
        "-f",
        "lavfi",
        "-i",
        f"color=c=white:s=640x360:d={seconds/2}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=220:sample_rate=22050:duration={seconds}",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map",
        "[v]",
        "-map",
        "2:a",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert path.exists()
    return path


def test_video_playbook_short_form_wants_vertical():
    video = VideoFeatures(
        duration_sec=60,
        width=1920,
        height=1080,
        fps=30,
        aspect="horizontal",
        scene_cut_count=10,
        cuts_per_minute=10,
        first_cut_sec=1.0,
        peak_visual_sec=20,
        visual_energy=0.5,
        opening_3s_energy=0.1,
        opening_15s_energy=0.2,
        audio_hook_visual_sync=0.8,
    )
    audio = AudioFeatures(
        duration_sec=60,
        tempo_bpm=100,
        energy=0.6,
        danceability=0.6,
        brightness=0.5,
        acousticness=0.2,
        speechiness=0.1,
        dynamic_range=0.5,
        hook_onset_sec=10,
        loudness_db=-12,
    )
    gaps = detect_video_gaps(video, audio, VideoGoal.short_form)
    assert any(g.code == "wrong_aspect" for g in gaps)
    windows = suggest_clip_windows(video, audio)
    assert any(w["label"] == "15s short" for w in windows)
    fit = score_video_fit(video, audio, VideoGoal.short_form)
    assert fit.score < 0.7


def test_analyze_video_brief(tmp_path: Path):
    mp4 = _make_test_mp4(tmp_path / "mv.mp4", seconds=6.0)
    brief = build_video_brief(mp4, goal=VideoGoal.youtube_mv)
    assert brief.video.width == 640
    assert brief.video.height == 360
    assert brief.video.aspect == "horizontal"
    assert brief.audio.duration_sec > 0
    assert len(brief.plays) >= 1
    assert any(p.primary for p in brief.plays)
    assert brief.clip_windows
