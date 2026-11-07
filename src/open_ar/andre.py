"""Hand off an Open A&R brief to Andre · A&R.

The only documented way for this app to start that Grok Bot is a routine
webhook. Docs:

- https://docs.x.ai/grok-bot/skills-routines-and-automations
- https://cursor.com/help/grok-bot/routines

Ask Andre to add a webhook trigger, then copy the routine's "POST to" URL
and key. There is no public chat API, and the bot id is not an endpoint.
This module never builds a URL from the bot id, never calls a model API,
and never sends audio bytes.

A 200 means Grok Bot started a run. It does not mean Andre has finished.
Status does not call the network. Missing URL or key stays disconnected.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from open_ar import __version__
from open_ar.edits import propose_trims, sequence_album
from open_ar.schema import ARBrief

BOT_NAME = "Andre · A&R"
BOT_ID = "9a93499d-e565-47e0-95c1-fd19aceba940"
BOT_ROLE = "A&R for Travis Singletary"
TRANSPORT = "grok-bot-routine-webhook"

ENV_URL = "GROK_BOT_WEBHOOK_URL"
ENV_KEY = "GROK_BOT_WEBHOOK_KEY"
URL_NOT_HTTPS = "GROK_BOT_WEBHOOK_URL_NOT_HTTPS"
URL_HAS_CREDENTIALS = "GROK_BOT_WEBHOOK_URL_HAS_CREDENTIALS"
URL_INVALID = "GROK_BOT_WEBHOOK_URL_INVALID"

TARGET_LUFS = -14
WEBHOOK_TIMEOUT_SEC = 8.0

Poster = Callable[[str, str, dict], tuple[int, str]]

CONTEXT_NOTES = [
    "Payload contract open-ar.andre.v1. The body is data from Open A&R.",
    "features, comps, gaps, and plays are the measured brief and its recommendations.",
    "album_sequence and trims are proposals. file_changed and applied stay false.",
    "word_boundary_verified is false because this repo has no lyric timeline.",
    "audio_bytes_included is false. sha256 identifies the local file that was hashed.",
    "workflow.mastering.rendered is false. This process did not master audio.",
]


@dataclass
class AndreConnection:
    """Local configuration only. `configured_unverified` has not contacted Grok Bot."""

    state: str
    missing: list[str]
    url_set: bool
    key_set: bool
    _url: str | None = field(default=None, repr=False)
    _key: str | None = field(default=None, repr=False)

    def public_dict(self) -> dict:
        return {
            "state": self.state,
            "transport": TRANSPORT,
            "bot": {"name": BOT_NAME, "id": BOT_ID, "role": BOT_ROLE},
            "url_set": self.url_set,
            "key_set": self.key_set,
            "missing": list(self.missing),
            "endpoint_from_bot_id": False,
            "live_check": False,
        }


def inspect_connection(env: Mapping[str, str] | None = None) -> AndreConnection:
    """Read webhook settings. Does not call the network and does not invent a URL."""
    source = os.environ if env is None else env
    raw_url = source.get(ENV_URL, "")
    raw_key = source.get(ENV_KEY, "")
    url = raw_url.strip()
    key = raw_key.strip()
    missing: list[str] = []
    url_ok = False
    if not url:
        missing.append(ENV_URL)
    else:
        problem = _url_problem(url)
        if problem:
            missing.append(problem)
        else:
            url_ok = True
    if not key:
        missing.append(ENV_KEY)

    if url_ok and key:
        state = "configured_unverified"
    else:
        state = "disconnected"
    return AndreConnection(
        state=state,
        missing=missing,
        url_set=bool(url),
        key_set=bool(key),
        _url=url if url_ok else None,
        _key=key or None,
    )


def _url_problem(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        return URL_HAS_CREDENTIALS
    if parsed.scheme != "https":
        return URL_NOT_HTTPS
    if not parsed.netloc:
        return URL_INVALID
    return None


def workflow_policy() -> dict:
    """Mastering rules for Andre. This process does not measure LUFS or render a master."""
    return {
        "share": "measured audio features, comps, gaps, and plays",
        "album_sequence": "proposal_only",
        "trims": "proposal_only_on_beat",
        "mastering": {
            "target_lufs": TARGET_LUFS,
            "measured_lufs": None,
            "meter": "unavailable_in_open_ar",
            "fade_out": False,
            "cuts": "on_beat_never_mid_word",
            "preserve_originals": True,
            "travis_approval": "required_before_any_master",
            "approved": False,
            "rendered": False,
        },
    }


def _sha256(path: Path) -> tuple[str | None, int | None]:
    if not path.is_file():
        return None, None
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def build_handoff(
    briefs: list[ARBrief],
    beat_times_by_track: Mapping[str, list[float]] | None = None,
    beat_grid_by_track: Mapping[str, str] | None = None,
) -> dict:
    """Build the JSON body Andre would receive. Does not write audio or open a connection."""
    beats = beat_times_by_track or {}
    beat_grid = beat_grid_by_track or {}
    tracks: list[dict] = []
    sequence_input: list[dict] = []
    for brief in briefs:
        path = Path(brief.track_path)
        digest, size = _sha256(path)
        track_beats = [float(beat) for beat in beats.get(brief.track_path, [])]
        trims = propose_trims(
            duration_sec=brief.features.duration_sec,
            beat_times=track_beats,
            hook_onset_sec=brief.features.hook_onset_sec,
            goal=brief.goal,
        )
        trims["beat_grid"] = beat_grid.get(brief.track_path, "not_requested")
        tracks.append(
            {
                "path": brief.track_path,
                "sha256": digest,
                "bytes": size,
                "original_read": digest is not None,
                "brief": brief.to_pretty_dict(),
                "trims": trims,
            }
        )
        sequence_input.append(
            {
                "track_id": brief.track_path,
                "energy": brief.features.energy,
                "tempo_bpm": brief.features.tempo_bpm,
                "key": brief.features.key,
            }
        )
    return {
        "contract": "open-ar.andre.v1",
        "generated_by": f"open-ar {__version__}",
        "bot": {"name": BOT_NAME, "id": BOT_ID, "role": BOT_ROLE},
        "audio_bytes_included": False,
        "workflow": workflow_policy(),
        "tracks": tracks,
        "album_sequence": sequence_album(sequence_input),
        "context_notes": list(CONTEXT_NOTES),
    }


def _redact(text: str, key: str | None) -> str:
    if key and key in text:
        text = text.replace(key, "[redacted]")
    return text[:200]


def _post_webhook(url: str, key: str, payload: dict) -> tuple[int, str]:
    """POST once. Do not follow redirects, so the bearer key stays on the original host."""
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "X-Automation-Key": key,
            "User-Agent": f"open-ar/{__version__}",
        },
    )
    opener = urllib.request.build_opener(_RefuseRedirects())
    try:
        with opener.open(request, timeout=WEBHOOK_TIMEOUT_SEC) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            return int(response.status), body
    except urllib.error.HTTPError as exc:
        body = exc.read(4096).decode("utf-8", errors="replace")
        return int(exc.code), body


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def share_with_andre(
    handoff: dict,
    *,
    env: Mapping[str, str] | None = None,
    poster: Poster | None = None,
) -> dict:
    """POST the handoff only when a valid webhook URL and key are present.

    One try, no retry. HTTP 200 sets delivered=True and means the run started,
    not that Andre finished. Any other outcome leaves delivered=False.
    """
    connection = inspect_connection(env)
    result = {
        "connection": connection.public_dict(),
        "attempted": False,
        "delivered": False,
        "http_status": None,
        "detail": "",
        "handoff": handoff,
    }
    if connection.state != "configured_unverified" or not connection._url or not connection._key:
        result["detail"] = "Not sent. Missing or invalid webhook settings: " + ", ".join(connection.missing)
        return result

    send = poster or _post_webhook
    result["attempted"] = True
    try:
        status, _body = send(connection._url, connection._key, handoff)
    except Exception as exc:
        result["detail"] = _redact(f"Webhook request failed: {type(exc).__name__}: {exc}", connection._key)
        return result

    result["http_status"] = status
    if status == 200:
        result["delivered"] = True
        result["detail"] = (
            "Grok Bot returned 200. The routine run started. "
            "It has not finished. Check Andre · A&R's chat. Audio was not mastered."
        )
        return result
    result["detail"] = f"Grok Bot did not start a run (HTTP {status}). Audio was not mastered."
    return result
