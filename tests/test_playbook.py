from open_ar.comps import find_comps, load_catalog, load_comps
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


def test_seed_comps_are_fixtures():
    catalog = load_catalog()
    assert catalog.kind == "fixture"
    assert catalog.verified is False
    assert len(catalog.tracks) >= 8
    assert load_comps() == catalog.tracks


def test_playlist_fit_prefers_early_verified_hook():
    comps = load_comps()
    early_feats = _features(hook_onset_sec=15, hook_verified=True)
    late_feats = _features(hook_onset_sec=50, hook_verified=True)
    early = find_comps(early_feats, Goal.playlist, comps=comps)
    late = find_comps(late_feats, Goal.playlist, comps=comps)
    early_fit = score_fit(early_feats, Goal.playlist, early)
    late_fit = score_fit(late_feats, Goal.playlist, late)
    assert early_fit.score > late_fit.score


def test_unverified_onset_does_not_score_as_a_hook():
    comps = load_comps()
    early = _features(hook_onset_sec=15, novelty_peak_sec=15, hook_verified=False)
    late = _features(hook_onset_sec=None, novelty_peak_sec=142.8, hook_verified=False)
    early_fit = score_fit(early, Goal.playlist, find_comps(early, Goal.playlist, comps=comps))
    late_fit = score_fit(late, Goal.playlist, find_comps(late, Goal.playlist, comps=comps))
    assert early_fit.score == late_fit.score
    assert any("not scored as a hook" in line for line in late_fit.rationale)


def test_unverified_peak_is_not_a_late_hook():
    feats = _features(hook_onset_sec=None, novelty_peak_sec=142.8, hook_verified=False, duration_sec=154)
    gaps = detect_gaps(feats, Goal.playlist, [])
    fit = score_fit(feats, Goal.playlist, [])
    plays = build_plays(feats, Goal.playlist, fit, gaps, [])
    assert any(g.code == "hook_unverified" for g in gaps)
    assert not any(g.code == "late_hook" for g in gaps)
    primary = next(p for p in plays if p.primary)
    assert "do not trim" in primary.title.lower()
    assert "Seed Artist" not in " ".join(primary.actions)


def test_verified_late_hook_still_holds():
    feats = _features(hook_onset_sec=48, hook_verified=True, duration_sec=180)
    gaps = detect_gaps(feats, Goal.playlist, [])
    fit = score_fit(feats, Goal.playlist, [])
    plays = build_plays(feats, Goal.playlist, fit, gaps, [])
    assert any(g.code == "late_hook" for g in gaps)
    primary = next(p for p in plays if p.primary)
    assert "Hold" in primary.title


def test_club_low_energy_remix_play():
    feats = _features(energy=0.4, danceability=0.45, tempo_bpm=90)
    comps = []
    gaps = detect_gaps(feats, Goal.club, comps)
    fit = score_fit(feats, Goal.club, comps)
    plays = build_plays(feats, Goal.club, fit, gaps, comps)
    assert any(g.code == "low_club_energy" for g in gaps)
    primary = next(p for p in plays if p.primary)
    assert "Remix" in primary.title
