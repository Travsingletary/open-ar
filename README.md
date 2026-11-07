# Open A&R

Local-first, open-source **Artists & Repertoire** briefs.

It does **not** answer “is this song good?”  
It answers: **given a goal, what should you do with this track — and why**, using measurable audio signals + comparable references.

## What you get

```bash
open-ar analyze your-song.wav --goal playlist
open-ar analyze-video your-video.mp4 --goal youtube_mv
open-ar strategy --brief brief.json --trends trends.csv --analytics analytics.csv --json strategy.json
```

**Audio brief**
- Sonic snapshot (BPM, energy, hook timing proxy, key/mode estimate)
- Nearest **comps** when you pass a permission-cleared catalog (`--comps`)
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

A reference is used for **sounds similar** only when the catalog says `"kind": "verified"` and `"verified": true`, and the track has all of these:

- `"permission_cleared": true`
- a non-empty `"permission_note"` (the rights note)
- `"measurement_source": "open_ar"`
- `"produced_by": "extracted"` (this package measured a WAV; `"hand_typed"` is held out)
- `"feature_version"` equal to this package's extractor version, `open-ar-features-1`

MusicBrainz recording MBIDs are identity only. Core MusicBrainz data is CC0. This package does not call MusicBrainz and does not pull cover art or CC BY-NC-SA supplements. An MBID does not add audio features.

AcousticBrainz low-level descriptors are CC0 historical measurements indexed by those MBIDs. Collection stopped in 2022. They are an incompatible method and are not on the Open A&R scale, so they never enter `find_comps`. You can import a low-level JSON you already have. The row stores provenance (source, dataset frozen in 2022, license CC0, essentia version and extractor version when the file has them, file path, sha256) and a held historical block. Those numbers are not copied into the feature fields used for distance. Essentia models are not bundled or downloaded. Commercial licensing is unchecked. Soundcharts is paid and is not called. Popularity stays `unavailable` with an empty item list. A popularity number is not a chart position and not a songwriting score.

**Good song** is only a 1–5 listener rating of `drum_impact`, `hook`, and `conviction`, with a `rater` name. Open A&R does not infer those from an onset peak. Missing ratings stay null with a reason.

```bash
open-ar analyze track.wav --comps ./my_comps.json --goal playlist
```

`examples/permission_cleared_catalog.example.json` is that shape. It is not seed artists and it is not a copyrighted recording. The `open_ar` row shows `feature_version`, `produced_by`, and a rights note so the file demonstrates the gate. The numbers are still synthetic placeholders. Copy the file and replace that row with features from `open-ar analyze` on a WAV you have permission to compare. `open-ar analyze` and `open-ar andre share` load that file through `--comps`.

Rows stay held when they are AcousticBrainz, Essentia, uncleared, missing a rights note, hand-typed, missing `feature_version`, or an MBID that is not a UUID. A MusicBrainz recording MBID is only an identifier. The command does not call MusicBrainz or AcousticBrainz.

```bash
open-ar import-acousticbrainz ./your-lowlevel.json --catalog my_comps.json
```

`examples/acousticbrainz_lowlevel.example.json` is a synthetic low-level shape, not a dump from acousticbrainz.org and not a real artist. The imported row is held. It is not a comp.

```bash
cp examples/permission_cleared_catalog.example.json my_comps.json
open-ar analyze path/to/reference.wav --json reference-features.json
open-ar analyze path/to/track.wav --comps my_comps.json --goal playlist
open-ar andre share path/to/track.wav --comps my_comps.json --goal playlist
```

Put the measured features into `my_comps.json` yourself. Set `feature_version` to `open-ar-features-1`, `produced_by` to `extracted`, and `permission_note` to who cleared the file. Distance to the untouched example is distance to a synthetic placeholder, not to a real song. Optional `ratings` on a reference (`drum_impact`, `hook`, `conviction` from 1 to 5, plus `rater`) answer **good song** only. They do not move distance or fit.

### Local marketing notes and attention evidence

Marketing notes are a separate document-level handoff lane. They are not `sounds_similar`, not `good_song`, and not `currently_popular`. There is no chart rank and no stream count. Nothing is fetched.

`examples/marketing_notes.example.json` shows `campaign`, `audience`, `playlist_pitch`, `radio`, `notes`, and `supplied_by`. The handoff sets `source` to `local_notes`. If you omit `--marketing`, the lane is `unavailable` and the reason says so. A popularity number in that file or in the catalog is ignored. Notes do not change fit, distance, comps, or ratings.

```bash
cp examples/marketing_notes.example.json my_marketing.json
open-ar analyze path/to/track.wav --comps my_comps.json --marketing my_marketing.json --goal playlist
open-ar andre share path/to/track.wav --comps my_comps.json --marketing my_marketing.json --json handoff.json
```

Attention and conversion evidence is a different lane from those notes. Pass CSV files you already downloaded. The reader does not scrape Google Trends and does not call Google. Each row needs a date (`YYYY-MM-DD`), a source label, a metric name, and a denominator. A Trends index has no impression denominator: put that in `denominator_missing` and the value stays an index, not a rate. A row with no date or no source is rejected. A missing number stays null and is not filled in. These rows do not change distance, fit, or listener ratings, and they do not set `currently_popular` to `ok`.

```bash
open-ar analyze path/to/track.wav --trends ./your-trends.csv --analytics ./your-analytics.csv --json brief.json
```

`examples/trends.example.csv` and `examples/analytics.example.csv` are synthetic column samples, not your accounts.

### Strategy, by hand

`open-ar strategy` reads a brief from `open-ar analyze --json` plus those evidence files and writes a strategy JSON. It does not schedule, post, or master.

A brief that exists, with mastering not rendered, produces audience and message **hypotheses** for music, video, and this product. They are labeled `hypothesis`. A comparison is written only when one source and metric (and variant, if that column is present) has at least two dated observations, each with a numeric value and a denominator greater than zero. Otherwise `comparison.status` is `insufficient_evidence`. A comparison that does run describes the change between the earliest and latest rate. It is not statistical significance and not a prediction that a song will hit.

The checklist is adapted from a few ideas in [marketingskills](https://github.com/coreyhaines31/marketingskills) by Corey Haines (MIT). See the license note below. This package does not vendor that repo and does not run its skills.

```bash
open-ar strategy --brief brief.json --trends ./your-trends.csv --analytics ./your-analytics.csv --marketing my_marketing.json --json strategy.json
```

### Feedback

Ratings, corrections, and campaign outcomes go in a JSON file you choose. The default path is `.data/feedback.json`, which is gitignored. `examples/feedback.example.json` is the shape. Each record has a rater or source, a timestamp, a target track id, what was corrected, and `user_supplied: true`.

An average of user-supplied `drum_impact` ratings is the only adjustment, and only for rows you did not mark `held_out: true`. That average is not model training. The app's own guesses are ignored. If you mark no row `held_out: true`, the check says it was not run. A correction does not rewrite `AudioFeatures`.

```bash
open-ar feedback add --file .data/feedback.json --track-id your-track --rater "Your Name" --kind rating --corrected listener_rating --drum-impact 4 --hook 3 --conviction 4
open-ar feedback add --file .data/feedback.json --track-id your-track --rater "Your Name" --kind rating --corrected listener_rating --drum-impact 5 --held-out
open-ar feedback check --file .data/feedback.json
```

### Run this on your Mac

The cloud agent that prepared this revision did not run these commands on your Mac, did not read the `.env` in that project, and did not measure the WAV. The 154 second claims (74 BPM, A# major, RMS -10.9 dB re peak, energy 1, acousticness 0.94, danceability 0.29, onset 142.8s) are not a result from this checkout. That WAV is not here.

Checkout: `/Users/user/Projects/open-ar`  
WAV: `/Users/user/Projects/open-ar-test/test-track.wav`  
Use the `.env` already in `/Users/user/Projects/open-ar`. Do not create another one and do not paste the key into chat. `open-ar andre status` stays `disconnected` until `GROK_BOT_WEBHOOK_URL` and `GROK_BOT_WEBHOOK_KEY` are present in the shell. This repo does not source that file.

```bash
cd /Users/user/Projects/open-ar
git fetch origin cursor/andre-ar-webhook-2ea1
git checkout cursor/andre-ar-webhook-2ea1
git pull --ff-only origin cursor/andre-ar-webhook-2ea1
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
open-ar andre status
open-ar analyze /Users/user/Projects/open-ar-test/test-track.wav --goal playlist --comps examples/permission_cleared_catalog.example.json --marketing examples/marketing_notes.example.json --json brief.json
env -u GROK_BOT_WEBHOOK_URL -u GROK_BOT_WEBHOOK_KEY open-ar andre share /Users/user/Projects/open-ar-test/test-track.wav --goal playlist --comps examples/permission_cleared_catalog.example.json --marketing examples/marketing_notes.example.json --json handoff.json
open-ar import-acousticbrainz examples/acousticbrainz_lowlevel.example.json --catalog /tmp/open-ar-acousticbrainz-example.json
open-ar strategy --brief brief.json --trends examples/trends.example.csv --analytics examples/analytics.example.csv --feedback examples/feedback.example.json --json strategy.json
```

Analyze prints measurements from that run, then sounds similar, good song, currently popular, marketing notes, and attention evidence. Sounds similar is `ok` only for a verified catalog row with permission, a rights note, `measurement_source: open_ar`, `produced_by: extracted`, and `feature_version` `open-ar-features-1`. The example holds AcousticBrainz, Essentia, uncleared, non-UUID, hand-typed, missing-version, and missing-rights rows, with reasons. Seed Artist names are not recommendations. Until you replace the placeholder features with a measurement from this package, a match is against that placeholder, not a real recording. Good song is `rated` only where a reference has all three 1–5 scores and a rater. Currently popular stays `unavailable` with an empty item list. The example Trends file is `insufficient_evidence` because an index is not a rate. The example analytics file can show a described change for one synthetic variant. That is not a hit prediction.

The `env -u` share writes `handoff.json` and does not post, even if the project `.env` is loaded in the shell: contract `open-ar.andre.v2`, `zz_end` of `complete`, mastering `approved: false` and `rendered: false`, target -14 LUFS, and no audio bytes. It exits 2 while the webhook variables are unset.

What is still blocked until you supply it: the WAV above, permission-cleared reference WAVs measured with this package, your own Trends CSV and first-party analytics export, and your ratings. The example files are not those things.

## Andre · A&R

[Andre · A&R](https://docs.x.ai/grok-bot/skills-routines-and-automations) is Travis Singletary's existing Grok Bot (`9a93499d-e565-47e0-95c1-fd19aceba940`). Open A&R can hand him a measured brief only through a **routine webhook**, which is the documented way to start a Bot with a JSON body. The bot id is identity. It is not a URL, and this repo does not call the xAI model API or any private gateway.

Until you export the routine's own URL and key, `open-ar andre status` stays **`disconnected`**. `configured_unverified` means both values are present locally. Status never contacts Grok Bot. `delivered: true` happens only after a share gets HTTP 200, which means a run **started**, not that Andre has finished. Check his chat.

```bash
open-ar andre status
open-ar andre share track.wav --goal playlist
open-ar andre share a.wav b.wav c.wav --goal lead_single --json handoff.json
```

`share` exits `0` when Grok Bot returns 200, `2` when it sent nothing, and `1` when the call failed. It posts once and does not retry. The body is contract `open-ar.andre.v2`: labeled measurements, comps for **sounds similar**, one document-level **good song** rating block, one document-level **currently popular** block, one document-level **marketing notes** block, gaps, plays, the album sequence, and trim blocks. A null measurement stays in the JSON with a note and is listed under `missing`. `zz_end` is `complete` only on a sealed document. The client does not slice the request. If validation fails, or the sealed body is over 96 KiB, nothing is posted. Required sections stay in the document either way. Long marketing notes are shortened so one track, and an eight-track album with a small reference library, can still seal. The cap stays 96 KiB.

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
4. **Similarity needs permission, rights, and the same meter.** The catalog must be `kind: verified` and `verified: true`. Each reference needs `permission_cleared: true`, a rights note, `measurement_source: open_ar`, `produced_by: extracted`, and `feature_version` `open-ar-features-1`. Fixtures stay fixtures. Hand-typed numbers stay out. AcousticBrainz numbers stay out of the distance.
5. **Name the unit.** RMS relative to the file peak is not LUFS. An onset peak is not a hook. Proxy scores say so. Popularity is unavailable. A dated export is attention evidence, not a chart and not a songwriting score.
6. **Marketing notes and evidence are local.** Notes are their own handoff lane. Trends and analytics CSVs are an attention lane you import by hand. They are not a chart, a stream count, or Soundcharts, and they do not change fit. Strategy hypotheses stay hypotheses until the evidence rule is met. Feedback is not model training.

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

The local playbook in `src/open_ar/market_playbook.py` adapts a few positioning, research, analytics, experimentation, and video-planning ideas from [marketingskills](https://github.com/coreyhaines31/marketingskills) by Corey Haines, used under the MIT License:

```
MIT License

Copyright (c) 2025 Corey Haines

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

That repository is not vendored here and is not a runtime dependency. Its skills are not executed.
