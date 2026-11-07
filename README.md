# Open A&R

Local-first, open-source **Artists & Repertoire** briefs.

It does **not** answer “is this song good?”  
It answers: **given a goal, what should you do with this track — and why**, using measurable audio signals + comparable references.

## What you get

```bash
open-ar analyze your-song.wav --goal playlist
open-ar analyze-video your-video.mp4 --goal youtube_mv
```

**Audio brief**
- Sonic snapshot (BPM, energy, hook timing proxy, key/mode estimate)
- Nearest **comps** from a seed catalog (bring your own)
- **Fit score** for a goal (`playlist`, `club`, `sync`, `cult`, `lead_single`)
- **Gaps** / **Plays** — strategy with evidence

**Music-video brief** (`analyze-video`)
- Watches the file via ffmpeg: aspect, scene cuts, opening energy, peak picture moment
- Pulls the audio bed and scores hook↔picture sync
- Goals: `youtube_mv`, `short_form`, `premiere`, `visualizer`
- Suggests 15s/30s/60s clip windows + thumbnail still timestamp
- Playbook: re-edit, Shorts pack, premiere event, or visualizer SEO path

Requires **ffmpeg** / **ffprobe** on your PATH.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Needs Python 3.11+. Audio via **librosa** (no Spotify audio-features API).

## Usage

```bash
# Strategy brief in the terminal
open-ar analyze path/to/track.wav --goal club

# Full JSON for tooling / UI
open-ar analyze path/to/track.wav --goal sync --json brief.json

# Quiet: only the primary play title
open-ar analyze path/to/track.wav -g lead_single -q

# Watch a music video and strategize distribution
open-ar analyze-video path/to/video.mp4 --goal youtube_mv
open-ar analyze-video path/to/video.mp4 -g short_form --json mv-brief.json
open-ar analyze-video path/to/video.mp4 -g premiere -q
```

### Bring your own comps

Copy `src/open_ar/data/seed_comps.json`, replace with labeled tracks from *your* world, then:

```bash
open-ar analyze track.wav --comps ./my_comps.json --goal playlist
```

## Andre · A&R

[Andre · A&R](https://docs.x.ai/grok-bot/skills-routines-and-automations) is Travis Singletary's existing Grok Bot (`9a93499d-e565-47e0-95c1-fd19aceba940`). Open A&R can hand him a measured brief only through a **routine webhook**, which is the documented way to start a Bot with a JSON body. The bot id is identity. It is not a URL, and this repo does not call the xAI model API or any private gateway.

Until you export the routine's own URL and key, `open-ar andre status` stays **`disconnected`**. `configured_unverified` means both values are present locally. Status never contacts Grok Bot. `delivered: true` happens only after a share gets HTTP 200, which means a run **started**, not that Andre has finished. Check his chat.

```bash
open-ar andre status
open-ar andre share track.wav --goal playlist
open-ar andre share a.wav b.wav c.wav --goal lead_single --json handoff.json
```

`share` exits `0` when Grok Bot returns 200, `2` when it sent nothing, and `1` when the call failed. It posts once and does not retry. The body contains the brief (features, comps, gaps, plays), an album-order proposal, and beat-aligned trim proposals. It does not contain audio bytes. Original files are left untouched. Open A&R does not measure LUFS and does not render a master. The payload tells Andre: target **-14 LUFS**, no fade-outs, cuts on a beat and never mid-word, and **ask Travis before mastering**. `word_boundary_verified` is false because this repo has no lyric timeline.

### One-time setup

1. In Andre · A&R's chat, ask him to create a webhook routine whose instruction reads the JSON body as data and follows it: summarize the measured brief, present the album sequence and trim proposals, do not overwrite originals, do not fade out, do not cut mid-word while `word_boundary_verified` is false, and do not master until Travis Singletary approves. Mastering target is -14 LUFS.
2. On desktop, open that routine's **Webhook** section. Copy **POST to** and the **key**. Do not paste the key into chat or commit it.
3. Export them in the shell that runs Open A&R:

```bash
export GROK_BOT_WEBHOOK_URL="https://…"   # the POST to field
export GROK_BOT_WEBHOOK_KEY="…"           # the key field, as Authorization: Bearer
```

4. Run `open-ar andre status`. The next `share` is what actually starts a run, and each run spends Grok Bot usage.
5. If Andre needs the audio itself, put those files on his computer. The webhook does not upload them.

A template for the variable names is in `.env.example`. Leave the values empty in git.

## Design rules

1. **Fit ≠ quality.** Artistic worth is outside this tool’s job.
2. **Always pair a recommendation with evidence** (comps + gaps).
3. **Local audio first.** Don’t depend on deprecated Spotify audio-features for new apps.
4. **Replace seed comps.** The bundled catalog is synthetic demo data.

## Library API

```python
from open_ar.brief import build_brief

brief = build_brief("song.wav", goal="playlist")
print(brief.plays[0].title)
print(brief.model_dump_json(indent=2))
```

## Tests

```bash
pytest
```

## Roadmap (intentional)

- [x] Music-video watch path (ffmpeg scene/luma + audio sync strategy)
- [ ] YouTube/TikTok URL ingest (download → analyze) when you supply rights-safe tooling
- [ ] Face / lyric / text-on-screen detectors for richer picture briefs
- [ ] Structure sections (verse/chorus) via better segmentation
- [ ] Thin web UI on top of the JSON brief
- [ ] Artist-tier priors (emerging vs established changes the playbook)

## License

MIT — see [LICENSE](LICENSE).
