"""User-supplied attention and conversion rows.

Google Trends and first-party analytics are accepted only as CSV files the
user already downloaded. This module does not scrape Trends, call Google, or
call Soundcharts. A row without a date or a source is rejected. A number
without a denominator stays null unless the row itself gives a
denominator_missing reason, and that row is still not a rate.

These rows are an attention/conversion lane. They are not audio distance,
not a listener rating, and not currently_popular.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import date
from pathlib import Path

EVIDENCE_RULE = (
    "A comparison requires at least two observations of the same source and metric, "
    "on different dates, each with a numeric value and a numeric denominator greater than zero. "
    "A variant or test column is part of that grouping, so two variants are not pooled. "
    "Rows without a date or a source are rejected. A missing denominator stays null unless the row "
    "states denominator_missing, and that row is still not a rate. Missing dates are not filled in. "
    "Meeting the rule describes the change between the earliest and latest supplied rate. "
    "It is not statistical significance, not a winning campaign, and not a prediction that a song will hit."
)
MIN_DATED_RATE_OBSERVATIONS = 2

_DATE_COLUMNS = ("date", "day", "week")
_SOURCE_COLUMNS = ("source", "source_label")
_METRIC_COLUMNS = ("metric", "metric_name")
_VALUE_COLUMNS = ("value", "numerator")
_DENOMINATOR_COLUMNS = ("denominator",)
_REASON_COLUMNS = ("denominator_missing", "denominator_missing_reason")
_VARIANT_COLUMNS = ("variant", "test")


def unavailable_attention(reason: str | None = None) -> dict:
    return {
        "status": "unavailable",
        "lane": "attention_conversion",
        "reason": reason
        or "No Google Trends CSV or first-party analytics CSV was provided.",
        "network": False,
        "called_google": False,
        "called_soundcharts": False,
        "files": [],
        "observations": [],
        "rejected": [],
        "does_not_change": [
            "sounds_similar",
            "good_song",
            "fit",
            "currently_popular",
            "audio_features",
        ],
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cell(row: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        if name in row and row[name] is not None:
            text = str(row[name]).strip()
            if text:
                return text
    return ""


def _normalize_row(raw: dict[str | None, str | None]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        if key is None:
            continue
        cleaned[str(key).strip().lower()] = "" if value is None else str(value).strip()
    return cleaned


def _parse_date(text: str) -> str | None:
    if len(text) < 10 or text[4] != "-" or text[7] != "-":
        return None
    candidate = text[:10]
    try:
        date.fromisoformat(candidate)
    except ValueError:
        return None
    return candidate


def _number(text: str) -> float | None:
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_evidence_csv(path: str | Path, kind: str) -> dict:
    """Read one local CSV. `kind` is the flag the user passed, not a filled-in source."""
    if kind not in {"google_trends", "first_party_analytics"}:
        raise ValueError("Evidence kind must be google_trends or first_party_analytics.")
    file_path = Path(path)
    observations: list[dict] = []
    rejected: list[dict] = []
    with file_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return {
                "kind": kind,
                "file_path": str(file_path),
                "sha256": _sha256(file_path),
                "user_supplied": True,
                "observations": [],
                "rejected": [{"line": 1, "reason": "missing header"}],
            }
        for index, raw in enumerate(reader):
            line = index + 2
            row = _normalize_row(raw)
            if not any(row.values()):
                continue
            missing: list[str] = []
            parsed_date = _parse_date(_cell(row, _DATE_COLUMNS))
            source = _cell(row, _SOURCE_COLUMNS)
            metric = _cell(row, _METRIC_COLUMNS)
            if parsed_date is None:
                missing.append("missing date")
            if not source:
                missing.append("missing source")
            if not metric:
                missing.append("missing metric")
            if missing:
                rejected.append(
                    {
                        "line": line,
                        "file": str(file_path),
                        "kind": kind,
                        "reason": "; ".join(missing),
                    }
                )
                continue
            value_text = _cell(row, _VALUE_COLUMNS)
            denominator_text = _cell(row, _DENOMINATOR_COLUMNS)
            missing_reason = _cell(row, _REASON_COLUMNS)
            reported_value = _number(value_text)
            denominator = _number(denominator_text)
            reason = None
            rate = None
            usable = False
            if value_text and reported_value is None:
                reported_value = None
                reason = "value is not a number; left null"
            elif denominator_text and denominator is None:
                denominator = None
                reported_value = None
                reason = "denominator is not a number; value not used"
            elif denominator is None:
                reported_value = reported_value if missing_reason else None
                if not missing_reason:
                    reason = "denominator missing and no denominator_missing reason; value not used"
                else:
                    reason = missing_reason
            elif denominator <= 0:
                reported_value = None
                denominator = None
                reason = "denominator must be greater than zero; value not used"
            elif reported_value is None:
                reason = "value missing; rate not computed"
            else:
                rate = reported_value / denominator
                usable = True
            observations.append(
                {
                    "date": parsed_date,
                    "source": source,
                    "metric": metric,
                    "variant": _cell(row, _VARIANT_COLUMNS),
                    "reported_value": reported_value,
                    "denominator": denominator if usable else (denominator if denominator and denominator > 0 else None),
                    "rate": rate,
                    "reason": reason,
                    "usable_as_rate": usable,
                    "user_supplied": True,
                    "file": str(file_path),
                    "kind": kind,
                    "line": line,
                }
            )
    return {
        "kind": kind,
        "file_path": str(file_path),
        "sha256": _sha256(file_path),
        "user_supplied": True,
        "observations": observations,
        "rejected": rejected,
    }


def load_attention_evidence(
    trends_path: str | Path | None = None,
    analytics_path: str | Path | None = None,
) -> dict:
    """Map local CSVs into the attention/conversion lane. No network."""
    loaded: list[tuple[str, dict]] = []
    if trends_path is not None:
        loaded.append(("google_trends", load_evidence_csv(trends_path, "google_trends")))
    if analytics_path is not None:
        loaded.append(("first_party_analytics", load_evidence_csv(analytics_path, "first_party_analytics")))
    if not loaded:
        return unavailable_attention()
    observations: list[dict] = []
    rejected: list[dict] = []
    files: list[dict] = []
    for _kind, parsed in loaded:
        observations.extend(parsed["observations"])
        rejected.extend(parsed["rejected"])
        files.append(
            {
                "kind": parsed["kind"],
                "file_path": parsed["file_path"],
                "sha256": parsed["sha256"],
                "user_supplied": True,
            }
        )
    return {
        "status": "supplied",
        "lane": "attention_conversion",
        "reason": None,
        "network": False,
        "called_google": False,
        "called_soundcharts": False,
        "files": files,
        "observations": observations,
        "rejected": rejected,
        "does_not_change": [
            "sounds_similar",
            "good_song",
            "fit",
            "currently_popular",
            "audio_features",
        ],
    }


def describe_comparisons(observations: list[dict]) -> dict:
    """Apply EVIDENCE_RULE. Does not interpolate dates or declare a winner."""
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for item in observations:
        if not item.get("usable_as_rate"):
            continue
        key = (str(item.get("source") or ""), str(item.get("metric") or ""), str(item.get("variant") or ""))
        groups.setdefault(key, []).append(item)
    items: list[dict] = []
    for (source, metric, variant), rows in groups.items():
        dated = [row for row in rows if row.get("date") and row.get("rate") is not None]
        distinct_dates = {row["date"] for row in dated}
        if len(dated) < MIN_DATED_RATE_OBSERVATIONS or len(distinct_dates) < MIN_DATED_RATE_OBSERVATIONS:
            continue
        ordered = sorted(dated, key=lambda row: (row["date"], row.get("line") or 0))
        earliest = ordered[0]
        latest = ordered[-1]
        if earliest["date"] == latest["date"]:
            continue
        items.append(
            {
                "source": source,
                "metric": metric,
                "variant": variant,
                "lane": "attention_conversion",
                "n": len(ordered),
                "earliest": {
                    "date": earliest["date"],
                    "rate": earliest["rate"],
                    "reported_value": earliest["reported_value"],
                    "denominator": earliest["denominator"],
                },
                "latest": {
                    "date": latest["date"],
                    "rate": latest["rate"],
                    "reported_value": latest["reported_value"],
                    "denominator": latest["denominator"],
                },
                "rate_change": latest["rate"] - earliest["rate"],
                "label": "described_change",
                "not_a_hit_prediction": True,
                "not_statistical_significance": True,
                "not_currently_popular": True,
                "not_a_songwriting_score": True,
            }
        )
    if items:
        return {
            "status": "comparison",
            "reason": None,
            "rule": EVIDENCE_RULE,
            "minimum_dated_observations": MIN_DATED_RATE_OBSERVATIONS,
            "items": items,
        }
    usable = sum(1 for item in observations if item.get("usable_as_rate"))
    return {
        "status": "insufficient_evidence",
        "reason": (
            "No metric has two dated observations with denominators. "
            f"Usable rate rows: {usable}. {EVIDENCE_RULE}"
        ),
        "rule": EVIDENCE_RULE,
        "minimum_dated_observations": MIN_DATED_RATE_OBSERVATIONS,
        "items": [],
    }
