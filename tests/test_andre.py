import base64
import hashlib
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from typer.testing import CliRunner

from open_ar.andre import (
    BOT_ID,
    CONTRACT,
    DEFAULT_PART_BYTES,
    ENV_KEY,
    ENV_PART_BYTES,
    ENV_URL,
    MAX_HANDOFF_UTF8_BYTES,
    URL_HAS_CREDENTIALS,
    URL_NOT_HTTPS,
    build_handoff,
    inspect_connection,
    plan_parts,
    posted_bytes,
    share_with_andre,
    validate_handoff,
)
from open_ar.cli import app
from open_ar.edits import propose_trims, sequence_album
from open_ar.schema import ARBrief, AudioFeatures, FitScore, Goal, Play


def _features(**overrides) -> AudioFeatures:
    base = dict(
        duration_sec=240.0,
        tempo_bpm=100.0,
        energy=0.4,
        danceability=0.5,
        brightness=0.4,
        acousticness=0.3,
        speechiness=0.1,
        dynamic_range=0.5,
        hook_onset_sec=40.0,
        loudness_db=-12.0,
        key="A",
        mode="minor",
    )
    base.update(overrides)
    return AudioFeatures(**base)


def _brief(path: str, **feature_overrides) -> ARBrief:
    feats = _features(**feature_overrides)
    return ARBrief(
        track_path=path,
        goal=Goal.playlist,
        features=feats,
        comps=[],
        fit=FitScore(goal=Goal.playlist, score=0.4, rationale=["fixture"]),
        gaps=[],
        plays=[
            Play(
                primary=True,
                title="Hold for a tighter intro",
                actions=["Review the proposed beat cut before any edit"],
                evidence=["hook proxy is late for a playlist"],
            )
        ],
    )


def test_status_disconnected_without_env():
    connection = inspect_connection({})
    public = connection.public_dict()
    assert public["state"] == "disconnected"
    assert public["missing"] == [ENV_URL, ENV_KEY]
    assert public["endpoint_from_bot_id"] is False
    assert public["live_check"] is False
    assert connection._url is None
    assert BOT_ID not in json.dumps({k: v for k, v in public.items() if k != "bot"})


def test_partial_and_invalid_urls_stay_disconnected():
    only_url = inspect_connection({ENV_URL: "https://hooks.example.test/routine"})
    assert only_url.state == "disconnected"
    assert only_url.missing == [ENV_KEY]

    http_url = inspect_connection({ENV_URL: "http://hooks.example.test/routine", ENV_KEY: "secret"})
    assert http_url.state == "disconnected"
    assert URL_NOT_HTTPS in http_url.missing
    assert http_url._url is None

    embedded = inspect_connection(
        {ENV_URL: "https://user:secret@hooks.example.test/routine", ENV_KEY: "secret"}
    )
    assert embedded.state == "disconnected"
    assert URL_HAS_CREDENTIALS in embedded.missing


def test_share_does_not_call_out_when_disconnected(tmp_path: Path):
    source = tmp_path / "song.wav"
    payload = b"original-audio-bytes"
    source.write_bytes(payload)
    calls = []

    def poster(url, key, body):
        calls.append((url, key, body))
        raise AssertionError("disconnected share must not post")

    handoff = build_handoff([_brief(str(source))], {str(source): [10.0, 30.0, 200.0]})
    result = share_with_andre(handoff, env={}, poster=poster)
    assert calls == []
    assert result["attempted"] is False
    assert result["delivered"] is False
    assert result["connection"]["state"] == "disconnected"
    assert source.read_bytes() == payload
    assert handoff["contract"] == CONTRACT
    assert handoff["zz_end"] == "complete"
    uuid.UUID(handoff["correlation_id"])
    raw = posted_bytes(handoff)
    assert raw.startswith(b'{"correlation_id":"')
    assert raw.endswith(b'"zz_end":"complete"}')
    assert raw.find(b'"tracks"') < raw.find(b'"context_notes"')
    assert raw.find(b'"integrated_lufs"') < raw.find(b'"rms_rel_peak_db"')
    assert handoff["workflow"]["mastering"]["measured_lufs"] is None
    assert handoff["workflow"]["mastering"]["file_lufs_field"] == "tracks[].measurements.integrated_lufs"
    assert validate_handoff(handoff) == []
    assert len(posted_bytes(handoff)) <= MAX_HANDOFF_UTF8_BYTES
    assert handoff["audio_bytes_included"] is False
    assert handoff["audio_pairing"]["endpoint"] is None
    assert handoff["workflow"]["mastering"]["approved"] is False
    assert handoff["workflow"]["mastering"]["rendered"] is False
    assert handoff["workflow"]["mastering"]["target_lufs"] == -14
    assert handoff["workflow"]["mastering"]["fade_out"] is False
    assert handoff["tracks"][0]["plays"][0]["title"] == "Hold for a tighter intro"
    assert handoff["tracks"][0]["audio"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert handoff["tracks"][0]["comps"]["status"] == "unavailable"
    assert handoff["tracks"][0]["comps"]["items"] == []
    assert "album_sequence" in handoff and "trims" in handoff["tracks"][0]
    assert handoff["tracks"][0]["measurements"]["hook"]["value"] is None
    assert handoff["tracks"][0]["measurements"]["rms_rel_peak_db"]["unit"] == "dB re peak RMS"
    dumped = json.dumps(result)
    assert "secret" not in dumped


def test_share_posts_once_and_only_200_is_delivered():
    handoff = build_handoff([_brief("/tmp/missing-open-ar-track.wav")])
    env = {ENV_URL: "https://hooks.example.test/routine", ENV_KEY: "super-secret-key"}
    calls = []

    def poster(url, key, body):
        calls.append((url, key, body))
        return 200, "started"

    result = share_with_andre(handoff, env=env, poster=poster)
    assert result["delivered"] is True
    assert result["http_status"] == 200
    assert calls
    assert len(calls) == calls[0][2]["parts"]
    assert [item[2]["part"] for item in calls] == list(range(1, len(calls) + 1))
    rebuilt = b"".join(base64.b64decode(item[2]["body_b64"]) for item in calls)
    assert rebuilt == posted_bytes(handoff)
    document = json.loads(rebuilt)
    assert calls[0][0] == "https://hooks.example.test/routine"
    assert calls[0][2]["contract"] == CONTRACT
    assert calls[0][2]["zz_end"] == "complete"
    assert "album_sequence" in document
    assert "trims" in document["tracks"][0]
    assert BOT_ID not in calls[0][0]
    assert "super-secret-key" not in json.dumps(result)
    assert "not finished" in result["detail"]
    for item in calls:
        wire = posted_bytes(item[2])
        assert len(wire) <= DEFAULT_PART_BYTES
        assert list(json.loads(wire))[-1] == "zz_end"

    created_calls = []

    def poster_created(url, key, body):
        created_calls.append(body)
        return 201, "created"

    created = share_with_andre(handoff, env=env, poster=poster_created)
    assert created["delivered"] is False
    assert created["http_status"] == 201
    assert len(created_calls) == 1


def test_trim_proposals_stay_on_beats_and_refuse_without_one():
    beats = [8.0, 16.0, 32.0, 180.0, 200.0, 230.0]
    trims = propose_trims(
        duration_sec=240.0,
        beat_times=beats,
        hook_onset_sec=40.0,
        hook_verified=True,
        goal=Goal.playlist,
    )
    assert trims["fade_out"] is False
    assert trims["applied"] is False
    assert trims["word_boundary_verified"] is False
    kinds = {item["kind"]: item for item in trims["proposals"]}
    assert kinds["trim_intro"]["at_sec"] == 32.0
    assert kinds["trim_intro"]["at_sec"] in beats
    assert kinds["trim_outro"]["at_sec"] == 200.0
    assert kinds["trim_outro"]["fade_out"] is False
    assert all(item["applied"] is False for item in trims["proposals"])

    refused = propose_trims(
        duration_sec=240.0,
        beat_times=[220.0, 230.0],
        hook_onset_sec=10.0,
        hook_verified=True,
        goal="playlist",
    )
    assert refused["outro"]["status"] == "refused"
    assert refused["outro"]["at_sec"] is None
    assert refused["proposals"][0]["on_beat"] is False


def test_onset_peak_does_not_become_an_intro_cut():
    trims = propose_trims(
        duration_sec=154.0,
        beat_times=[8.0, 140.0, 142.8],
        hook_onset_sec=None,
        hook_verified=False,
        novelty_peak_sec=142.8,
        goal=Goal.playlist,
    )
    assert trims["intro"]["status"] == "unavailable"
    assert trims["intro"]["at_sec"] is None
    assert not any(item["kind"] == "trim_intro" for item in trims["proposals"])
    assert "not a cut" in trims["intro"]["reason"]


def test_album_sequence_is_a_proposal_and_keeps_input_order_separate():
    tracks = [
        {"track_id": "b.wav", "energy": 0.9, "tempo_bpm": 140, "key": "G"},
        {"track_id": "a.wav", "energy": 0.2, "tempo_bpm": 90, "key": "A"},
        {"track_id": "c.wav", "energy": 0.35, "tempo_bpm": 100, "key": "D"},
    ]
    order = sequence_album(tracks)
    assert [item["track_id"] for item in order] == ["a.wav", "b.wav", "c.wav"]
    assert [item["role"] for item in order] == ["opener", "peak", "closer"]
    assert all(item["file_changed"] is False for item in order)

    briefs = [
        _brief("b.wav", energy=0.9, tempo_bpm=140),
        _brief("a.wav", energy=0.2, tempo_bpm=90),
    ]
    handoff = build_handoff(briefs)
    assert [track["audio"]["source_path"] for track in handoff["tracks"]] == ["b.wav", "a.wav"]
    assert [item["track_id"] for item in handoff["album_sequence"]] == ["a.wav", "b.wav"]


class _Recorder(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "automation": self.headers.get("X-Automation-Key"),
                "content_type": self.headers.get("Content-Type"),
                "body": body,
            }
        )
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/steal")
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, fmt, *args):  # noqa: A003
        return


def _server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_webhook_post_is_single_and_does_not_follow_redirects():
    from open_ar.andre import _post_webhook

    server = _server()
    try:
        host, port = server.server_address
        status, _body = _post_webhook(
            f"http://{host}:{port}/hook",
            "local-key",
            {"contract": "open-ar.andre.v1"},
        )
        assert status == 200
        assert len(server.requests) == 1
        assert server.requests[0]["authorization"] == "Bearer local-key"
        assert server.requests[0]["automation"] == "local-key"
        assert json.loads(server.requests[0]["body"])["contract"] == "open-ar.andre.v1"
        assert server.requests[0]["content_type"] == "application/json; charset=utf-8"

        redirected, _ignored = _post_webhook(f"http://{host}:{port}/redirect", "local-key", {"a": 1})
        assert redirected == 302
        assert len(server.requests) == 2
        assert all(item["path"] != "/steal" for item in server.requests)
    finally:
        server.shutdown()
        server.server_close()


def test_cli_status_reports_disconnected(monkeypatch):
    monkeypatch.delenv(ENV_URL, raising=False)
    monkeypatch.delenv(ENV_KEY, raising=False)
    result = CliRunner().invoke(app, ["andre", "status"])
    assert result.exit_code == 0
    assert "disconnected" in result.stdout
    assert BOT_ID in result.stdout


def test_cli_share_leaves_audio_and_exits_disconnected(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(ENV_URL, raising=False)
    monkeypatch.delenv(ENV_KEY, raising=False)
    wav = tmp_path / "tone.wav"
    # Local tone, same shape as the feature tests, so the brief is from real audio.
    import numpy as np
    import soundfile as sf

    sr = 22050
    seconds = 12.0
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    beat_hz = 2.0
    amp = 0.35 + 0.35 * (np.sin(2 * np.pi * beat_hz * t) > 0).astype(float)
    y = amp * np.sin(2 * np.pi * 220.0 * t)
    sf.write(wav, y.astype(np.float32), sr)
    original = wav.read_bytes()
    out = tmp_path / "handoff.json"
    result = CliRunner().invoke(app, ["andre", "share", str(wav), "--json", str(out)])
    assert result.exit_code == 2
    assert wav.read_bytes() == original
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["delivered"] is False
    assert saved["attempted"] is False
    assert saved["connection"]["state"] == "disconnected"
    track = saved["handoff"]["tracks"][0]
    assert track["measurements"]["duration_sec"]["value"] > 10
    assert track["measurements"]["duration_sec"]["unit"] == "s"
    assert track["measurements"]["hook"]["value"] is None
    assert track["measurements"]["hook"]["verified"] is False
    assert track["measurements"]["integrated_lufs"]["unit"] == "LUFS"
    assert track["measurements"]["rms_rel_peak_db"]["unit"] == "dB re peak RMS"
    assert track["comps"]["status"] == "unavailable"
    assert track["comps"]["items"] == []
    assert saved["handoff"]["album_sequence"]
    assert "intro" in track["trims"] and "outro" in track["trims"]
    assert saved["handoff"]["zz_end"] == "complete"
    uuid.UUID(saved["handoff"]["correlation_id"])
    assert saved["correlation_id"] == saved["handoff"]["correlation_id"]
    assert saved["zz_end"] == "complete"
    assert saved["handoff"]["workflow"]["mastering"]["rendered"] is False
    assert saved["handoff"]["audio_bytes_included"] is False
    assert "Seed Artist" not in out.read_text(encoding="utf-8")
    assert len(out.read_bytes()) > 0
    assert validate_handoff(saved["handoff"]) == []
    assert saved["handoff"]["tracks"][0]["trims"]["beat_grid"] == "ok"
    assert saved["handoff"]["tracks"][0]["trims"]["word_boundary_verified"] is False
    assert "GROK_BOT_WEBHOOK_URL" in saved["connection"]["missing"]
    assert "GROK_BOT_WEBHOOK_KEY" in saved["connection"]["missing"]


def test_reported_profile_labels_units_and_does_not_verify_the_peak():
    """The 154s profile is an implementation check, not a musical verdict."""
    feats = _features(
        duration_sec=154,
        tempo_bpm=74,
        energy=1,
        energy_saturated=True,
        acousticness=0.94,
        danceability=0.29,
        hook_onset_sec=None,
        novelty_peak_sec=142.8,
        hook_verified=False,
        loudness_db=-10.9,
        rms_rel_peak_db=-10.9,
        mean_rms_dbfs=None,
        integrated_lufs=None,
        lufs_note="not measured on this constructed fixture",
        key="A#",
        mode="major",
    )
    brief = _brief("/tmp/open-ar-reported-profile.wav", **{})
    brief = brief.model_copy(update={"features": feats, "track_path": "/tmp/open-ar-reported-profile.wav"})
    handoff = build_handoff([brief])
    measured = handoff["tracks"][0]["measurements"]
    assert measured["duration_sec"]["value"] == 154
    assert measured["tempo_bpm"]["value"] == 74
    assert measured["tempo_bpm"]["confidence"] is None
    assert measured["tempo_bpm"]["octave_ambiguous"] is True
    assert "Half-time" in measured["tempo_bpm"]["note"]
    assert measured["hook"]["value"] is None
    assert measured["novelty_peak_sec"]["value"] == 142.8
    assert "Not a verified hook" in measured["novelty_peak_sec"]["note"]
    assert measured["rms_rel_peak_db"]["value"] == -10.9
    assert measured["rms_rel_peak_db"]["unit"] == "dB re peak RMS"
    assert measured["integrated_lufs"]["value"] is None
    assert measured["integrated_lufs"]["unit"] == "LUFS"
    assert measured["energy_proxy"]["saturated"] is True
    assert measured["acousticness_proxy"]["value"] == 0.94
    assert "not that the record is acoustic" in measured["acousticness_proxy"]["note"]
    assert measured["danceability_proxy"]["value"] == 0.29
    assert handoff["tracks"][0]["trims"]["intro"]["status"] == "unavailable"
    assert handoff["tracks"][0]["comps"]["status"] == "unavailable"
    assert any(item["field"].endswith("integrated_lufs") for item in handoff["missing"])
    assert handoff["zz_end"] == "complete"
    assert validate_handoff(handoff) == []
    assert len(posted_bytes(handoff)) <= MAX_HANDOFF_UTF8_BYTES


def _profile_brief(index: int) -> ARBrief:
    """A full labeled brief, the shape a real share builds. No audio file is read."""
    feats = _features(
        duration_sec=154.0,
        tempo_bpm=74 + index,
        energy=1.0,
        energy_saturated=True,
        acousticness=0.94,
        danceability=0.29,
        hook_onset_sec=None,
        novelty_peak_sec=142.8,
        hook_verified=False,
        loudness_db=-10.9,
        rms_rel_peak_db=-10.9,
        mean_rms_dbfs=-14.2,
        integrated_lufs=-11.4,
        lufs_channels=2,
        lufs_note=None,
        key="A#",
        mode="major",
        key_margin=0.02,
        mode_margin=0.11,
        beat_interval_regularity=0.8,
    )
    return ARBrief(
        track_path=f"/tmp/open-ar-track-{index}.wav",
        goal=Goal.playlist,
        features=feats,
        comps=[],
        comps_status="unavailable",
        comps_reason="Bundled examples are fixtures, not artist or chart comparisons.",
        fit=FitScore(
            goal=Goal.playlist,
            score=0.42,
            rationale=["hook timing unavailable; onset peak is not scored as a hook"],
        ),
        gaps=[],
        plays=[
            Play(
                primary=True,
                title="Hook unverified — do not trim to the onset peak",
                actions=[
                    "No intro cut is proposed. An onset peak is not a hook mark.",
                    "No verified comparison catalog. Do not cite fixture or example artists.",
                    "Add a verified hook mark before asking for an edit.",
                ],
                evidence=["No verified hook. Strongest onset peak at 142.8s is not a hook and is not a cut point."],
            )
        ],
    )


def test_one_track_fits_and_eight_are_refused_without_dropping_sections():
    """The sender does not slice. A batch over the byte cap is refused whole."""
    one = build_handoff(
        [_profile_brief(0)],
        {"/tmp/open-ar-track-0.wav": [8.0, 140.0, 142.8]},
        {"/tmp/open-ar-track-0.wav": "ok"},
    )
    assert validate_handoff(one) == []
    assert len(posted_bytes(one)) <= MAX_HANDOFF_UTF8_BYTES
    assert one["workflow"]["mastering"]["approved"] is False
    assert one["workflow"]["mastering"]["rendered"] is False

    paths = [f"/tmp/open-ar-track-{index}.wav" for index in range(8)]
    eight = build_handoff(
        [_profile_brief(index) for index in range(8)],
        {path: [8.0, 16.0, 32.0, 140.0, 142.8] for path in paths},
        {path: "ok" for path in paths},
    )
    assert eight["zz_end"] == "complete"
    assert len(eight["tracks"]) == 8
    assert len(eight["album_sequence"]) == 8
    for track in eight["tracks"]:
        assert track["comps"]["status"] == "unavailable"
        assert track["comps"]["items"] == []
        for name in (
            "duration_sec",
            "tempo_bpm",
            "integrated_lufs",
            "rms_rel_peak_db",
            "hook",
            "novelty_peak_sec",
        ):
            assert name in track["measurements"]
        assert "intro" in track["trims"] and "outro" in track["trims"]
        assert track["plays"]
    assert "Seed Artist" not in json.dumps(eight)
    posted = posted_bytes(eight)
    errors = validate_handoff(eight)
    calls = []

    def poster(url, key, body):
        calls.append(body)
        return 200, "ok"

    result = share_with_andre(
        eight,
        env={ENV_URL: "https://hooks.example.test/routine", ENV_KEY: "k"},
        poster=poster,
    )
    if len(posted) > MAX_HANDOFF_UTF8_BYTES:
        assert errors == [f"over_bound:{len(posted)}"]
        assert calls == []
        assert result["attempted"] is False
        assert result["delivered"] is False
    else:
        assert errors == []


def test_single_part_envelope_stays_under_a_wide_cap():
    handoff = build_handoff([_brief("/tmp/open-ar-one-part.wav")])
    parts, problem = plan_parts(handoff, part_bytes=20_000)
    assert problem is None
    assert len(parts) == 1
    wire = posted_bytes(parts[0])
    assert len(wire) <= 20_000
    assert list(json.loads(wire))[-1] == "zz_end"
    assert base64.b64decode(parts[0]["body_b64"]) == posted_bytes(handoff)
    assert parts[0]["canonical_sha256"] == handoff["payload_sha256"]
    assert parts[0]["canonical_utf8_bytes"] == handoff["payload_utf8_bytes"]


def test_part_over_cap_posts_nothing():
    handoff = build_handoff([_brief("/tmp/missing-open-ar-track.wav")])
    env = {
        ENV_URL: "https://hooks.example.test/routine",
        ENV_KEY: "k",
        ENV_PART_BYTES: "200",
    }
    calls = []

    def poster(url, key, body):
        calls.append(body)
        return 200, "ok"

    result = share_with_andre(handoff, env=env, poster=poster)
    assert calls == []
    assert result["attempted"] is False
    assert result["delivered"] is False
    assert "Not sent" in result["detail"]


def test_large_single_track_brief_splits_without_dropping_evidence():
    """A sealed single-track brief of about 8.8 KB is delivered in full, in parts."""
    handoff = build_handoff([_brief("/Users/user/Projects/open-ar-test/test-track.wav")])
    document = posted_bytes(handoff)
    assert 8600 <= len(document) <= 9800
    parts, problem = plan_parts(handoff, DEFAULT_PART_BYTES)
    assert problem is None
    assert len(parts) > 1
    decoded = b""
    for index, part in enumerate(parts, start=1):
        wire = posted_bytes(part)
        parsed = json.loads(wire)
        assert len(wire) <= DEFAULT_PART_BYTES
        assert list(parsed)[-1] == "zz_end"
        assert parsed["zz_end"] == "complete"
        assert parsed["part"] == index
        assert parsed["parts"] == len(parts)
        assert parsed["correlation_id"] == handoff["correlation_id"]
        assert parsed["canonical_sha256"] == handoff["payload_sha256"]
        assert parsed["canonical_utf8_bytes"] == handoff["payload_utf8_bytes"]
        assert parsed["document_utf8_bytes"] == len(document)
        raw_slice = base64.b64decode(parsed["body_b64"])
        assert hashlib.sha256(raw_slice).hexdigest() == parsed["part_sha256"]
        decoded += raw_slice
    assert decoded == document
    rebuilt = json.loads(decoded)
    measurements = rebuilt["tracks"][0]["measurements"]
    assert measurements["integrated_lufs"]["unit"] == "LUFS"
    assert measurements["rms_rel_peak_db"]["unit"] == "dB re peak RMS"
    assert measurements["duration_sec"]["unit"] == "s"
    assert rebuilt["missing"]
    assert all(item.get("reason") for item in rebuilt["missing"])
    assert rebuilt["complete"] is True
    assert rebuilt["zz_end"] == "complete"
    assert rebuilt["payload_sha256"] == handoff["payload_sha256"]


def test_bad_correlation_id_is_not_posted():
    handoff = build_handoff([_brief("/tmp/missing-open-ar-track.wav")], correlation_id="not-a-uuid")
    assert "correlation_id" in validate_handoff(handoff)
    calls = []

    def poster(url, key, body):
        calls.append(body)
        return 200, "ok"

    result = share_with_andre(
        handoff,
        env={ENV_URL: "https://hooks.example.test/routine", ENV_KEY: "k"},
        poster=poster,
    )
    assert calls == []
    assert result["attempted"] is False
    assert result["delivered"] is False


def test_invalid_payload_is_not_posted():
    handoff = build_handoff([_brief("/tmp/missing-open-ar-track.wav")])
    broken = dict(handoff)
    broken["context_notes"] = ["x" * (MAX_HANDOFF_UTF8_BYTES + 50)]
    calls = []

    def poster(url, key, body):
        calls.append(body)
        return 200, "ok"

    result = share_with_andre(
        broken,
        env={ENV_URL: "https://hooks.example.test/routine", ENV_KEY: "k"},
        poster=poster,
    )
    assert calls == []
    assert result["attempted"] is False
    assert result["delivered"] is False
    assert result["validation_errors"]


def test_module_does_not_embed_undocumented_endpoints():
    source = (Path(__file__).resolve().parents[1] / "src" / "open_ar" / "andre.py").read_text(
        encoding="utf-8"
    )
    for banned in ("api2.cursor.sh", "api.x.ai", ":1340", "grok-bot-cli"):
        assert banned not in source
