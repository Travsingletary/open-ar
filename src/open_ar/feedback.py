"""Explicit local feedback.

Records are ratings, corrections, and campaign outcomes the user writes.
Personalization from these records is an average of the ratings they marked
for use. It is not model training. Held-out rows are skipped when building
that average. Corrections are stored and do not rewrite AudioFeatures.
Rows the app would have guessed are ignored.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from open_ar.schema import AudioFeatures

DEFAULT_FEEDBACK_PATH = Path(".data/feedback.json")
PERSONALIZATION = "not_model_training"
STORE_VERSION = "open-ar-feedback-1"
IGNORED_SOURCES = {"open_ar_guess", "model", "app"}
KINDS = {"rating", "correction", "campaign_outcome"}


def empty_store() -> dict:
    return {
        "version": STORE_VERSION,
        "personalization": PERSONALIZATION,
        "note": (
            "Explicit user input. Not used to fit a model, and not used to rewrite AudioFeatures. "
            "Skip records with held_out true when building a rule. If none are marked held out, "
            "the check was not run."
        ),
        "records": [],
    }


def load_store(path: str | Path | None) -> dict:
    if path is None:
        return empty_store()
    file_path = Path(path)
    if not file_path.is_file():
        return empty_store()
    parsed = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or not isinstance(parsed.get("records"), list):
        raise ValueError("Feedback file must be a JSON object with a records list.")
    parsed["personalization"] = PERSONALIZATION
    return parsed


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_record(
    path: str | Path,
    *,
    target_track_id: str,
    rater: str,
    kind: str,
    corrected: str,
    source: str = "user",
    timestamp: str | None = None,
    held_out: bool = False,
    drum_impact: int | None = None,
    hook: int | None = None,
    conviction: int | None = None,
    detail: str = "",
    user_supplied: bool = True,
) -> dict:
    """Append one user record. Does not read or write audio."""
    if kind not in KINDS:
        raise ValueError("Feedback kind must be rating, correction, or campaign_outcome.")
    if not target_track_id.strip():
        raise ValueError("target_track_id is required.")
    if not rater.strip() and not source.strip():
        raise ValueError("A rater or a source is required.")
    if not corrected.strip():
        raise ValueError("Say what was corrected.")
    file_path = Path(path)
    store = load_store(file_path)
    record = {
        "id": str(uuid.uuid4()),
        "kind": kind,
        "rater": rater.strip(),
        "source": source.strip() or "user",
        "timestamp": timestamp or _utc_now(),
        "target_track_id": target_track_id.strip(),
        "corrected": corrected.strip(),
        "user_supplied": user_supplied is True,
        "held_out": held_out is True,
        "drum_impact": drum_impact,
        "hook": hook,
        "conviction": conviction,
        "detail": detail.strip(),
    }
    store["records"].append(record)
    store["version"] = STORE_VERSION
    store["personalization"] = PERSONALIZATION
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    return record


def _rating_value(record: dict) -> float | None:
    value = record.get("drum_impact")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _ignored(record: dict) -> bool:
    if record.get("user_supplied") is not True:
        return True
    if str(record.get("source") or "") in IGNORED_SOURCES:
        return True
    return False


def rating_rule(records: list[dict]) -> dict:
    """Mean drum_impact per track from user ratings that are not held out.

    This is arithmetic on explicit ratings. No model is fit. Held-out rows
    and app guesses are counted as excluded and are not in the mean.
    """
    buckets: dict[str, list[float]] = {}
    excluded_held_out: dict[str, int] = {}
    excluded_other: dict[str, int] = {}
    for record in records:
        if record.get("kind") != "rating":
            continue
        track_id = str(record.get("target_track_id") or "")
        if not track_id:
            continue
        value = _rating_value(record)
        if value is None:
            continue
        if record.get("held_out") is True and not _ignored(record):
            excluded_held_out[track_id] = excluded_held_out.get(track_id, 0) + 1
            continue
        if _ignored(record) or record.get("held_out") is True:
            excluded_other[track_id] = excluded_other.get(track_id, 0) + 1
            continue
        buckets.setdefault(track_id, []).append(value)
    by_track = {}
    for track_id, values in buckets.items():
        by_track[track_id] = {
            "drum_impact_mean": sum(values) / len(values),
            "n": len(values),
            "excluded_held_out": excluded_held_out.get(track_id, 0),
            "excluded_not_user_supplied": excluded_other.get(track_id, 0),
        }
    for track_id in set(excluded_held_out) | set(excluded_other):
        by_track.setdefault(
            track_id,
            {
                "drum_impact_mean": None,
                "n": 0,
                "excluded_held_out": excluded_held_out.get(track_id, 0),
                "excluded_not_user_supplied": excluded_other.get(track_id, 0),
            },
        )
    return {
        "personalization": PERSONALIZATION,
        "method": "mean of user-supplied drum_impact, skipping held_out",
        "model_fit": False,
        "by_track": by_track,
    }


def held_out_check(records: list[dict]) -> dict:
    """Compare the rule with rows the user marked held_out. Does not refit."""
    rule = rating_rule(records)
    held = [
        record
        for record in records
        if record.get("kind") == "rating"
        and record.get("user_supplied") is True
        and record.get("held_out") is True
        and str(record.get("source") or "") not in IGNORED_SOURCES
        and _rating_value(record) is not None
    ]
    if not held:
        return {
            "held_out_check": "not_run",
            "reason": "No held_out=true user-supplied rating was marked, so the check was not run.",
            "personalization": PERSONALIZATION,
            "model_fit": False,
            "rule_uses_held_out": False,
            "comparisons": [],
        }
    comparisons = []
    for record in held:
        track_id = str(record.get("target_track_id") or "")
        suggested = rule["by_track"].get(track_id) or {}
        mean = suggested.get("drum_impact_mean")
        actual = _rating_value(record)
        difference = None if mean is None or actual is None else abs(mean - actual)
        comparisons.append(
            {
                "target_track_id": track_id,
                "held_out_drum_impact": actual,
                "rule_drum_impact": mean,
                "absolute_difference": difference,
                "used_to_build_rule": False,
            }
        )
    return {
        "held_out_check": "ran",
        "reason": None,
        "personalization": PERSONALIZATION,
        "model_fit": False,
        "rule_uses_held_out": False,
        "comparisons": comparisons,
    }


def features_after_feedback(features: AudioFeatures, records: list[dict]) -> AudioFeatures:
    """Return the same measurements. Corrections stay in the feedback file."""
    del records
    return features.model_copy(deep=True)
