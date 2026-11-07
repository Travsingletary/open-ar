from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from open_ar.features import extract_features
from open_ar.schema import AudioFeatures, VideoFeatures


class VideoIngestError(RuntimeError):
    pass


def _run(cmd: list[str], *, capture_stderr: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=True,
    )


def probe_video(path: Path) -> dict:
    proc = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=width,height,avg_frame_rate,codec_type",
            "-of",
            "json",
            str(path),
        ]
    )
    if proc.returncode != 0:
        raise VideoIngestError(f"ffprobe failed: {proc.stderr.strip()}")
    data = json.loads(proc.stdout or "{}")
    duration = float(data.get("format", {}).get("duration") or 0.0)
    width = height = 0
    fps = 0.0
    for stream in data.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        rate = stream.get("avg_frame_rate") or "0/1"
        if "/" in rate:
            num, den = rate.split("/", 1)
            fps = float(num) / float(den) if float(den) else 0.0
        else:
            fps = float(rate or 0.0)
        break
    if duration <= 0 or width <= 0 or height <= 0:
        raise VideoIngestError(f"Could not read video streams from {path}")
    return {"duration_sec": duration, "width": width, "height": height, "fps": fps}


def extract_audio_wav(video_path: Path, wav_path: Path) -> Path:
    proc = _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "22050",
            str(wav_path),
        ]
    )
    if proc.returncode != 0 or not wav_path.exists():
        raise VideoIngestError(f"ffmpeg audio extract failed: {proc.stderr.strip()[-500:]}")
    return wav_path


def detect_scene_cuts(video_path: Path, threshold: float = 0.35) -> list[float]:
    """Return timestamps (sec) where ffmpeg scene score exceeds threshold."""
    # showinfo prints pts_time on stderr when a scene frame is selected.
    proc = _run(
        [
            "ffmpeg",
            "-i",
            str(video_path),
            "-vf",
            f"select='gt(scene,{threshold})',showinfo",
            "-f",
            "null",
            "-",
        ]
    )
    times: list[float] = []
    for match in re.finditer(r"pts_time:([0-9.]+)", proc.stderr or ""):
        times.append(float(match.group(1)))
    # Deduplicate near-identical timestamps.
    cleaned: list[float] = []
    for t in times:
        if not cleaned or abs(t - cleaned[-1]) > 0.15:
            cleaned.append(t)
    return cleaned


def sample_luma_series(video_path: Path, every_n_sec: float = 1.0) -> list[tuple[float, float]]:
    """Sample mean luma (0–1) about once per second via ffmpeg signalstats."""
    proc = _run(
        [
            "ffmpeg",
            "-i",
            str(video_path),
            "-vf",
            f"fps=1/{every_n_sec},signalstats,metadata=print:file=-",
            "-f",
            "null",
            "-",
        ]
    )
    # metadata print goes to stdout when file=-
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    samples: list[tuple[float, float]] = []
    pts = 0.0
    for line in text.splitlines():
        if "pts_time:" in line:
            m = re.search(r"pts_time:([0-9.]+)", line)
            if m:
                pts = float(m.group(1))
        if "lavfi.signalstats.YAVG" in line:
            m = re.search(r"YAVG=([0-9.]+)", line)
            if m:
                # YAVG is 0–255 for 8-bit.
                samples.append((pts, float(m.group(1)) / 255.0))
    return samples


def _aspect_label(width: int, height: int) -> str:
    ratio = width / max(height, 1)
    if ratio < 0.85:
        return "vertical"
    if ratio > 1.3:
        return "horizontal"
    return "squareish"


def extract_video_features(path: str | Path) -> tuple[VideoFeatures, AudioFeatures, Path]:
    """
    Watch a music video file: probe picture, scene cuts, luma motion, and pull audio.

    Returns (video_features, audio_features, temp_wav_path). Caller may delete the wav.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    probe = probe_video(path)
    cuts = detect_scene_cuts(path)
    luma = sample_luma_series(path, every_n_sec=1.0)

    duration = probe["duration_sec"]
    cut_count = len(cuts)
    cut_rate = cut_count / max(duration / 60.0, 1e-6)  # cuts per minute

    first_cut = cuts[0] if cuts else None
    # Visual energy: mean absolute luma delta between samples.
    luma_deltas = [abs(luma[i][1] - luma[i - 1][1]) for i in range(1, len(luma))]
    visual_energy = float(sum(luma_deltas) / len(luma_deltas)) if luma_deltas else 0.0
    visual_energy = max(0.0, min(1.0, visual_energy * 4.0))

    # Opening retention windows (platforms punish dull cold opens).
    def _window_energy(start: float, end: float) -> float:
        pts = [v for t, v in luma if start <= t <= end]
        if len(pts) < 2:
            return visual_energy
        deltas = [abs(pts[i] - pts[i - 1]) for i in range(1, len(pts))]
        return max(0.0, min(1.0, (sum(deltas) / len(deltas)) * 4.0))

    opening_3s_energy = _window_energy(0.0, 3.0)
    opening_15s_energy = _window_energy(0.0, 15.0)

    # Peak visual motion timestamp.
    peak_visual_sec = 0.0
    if luma_deltas:
        idx = max(range(len(luma_deltas)), key=lambda i: luma_deltas[i])
        peak_visual_sec = float(luma[idx + 1][0])

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    wav_path = Path(tmp.name)
    extract_audio_wav(path, wav_path)
    audio = extract_features(wav_path)

    # Alignment: how close is first strong cut / peak visual to audio hook.
    hook = audio.hook_onset_sec
    candidates = ([first_cut] if first_cut is not None else []) + [peak_visual_sec]
    best_delta = min(abs(c - hook) for c in candidates) if candidates else abs(peak_visual_sec - hook)
    # 0 = perfect sync within 0s, 1 = 20s+ off
    sync_score = max(0.0, min(1.0, 1.0 - best_delta / 20.0))

    video = VideoFeatures(
        duration_sec=duration,
        width=probe["width"],
        height=probe["height"],
        fps=probe["fps"],
        aspect=_aspect_label(probe["width"], probe["height"]),
        scene_cut_count=cut_count,
        cuts_per_minute=round(cut_rate, 2),
        first_cut_sec=first_cut,
        peak_visual_sec=peak_visual_sec,
        visual_energy=round(visual_energy, 3),
        opening_3s_energy=round(opening_3s_energy, 3),
        opening_15s_energy=round(opening_15s_energy, 3),
        audio_hook_visual_sync=round(sync_score, 3),
        scene_cut_times_sec=[round(t, 2) for t in cuts[:40]],
    )
    return video, audio, wav_path
