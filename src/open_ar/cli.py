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
from open_ar.andre import build_handoff, inspect_connection, share_with_andre
from open_ar.brief import build_brief
from open_ar.edits import read_beat_times
from open_ar.schema import Goal, VideoGoal
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
    json_out: Optional[Path] = typer.Option(None, "--json", help="Write full brief JSON to path"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Only print primary play title"),
) -> None:
    """Analyze a track and print an A&R strategy brief."""
    brief = build_brief(track, goal=Goal(goal.value), comps_path=comps)

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
    json_out: Optional[Path] = typer.Option(None, "--json", help="Write the local result JSON to path"),
) -> None:
    """Analyze tracks and POST the handoff when a webhook is configured.

    Exit 0 only when Grok Bot returns 200 (run started, not finished).
    Exit 2 when nothing was sent. Original audio is not modified or mastered.
    """
    briefs = []
    beats: dict[str, list[float]] = {}
    beat_grid: dict[str, str] = {}
    for track in tracks:
        brief = build_brief(track, goal=Goal(goal.value), comps_path=comps)
        briefs.append(brief)
        try:
            beats[brief.track_path] = read_beat_times(brief.track_path)
            beat_grid[brief.track_path] = "ok"
        except Exception:
            # Beat tracking can fail per file. Keep the brief and say the grid is unavailable.
            beats[brief.track_path] = []
            beat_grid[brief.track_path] = "unavailable"
    before = {track: track.read_bytes() for track in tracks}
    handoff = build_handoff(briefs, beats, beat_grid)
    result = share_with_andre(handoff)
    for track, original in before.items():
        if track.read_bytes() != original:
            raise RuntimeError(f"Original audio changed during share: {track}")
    if json_out:
        _write_json(json_out, result)
    state = result["connection"]["state"]
    console.print(
        Panel.fit(
            f"state: {state}\n"
            f"attempted: {result['attempted']}\n"
            f"delivered: {result['delivered']}\n"
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


if __name__ == "__main__":
    app()
