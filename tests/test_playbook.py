from open_ar.comps import find_comps, load_comps
from open_ar.playbook import build_plays, detect_gaps, score_fit
from open_ar.schema import AudioFeatures, Goal


def _features(**overrides) -> AudioFeatures:
    base = dict(
        duration_sec=180,
        tempo_bpm=100,
        energy=0.65,
        danceability=0.7,
        brightness=0.5,
        acousticness=0.2,
        speechiness=0.1,
        dynamic_range=0.55,
        hook_onset_sec=18,
        loudness_db=-12.0,
        key="A",
        mode="minor",
    )
    base.update(overrides)
    return AudioFeatures(**base)


def test_seed_comps_load():
    comps = load_comps()
    assert len(comps) >= 8


def test_playlist_fit_prefers_early_hook():
    comps = load_comps()
    early = find_comps(_features(hook_onset_sec=15), Goal.playlist, comps=comps)
    late = find_comps(_features(hook_onset_sec=50), Goal.playlist, comps=comps)
    early_fit = score_fit(_features(hook_onset_sec=15), Goal.playlist, early)
    late_fit = score_fit(_features(hook_onset_sec=50), Goal.playlist, late)
    assert early_fit.score > late_fit.score


def test_late_hook_gap_and_hold_play():
    feats = _features(hook_onset_sec=48, duration_sec=260)
    comps = find_comps(feats, Goal.playlist)
    gaps = detect_gaps(feats, Goal.playlist, comps)
    fit = score_fit(feats, Goal.playlist, comps)
    plays = build_plays(feats, Goal.playlist, fit, gaps, comps)
    assert any(g.code == "late_hook" for g in gaps)
    primary = next(p for p in plays if p.primary)
    assert "Hold" in primary.title or "content" in primary.title.lower()


def test_club_low_energy_remix_play():
    feats = _features(energy=0.4, danceability=0.45, tempo_bpm=90)
    comps = find_comps(feats, Goal.club)
    gaps = detect_gaps(feats, Goal.club, comps)
    fit = score_fit(feats, Goal.club, comps)
    plays = build_plays(feats, Goal.club, fit, gaps, comps)
    assert any(g.code == "low_club_energy" for g in gaps)
    primary = next(p for p in plays if p.primary)
    assert "Remix" in primary.title
