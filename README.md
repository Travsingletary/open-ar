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
