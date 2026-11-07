from __future__ import annotations

from pathlib import Path

from open_ar.comps import find_comps, load_comps
from open_ar.schema import Goal, VideoBrief, VideoGoal
from open_ar.video import extract_video_features
from open_ar.video_playbook import (
    build_video_plays,
    detect_video_gaps,
    score_video_fit,
    suggest_clip_windows,
)


def build_video_brief(
    video_path: str | Path,
    goal: VideoGoal | str = VideoGoal.youtube_mv,
    comps_path: str | Path | None = None,
    cleanup_wav: bool = True,
) -> VideoBrief:
    goal = VideoGoal(goal) if isinstance(goal, str) else goal
    video_path = Path(video_path)
    video, audio, wav_path = extract_video_features(video_path)
    try:
        # Audio comps still useful for sonic neighborhood even on video briefs.
        catalog = load_comps(comps_path) if comps_path else load_comps()
        audio_comps = find_comps(audio, Goal.playlist, comps=catalog, k=5)
        fit = score_video_fit(video, audio, goal)
        gaps = detect_video_gaps(video, audio, goal)
        clips = suggest_clip_windows(video, audio)
        plays = build_video_plays(video, audio, goal, fit, gaps, clips)
        return VideoBrief(
            video_path=str(video_path),
            goal=goal,
            video=video,
            audio=audio,
            audio_comps=audio_comps,
            fit=fit,
            gaps=gaps,
            plays=plays,
            clip_windows=clips,
        )
    finally:
        if cleanup_wav:
            wav_path.unlink(missing_ok=True)
