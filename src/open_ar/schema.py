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
    hook_onset_sec: float
    loudness_db: float
    key: str | None = None
    mode: str | None = None


class CompTrack(BaseModel):
    id: str
    title: str
    artist: str
    genre: str
    goal_tags: list[str]
    outcome: str
    features: AudioFeatures
    notes: str = ""


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
    scene_cut_times_sec: list[float] = Field(default_factory=list)


class VideoFitScore(BaseModel):
    goal: VideoGoal
    score: float = Field(ge=0.0, le=1.0)
    rationale: list[str]


class ARBrief(BaseModel):
    version: str = "0.1.0"
    track_path: str
    goal: Goal
    features: AudioFeatures
    comps: list[CompMatch]
    fit: FitScore
    gaps: list[Gap]
    plays: list[Play]
    disclaimer: str = (
        "This is a fit-and-strategy brief against comps and measurable audio "
        "signals — not a verdict on artistic quality."
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
