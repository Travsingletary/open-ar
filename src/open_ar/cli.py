from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from open_ar import __version__
from open_ar.acousticbrainz import add_to_catalog
from open_ar.andre import build_handoff, inspect_connection, posted_bytes, share_with_andre
from open_ar.brief import build_brief
from open_ar.comps import similarity_problem
from open_ar.edits import read_beat_times
from open_ar.feedback import DEFAULT_FEEDBACK_PATH, add_record, held_out_check, load_store
from open_ar.marketing import load_marketing_notes
from open_ar.schema import CompTrack, Goal, VideoGoal
from open_ar.strategy import build_strategy
from open_ar.video_brief import build_video_brief

app = typer.Typer(
    name="open-ar",
    help="Open-source A&R briefs: fit + strategy from local audio and music-video analysis.",
    no_args_is_help=True,
)
console = Console()


class GoalOption(str, Enum):
    playlist = "playlist"
    club = "club"
    sync = "sync"
    cult = "cult"
    lead_single = "lead_single"


class VideoGoalOption(str, Enum):
    youtube_mv = "youtube_mv"
    short_form = "short_form"
    premiere = "premiere"
    visualizer = "visualizer"


@app.callback()
def main() -> None:
    """Open A&R CLI."""


@app.command("version")
def version_cmd() -> None:
    """Print package version."""
    console.print(__version__)


def _print_plays_and_gaps(gaps, plays, disclaimer: str) -> None:
    if gaps:
        gap_table = Table(title="Gaps")
        gap_table.add_column("Severity")
        gap_table.add_column("Code")
        gap_table.add_column("Message")
        for g in gaps:
            gap_table.add_row(g.severity, g.code, g.message)
        console.print(gap_table)

    for play in plays:
        tag = "PRIMARY" if play.primary else "ALT"
        console.print(Panel("\n".join(f"• {a}" for a in play.actions), title=f"{tag}: {play.title}"))

    console.print(f"[dim]{disclaimer}[/dim]")


@app.command("analyze")
def analyze(
    track: Path = typer.Argument(..., exists=True, readable=True, help="Path to audio file"),
    goal: GoalOption = typer.Option(GoalOption.playlist, "--goal", "-g", help="Strategic goal"),
    comps: Optional[Path] = typer.Option(None, "--comps", help="Optional comps JSON catalog"),
    marketing: Optional[Path] = typer.Option(
        None,
        "--marketing",
        exists=True,
        readable=True,
        help="Local marketing notes JSON. Not popularity and not Soundcharts.",
    ),
    trends: Optional[Path] = typer.Option(
        None,
        "--trends",
        exists=True,
        readable=True,
        help="Local Google Trends CSV you already downloaded. Not a live Google call.",
    ),
    analytics: Optional[Path] = typer.Option(
        None,
        "--analytics",
        exists=True,
        readable=True,
        help="Local first-party analytics CSV you already downloaded.",
    ),
    json_out: Optional[Path] = typer.Option(None, "--json", help="Write full brief JSON to path"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Only print primary play title"),
) -> None:
    """Analyze a track and print an A&R strategy brief."""
    brief = build_brief(
        track,
        goal=Goal(goal.value),
        comps_path=comps,
        marketing_path=marketing,
        trends_path=trends,
        analytics_path=analytics,
    )

    if json_out:
        json_out.write_text(json.dumps(brief.to_pretty_dict(), indent=2), encoding="utf-8")
        console.print(f"[dim]Wrote {json_out}[/dim]")

    if quiet:
        primary = next((p for p in brief.plays if p.primary), brief.plays[0] if brief.plays else None)
        console.print(primary.title if primary else "No play generated")
        return

    console.print(
        Panel.fit(
            f"[bold]{track.name}[/bold]\n"
            f"Goal: {brief.goal.value} · Fit: {brief.fit.score:.2f}\n"
            f"{brief.features.tempo_bpm:.0f} BPM estimate · "
            f"{brief.features.duration_sec/60:.2f} min · "
            f"onset peak {brief.features.novelty_peak_sec or 'n/a'}s (not a verified hook) · "
            f"key estimate {brief.features.key or '?'} {brief.features.mode or ''} · "
            f"LUFS {brief.features.integrated_lufs if brief.features.integrated_lufs is not None else 'unavailable'}",
            title="Open A&R",
        )
    )

    fit_table = Table(title="Fit rationale")
    fit_table.add_column("Signal")
    for line in brief.fit.rationale:
        fit_table.add_row(line)
    console.print(fit_table)

    questions = brief.questions or {}
    if questions:
        console.print(
            "sounds similar: "
            f"{questions['sounds_similar']['status']} · "
            "good song: "
            f"{questions['good_song']['status']} · "
            "currently popular: "
            f"{questions['currently_popular']['status']}"
        )
    marketing_notes = brief.marketing_notes or {}
    console.print(
        "marketing notes: "
        f"{marketing_notes.get('status', 'unavailable')} · "
        f"source: {marketing_notes.get('source') or 'none'}"
    )
    attention = brief.attention_evidence or {}
    console.print(
        "attention evidence: "
        f"{attention.get('status', 'unavailable')} · "
        f"observations {len(attention.get('observations') or [])} · "
        f"rejected {len(attention.get('rejected') or [])}"
    )
    if brief.comparison_held:
        held_table = Table(title="Held out of similarity")
        held_table.add_column("Title")
        held_table.add_column("Reason")
        for item in brief.comparison_held:
            held_table.add_row(str(item.get("title") or item.get("id") or ""), str(item.get("reason") or ""))
        console.print(held_table)
    if brief.comps_status != "ok":
        console.print(f"[yellow]Comps unavailable: {brief.comps_reason}[/yellow]")
    else:
        comp_table = Table(title="Verified comps")
        comp_table.add_column("Title")
        comp_table.add_column("Artist")
        comp_table.add_column("Dist", justify="right")
        comp_table.add_column("Why")
        for m in brief.comps[:5]:
            comp_table.add_row(m.comp.title, m.comp.artist, f"{m.distance:.3f}", ", ".join(m.why))
        console.print(comp_table)

    _print_plays_and_gaps(brief.gaps, brief.plays, brief.disclaimer)


@app.command("analyze-video")
def analyze_video(
    video: Path = typer.Argument(..., exists=True, readable=True, help="Path to music video file"),
    goal: VideoGoalOption = typer.Option(
        VideoGoalOption.youtube_mv,
        "--goal",
        "-g",
        help="Video strategy goal",
    ),
    comps: Optional[Path] = typer.Option(None, "--comps", help="Optional audio comps JSON"),
    json_out: Optional[Path] = typer.Option(None, "--json", help="Write full brief JSON to path"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Only print primary play title"),
) -> None:
    """Watch a music video (picture + audio) and print a distribution strategy brief."""
    brief = build_video_brief(video, goal=VideoGoal(goal.value), comps_path=comps)

    if json_out:
        json_out.write_text(json.dumps(brief.to_pretty_dict(), indent=2), encoding="utf-8")
        console.print(f"[dim]Wrote {json_out}[/dim]")

    if quiet:
        primary = next((p for p in brief.plays if p.primary), brief.plays[0] if brief.plays else None)
        console.print(primary.title if primary else "No play generated")
        return

    v = brief.video
    console.print(
        Panel.fit(
            f"[bold]{video.name}[/bold]\n"
            f"Goal: {brief.goal.value} · Fit: {brief.fit.score:.2f}\n"
            f"{v.width}x{v.height} {v.aspect} · {v.duration_sec/60:.2f} min · "
            f"{v.scene_cut_count} cuts ({v.cuts_per_minute:.1f}/min)\n"
            f"open3={v.opening_3s_energy:.2f} open15={v.opening_15s_energy:.2f} · "
            f"hook↔picture sync={v.audio_hook_visual_sync:.2f}\n"
            f"audio {brief.audio.tempo_bpm:.0f} BPM estimate · "
            f"onset peak {brief.audio.novelty_peak_sec or 'n/a'}s (not a verified hook)",
            title="Open A&R · Music Video",
        )
    )

    fit_table = Table(title="Video fit rationale")
    fit_table.add_column("Signal")
    for line in brief.fit.rationale:
        fit_table.add_row(line)
    console.print(fit_table)

    clip_table = Table(title="Suggested clip windows")
    clip_table.add_column("Label")
    clip_table.add_column("Start", justify="right")
    clip_table.add_column("End", justify="right")
    clip_table.add_column("Why")
    for w in brief.clip_windows:
        clip_table.add_row(w["label"], f"{w['start_sec']:.1f}s", f"{w['end_sec']:.1f}s", w["why"])
    console.print(clip_table)

    _print_plays_and_gaps(brief.gaps, brief.plays, brief.disclaimer)


andre_app = typer.Typer(
    help=(
        "Hand off measured briefs to Andre · A&R through a Grok Bot routine webhook. "
        "Stays disconnected until you set the routine URL and key."
    )
)
app.add_typer(andre_app, name="andre")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    console.print(f"[dim]Wrote {path}[/dim]")


@andre_app.command("status")
def andre_status(
    json_out: Optional[Path] = typer.Option(None, "--json", help="Write connection JSON to path"),
) -> None:
    """Show whether Andre's routine webhook is configured. Does not call Grok Bot."""
    info = inspect_connection().public_dict()
    if json_out:
        _write_json(json_out, info)
    missing = ", ".join(info["missing"]) if info["missing"] else "none"
    console.print(
        Panel.fit(
            f"[bold]{info['bot']['name']}[/bold]\n"
            f"{info['bot']['role']}\n"
            f"id: {info['bot']['id']}\n"
            f"state: {info['state']}\n"
            f"transport: {info['transport']}\n"
            f"url set: {info['url_set']} · key set: {info['key_set']}\n"
            f"missing: {missing}\n"
            "The bot id is not an endpoint. Status does not contact Grok Bot.",
            title="Open A&R · Andre",
        )
    )


@andre_app.command("share")
def andre_share(
    tracks: list[Path] = typer.Argument(..., exists=True, readable=True, help="Audio files to brief"),
    goal: GoalOption = typer.Option(GoalOption.playlist, "--goal", "-g", help="Strategic goal"),
    comps: Optional[Path] = typer.Option(None, "--comps", help="Optional comps JSON catalog"),
    marketing: Optional[Path] = typer.Option(
        None,
        "--marketing",
        exists=True,
        readable=True,
        help="Local marketing notes JSON. Not popularity and not Soundcharts.",
    ),
    json_out: Optional[Path] = typer.Option(None, "--json", help="Write the local result JSON to path"),
) -> None:
    """Analyze tracks and POST the handoff when a webhook is configured.

    Exit 0 only when Grok Bot returns 200 (run started, not finished).
    Exit 2 when nothing was sent. Original audio is not modified or mastered.
    """
    notes = load_marketing_notes(marketing)
    briefs = []
    beats: dict[str, list[float]] = {}
    beat_grid: dict[str, str] = {}
    for track in tracks:
        brief = build_brief(
            track,
            goal=Goal(goal.value),
            comps_path=comps,
            marketing_path=marketing,
        )
        briefs.append(brief)
        try:
            beats[brief.track_path] = read_beat_times(brief.track_path)
            beat_grid[brief.track_path] = "ok"
        except Exception:
            # Beat tracking can fail per file. Keep the brief and say the grid is unavailable.
            beats[brief.track_path] = []
            beat_grid[brief.track_path] = "unavailable"
    before = {track: track.read_bytes() for track in tracks}
    handoff = build_handoff(briefs, beats, beat_grid, marketing_notes=notes)
    result = share_with_andre(handoff)
    for track, original in before.items():
        if track.read_bytes() != original:
            raise RuntimeError(f"Original audio changed during share: {track}")
    if json_out:
        _write_json(json_out, result)
    state = result["connection"]["state"]
    handoff_body = result["handoff"]
    posted_len = len(posted_bytes(handoff_body))
    marketing_status = (handoff_body.get("marketing_notes") or {}).get("status", "unavailable")
    marketing_source = (handoff_body.get("marketing_notes") or {}).get("source") or "none"
    popular_status = (handoff_body.get("currently_popular") or {}).get("status", "unavailable")
    similar_status = "unavailable"
    tracks_out = handoff_body.get("tracks") or []
    if tracks_out:
        similar_status = (
            (tracks_out[0].get("questions") or {}).get("sounds_similar") or {}
        ).get("status", "unavailable")
    console.print(
        Panel.fit(
            f"state: {state}\n"
            f"correlation_id: {handoff_body.get('correlation_id')}\n"
            f"contract: {handoff_body.get('contract')}\n"
            f"zz_end: {handoff_body.get('zz_end')}\n"
            f"canonical_utf8_bytes: {handoff_body.get('payload_utf8_bytes')}\n"
            f"canonical_sha256: {handoff_body.get('payload_sha256')}\n"
            f"posted_utf8_bytes: {posted_len}\n"
            f"attempted: {result['attempted']}\n"
            f"delivered: {result['delivered']}\n"
            f"sounds similar: {similar_status}\n"
            f"currently popular: {popular_status}\n"
            f"marketing notes: {marketing_status} · source: {marketing_source}\n"
            f"{result['detail']}\n"
            "Original files were not modified. No master was rendered.",
            title="Open A&R · Andre share",
        )
    )
    if result["delivered"]:
        raise typer.Exit(code=0)
    if not result["attempted"]:
        raise typer.Exit(code=2)
    raise typer.Exit(code=1)


@app.command("import-acousticbrainz")
def import_acousticbrainz_cmd(
    lowlevel: Path = typer.Argument(..., exists=True, readable=True, help="Local AcousticBrainz low-level JSON"),
    catalog: Path = typer.Option(..., "--catalog", help="Catalog JSON to create or update"),
) -> None:
    """Import a local AcousticBrainz low-level file as a held row. No network."""
    result = add_to_catalog(lowlevel, catalog)
    track = CompTrack.model_validate(result["track"])
    reason = similarity_problem(track)
    console.print(
        Panel.fit(
            f"id: {track.id}\n"
            f"held: {result['held']}\n"
            f"reason: {reason}\n"
            f"catalog: {result['catalog']}\n"
            "The row is not a similarity comp. AcousticBrainz was not contacted.",
            title="Open A&R · AcousticBrainz import",
        )
    )


@app.command("strategy")
def strategy_cmd(
    brief: Path = typer.Option(..., "--brief", exists=True, readable=True, help="Brief JSON from open-ar analyze --json"),
    trends: Optional[Path] = typer.Option(
        None,
        "--trends",
        exists=True,
        readable=True,
        help="Local Google Trends CSV you already downloaded.",
    ),
    analytics: Optional[Path] = typer.Option(
        None,
        "--analytics",
        exists=True,
        readable=True,
        help="Local first-party analytics CSV you already downloaded.",
    ),
    marketing: Optional[Path] = typer.Option(
        None,
        "--marketing",
        exists=True,
        readable=True,
        help="Local marketing notes JSON.",
    ),
    feedback: Optional[Path] = typer.Option(
        None,
        "--feedback",
        help="Feedback JSON. Defaults to .data/feedback.json when that file exists.",
    ),
    json_out: Optional[Path] = typer.Option(None, "--json", help="Write the strategy JSON"),
) -> None:
    """Write audience hypotheses and, only with enough dated rates, a comparison.

    No scheduler, no post, and no master. Insufficient evidence stays labeled.
    """
    feedback_path = feedback
    if feedback_path is None and DEFAULT_FEEDBACK_PATH.is_file():
        feedback_path = DEFAULT_FEEDBACK_PATH
    try:
        document = build_strategy(
            brief,
            trends_path=trends,
            analytics_path=analytics,
            marketing_path=marketing,
            feedback_path=feedback_path,
        )
    except ValueError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc
    if json_out:
        _write_json(json_out, document)
    mastering = document["asset"]["mastering"]
    console.print(
        Panel.fit(
            f"hypotheses: {document['hypothesis_status']} ({len(document['hypotheses'])})\n"
            f"comparison: {document['comparison']['status']}\n"
            f"currently popular: {document['currently_popular']['status']}\n"
            f"mastering approved: {mastering['approved']} · rendered: {mastering['rendered']}\n"
            "Hypotheses are labeled hypotheses. This is not a hit prediction and nothing was posted.",
            title="Open A&R · strategy",
        )
    )


feedback_app = typer.Typer(help="Store explicit ratings, corrections, and campaign outcomes locally.")
app.add_typer(feedback_app, name="feedback")


@feedback_app.command("add")
def feedback_add(
    track_id: str = typer.Option(..., "--track-id", help="Target track id"),
    rater: str = typer.Option(..., "--rater", help="Who supplied this record"),
    kind: str = typer.Option("rating", "--kind", help="rating, correction, or campaign_outcome"),
    corrected: str = typer.Option(..., "--corrected", help="What the user corrected or rated"),
    source: str = typer.Option("user", "--source", help="user, or another label you supply"),
    detail: str = typer.Option("", "--detail", help="Short note in your own words"),
    drum_impact: Optional[int] = typer.Option(None, "--drum-impact", min=1, max=5),
    hook: Optional[int] = typer.Option(None, "--hook", min=1, max=5),
    conviction: Optional[int] = typer.Option(None, "--conviction", min=1, max=5),
    held_out: bool = typer.Option(False, "--held-out", help="Mark this row held out of the rating rule"),
    file: Path = typer.Option(DEFAULT_FEEDBACK_PATH, "--file", help="Feedback JSON path"),
) -> None:
    """Append one user-supplied record. Does not train a model or rewrite audio features."""
    record = add_record(
        file,
        target_track_id=track_id,
        rater=rater,
        kind=kind,
        corrected=corrected,
        source=source,
        held_out=held_out,
        drum_impact=drum_impact,
        hook=hook,
        conviction=conviction,
        detail=detail,
        user_supplied=True,
    )
    console.print(
        f"stored {record['kind']} for {record['target_track_id']} in {file} "
        f"(user_supplied={record['user_supplied']}, held_out={record['held_out']})"
    )


@feedback_app.command("check")
def feedback_check(
    file: Path = typer.Option(DEFAULT_FEEDBACK_PATH, "--file", help="Feedback JSON path"),
    json_out: Optional[Path] = typer.Option(None, "--json", help="Write the check JSON"),
) -> None:
    """Show whether a held-out rating was kept out of the rule. Does not fit a model."""
    store = load_store(file)
    records = [record for record in store.get("records", []) if isinstance(record, dict)]
    report = held_out_check(records)
    if json_out:
        _write_json(json_out, report)
    console.print(
        Panel.fit(
            f"held-out check: {report['held_out_check']}\n"
            f"personalization: {report['personalization']}\n"
            f"model fit: {report['model_fit']}\n"
            f"rule uses held-out rows: {report['rule_uses_held_out']}\n"
            f"{report.get('reason') or 'Held-out rows were compared and not used to build the rule.'}",
            title="Open A&R · feedback",
        )
    )


if __name__ == "__main__":
    app()
