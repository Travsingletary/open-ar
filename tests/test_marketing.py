"""Local marketing notes and the permission-cleared catalog template.

Synthetic tones and placeholder catalogs only. No network and no user WAV.
"""

import json
from pathlib import Path

import numpy as np
import soundfile as sf
from typer.testing import CliRunner

from open_ar.andre import (
    MAX_HANDOFF_UTF8_BYTES,
    build_handoff,
    posted_bytes,
    seal_handoff,
    validate_handoff,
)
from open_ar.brief import build_brief
from open_ar.cli import app
from open_ar.comps import ACOUSTICBRAINZ_HELD, ESSENTIA_HELD
from open_ar.features import extract_features
from open_ar.marketing import load_marketing_notes
from open_ar.schema import ARBrief, AudioFeatures, FitScore, Goal, Play

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CATALOG = ROOT / "examples" / "permission_cleared_catalog.example.json"
EXAMPLE_MARKETING = ROOT / "examples" / "marketing_notes.example.json"
POPULARITY_NUMBER = 8675309
STREAM_NUMBER = 12000000


def _tone(path: Path) -> Path:
    sample_rate = 22050
    seconds = 12.0
    time = np.linspace(0, seconds, int(sample_rate * seconds), endpoint=False)
    tone = 0.2 * np.sin(2 * np.pi * 220.0 * time)
    sf.write(path, tone.astype(np.float32), sample_rate)
    return path


def _features() -> AudioFeatures:
    return AudioFeatures(
        duration_sec=180.0,
        tempo_bpm=96.0,
        energy=0.42,
        danceability=0.48,
        brightness=0.4,
        acousticness=0.33,
        speechiness=0.08,
        dynamic_range=0.55,
    )


def _bare(path: str) -> ARBrief:
    return ARBrief(
        track_path=path,
        goal=Goal.playlist,
        features=_features(),
        comps=[],
        fit=FitScore(goal=Goal.playlist, score=0.4, rationale=["synthetic"]),
        gaps=[],
        plays=[
            Play(
                primary=True,
                title="Hold for a tighter intro",
                actions=["Review the proposed beat cut before any edit"],
                evidence=["synthetic brief"],
            )
        ],
    )


def test_example_catalog_documents_the_gates_and_skips_seed_artists():
    raw = json.loads(EXAMPLE_CATALOG.read_text(encoding="utf-8"))
    assert raw["kind"] == "verified"
    assert raw["verified"] is True
    assert "Seed Artist" not in EXAMPLE_CATALOG.read_text(encoding="utf-8")
    for track in raw["tracks"]:
        assert "permission_cleared" in track
        assert "permission_note" in track
        assert "measurement_source" in track
    assert any(track.get("musicbrainz_recording_mbid") for track in raw["tracks"])
    assert any(track.get("ratings") for track in raw["tracks"])

    brief = build_brief(
        "/tmp/open-ar-synthetic.wav",
        goal=Goal.playlist,
        comps_path=EXAMPLE_CATALOG,
        features=_features(),
    )
    assert [match.comp.id for match in brief.comps] == ["local-ref-placeholder"]
    assert brief.comps[0].comp.artist == "Local library"
    assert brief.comps_status == "ok"
    reasons = {item["id"]: item["reason"] for item in brief.comparison_held}
    assert reasons["held-acousticbrainz"] == ACOUSTICBRAINZ_HELD
    assert "2022" in reasons["held-acousticbrainz"]
    assert reasons["held-essentia"] == ESSENTIA_HELD
    assert "Commercial licensing" in reasons["held-essentia"]
    assert reasons["held-uncleared"] == "no permission clearance"
    assert "UUID" in reasons["held-bad-mbid"]
    assert brief.questions["good_song"]["status"] == "rated"
    assert brief.questions["good_song"]["items"][0]["id"] == "local-ref-placeholder"
    assert brief.questions["currently_popular"]["status"] == "unavailable"
    assert brief.questions["currently_popular"]["items"] == []
    assert "Seed Artist" not in brief.model_dump_json()


def test_marketing_absent_versus_present_does_not_change_distance_or_fit(tmp_path: Path):
    wav = _tone(tmp_path / "song.wav")
    feats = extract_features(wav)
    plain = build_brief(wav, goal=Goal.playlist, comps_path=EXAMPLE_CATALOG, features=feats)
    noted = build_brief(
        wav,
        goal=Goal.playlist,
        comps_path=EXAMPLE_CATALOG,
        features=feats,
        marketing_path=EXAMPLE_MARKETING,
    )
    assert plain.marketing_notes["status"] == "unavailable"
    assert plain.marketing_notes["source"] is None
    assert "currently_popular" in plain.marketing_notes["reason"]
    assert noted.marketing_notes["status"] == "supplied"
    assert noted.marketing_notes["source"] == "local_notes"
    assert noted.marketing_notes["campaign"]
    assert plain.fit.score == noted.fit.score
    assert plain.fit.rationale == noted.fit.rationale
    assert [match.distance for match in plain.comps] == [match.distance for match in noted.comps]
    assert [match.comp.id for match in plain.comps] == [match.comp.id for match in noted.comps]
    assert plain.questions["good_song"] == noted.questions["good_song"]
    assert plain.questions["sounds_similar"]["items"] == noted.questions["sounds_similar"]["items"]
    assert plain.questions["currently_popular"] == noted.questions["currently_popular"]
    assert set(noted.questions) == {"sounds_similar", "good_song", "currently_popular"}

    absent = build_handoff([plain])
    present = build_handoff([plain], marketing_notes=load_marketing_notes(EXAMPLE_MARKETING))
    assert validate_handoff(absent) == []
    assert validate_handoff(present) == []
    assert absent["marketing_notes"]["status"] == "unavailable"
    assert absent["marketing_notes"]["notes"] == ""
    assert present["marketing_notes"]["status"] == "supplied"
    assert present["marketing_notes"]["source"] == "local_notes"
    assert present["tracks"][0]["fit"]["score"] == absent["tracks"][0]["fit"]["score"]
    assert present["tracks"][0]["comps"] == absent["tracks"][0]["comps"]
    assert "marketing_notes" not in present["tracks"][0]["questions"]
    assert "good_song" not in present["tracks"][0]["questions"]
    assert "currently_popular" not in present["tracks"][0]["questions"]


def test_popularity_numbers_in_marketing_or_catalog_stay_empty(tmp_path: Path):
    catalog = json.loads(EXAMPLE_CATALOG.read_text(encoding="utf-8"))
    catalog["tracks"][0]["popularity"] = POPULARITY_NUMBER
    catalog["tracks"][0]["chart_rank"] = 4
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    notes = {
        "campaign": "spring notes",
        "audience": "people who already have the record",
        "playlist_pitch": "write the pitch yourself",
        "radio": "college radio",
        "notes": "hand written",
        "supplied_by": "Tester",
        "source": "soundcharts",
        "popularity": POPULARITY_NUMBER,
        "streams": STREAM_NUMBER,
        "chart_rank": 4,
    }
    notes_path = tmp_path / "notes.json"
    notes_path.write_text(json.dumps(notes), encoding="utf-8")

    brief = build_brief(
        "/tmp/open-ar-synthetic.wav",
        goal=Goal.playlist,
        comps_path=catalog_path,
        features=_features(),
        marketing_path=notes_path,
    )
    plain = build_brief(
        "/tmp/open-ar-synthetic.wav",
        goal=Goal.playlist,
        comps_path=EXAMPLE_CATALOG,
        features=_features(),
    )
    assert brief.fit.score == plain.fit.score
    assert [match.distance for match in brief.comps] == [match.distance for match in plain.comps]
    assert brief.questions["currently_popular"]["status"] == "unavailable"
    assert brief.questions["currently_popular"]["items"] == []
    assert str(POPULARITY_NUMBER) not in json.dumps(brief.questions["currently_popular"])
    assert brief.marketing_notes["source"] == "local_notes"
    assert "popularity" not in brief.marketing_notes
    assert "soundcharts" not in json.dumps(brief.marketing_notes).lower()

    handoff = build_handoff([brief], marketing_notes=load_marketing_notes(notes_path))
    assert validate_handoff(handoff) == []
    assert handoff["currently_popular"]["status"] == "unavailable"
    assert handoff["currently_popular"]["items"] == []
    dumped = json.dumps(handoff)
    assert str(POPULARITY_NUMBER) not in dumped
    assert str(STREAM_NUMBER) not in dumped
    assert "chart_rank" not in handoff["marketing_notes"]
    assert handoff["marketing_notes"]["source"] == "local_notes"


def test_validate_requires_marketing_and_rejects_any_other_popularity_block():
    handoff = build_handoff([_bare("/tmp/open-ar-synthetic.wav")])
    assert validate_handoff(handoff) == []
    assert handoff["workflow"]["mastering"]["approved"] is False
    assert handoff["workflow"]["mastering"]["rendered"] is False
    assert handoff["workflow"]["mastering"]["target_lufs"] == -14

    stripped = {key: value for key, value in handoff.items() if key != "marketing_notes"}
    assert "missing:marketing_notes" in validate_handoff(seal_handoff(stripped))

    with_items = dict(handoff)
    with_items["currently_popular"] = {
        "status": "unavailable",
        "reason": handoff["currently_popular"]["reason"],
        "source": None,
        "items": [{"popularity": POPULARITY_NUMBER}],
    }
    assert "currently_popular" in validate_handoff(seal_handoff(with_items))

    ranked = dict(handoff)
    ranked["currently_popular"] = {
        "status": "ok",
        "reason": "a chart",
        "source": "soundcharts",
        "items": [],
    }
    assert "currently_popular" in validate_handoff(seal_handoff(ranked))


def test_long_marketing_notes_are_shortened_instead_of_dropping_sections():
    notes = {
        "campaign": "spring",
        "audience": "listeners",
        "playlist_pitch": "a pitch",
        "radio": "college",
        "notes": "n" * 120_000,
        "supplied_by": "Tester",
    }
    handoff = build_handoff([_bare("/tmp/open-ar-synthetic.wav")], marketing_notes=notes)
    assert validate_handoff(handoff) == []
    assert len(posted_bytes(handoff)) <= MAX_HANDOFF_UTF8_BYTES
    assert len(handoff["marketing_notes"]["notes"]) < 120_000
    assert handoff["marketing_notes"]["status"] == "supplied"
    assert handoff["marketing_notes"]["source"] == "local_notes"
    assert handoff["marketing_notes"]["reason"] == (
        "Notes were shortened so the sealed handoff stays within 96 KiB."
    )
    assert handoff["zz_end"] == "complete"
    assert handoff["tracks"]
    assert handoff["album_sequence"]
    assert handoff["good_song"]["items"] == []
    assert handoff["currently_popular"]["items"] == []
    assert handoff["workflow"]["mastering"]["rendered"] is False
    assert handoff["workflow"]["mastering"]["approved"] is False


def test_one_track_and_eight_track_album_with_notes_stay_under_the_cap():
    """Synthetic album. Not a verdict on any unmeasured file."""
    feats = _features()
    briefs = [
        build_brief(
            f"/tmp/open-ar-album-{index}.wav",
            goal=Goal.playlist,
            comps_path=EXAMPLE_CATALOG,
            features=feats,
            marketing_path=EXAMPLE_MARKETING,
        )
        for index in range(8)
    ]
    notes = load_marketing_notes(EXAMPLE_MARKETING)
    one = build_handoff(briefs[:1], marketing_notes=notes)
    eight = build_handoff(briefs, marketing_notes=notes)
    assert validate_handoff(one) == []
    assert validate_handoff(eight) == []
    assert len(posted_bytes(one)) <= MAX_HANDOFF_UTF8_BYTES
    assert len(posted_bytes(eight)) <= MAX_HANDOFF_UTF8_BYTES
    assert len(eight["tracks"]) == 8
    assert len(eight["album_sequence"]) == 8
    assert eight["marketing_notes"]["source"] == "local_notes"
    assert eight["marketing_notes"]["notes"] == notes["notes"]
    assert eight["currently_popular"]["status"] == "unavailable"
    assert eight["currently_popular"]["items"] == []
    assert eight["tracks"][0]["comps"]["status"] == "ok"
    assert eight["tracks"][0]["comps"]["items"][0]["artist"] == "Local library"
    assert "Seed Artist" not in json.dumps(eight)
    assert any("2022" in item["reason"] for item in eight["comparison_held"])
    assert eight["workflow"]["mastering"]["approved"] is False
    assert eight["workflow"]["mastering"]["rendered"] is False
    assert eight["workflow"]["mastering"]["target_lufs"] == -14
    assert eight["workflow"]["mastering"]["fade_out"] is False
    assert eight["audio_bytes_included"] is False


def test_cli_analyze_and_share_load_the_examples_and_leave_the_wav(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GROK_BOT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("GROK_BOT_WEBHOOK_KEY", raising=False)
    wav = _tone(tmp_path / "song.wav")
    original = wav.read_bytes()
    brief_path = tmp_path / "brief.json"
    analyzed = CliRunner().invoke(
        app,
        [
            "analyze",
            str(wav),
            "--goal",
            "playlist",
            "--comps",
            str(EXAMPLE_CATALOG),
            "--marketing",
            str(EXAMPLE_MARKETING),
            "--json",
            str(brief_path),
        ],
    )
    assert analyzed.exit_code == 0, analyzed.stdout
    assert wav.read_bytes() == original
    assert "marketing notes: supplied" in analyzed.stdout
    assert "source: local_notes" in analyzed.stdout
    assert "Held out of similarity" in analyzed.stdout
    assert "2022" in analyzed.stdout
    assert "Seed Artist" not in analyzed.stdout
    saved_brief = json.loads(brief_path.read_text(encoding="utf-8"))
    assert saved_brief["comps"][0]["comp"]["id"] == "local-ref-placeholder"
    assert saved_brief["questions"]["currently_popular"]["items"] == []
    assert saved_brief["marketing_notes"]["source"] == "local_notes"

    handoff_path = tmp_path / "handoff.json"
    shared = CliRunner().invoke(
        app,
        [
            "andre",
            "share",
            str(wav),
            "--goal",
            "playlist",
            "--comps",
            str(EXAMPLE_CATALOG),
            "--marketing",
            str(EXAMPLE_MARKETING),
            "--json",
            str(handoff_path),
        ],
    )
    assert shared.exit_code == 2, shared.stdout
    assert wav.read_bytes() == original
    assert "marketing notes: supplied" in shared.stdout
    assert "currently popular: unavailable" in shared.stdout
    assert "Original files were not modified" in shared.stdout
    saved = json.loads(handoff_path.read_text(encoding="utf-8"))
    assert saved["attempted"] is False
    assert saved["delivered"] is False
    assert validate_handoff(saved["handoff"]) == []
    assert saved["handoff"]["marketing_notes"]["source"] == "local_notes"
    assert saved["handoff"]["currently_popular"]["items"] == []
    assert saved["handoff"]["workflow"]["mastering"]["approved"] is False
    assert saved["handoff"]["workflow"]["mastering"]["rendered"] is False
    assert "Seed Artist" not in handoff_path.read_text(encoding="utf-8")
