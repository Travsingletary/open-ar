# Open A&R

Local-first, open-source **Artists & Repertoire** briefs.

It does **not** answer “is this song good?”  
It answers: **given a goal, what should you do with this track — and why**, using measurable audio signals + comparable references.

## What you get

```bash
open-ar analyze your-song.wav --goal playlist
```

Output:
- Sonic snapshot (BPM, energy, hook timing proxy, key/mode estimate)
- Nearest **comps** from a seed catalog (bring your own)
- **Fit score** for a goal (`playlist`, `club`, `sync`, `cult`, `lead_single`)
- **Gaps** (late hook, long runtime, low club energy, …)
- **Plays** — one primary strategy + alternates

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

- [ ] Structure sections (verse/chorus) via better segmentation
- [ ] Optional DSP metadata enrichment (when you already have rights/IDs)
- [ ] Thin web UI on top of the JSON brief
- [ ] Artist-tier priors (emerging vs established changes the playbook)

## License

MIT — see [LICENSE](LICENSE).
