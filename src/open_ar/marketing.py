"""Local marketing notes.

This lane is a file someone writes by hand. It does not call Soundcharts or any
network. It is not sounds_similar, good_song, or currently_popular.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

MARKETING_FIELDS = (
    "supplied_by",
    "campaign",
    "audience",
    "playlist_pitch",
    "radio",
    "notes",
)

MARKETING_ABSENT = (
    "No local marketing notes file was provided. "
    "Pass --marketing with notes you wrote. "
    "Marketing notes are local_notes, not Soundcharts, and they are not currently_popular."
)


def unavailable_marketing(reason: str | None = None) -> dict:
    return {
        "status": "unavailable",
        "reason": reason or MARKETING_ABSENT,
        "source": None,
        "supplied_by": "",
        "campaign": "",
        "audience": "",
        "playlist_pitch": "",
        "radio": "",
        "notes": "",
    }


def _text(raw: Mapping[str, object], key: str) -> str:
    value = raw.get(key, "")
    if not isinstance(value, str):
        return ""
    return value.strip()


def marketing_lane(raw: Mapping[str, object] | None) -> dict:
    """Normalize notes into the handoff lane.

    Chart ranks, stream counts, and popularity numbers are not copied.
    Source is local_notes only when notes were supplied.
    """
    if not isinstance(raw, Mapping):
        return unavailable_marketing()
    texts = {field: _text(raw, field) for field in MARKETING_FIELDS}
    if raw.get("status") == "unavailable" and not any(texts.values()):
        reason = raw.get("reason")
        if isinstance(reason, str) and reason.strip():
            return unavailable_marketing(reason.strip())
        return unavailable_marketing()
    return {
        "status": "supplied",
        "reason": None,
        "source": "local_notes",
        **texts,
    }


def load_marketing_notes(path: str | Path | None) -> dict:
    """Read a local JSON file. No network. An absent path is an unavailable lane."""
    if path is None:
        return unavailable_marketing()
    parsed = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("Marketing notes file must be a JSON object.")
    return marketing_lane(parsed)
