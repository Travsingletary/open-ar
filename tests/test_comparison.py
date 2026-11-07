import json
from pathlib import Path

import numpy as np
import soundfile as sf

from open_ar.andre import build_handoff, validate_handoff
from open_ar.brief import build_brief
from open_ar.schema import Goal


def _tone(path: Path) -> Path:
    sample_rate = 22050
    seconds = 12.0
    time = np.linspace(0, seconds, int(sample_rate * seconds), endpoint=False)
    tone = 0.2 * np.sin(2 * np.pi * 220.0 * time)
    sf.write(path, tone.astype(np.float32), sample_rate)
    return path


def _features() -> dict:
    return {
        "duration_sec": 180,
        "tempo_bpm": 100,
        "energy": 0.5,
        "danceability": 0.5,
        "brightness": 0.4,
        "acousticness": 0.3,
        "speechiness": 0.1,
        "dynamic_range": 0.5,
    }


def _track(track_id: str, **extra) -> dict:
    base = {
        "id": track_id,
        "title": track_id,
        "artist": "Known Act",
        "genre": "pop",
        "goal_tags": ["playlist"],
        "outcome": "in_house_reference",
        "measurement_source": "open_ar",
        "permission_cleared": True,
        "permission_note": "Owner supplied the reference file.",
        "features": _features(),
    }
    base.update(extra)
    return base


def _catalog(path: Path, tracks: list[dict]) -> Path:
    path.write_text(
        json.dumps({"kind": "verified", "verified": True, "tracks": tracks}),
        encoding="utf-8",
    )
    return path


def test_ratings_do_not_change_similarity_and_popularity_stays_empty(tmp_path: Path):
    wav = _tone(tmp_path / "song.wav")
    low = _catalog(
        tmp_path / "low.json",
        [
            _track(
                "ref-low",
                ratings={"drum_impact": 1, "hook": 1, "conviction": 1, "rater": "Travis Singletary"},
                popularity=99,
            )
        ],
    )
    high = _catalog(
        tmp_path / "high.json",
        [
            _track(
                "ref-high",
                ratings={"drum_impact": 5, "hook": 5, "conviction": 5, "rater": "Travis Singletary"},
                popularity=1,
            )
        ],
    )
    low_brief = build_brief(wav, goal=Goal.playlist, comps_path=low)
    high_brief = build_brief(wav, goal=Goal.playlist, comps_path=high)
    assert low_brief.comps[0].distance == high_brief.comps[0].distance
    assert low_brief.fit.score == high_brief.fit.score
    assert low_brief.questions["sounds_similar"]["items"][0]["id"] == "ref-low"
    assert "drum_impact" not in low_brief.questions["sounds_similar"]["items"][0]
    assert low_brief.questions["good_song"]["status"] == "rated"
    assert low_brief.questions["good_song"]["items"][0]["conviction"] == 1
    assert high_brief.questions["good_song"]["items"][0]["conviction"] == 5
    assert low_brief.questions["currently_popular"]["items"] == []
    assert "99" not in json.dumps(low_brief.questions["currently_popular"])
    assert "Soundcharts" in low_brief.questions["currently_popular"]["reason"]
    handoff = build_handoff([low_brief])
    assert validate_handoff(handoff) == []
    assert handoff["tracks"][0]["questions"]["sounds_similar"]["items_field"] == "comps"
    assert "good_song" not in handoff["tracks"][0]["questions"]
    assert handoff["good_song"]["items"][0]["conviction"] == 1
    assert handoff["currently_popular"]["items"] == []
    assert "99" not in json.dumps(handoff["currently_popular"])
    assert handoff["tracks"][0]["comps"]["items"][0]["musicbrainz_recording_mbid"] is None


def test_acousticbrainz_and_uncleared_tracks_are_not_similarity_comps(tmp_path: Path):
    wav = _tone(tmp_path / "song.wav")
    path = _catalog(
        tmp_path / "mixed.json",
        [
            _track(
                "ab",
                measurement_source="acousticbrainz",
                musicbrainz_recording_mbid="b6c8d1c2-0c1a-4f3e-9a55-1c2b3d4e5f60",
            ),
            _track("uncleared", permission_cleared=False),
            _track("bad-id", musicbrainz_recording_mbid="not-a-uuid"),
            _track("essentia-model", measurement_source="essentia"),
        ],
    )
    brief = build_brief(wav, goal=Goal.playlist, comps_path=path)
    assert brief.comps == []
    assert brief.comps_status == "unavailable"
    assert brief.questions["sounds_similar"]["items"] == []
    reasons = {item["id"]: item["reason"] for item in brief.questions["sounds_similar"]["held"]}
    assert "2022" in reasons["ab"]
    assert reasons["uncleared"] == "no permission clearance"
    assert "UUID" in reasons["bad-id"]
    assert "Commercial licensing" in reasons["essentia-model"]
    assert brief.questions["good_song"]["status"] == "unavailable"


def test_incomplete_ratings_stay_unavailable(tmp_path: Path):
    wav = _tone(tmp_path / "song.wav")
    path = _catalog(
        tmp_path / "partial.json",
        [_track("ref", ratings={"drum_impact": 4, "hook": None, "conviction": 5, "rater": "Travis Singletary"})],
    )
    brief = build_brief(wav, goal=Goal.playlist, comps_path=path)
    assert brief.comps_status == "ok"
    assert brief.questions["good_song"]["status"] == "unavailable"
    assert "drum impact" in brief.questions["good_song"]["reason"]
