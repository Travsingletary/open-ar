"""Manual strategy document from a brief plus local evidence.

A brief that exists, with mastering not rendered, yields audience and message
hypotheses. A comparison is written only when the evidence rule is met.
Otherwise the status is insufficient_evidence. Nothing is scheduled, posted,
or mastered. Soundcharts, Google, and Spotify are not called.
"""

from __future__ import annotations

import json
from pathlib import Path

from open_ar.andre import workflow_policy
from open_ar.comps import POPULARITY_UNAVAILABLE
from open_ar.evidence import EVIDENCE_RULE, describe_comparisons, load_attention_evidence
from open_ar.feedback import (
    PERSONALIZATION,
    features_after_feedback,
    held_out_check,
    load_store,
    rating_rule,
)
from open_ar.market_playbook import ATTRIBUTION, CHECKLIST, hypotheses_for_asset
from open_ar.marketing import load_marketing_notes, marketing_lane
from open_ar.schema import ARBrief, AudioFeatures


def _mastering_claim(raw: dict) -> bool | None:
    """True when the file claims a master was rendered. None when it does not say."""
    workflow = raw.get("workflow")
    if isinstance(workflow, dict) and isinstance(workflow.get("mastering"), dict):
        return workflow["mastering"].get("rendered") is True
    if raw.get("mastering_rendered") is True:
        return True
    return None


def load_brief(path: str | Path) -> tuple[ARBrief, dict]:
    file_path = Path(path)
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Brief JSON must be an object written by open-ar analyze --json.")
    contract = raw.get("contract")
    if isinstance(contract, str) and contract.startswith("open-ar.andre."):
        raise ValueError("Pass the analyze brief, not the Andre handoff.")
    try:
        brief = ARBrief.model_validate(raw)
    except Exception as exc:
        raise ValueError(f"Brief JSON could not be read: {exc}") from exc
    return brief, raw


def build_strategy(
    brief_path: str | Path,
    *,
    trends_path: str | Path | None = None,
    analytics_path: str | Path | None = None,
    marketing_path: str | Path | None = None,
    feedback_path: str | Path | None = None,
) -> dict:
    """Write the strategy document. Does not modify audio or fit a model."""
    brief, raw = load_brief(brief_path)
    rendered_claim = _mastering_claim(raw)
    mastering = workflow_policy()["mastering"]
    if marketing_path is not None:
        notes = load_marketing_notes(marketing_path)
    else:
        notes = marketing_lane(brief.marketing_notes)
    evidence = load_attention_evidence(trends_path, analytics_path)
    if trends_path is None and analytics_path is None:
        comparison = {
            "status": "insufficient_evidence",
            "reason": "No campaign evidence file was provided. " + EVIDENCE_RULE,
            "rule": EVIDENCE_RULE,
            "items": [],
        }
    else:
        comparison = describe_comparisons(evidence["observations"])
        if comparison["status"] != "comparison" and not comparison.get("reason"):
            comparison["reason"] = EVIDENCE_RULE
    asset_ok = rendered_claim is not True
    if asset_ok:
        hypotheses = hypotheses_for_asset(
            goal=brief.goal.value,
            audience=str(notes.get("audience") or ""),
            campaign=str(notes.get("campaign") or ""),
        )
        hypothesis_status = "hypotheses"
        hypothesis_reason = None
    else:
        hypotheses = []
        hypothesis_status = "not_generated"
        hypothesis_reason = (
            "Hypotheses are generated only when a brief exists and mastering is not rendered."
        )
    feedback_block = _feedback_block(feedback_path, brief.features)
    return {
        "version": "open-ar-strategy-1",
        "generated_by": "open-ar strategy",
        "scheduler": False,
        "network": False,
        "called_soundcharts": False,
        "called_google": False,
        "hit_prediction": False,
        "automatic_marketing": False,
        "asset": {
            "brief_path": str(brief_path),
            "track_path": brief.track_path,
            "goal": brief.goal.value,
            "brief_present": True,
            "approval": "brief_exists_master_not_rendered" if asset_ok else "not_an_unmastered_brief",
            "mastering": mastering,
        },
        "hypotheses": hypotheses,
        "hypothesis_status": hypothesis_status,
        "hypothesis_reason": hypothesis_reason,
        "playbook": {
            "attribution": ATTRIBUTION,
            "checklist": list(CHECKLIST),
        },
        "evidence_rule": EVIDENCE_RULE,
        "attention_evidence": evidence,
        "comparison": comparison,
        "feedback": feedback_block,
        "currently_popular": {
            "status": "unavailable",
            "reason": POPULARITY_UNAVAILABLE,
            "source": None,
            "items": [],
        },
        "does_not_change": [
            "sounds_similar",
            "good_song",
            "fit",
            "audio_features",
            "currently_popular",
        ],
        "audio_features_rewritten": False,
    }


def _feedback_block(path: str | Path | None, features: AudioFeatures) -> dict:
    if path is None or not Path(path).is_file():
        unchanged = features_after_feedback(features, [])
        return {
            "path": None if path is None else str(path),
            "personalization": PERSONALIZATION,
            "model_fit": False,
            "features_rewritten": unchanged.model_dump() != features.model_dump(),
            "rule": {"by_track": {}, "model_fit": False, "personalization": PERSONALIZATION},
            "held_out_check": {
                "held_out_check": "not_run",
                "reason": "No feedback file was provided, so the check was not run.",
                "rule_uses_held_out": False,
                "comparisons": [],
            },
        }
    store = load_store(path)
    records = [record for record in store.get("records", []) if isinstance(record, dict)]
    unchanged = features_after_feedback(features, records)
    return {
        "path": str(path),
        "personalization": PERSONALIZATION,
        "model_fit": False,
        "features_rewritten": unchanged.model_dump() != features.model_dump(),
        "rule": rating_rule(records),
        "held_out_check": held_out_check(records),
    }
