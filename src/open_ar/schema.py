from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Goal(str, Enum):
    playlist = "playlist"
    club = "club"
    sync = "sync"
    cult = "cult"
    lead_single = "lead_single"


class VideoGoal(str, Enum):
    youtube_mv = "youtube_mv"
    short_form = "short_form"
    premiere = "premiere"
    visualizer = "visualizer"


class AudioFeatures(BaseModel):
    duration_sec: float
    tempo_bpm: float
    energy: float = Field(ge=0.0, le=1.0)
    danceability: float = Field(ge=0.0, le=1.0)
    brightness: float = Field(ge=0.0, le=1.0)
    acousticness: float = Field(ge=0.0, le=1.0)
    speechiness: float = Field(ge=0.0, le=1.0)
    dynamic_range: float = Field(ge=0.0, le=1.0)
    # None unless a hook was marked by something other than an onset peak.
    hook_onset_sec: float | None = None
    hook_verified: bool = False
    novelty_peak_sec: float | None = None
    # Mean of per-frame RMS relative to this file's own peak RMS. Not LUFS.
    loudness_db: float | None = None
    rms_rel_peak_db: float | None = None
    mean_rms_dbfs: float | None = None
    energy_saturated: bool = False
    integrated_lufs: float | None = None
    lufs_channels: int | None = None
    lufs_note: str | None = None
    tempo_octave_ambiguous: bool = True
    beat_interval_regularity: float | None = None
    key_margin: float | None = None
    mode_margin: float | None = None
    key: str | None = None
    mode: str | None = None

    def timing_anchor(self) -> tuple[float | None, str]:
        if self.hook_verified and self.hook_onset_sec is not None:
            return self.hook_onset_sec, "verified_hook"
        if self.novelty_peak_sec is not None:
            return self.novelty_peak_sec, "onset_peak"
        return None, "unavailable"


class SongRatings(BaseModel):
    """Listener ratings. These are not acoustic measurements and not popularity."""

    drum_impact: int | None = Field(default=None, ge=1, le=5)
    hook: int | None = Field(default=None, ge=1, le=5)
    conviction: int | None = Field(default=None, ge=1, le=5)
    rater: str = ""


class CompTrack(BaseModel):
    id: str
    title: str
    artist: str
    genre: str
    goal_tags: list[str]
    outcome: str
    features: AudioFeatures
    notes: str = ""
    musicbrainz_recording_mbid: str | None = None
    measurement_source: str = "unspecified"
    permission_cleared: bool = False
    permission_note: str = ""
    ratings: SongRatings | None = None


class CompMatch(BaseModel):
    comp: CompTrack
    distance: float
    why: list[str]


class FitScore(BaseModel):
    goal: Goal
    score: float = Field(ge=0.0, le=1.0)
    rationale: list[str]


class Gap(BaseModel):
    code: str
    severity: str
    message: str


class Play(BaseModel):
    primary: bool
    title: str
    actions: list[str]
    evidence: list[str]


class VideoFeatures(BaseModel):
    duration_sec: float
    width: int
    height: int
    fps: float
    aspect: str
    scene_cut_count: int
    cuts_per_minute: float
    first_cut_sec: float | None
    peak_visual_sec: float
    visual_energy: float = Field(ge=0.0, le=1.0)
    opening_3s_energy: float = Field(ge=0.0, le=1.0)
    opening_15s_energy: float = Field(ge=0.0, le=1.0)
    audio_hook_visual_sync: float = Field(ge=0.0, le=1.0)
    audio_sync_basis: str = "unspecified"
    scene_cut_times_sec: list[float] = Field(default_factory=list)


class VideoFitScore(BaseModel):
    goal: VideoGoal
    score: float = Field(ge=0.0, le=1.0)
    rationale: list[str]


class ARBrief(BaseModel):
    version: str = "0.2.0"
    track_path: str
    goal: Goal
    features: AudioFeatures
    comps: list[CompMatch]
    comps_status: str = "unavailable"
    comps_reason: str | None = None
    comparison_held: list[dict[str, Any]] = Field(default_factory=list)
    questions: dict[str, Any] = Field(default_factory=dict)
    fit: FitScore
    gaps: list[Gap]
    plays: list[Play]
    disclaimer: str = (
        "Fit uses measured signals and, only when configured, a verified comparison "
        "catalog. Bundled seed comps are fixtures, not artist or chart recommendations. "
        "An onset peak is not a verified hook. RMS relative to the file peak is not LUFS. "
        "This is not a verdict on artistic quality."
    )

    def to_pretty_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class VideoBrief(BaseModel):
    version: str = "0.1.0"
    video_path: str
    goal: VideoGoal
    video: VideoFeatures
    audio: AudioFeatures
    audio_comps: list[CompMatch] = Field(default_factory=list)
    fit: VideoFitScore
    gaps: list[Gap]
    plays: list[Play]
    clip_windows: list[dict[str, Any]] = Field(default_factory=list)
    disclaimer: str = (
        "This is a music-video strategy brief from measurable picture + audio "
        "signals — not a taste judgment on the film or song."
    )

    def to_pretty_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
