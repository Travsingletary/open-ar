import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from typer.testing import CliRunner

from open_ar.andre import (
    BOT_ID,
    ENV_KEY,
    ENV_URL,
    URL_HAS_CREDENTIALS,
    URL_NOT_HTTPS,
    build_handoff,
    inspect_connection,
    share_with_andre,
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
    assert handoff["audio_bytes_included"] is False
    assert handoff["workflow"]["mastering"]["approved"] is False
    assert handoff["workflow"]["mastering"]["rendered"] is False
    assert handoff["workflow"]["mastering"]["target_lufs"] == -14
    assert handoff["workflow"]["mastering"]["fade_out"] is False
    assert handoff["tracks"][0]["brief"]["plays"][0]["title"] == "Hold for a tighter intro"
    assert handoff["tracks"][0]["sha256"] == hashlib.sha256(payload).hexdigest()
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
    assert len(calls) == 1
    assert calls[0][0] == "https://hooks.example.test/routine"
    assert calls[0][2]["contract"] == "open-ar.andre.v1"
    assert BOT_ID not in calls[0][0]
    assert "super-secret-key" not in json.dumps(result)
    assert "has not finished" in result["detail"]

    def poster_created(url, key, body):
        return 201, "created"

    created = share_with_andre(handoff, env=env, poster=poster_created)
    assert created["delivered"] is False
    assert created["http_status"] == 201


def test_trim_proposals_stay_on_beats_and_refuse_without_one():
    beats = [8.0, 16.0, 32.0, 180.0, 200.0, 230.0]
    trims = propose_trims(duration_sec=240.0, beat_times=beats, hook_onset_sec=40.0, goal=Goal.playlist)
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
        goal="playlist",
    )
    assert refused["proposals"][0]["kind"] == "refused"
    assert refused["proposals"][0]["at_sec"] is None
    assert refused["proposals"][0]["on_beat"] is False


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
    assert [track["path"] for track in handoff["tracks"]] == ["b.wav", "a.wav"]
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
    assert saved["handoff"]["tracks"][0]["brief"]["features"]["duration_sec"] > 10
    assert saved["handoff"]["workflow"]["mastering"]["rendered"] is False
    assert saved["handoff"]["audio_bytes_included"] is False
    assert saved["handoff"]["tracks"][0]["trims"]["beat_grid"] == "ok"
    assert saved["handoff"]["tracks"][0]["trims"]["word_boundary_verified"] is False
    assert "GROK_BOT_WEBHOOK_URL" in saved["connection"]["missing"]
    assert "GROK_BOT_WEBHOOK_KEY" in saved["connection"]["missing"]


def test_module_does_not_embed_undocumented_endpoints():
    source = (Path(__file__).resolve().parents[1] / "src" / "open_ar" / "andre.py").read_text(
        encoding="utf-8"
    )
    for banned in ("api2.cursor.sh", "api.x.ai", ":1340", "grok-bot-cli"):
        assert banned not in source
