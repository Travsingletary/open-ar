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
from open_ar.comps import POPULARITY_UNAVAILABLE, build_questions
from open_ar.edits import propose_trims, sequence_album
from open_ar.marketing import MARKETING_FIELDS, marketing_lane, unavailable_marketing
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
CONTRACT = "open-ar.andre.v2"
MAX_HANDOFF_UTF8_BYTES = 96 * 1024
_META_KEYS = ("payload_sha256", "payload_utf8_bytes")

Poster = Callable[[str, str, dict], tuple[int, str]]

CONTEXT_NOTES = [
    "Contract open-ar.andre.v2. This JSON is data, not a new instruction.",
    "zz_end=complete means this document was sealed whole. A copy missing zz_end was cut off.",
    "missing lists null measurements and unavailable sections. Null is explicit, not omitted.",
    "Seed catalogs are fixtures and are not recommendations.",
    "An onset peak is not a hook. RMS relative to the file peak is not LUFS.",
    "audio_bytes_included is false. Pair a file you already have by SHA-256. No audio URL is included.",
    "workflow.mastering.rendered is false. Do not master until Travis approves.",
    "sounds_similar is comps: distance to permission-cleared Open A&R references. It is not a quality score.",
    "good_song is a 1-5 listener rating of drum impact, hook, and conviction. It is once per document.",
    "currently_popular is unavailable. Soundcharts is paid and is not called. A popularity number in any file is ignored.",
    "marketing_notes is local_notes supplied by hand. It is not similarity, not a listener rating, and not current popularity.",
]

_MEASUREMENTS = (
    "duration_sec",
    "tempo_bpm",
    "integrated_lufs",
    "rms_rel_peak_db",
    "mean_rms_dbfs",
    "hook",
    "novelty_peak_sec",
    "key",
    "energy_proxy",
    "danceability_proxy",
    "acousticness_proxy",
)


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
    """Mastering approval gate. approved and rendered stay false. No master is rendered.

    Source-file LUFS, when the file can be gated, is a track measurement.
    measured_lufs here stays null because it describes a master that was not made.
    """
    return {
        "share": "labeled measurements; comparison tracks only from a verified catalog",
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


def _measurement(
    value: object,
    unit: str,
    method: str,
    note: str,
    confidence: float | None = None,
    **extra: object,
) -> dict:
    item: dict = {
        "value": value,
        "unit": unit,
        "method": method,
        "confidence": confidence,
        "note": note,
    }
    item.update(extra)
    return item


def _measurements(features) -> dict:
    """Label every signal. Confidence stays null where we have no validated error rate."""
    key_value = None
    if features.key:
        key_value = f"{features.key} {features.mode or ''}".strip()
    return {
        "duration_sec": _measurement(
            round(features.duration_sec, 3),
            "s",
            "samples/sample_rate",
            "Duration of the decoded file.",
        ),
        "tempo_bpm": _measurement(
            round(features.tempo_bpm, 2),
            "BPM",
            "librosa.beat.beat_track",
            "Beat-tracker estimate. Half-time and double-time locks are common. Not a validated tempo.",
            regularity=features.beat_interval_regularity,
            octave_ambiguous=True,
        ),
        "integrated_lufs": _measurement(
            None if features.integrated_lufs is None else round(features.integrated_lufs, 2),
            "LUFS",
            "ITU-R BS.1770-4",
            features.lufs_note or "Integrated loudness of the file channels. Not the RMS figure.",
            channels=features.lufs_channels,
        ),
        "rms_rel_peak_db": _measurement(
            None if features.rms_rel_peak_db is None else round(features.rms_rel_peak_db, 2),
            "dB re peak RMS",
            "mean(amplitude_to_db(rms, ref=max rms))",
            "Mean frame level relative to this file's own loudest RMS frame. Not LUFS and not dBFS.",
        ),
        "mean_rms_dbfs": _measurement(
            None if features.mean_rms_dbfs is None else round(features.mean_rms_dbfs, 2),
            "dBFS",
            "20*log10(mean RMS amplitude)",
            "Average RMS against digital full scale. Not LUFS.",
        ),
        "hook": _measurement(
            round(features.hook_onset_sec, 3) if features.hook_verified and features.hook_onset_sec is not None else None,
            "s",
            "verified_mark" if features.hook_verified else "none",
            "No hook detector. An onset peak is not a hook, so this value stays null.",
            verified=features.hook_verified,
        ),
        "novelty_peak_sec": _measurement(
            None if features.novelty_peak_sec is None else round(features.novelty_peak_sec, 3),
            "s",
            "argmax onset strength after 8s",
            "Strongest onset after 8 seconds. Not a verified hook and not a cut point.",
        ),
        "key": _measurement(
            key_value,
            "pitch-class estimate",
            "chroma_cqt argmax plus major/minor triad energy",
            "Chroma estimate only. key_margin is a bin gap, not a probability that the key is correct.",
            key_margin=None if features.key_margin is None else round(features.key_margin, 4),
            mode_margin=None if features.mode_margin is None else round(features.mode_margin, 4),
        ),
        "energy_proxy": _measurement(
            round(features.energy, 4),
            "1",
            "clamp(mean_rms * 8)",
            "Clipped heuristic. A value of 1 means the scale saturated, not a measured maximum.",
            saturated=features.energy_saturated,
        ),
        "danceability_proxy": _measurement(
            round(features.danceability, 4),
            "1",
            "onset strength plus closeness of BPM to 100, 120, or 140",
            "Heuristic. Not a listening test and not a streaming-service danceability feature.",
        ),
        "acousticness_proxy": _measurement(
            round(features.acousticness, 4),
            "1",
            "clamp(1 - 4 * mean spectral flatness)",
            "High means the spectrum is tonal, not that the record is acoustic.",
        ),
    }


def _comps_block(brief: ARBrief) -> dict:
    if brief.comps_status != "ok":
        return {
            "status": "unavailable",
            "reason": brief.comps_reason or "no verified comparison catalog",
            "count": 0,
            "shown": 0,
            "omitted": 0,
            "items": [],
        }
    shown = brief.comps[:3]
    return {
        "status": "ok",
        "reason": None,
        "count": len(brief.comps),
        "shown": len(shown),
        "omitted": max(0, len(brief.comps) - len(shown)),
        "items": [
            {
                "title": match.comp.title,
                "artist": match.comp.artist,
                "distance": match.distance,
                "why": match.why[:3],
                "musicbrainz_recording_mbid": match.comp.musicbrainz_recording_mbid,
            }
            for match in shown
        ],
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


def _questions(brief: ARBrief) -> dict:
    questions = brief.questions or {}
    if all(lane in questions for lane in ("sounds_similar", "good_song", "currently_popular")):
        return questions
    return build_questions(
        catalog_verified=False,
        catalog_reason=brief.comps_reason or "no comparison questions were computed",
        tracks=[],
        matches=[],
        held=[],
    )


def _handoff_questions(brief: ARBrief) -> dict:
    """Similarity stays on the track. Quality and popularity are hoisted once per document."""
    similar = dict(_questions(brief)["sounds_similar"])
    similar.pop("items", None)
    similar.pop("held", None)
    similar["items_field"] = "comps"
    return {"sounds_similar": similar}


def _document_lanes(briefs: list[ARBrief]) -> tuple[dict, dict, list]:
    if not briefs:
        empty = build_questions(
            catalog_verified=False,
            catalog_reason="no tracks",
            tracks=[],
            matches=[],
            held=[],
        )
        return empty["good_song"], empty["currently_popular"], []
    questions = [_questions(brief) for brief in briefs]
    good = questions[0]["good_song"]
    popular = questions[0]["currently_popular"]
    held = list(briefs[0].comparison_held)
    good_same = all(item["good_song"] == good for item in questions)
    popular_same = all(item["currently_popular"] == popular for item in questions)
    held_same = all(brief.comparison_held == held for brief in briefs)
    if not good_same:
        good = {
            "status": "unavailable",
            "reason": "Listener ratings differ across tracks. Each differing track carries its own good_song.",
            "scale": "1-5 listener rating",
            "items": [],
        }
    if not popular_same:
        popular = {
            "status": "unavailable",
            "reason": POPULARITY_UNAVAILABLE,
            "source": None,
            "items": [],
        }
    if not held_same:
        held = []
    return good, popular, held


def _track_record(brief: ARBrief, beats: list[float], beat_grid: str) -> dict:
    path = Path(brief.track_path)
    digest, size = _sha256(path)
    trims = propose_trims(
        duration_sec=brief.features.duration_sec,
        beat_times=beats,
        hook_onset_sec=brief.features.hook_onset_sec,
        hook_verified=brief.features.hook_verified,
        novelty_peak_sec=brief.features.novelty_peak_sec,
        goal=brief.goal,
    )
    trims["beat_grid"] = beat_grid
    return {
        "filename": path.name,
        "audio": {
            "sha256": digest,
            "bytes": size,
            "source_path": brief.track_path,
            "bytes_included": False,
            "readable": digest is not None,
            "reason": None if digest is not None else "file was not readable; no digest to pair",
        },
        "duration_sec": round(brief.features.duration_sec, 3),
        "goal": brief.goal.value,
        "measurements": _measurements(brief.features),
        "comps": _comps_block(brief),
        "questions": _handoff_questions(brief),
        "fit": {"score": round(brief.fit.score, 4), "rationale": brief.fit.rationale},
        "gaps": [{"code": gap.code, "severity": gap.severity, "message": gap.message} for gap in brief.gaps],
        "plays": [
            {"primary": play.primary, "title": play.title, "actions": play.actions, "evidence": play.evidence}
            for play in brief.plays
        ],
        "trims": trims,
    }


def _missing_fields(
    tracks: list[dict],
    good_song: dict,
    currently_popular: dict,
    marketing_notes: dict,
) -> list[dict]:
    missing: list[dict] = []
    for lane, block in (("good_song", good_song), ("currently_popular", currently_popular)):
        if block.get("status") not in {"ok", "rated"}:
            missing.append({"field": lane, "reason": block.get("reason") or "unavailable"})
    if marketing_notes.get("status") != "supplied":
        missing.append(
            {"field": "marketing_notes", "reason": marketing_notes.get("reason") or "unavailable"}
        )
    for index, track in enumerate(tracks):
        for name, measurement in track["measurements"].items():
            if measurement.get("value") is None:
                missing.append(
                    {
                        "field": f"tracks[{index}].measurements.{name}",
                        "reason": measurement.get("note") or "null",
                    }
                )
        if track["comps"]["status"] != "ok":
            missing.append({"field": f"tracks[{index}].comps", "reason": track["comps"]["reason"]})
        similar = (track.get("questions") or {}).get("sounds_similar")
        if not isinstance(similar, dict) or similar.get("status") not in {"ok", "rated"}:
            reason = similar.get("reason") if isinstance(similar, dict) else None
            missing.append(
                {
                    "field": f"tracks[{index}].questions.sounds_similar",
                    "reason": reason or "unavailable",
                }
            )
        if track["audio"]["sha256"] is None:
            missing.append({"field": f"tracks[{index}].audio.sha256", "reason": track["audio"]["reason"]})
        for edge in ("intro", "outro"):
            block = track["trims"][edge]
            if block["status"] != "proposed":
                missing.append({"field": f"tracks[{index}].trims.{edge}", "reason": block["reason"]})
    return missing


def canonical_body(payload: Mapping[str, object]) -> bytes:
    """Stable JSON of the handoff, excluding the seal fields that describe those bytes."""
    body = {key: value for key, value in payload.items() if key not in _META_KEYS}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def posted_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def seal_handoff(payload: dict) -> dict:
    sealed = dict(payload)
    raw = canonical_body(sealed)
    sealed["payload_utf8_bytes"] = len(raw)
    sealed["payload_sha256"] = hashlib.sha256(raw).hexdigest()
    return sealed


def validate_handoff(payload: Mapping[str, object]) -> list[str]:
    """Return structural errors. Empty means the sealed document is complete and within the cap."""
    errors: list[str] = []
    required = (
        "contract",
        "complete",
        "missing",
        "payload_utf8_bytes",
        "payload_sha256",
        "audio_bytes_included",
        "audio_pairing",
        "tracks",
        "album_sequence",
        "good_song",
        "currently_popular",
        "marketing_notes",
        "comparison_held",
        "workflow",
        "zz_end",
    )
    for key in required:
        if key not in payload:
            errors.append(f"missing:{key}")
    if payload.get("contract") != CONTRACT:
        errors.append("contract")
    if payload.get("zz_end") != "complete":
        errors.append("zz_end")
    if payload.get("audio_bytes_included") is not False:
        errors.append("audio_bytes_included")
    mastering = (payload.get("workflow") or {}).get("mastering") if isinstance(payload.get("workflow"), dict) else None
    if not isinstance(mastering, dict) or mastering.get("approved") is not False:
        errors.append("mastering_approved")
    if not isinstance(mastering, dict) or mastering.get("rendered") is not False:
        errors.append("mastering_rendered")
    if not isinstance(mastering, dict) or mastering.get("target_lufs") != TARGET_LUFS:
        errors.append("mastering_target")
    tracks = payload.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        errors.append("tracks")
        tracks = []
    for index, track in enumerate(tracks):
        if not isinstance(track, dict):
            errors.append(f"tracks[{index}]")
            continue
        for key in ("filename", "audio", "measurements", "comps", "questions", "fit", "gaps", "plays", "trims"):
            if key not in track:
                errors.append(f"tracks[{index}].{key}")
        questions = track.get("questions") if isinstance(track.get("questions"), dict) else {}
        similar = questions.get("sounds_similar")
        if not isinstance(similar, dict) or "status" not in similar or similar.get("items_field") != "comps":
            errors.append(f"tracks[{index}].questions.sounds_similar")
        elif similar["status"] not in {"ok", "unavailable"}:
            errors.append(f"tracks[{index}].questions.sounds_similar.status")
        elif similar["status"] == "unavailable" and not similar.get("reason"):
            errors.append(f"tracks[{index}].questions.sounds_similar.unavailable")
        for lane in ("good_song", "currently_popular"):
            block = questions.get(lane)
            if block is None:
                continue
            if not isinstance(block, dict) or "status" not in block or "items" not in block:
                errors.append(f"tracks[{index}].questions.{lane}")
            elif block["status"] == "unavailable" and (not block.get("reason") or block.get("items")):
                errors.append(f"tracks[{index}].questions.{lane}.unavailable")
        measurements = track.get("measurements") if isinstance(track.get("measurements"), dict) else {}
        for name in _MEASUREMENTS:
            measurement = measurements.get(name)
            if not isinstance(measurement, dict):
                errors.append(f"tracks[{index}].measurements.{name}")
                continue
            for field in ("value", "unit", "method", "note"):
                if field not in measurement:
                    errors.append(f"tracks[{index}].measurements.{name}.{field}")
            if measurement.get("value") is None and not measurement.get("note"):
                errors.append(f"tracks[{index}].measurements.{name}.null_without_note")
        comps = track.get("comps") if isinstance(track.get("comps"), dict) else {}
        if comps.get("status") not in {"ok", "unavailable"}:
            errors.append(f"tracks[{index}].comps.status")
        if comps.get("status") == "unavailable" and (not comps.get("reason") or comps.get("items")):
            errors.append(f"tracks[{index}].comps.unavailable")
        if isinstance(similar, dict) and similar.get("status") == "ok" and comps.get("status") != "ok":
            errors.append(f"tracks[{index}].questions.sounds_similar.comps")
        if isinstance(similar, dict) and similar.get("status") == "unavailable" and comps.get("items"):
            errors.append(f"tracks[{index}].questions.sounds_similar.comps")
        trims = track.get("trims") if isinstance(track.get("trims"), dict) else {}
        for edge in ("intro", "outro"):
            if edge not in trims:
                errors.append(f"tracks[{index}].trims.{edge}")
        if trims.get("fade_out") is not False or trims.get("applied") is not False:
            errors.append(f"tracks[{index}].trims.not_applied")
        blob = json.dumps(track.get("comps")) + json.dumps(track.get("plays")) + json.dumps(track.get("questions"))
        if "Seed Artist" in blob:
            errors.append(f"tracks[{index}].fixture_comp")
    popular = payload.get("currently_popular") if isinstance(payload.get("currently_popular"), dict) else {}
    if (
        set(popular) - {"status", "reason", "source", "items"}
        or popular.get("status") != "unavailable"
        or popular.get("items") != []
        or not popular.get("reason")
    ):
        errors.append("currently_popular")
    marketing = payload.get("marketing_notes") if isinstance(payload.get("marketing_notes"), dict) else {}
    marketing_fields = ("status", "reason", "source", *MARKETING_FIELDS)
    if any(field not in marketing for field in marketing_fields) or set(marketing) - set(marketing_fields):
        errors.append("marketing_notes")
    elif marketing.get("status") == "unavailable":
        if not marketing.get("reason") or marketing.get("source") is not None:
            errors.append("marketing_notes.unavailable")
        elif any(marketing.get(field) for field in MARKETING_FIELDS):
            errors.append("marketing_notes.unavailable")
    elif marketing.get("status") != "supplied" or marketing.get("source") != "local_notes":
        errors.append("marketing_notes.status")
    elif any(not isinstance(marketing.get(field), str) for field in MARKETING_FIELDS):
        errors.append("marketing_notes.fields")
    good = payload.get("good_song") if isinstance(payload.get("good_song"), dict) else {}
    if "status" not in good or "items" not in good:
        errors.append("good_song")
    elif good.get("status") == "unavailable" and (not good.get("reason") or good.get("items")):
        errors.append("good_song.unavailable")
    if not isinstance(payload.get("comparison_held"), list):
        errors.append("comparison_held")
    raw = canonical_body(payload)
    posted = posted_bytes(payload)
    if len(posted) > MAX_HANDOFF_UTF8_BYTES:
        errors.append(f"over_bound:{len(posted)}")
    if payload.get("payload_sha256") != hashlib.sha256(raw).hexdigest():
        errors.append("payload_sha256")
    if payload.get("payload_utf8_bytes") != len(raw):
        errors.append("payload_utf8_bytes")
    if errors:
        return errors
    if payload.get("complete") is not True:
        errors.append("complete")
    return errors


def _shared_marketing(briefs: list[ARBrief]) -> dict:
    if not briefs:
        return unavailable_marketing()
    lanes = [marketing_lane(brief.marketing_notes) for brief in briefs]
    first = lanes[0]
    if all(lane == first for lane in lanes):
        return first
    return unavailable_marketing(
        "Marketing notes differ across tracks. Pass one --marketing file for the document."
    )


def _sealed_len(payload: dict) -> int:
    return len(posted_bytes(seal_handoff(payload)))


def _longest_prefix(payload: dict, lane: dict, field: str, text: str) -> int:
    lo = 0
    hi = len(text)
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        lane[field] = text[:mid]
        if _sealed_len(payload) <= MAX_HANDOFF_UTF8_BYTES:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    lane[field] = text[:best]
    return best


_SHRINK_ORDER = ("notes", "playlist_pitch", "radio", "campaign", "audience", "supplied_by")
_SHORTEN_REASON = "Notes were shortened so the sealed handoff stays within 96 KiB."


def _shrink_marketing_notes(payload: dict) -> dict:
    """Shorten marketing text when that is what would cross 96 KiB.

    Required sections stay in the document. If the tracks alone exceed the cap,
    the notes are left as written and validate_handoff refuses the whole body.
    """
    lane = payload.get("marketing_notes")
    if not isinstance(lane, dict) or _sealed_len(payload) <= MAX_HANDOFF_UTF8_BYTES:
        return payload
    originals = {
        field: lane.get(field) if isinstance(lane.get(field), str) else "" for field in _SHRINK_ORDER
    }
    for field in _SHRINK_ORDER:
        lane[field] = ""
    if _sealed_len(payload) > MAX_HANDOFF_UTF8_BYTES:
        for field, text in originals.items():
            lane[field] = text
        return payload
    for field, text in originals.items():
        lane[field] = text
    previous_reason = lane.get("reason")
    if lane.get("status") == "supplied":
        lane["reason"] = _SHORTEN_REASON
    for field in _SHRINK_ORDER:
        if _sealed_len(payload) <= MAX_HANDOFF_UTF8_BYTES:
            break
        _longest_prefix(payload, lane, field, originals[field])
    if _sealed_len(payload) <= MAX_HANDOFF_UTF8_BYTES:
        return payload
    lane["reason"] = previous_reason if isinstance(previous_reason, str) or previous_reason is None else None
    for field in _SHRINK_ORDER:
        if _sealed_len(payload) <= MAX_HANDOFF_UTF8_BYTES:
            break
        current = lane.get(field) if isinstance(lane.get(field), str) else ""
        _longest_prefix(payload, lane, field, current)
    return payload


def build_handoff(
    briefs: list[ARBrief],
    beat_times_by_track: Mapping[str, list[float]] | None = None,
    beat_grid_by_track: Mapping[str, str] | None = None,
    marketing_notes: Mapping[str, object] | None = None,
) -> dict:
    """Build the sealed JSON body. Does not write audio or open a connection."""
    beats = beat_times_by_track or {}
    beat_grid = beat_grid_by_track or {}
    tracks: list[dict] = []
    sequence_input: list[dict] = []
    for brief in briefs:
        tracks.append(
            _track_record(
                brief,
                [float(beat) for beat in beats.get(brief.track_path, [])],
                beat_grid.get(brief.track_path, "not_requested"),
            )
        )
        sequence_input.append(
            {
                "track_id": brief.track_path,
                "energy": brief.features.energy,
                "tempo_bpm": brief.features.tempo_bpm,
                "key": brief.features.key,
            }
        )
    good_song, currently_popular, held = _document_lanes(briefs)
    shared_good = json.dumps(good_song, sort_keys=True) != json.dumps(
        {
            "status": "unavailable",
            "reason": "Listener ratings differ across tracks. Each differing track carries its own good_song.",
            "scale": "1-5 listener rating",
            "items": [],
        },
        sort_keys=True,
    )
    if briefs and not shared_good:
        for brief, track in zip(briefs, tracks, strict=True):
            track["questions"]["good_song"] = _questions(brief)["good_song"]
    if marketing_notes is not None:
        lane = marketing_lane(marketing_notes)
    else:
        lane = _shared_marketing(briefs)
    payload = {
        "contract": CONTRACT,
        "generated_by": f"open-ar {__version__}",
        "bot": {"name": BOT_NAME, "id": BOT_ID, "role": BOT_ROLE},
        "audio_bytes_included": False,
        "audio_pairing": {
            "method": "sha256",
            "bytes_included": False,
            "upload": "not_performed",
            "endpoint": None,
            "note": (
                "No audio URL is included. Copy the file onto Andre's computer by a path you already trust. "
                "Hash it with SHA-256 and pair it only when the digest and byte size match. "
                "If the file is absent, leave the audio unavailable."
            ),
        },
        "workflow": workflow_policy(),
        "tracks": tracks,
        "album_sequence": sequence_album(sequence_input),
        "good_song": good_song,
        "currently_popular": currently_popular,
        "marketing_notes": lane,
        "comparison_held": held,
        "missing": [],
        "context_notes": list(CONTEXT_NOTES),
        "zz_end": "complete",
    }
    payload["missing"] = _missing_fields(tracks, good_song, currently_popular, lane)
    payload["complete"] = True
    payload = _shrink_marketing_notes(payload)
    payload["missing"] = _missing_fields(tracks, good_song, currently_popular, payload["marketing_notes"])
    payload["complete"] = True
    return seal_handoff(payload)


def _redact(text: str, key: str | None) -> str:
    if key and key in text:
        text = text.replace(key, "[redacted]")
    return text[:200]


def _post_webhook(url: str, key: str, payload: dict) -> tuple[int, str]:
    """POST once. Do not follow redirects, so the bearer key stays on the original host."""
    data = posted_bytes(payload)
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
    errors = validate_handoff(handoff)
    result = {
        "connection": connection.public_dict(),
        "attempted": False,
        "delivered": False,
        "http_status": None,
        "detail": "",
        "validation_errors": errors,
        "handoff": handoff,
    }
    if errors:
        result["detail"] = "Not sent. Payload failed validation: " + ", ".join(errors)
        return result
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
