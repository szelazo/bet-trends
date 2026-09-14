import json
from datetime import date

from app.autotune import (
    disabled_league_keys,
    effective_clear_edge,
    load_state,
    maybe_run,
    save_state,
)
from app.config import CLEAR_EDGE


def _write_day(tmp_path, day, games):
    (tmp_path / f"{day}.json").write_text(json.dumps({"date": day, "games": games}))


def _g(league_key, result, clear=True, below_bar=False):
    return {
        "league": {"key": league_key}, "result": result,
        "clear": clear, "below_bar": below_bar,
        "pick": {"selection": "HOME"},
    }


def test_load_state_defaults_when_missing(tmp_path):
    state = load_state(tmp_path)
    assert state["disabled_leagues"] == {}
    assert state["last_run"] is None
    assert effective_clear_edge(state) == CLEAR_EDGE


def test_not_due_before_interval(tmp_path):
    save_state(tmp_path, {"last_run": "2026-09-10", "disabled_leagues": {}, "clear_edge_overrides": {}, "log": []})
    state = maybe_run(tmp_path, date(2026, 9, 15))  # só 5 dias depois
    assert state["last_run"] == "2026-09-10"  # não mexeu


def test_disables_league_with_bad_hitrate_and_enough_samples(tmp_path):
    games = [_g("bad_league", "hit" if i < 3 else "miss") for i in range(8)]  # 3/8 = 37%
    _write_day(tmp_path, "2026-09-01", games)
    state = maybe_run(tmp_path, date(2026, 9, 20))
    assert "bad_league" in disabled_league_keys(state)
    assert state["disabled_leagues"]["bad_league"]["total"] == 8


def test_ignores_leagues_below_min_sample(tmp_path):
    games = [_g("small_league", "miss") for _ in range(3)]  # amostra pequena demais
    _write_day(tmp_path, "2026-09-01", games)
    state = maybe_run(tmp_path, date(2026, 9, 20))
    assert disabled_league_keys(state) == set()


def test_ignores_fillers_and_non_clear(tmp_path):
    games = [_g("league_x", "miss", clear=False) for _ in range(10)]  # nenhum é "clear"
    _write_day(tmp_path, "2026-09-01", games)
    state = maybe_run(tmp_path, date(2026, 9, 20))
    assert disabled_league_keys(state) == set()


def test_tightens_global_criteria_when_overall_hitrate_low(tmp_path):
    # 12/24 = 50%, bem abaixo do global_tighten_hitrate (65%), amostra >= 20
    games = [_g(f"lg{i%6}", "hit" if i % 2 == 0 else "miss") for i in range(24)]
    _write_day(tmp_path, "2026-09-01", games)
    state = maybe_run(tmp_path, date(2026, 9, 20))
    ce = effective_clear_edge(state)
    assert ce["fav_form_ppg"] > CLEAR_EDGE["fav_form_ppg"]
    assert ce["min_table_gap"] > CLEAR_EDGE["min_table_gap"]
    assert state["log"][-1]["changes"]


def test_never_loosens_and_respects_caps(tmp_path):
    save_state(tmp_path, {
        "last_run": "2026-08-01",
        "disabled_leagues": {},
        "clear_edge_overrides": {"fav_form_ppg": 2.2, "min_table_gap": 9},  # já no teto
        "log": [],
    })
    games = [_g(f"lg{i%6}", "hit" if i % 3 == 0 else "miss") for i in range(24)]
    _write_day(tmp_path, "2026-09-01", games)
    state = maybe_run(tmp_path, date(2026, 9, 20))
    ce = effective_clear_edge(state)
    assert ce["fav_form_ppg"] == 2.2   # já no teto, não passa
    assert ce["min_table_gap"] == 9    # já no teto, não passa


def test_good_performance_leaves_state_untouched(tmp_path):
    games = [_g(f"lg{i%6}", "hit") for i in range(24)]  # 100%
    _write_day(tmp_path, "2026-09-01", games)
    state = maybe_run(tmp_path, date(2026, 9, 20))
    assert state["clear_edge_overrides"] == {}
    assert disabled_league_keys(state) == set()
    assert "nada a ajustar" in state["log"][-1]["changes"][0]
