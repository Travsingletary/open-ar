"""Album order and trim proposals. Nothing in this module writes or replaces audio."""

from __future__ import annotations

from pathlib import Path

from open_ar.schema import Goal

# Same streaming-single ceiling score_fit already uses for playlist and lead_single.
PLAYLIST_MAX_SEC = 210.0
LATE_HOOK_SEC = 25.0


def sequence_album(tracks: list[dict]) -> list[dict]:
    """Propose a listening order.

    Opener is the lowest energy, then the lowest track id.
    Closer is the remaining track whose energy is nearest 0.35, then the lowest track id.
    The highest-energy track still left is the peak and sits immediately before the closer.
    Any other tracks sit between the opener and the peak, each chosen as the nearest tempo
    to the previous track.

    This does not rename, move, or edit files.
    """
    if not tracks:
        return []

    def track_id(track: dict) -> str:
        return str(track["track_id"])

    if len(tracks) == 1:
        only = tracks[0]
        return [_slot(only, 1, "only", "single track; nothing to sequence")]

    remaining = list(tracks)
    opener = min(remaining, key=lambda track: (float(track["energy"]), track_id(track)))
    remaining.remove(opener)
    closer = min(remaining, key=lambda track: (abs(float(track["energy"]) - 0.35), track_id(track)))
    remaining.remove(closer)

    peak = None
    if remaining:
        peak = max(remaining, key=lambda track: (float(track["energy"]), track_id(track)))
        remaining.remove(peak)

    ordered = [opener]
    roles = ["opener"]
    reasons = ["lowest energy; opens the record without spending the peak"]
    previous_tempo = float(opener["tempo_bpm"])
    while remaining:
        nxt = min(
            remaining,
            key=lambda track: (abs(float(track["tempo_bpm"]) - previous_tempo), track_id(track)),
        )
        remaining.remove(nxt)
        ordered.append(nxt)
        roles.append("bridge")
        reasons.append(
            f"tempo {float(nxt['tempo_bpm']):.1f} BPM is the closest remaining step from {previous_tempo:.1f} BPM"
        )
        previous_tempo = float(nxt["tempo_bpm"])
    if peak is not None:
        ordered.append(peak)
        roles.append("peak")
        reasons.append("highest remaining energy, placed immediately before the closer")
    ordered.append(closer)
    roles.append("closer")
    reasons.append("energy nearest a resolve (0.35) among tracks that are not the opener")

    return [
        _slot(track, index, role, why)
        for index, (track, role, why) in enumerate(zip(ordered, roles, reasons), start=1)
    ]


def _slot(track: dict, position: int, role: str, why: str) -> dict:
    return {
        "position": position,
        "track_id": track["track_id"],
        "role": role,
        "energy": track["energy"],
        "tempo_bpm": track["tempo_bpm"],
        "key": track.get("key"),
        "why": why,
        "file_changed": False,
    }


def propose_trims(
    *,
    duration_sec: float,
    beat_times: list[float],
    hook_onset_sec: float,
    goal: Goal | str,
) -> dict:
    """Propose cuts that already exist on the beat grid. Never applies them.

    Open A&R has no lyric timeline, so every proposal is marked unverified for words.
    A missing beat at the target becomes a refusal, not an invented mid-beat cut.
    """
    goal = Goal(goal) if isinstance(goal, str) else goal
    beats = sorted(float(beat) for beat in beat_times if 0.0 <= float(beat) <= duration_sec)
    base = {
        "goal": goal.value,
        "fade_out": False,
        "preserve_original": True,
        "applied": False,
        "word_boundary_verified": False,
        "word_boundary_note": (
            "Open A&R has no lyric alignment. Do not cut mid-word until a verified "
            "lyric timeline is supplied."
        ),
        "target_sec": PLAYLIST_MAX_SEC if goal in (Goal.playlist, Goal.lead_single) else None,
        "proposals": [],
    }
    if goal not in (Goal.playlist, Goal.lead_single):
        return base

    if hook_onset_sec > LATE_HOOK_SEC:
        intro_candidates = [beat for beat in beats if 8.0 <= beat < hook_onset_sec - 0.25]
        if intro_candidates:
            cut = intro_candidates[-1]
            base["proposals"].append(
                _proposal(
                    "trim_intro",
                    cut,
                    True,
                    (
                        f"hook proxy is {hook_onset_sec:.1f}s, after the {LATE_HOOK_SEC:.0f}s "
                        "playlist window. Proposed start is the latest beat still before that hook. "
                        "No fade. Not applied."
                    ),
                )
            )

    if duration_sec > PLAYLIST_MAX_SEC + 1.0:
        outro_candidates = [beat for beat in beats if beat <= PLAYLIST_MAX_SEC]
        if outro_candidates:
            cut = outro_candidates[-1]
            base["proposals"].append(
                _proposal(
                    "trim_outro",
                    cut,
                    True,
                    (
                        f"duration {duration_sec:.1f}s is past {PLAYLIST_MAX_SEC:.0f}s. "
                        "Proposed end is the last beat at or before that ceiling. No fade-out. Not applied."
                    ),
                )
            )
        else:
            base["proposals"].append(
                _proposal(
                    "refused",
                    None,
                    False,
                    (
                        f"duration {duration_sec:.1f}s is past {PLAYLIST_MAX_SEC:.0f}s, "
                        "and no beat falls at or before that ceiling. Refusing a mid-beat cut."
                    ),
                )
            )
    return base


def _proposal(kind: str, at_sec: float | None, on_beat: bool, why: str) -> dict:
    return {
        "kind": kind,
        "at_sec": at_sec,
        "on_beat": on_beat,
        "fade_out": False,
        "applied": False,
        "why": why,
    }


def read_beat_times(path: str | Path) -> list[float]:
    """Return beat times in seconds. Empty when the file has no detected beats."""
    import librosa
    import numpy as np

    audio_path = Path(path)
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    _tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
    if beats is None or len(np.atleast_1d(beats)) == 0:
        return []
    times = librosa.frames_to_time(np.atleast_1d(beats), sr=sr)
    return [float(t) for t in times]
