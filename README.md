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

### Comparison library

Three questions stay in separate fields: `sounds_similar`, `good_song`, and `currently_popular`.

`src/open_ar/data/seed_comps.json` is a fixture. It is not a recommendation.

A reference is used for **sounds similar** only when the catalog says `"kind": "verified"` and `"verified": true`, the track has `"permission_cleared": true`, and `"measurement_source": "open_ar"`. That last flag means the reference WAV was measured with this package, so the numbers are on the same scale. MusicBrainz recording MBIDs are identity only. Core MusicBrainz data is CC0. An MBID does not add audio features.

AcousticBrainz low-level and high-level JSON is CC0 and indexed by those MBIDs, but collection stopped in 2022. A track marked `"measurement_source": "acousticbrainz"` is held out of the similarity distance and the reason says so. Essentia models are not bundled; commercial licensing is unchecked. Soundcharts is paid and is not called. Popularity stays `unavailable`. There is no popularity number in the handoff.

**Good song** is only a 1–5 listener rating of `drum_impact`, `hook`, and `conviction`, with a `rater` name. Open A&R does not infer those from an onset peak. Missing ratings stay null with a reason.

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

`share` exits `0` when Grok Bot returns 200, `2` when it sent nothing, and `1` when the call failed. It posts once and does not retry. The body is contract `open-ar.andre.v2`: labeled measurements, comps for **sounds similar**, one document-level **good song** rating block, one document-level **currently popular** block, gaps, plays, the album sequence, and trim blocks. A null measurement stays in the JSON with a note and is listed under `missing`. `zz_end` is `complete` only on a sealed document. The client does not slice the request. If validation fails, or the sealed body is over 96 KiB, nothing is posted. Required sections stay in the document either way.

The earlier handoff nested full fixture comps inside each track and put sequence and trims after that block. A summary that stopped mid-comps could hide the tail even though the POST sent the whole object. The response reader still limits itself to 4 KiB; that limit is the reply, not the request.

Audio bytes are not in the body, and there is no audio URL. To pair a brief with a file Andre can already read: copy the file onto his computer yourself, hash it with SHA-256, and accept the pair only when the digest and byte size match `tracks[].audio`. If the file is not there, the audio stays unavailable.

Original files are left untouched. Nothing is mastered. The payload still says target **-14 LUFS**, no fade-outs, cuts on a beat and never mid-word, and **ask Travis before mastering**. Integrated LUFS is measured with ITU-R BS.1770-4 when the file can be gated. The RMS figure is `dB re peak RMS`, not LUFS. An onset peak is not a verified hook, and it is not used as a cut.

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

1. **Fit is not quality.** A good song is only a listener rating of drum impact, hook, and conviction.
2. **Keep the three questions apart.** Sounds similar, good song, and currently popular are separate fields.
3. **Local audio first.** Compatible references are WAVs measured by this package. Spotify audio-features are not a source.
4. **Similarity needs permission and the same meter.** The catalog must be `kind: verified` and `verified: true`, and each reference needs `permission_cleared: true` and `measurement_source: open_ar`. Fixtures stay fixtures. AcousticBrainz numbers stay out of the distance.
5. **Name the unit.** RMS relative to the file peak is not LUFS. An onset peak is not a hook. Proxy scores say so. Popularity is unavailable.

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
