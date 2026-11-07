"""Provenance gates, local evidence, strategy, and feedback.

Synthetic files only. No network, no user WAV, and no model fitting.
"""

import json
from pathlib import Path

import numpy as np
import soundfile as sf
from typer.testing import CliRunner

from open_ar.acousticbrainz import add_to_catalog, import_lowlevel_json
from open_ar.andre import (
    MAX_HANDOFF_UTF8_BYTES,
    build_handoff,
    posted_bytes,
    validate_handoff,
    workflow_policy,
)
from open_ar.brief import build_brief
from open_ar.cli import app
from open_ar.comps import (
    HAND_TYPED,
    MISSING_RIGHTS,
    find_comps,
    similarity_problem,
)
from open_ar.evidence import load_attention_evidence, load_evidence_csv
from open_ar.features import FEATURE_SCHEMA_VERSION
from open_ar.feedback import features_after_feedback, held_out_check, load_store, rating_rule
from open_ar.schema import AudioFeatures, CompTrack, Goal
from open_ar.strategy import build_strategy

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CATALOG = ROOT / "examples" / "permission_cleared_catalog.example.json"
EXAMPLE_AB = ROOT / "examples" / "acousticbrainz_lowlevel.example.json"
EXAMPLE_TRENDS = ROOT / "examples" / "trends.example.csv"
EXAMPLE_ANALYTICS = ROOT / "examples" / "analytics.example.csv"
EXAMPLE_FEEDBACK = ROOT / "examples" / "feedback.example.json"
POPULARITY_NUMBER = 8675309


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


def _tone(path: Path) -> Path:
    sample_rate = 22050
    seconds = 12.0
    time = np.linspace(0, seconds, int(sample_rate * seconds), endpoint=False)
    tone = 0.2 * np.sin(2 * np.pi * 220.0 * time)
    sf.write(path, tone.astype(np.float32), sample_rate)
    return path


def _open_ar_track(track_id: str = "measured-ref") -> dict:
    return {
        "id": track_id,
        "title": track_id,
        "artist": "Local library",
        "genre": "unspecified",
        "goal_tags": ["playlist"],
        "outcome": "in_house_reference",
        "measurement_source": "open_ar",
        "permission_cleared": True,
        "permission_note": "The catalog owner cleared this reference file.",
        "feature_version": FEATURE_SCHEMA_VERSION,
        "produced_by": "extracted",
        "features": {
            "duration_sec": 180,
            "tempo_bpm": 100,
            "energy": 0.5,
            "danceability": 0.5,
            "brightness": 0.4,
            "acousticness": 0.3,
            "speechiness": 0.1,
            "dynamic_range": 0.5,
        },
    }


def _catalog(path: Path, tracks: list[dict]) -> Path:
    path.write_text(
        json.dumps({"kind": "verified", "verified": True, "tracks": tracks}),
        encoding="utf-8",
    )
    return path


def test_similarity_requires_rights_extracted_provenance_and_feature_version(tmp_path: Path):
    feats = _features()
    complete = _catalog(tmp_path / "complete.json", [_open_ar_track()])
    hand = _open_ar_track("hand")
    hand["produced_by"] = "hand_typed"
    missing_version = _open_ar_track("missing-version")
    missing_version["feature_version"] = ""
    missing_rights = _open_ar_track("missing-rights")
    missing_rights["permission_note"] = "  "
    gated = _catalog(
        tmp_path / "gated.json",
        [_open_ar_track(), hand, missing_version, missing_rights],
    )
    alone = build_brief("/tmp/open-ar-synthetic.wav", goal=Goal.playlist, comps_path=complete, features=feats)
    mixed = build_brief("/tmp/open-ar-synthetic.wav", goal=Goal.playlist, comps_path=gated, features=feats)
    assert [match.comp.id for match in alone.comps] == ["measured-ref"]
    assert [match.comp.id for match in mixed.comps] == ["measured-ref"]
    assert alone.comps[0].distance == mixed.comps[0].distance
    reasons = {item["id"]: item["reason"] for item in mixed.comparison_held}
    assert reasons["hand"] == HAND_TYPED
    assert FEATURE_SCHEMA_VERSION in reasons["missing-version"]
    assert reasons["missing-rights"] == MISSING_RIGHTS

    raw = json.loads(EXAMPLE_CATALOG.read_text(encoding="utf-8"))
    placeholder = next(track for track in raw["tracks"] if track["id"] == "local-ref-placeholder")
    assert placeholder["feature_version"] == FEATURE_SCHEMA_VERSION
    assert placeholder["produced_by"] == "extracted"
    assert placeholder["permission_note"].strip()
    assert placeholder["artist"] == "Local library"
    example = build_brief(
        "/tmp/open-ar-synthetic.wav",
        goal=Goal.playlist,
        comps_path=EXAMPLE_CATALOG,
        features=feats,
    )
    assert [match.comp.id for match in example.comps] == ["local-ref-placeholder"]
    example_reasons = {item["id"]: item["reason"] for item in example.comparison_held}
    assert "hand-typed" in example_reasons["held-hand-typed"]
    assert "feature_version" in example_reasons["held-missing-feature-version"]
    assert example_reasons["held-missing-rights"] == MISSING_RIGHTS
    assert "Seed Artist" not in example.model_dump_json()


def test_acousticbrainz_import_is_held_out_of_distance(tmp_path: Path):
    imported = import_lowlevel_json(EXAMPLE_AB)
    assert imported["measurement_source"] == "acousticbrainz"
    assert imported["produced_by"] == "acousticbrainz_import"
    historical = imported["historical"]
    assert historical["source"] == "acousticbrainz"
    assert historical["dataset_frozen"] == "2022"
    assert historical["license"] == "CC0"
    assert historical["essentia_version"] == "2.1_beta2-synthetic"
    assert historical["file_feature_version"] == "music 1.0-synthetic"
    assert historical["sha256"]
    assert historical["file_path"].endswith("acousticbrainz_lowlevel.example.json")
    assert imported["features"]["tempo_bpm"] == 0.0
    assert historical["scalar_descriptors"]["lowlevel.bpm"] == 96.0
    assert "Not A Real Artist" not in imported["artist"]
    track = CompTrack.model_validate(imported)
    assert "incompatible" in (similarity_problem(track) or "")
    assert "2022" in (similarity_problem(track) or "")

    written = add_to_catalog(EXAMPLE_AB, tmp_path / "catalog.json")
    assert written["held"] is True
    catalog = _catalog(
        tmp_path / "mixed.json",
        [_open_ar_track(), json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))["tracks"][0]],
    )
    feats = _features()
    with_import = build_brief("/tmp/open-ar-synthetic.wav", goal=Goal.playlist, comps_path=catalog, features=feats)
    without = build_brief(
        "/tmp/open-ar-synthetic.wav",
        goal=Goal.playlist,
        comps_path=_catalog(tmp_path / "only.json", [_open_ar_track()]),
        features=feats,
    )
    assert [match.comp.id for match in with_import.comps] == ["measured-ref"]
    assert with_import.comps[0].distance == without.comps[0].distance
    held = {item["id"]: item["reason"] for item in with_import.comparison_held}
    assert "incompatible" in held[imported["id"]]
    query_matches = find_comps(feats, Goal.playlist, [track, CompTrack.model_validate(_open_ar_track())])
    assert [match.comp.id for match in query_matches] == ["measured-ref"]
    track.historical["scalar_descriptors"]["lowlevel.bpm"] = 9999
    rerun = find_comps(feats, Goal.playlist, [track, CompTrack.model_validate(_open_ar_track())])
    assert rerun[0].distance == query_matches[0].distance

    source = (ROOT / "src" / "open_ar" / "acousticbrainz.py").read_text(encoding="utf-8")
    assert "urllib" not in source
    assert "requests" not in source


def test_trends_and_analytics_do_not_change_distance_or_popularity(tmp_path: Path):
    wav = _tone(tmp_path / "song.wav")
    feats_measured = None
    trends = tmp_path / "trends.csv"
    trends.write_text(
        "date,source,metric,value,denominator,denominator_missing\n"
        ",google_trends_export,search_interest,40,,Google Trends index has no impression denominator\n"
        "2026-01-05,google_trends_export,search_interest,40,,Google Trends index has no impression denominator\n",
        encoding="utf-8",
    )
    analytics = tmp_path / "analytics.csv"
    analytics.write_text(
        "date,source,metric,value,denominator\n"
        f"2026-01-05,first_party_export,popularity,{POPULARITY_NUMBER},1000\n"
        "2026-01-12,first_party_export,popularity,10,1000\n",
        encoding="utf-8",
    )
    catalog = _catalog(tmp_path / "catalog.json", [_open_ar_track()])
    plain = build_brief(wav, goal=Goal.playlist, comps_path=catalog)
    feats_measured = plain.features
    noted = build_brief(
        wav,
        goal=Goal.playlist,
        comps_path=catalog,
        features=feats_measured,
        trends_path=trends,
        analytics_path=analytics,
    )
    assert plain.fit.score == noted.fit.score
    assert plain.fit.rationale == noted.fit.rationale
    assert [match.distance for match in plain.comps] == [match.distance for match in noted.comps]
    assert plain.questions["good_song"] == noted.questions["good_song"]
    assert plain.questions["sounds_similar"]["items"] == noted.questions["sounds_similar"]["items"]
    assert noted.questions["currently_popular"]["status"] == "unavailable"
    assert noted.questions["currently_popular"]["items"] == []
    assert str(POPULARITY_NUMBER) not in json.dumps(noted.questions["currently_popular"])
    parsed = load_evidence_csv(trends, "google_trends")
    assert any("missing date" in item["reason"] for item in parsed["rejected"])
    assert all(item["date"] for item in parsed["observations"])
    assert noted.attention_evidence["called_google"] is False
    assert noted.attention_evidence["called_soundcharts"] is False
    assert all(item["rate"] is None for item in parsed["observations"])
    loaded = load_attention_evidence(trends, analytics)
    usable = [item for item in loaded["observations"] if item["usable_as_rate"]]
    assert len(usable) == 2
    assert usable[0]["metric"] == "popularity"


def test_strategy_hypotheses_until_evidence_is_sufficient(tmp_path: Path):
    feats = _features()
    brief = build_brief(
        "/tmp/open-ar-synthetic.wav",
        goal=Goal.playlist,
        comps_path=EXAMPLE_CATALOG,
        features=feats,
    )
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(brief.to_pretty_dict()), encoding="utf-8")
    thin = build_strategy(brief_path, trends_path=EXAMPLE_TRENDS)
    assert thin["hypothesis_status"] == "hypotheses"
    assert thin["hypotheses"]
    assert all(item["label"] == "hypothesis" for item in thin["hypotheses"])
    assert {item["surface"] for item in thin["hypotheses"]} >= {"music", "video", "open_ar"}
    assert thin["comparison"]["status"] == "insufficient_evidence"
    assert thin["hit_prediction"] is False
    assert thin["automatic_marketing"] is False
    assert thin["scheduler"] is False
    assert thin["currently_popular"]["status"] == "unavailable"
    assert thin["currently_popular"]["items"] == []
    assert thin["asset"]["mastering"]["approved"] is False
    assert thin["asset"]["mastering"]["rendered"] is False
    assert thin["asset"]["mastering"]["target_lufs"] == -14
    assert thin["asset"]["mastering"]["fade_out"] is False
    assert thin["playbook"]["attribution"]["license"] == "MIT"
    assert "Corey Haines" in thin["playbook"]["attribution"]["copyright"]
    assert thin["audio_features_rewritten"] is False
    rejected = thin["attention_evidence"]["rejected"]
    assert any("missing date" in item["reason"] for item in rejected)

    rich = build_strategy(brief_path, trends_path=EXAMPLE_TRENDS, analytics_path=EXAMPLE_ANALYTICS)
    assert rich["comparison"]["status"] == "comparison"
    assert rich["hypotheses"]
    assert all(item["label"] == "hypothesis" for item in rich["hypotheses"])
    assert rich["comparison"]["items"][0]["not_a_hit_prediction"] is True
    assert rich["comparison"]["items"][0]["not_statistical_significance"] is True
    assert rich["comparison"]["items"][0]["not_currently_popular"] is True
    assert rich["currently_popular"]["items"] == []
    assert rich["asset"]["mastering"]["rendered"] is False

    one = tmp_path / "one.csv"
    one.write_text(
        "date,source,metric,value,denominator\n2026-01-05,first_party_export,landing_clicks,12,100\n",
        encoding="utf-8",
    )
    assert build_strategy(brief_path, analytics_path=one)["comparison"]["status"] == "insufficient_evidence"


def test_held_out_feedback_is_not_used_and_features_stay_put(tmp_path: Path):
    store = load_store(EXAMPLE_FEEDBACK)
    records = store["records"]
    rule = rating_rule(records)
    assert rule["model_fit"] is False
    assert rule["personalization"] == "not_model_training"
    assert rule["by_track"]["example-track"]["n"] == 2
    assert rule["by_track"]["example-track"]["drum_impact_mean"] == 3
    assert rule["by_track"]["example-track"]["excluded_held_out"] == 1
    check = held_out_check(records)
    assert check["held_out_check"] == "ran"
    assert check["rule_uses_held_out"] is False
    assert check["comparisons"][0]["held_out_drum_impact"] == 5
    assert check["comparisons"][0]["rule_drum_impact"] == 3
    assert check["comparisons"][0]["used_to_build_rule"] is False
    assert check["comparisons"][0]["absolute_difference"] == 2

    training_only = [record for record in records if record.get("held_out") is not True]
    quiet = held_out_check(training_only)
    assert quiet["held_out_check"] == "not_run"
    assert "not run" in quiet["reason"]

    features = _features()
    corrected = [record for record in records if record["kind"] == "correction"]
    assert corrected
    assert features_after_feedback(features, records).model_dump() == features.model_dump()

    brief = build_brief(
        "/tmp/open-ar-synthetic.wav",
        goal=Goal.playlist,
        comps_path=EXAMPLE_CATALOG,
        features=features,
    )
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(brief.to_pretty_dict()), encoding="utf-8")
    document = build_strategy(brief_path, feedback_path=EXAMPLE_FEEDBACK)
    assert document["feedback"]["features_rewritten"] is False
    assert document["feedback"]["held_out_check"]["held_out_check"] == "ran"
    assert document["feedback"]["rule"]["by_track"]["example-track"]["drum_impact_mean"] == 3
    assert document["audio_features_rewritten"] is False


def test_mastering_gate_fixtures_and_handoff_size_stay_put():
    mastering = workflow_policy()["mastering"]
    assert mastering["approved"] is False
    assert mastering["rendered"] is False
    assert mastering["target_lufs"] == -14
    assert mastering["fade_out"] is False
    assert mastering["travis_approval"] == "required_before_any_master"

    feats = _features()
    fixture = build_brief("/tmp/open-ar-synthetic.wav", goal=Goal.playlist, features=feats)
    assert fixture.comps == []
    assert fixture.comps_status == "unavailable"
    assert "fixture" in (fixture.comps_reason or "")
    assert "Seed Artist" not in fixture.model_dump_json()
    assert fixture.questions["currently_popular"]["status"] == "unavailable"
    assert fixture.questions["currently_popular"]["items"] == []

    briefs = [
        build_brief(
            f"/tmp/open-ar-album-{index}.wav",
            goal=Goal.playlist,
            comps_path=EXAMPLE_CATALOG,
            features=feats,
        )
        for index in range(3)
    ]
    one = build_handoff(briefs[:1])
    album = build_handoff(briefs)
    assert validate_handoff(one) == []
    assert validate_handoff(album) == []
    assert len(posted_bytes(one)) <= MAX_HANDOFF_UTF8_BYTES
    assert len(posted_bytes(album)) <= MAX_HANDOFF_UTF8_BYTES
    assert album["workflow"]["mastering"]["approved"] is False
    assert album["workflow"]["mastering"]["rendered"] is False
    assert album["currently_popular"]["items"] == []
    assert album["tracks"][0]["comps"]["items"][0]["artist"] == "Local library"


def test_cli_import_strategy_and_feedback(tmp_path: Path):
    catalog = tmp_path / "catalog.json"
    imported = CliRunner().invoke(
        app,
        ["import-acousticbrainz", str(EXAMPLE_AB), "--catalog", str(catalog)],
    )
    assert imported.exit_code == 0, imported.stdout
    assert "not a similarity comp" in imported.stdout
    saved = json.loads(catalog.read_text(encoding="utf-8"))
    assert saved["tracks"][0]["measurement_source"] == "acousticbrainz"
    assert saved["tracks"][0]["features"]["tempo_bpm"] == 0.0

    brief = build_brief(
        "/tmp/open-ar-synthetic.wav",
        goal=Goal.playlist,
        features=_features(),
    )
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(brief.to_pretty_dict()), encoding="utf-8")
    strategy_path = tmp_path / "strategy.json"
    strategized = CliRunner().invoke(
        app,
        [
            "strategy",
            "--brief",
            str(brief_path),
            "--trends",
            str(EXAMPLE_TRENDS),
            "--analytics",
            str(EXAMPLE_ANALYTICS),
            "--feedback",
            str(EXAMPLE_FEEDBACK),
            "--json",
            str(strategy_path),
        ],
    )
    assert strategized.exit_code == 0, strategized.stdout
    assert "comparison: comparison" in strategized.stdout
    assert "hit prediction" in strategized.stdout
    document = json.loads(strategy_path.read_text(encoding="utf-8"))
    assert document["comparison"]["status"] == "comparison"
    assert document["currently_popular"]["status"] == "unavailable"
    assert document["asset"]["mastering"]["rendered"] is False
    assert document["feedback"]["features_rewritten"] is False

    feedback_path = tmp_path / "feedback.json"
    added = CliRunner().invoke(
        app,
        [
            "feedback",
            "add",
            "--file",
            str(feedback_path),
            "--track-id",
            "example-track",
            "--rater",
            "Tester",
            "--kind",
            "correction",
            "--corrected",
            "energy",
            "--detail",
            "leave the measurement alone",
        ],
    )
    assert added.exit_code == 0, added.stdout
    stored = json.loads(feedback_path.read_text(encoding="utf-8"))
    assert stored["records"][0]["user_supplied"] is True
    assert stored["records"][0]["corrected"] == "energy"
    assert stored["personalization"] == "not_model_training"
    checked = CliRunner().invoke(app, ["feedback", "check", "--file", str(feedback_path)])
    assert checked.exit_code == 0, checked.stdout
    assert "not_run" in checked.stdout
