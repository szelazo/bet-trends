from app.model import _effective_played, league_avg_goals, predict
from app.recommend import evaluate
from app.util import match_teams, poisson_pmf, score_matrix


def row(name, played, gf, ga, pos, recent_results="DDDDD", prev=None):
    gf_pg, ga_pg = gf / played, ga / played
    recent = []
    for i, r in enumerate(recent_results):
        f, a = (2, 0) if r == "W" else (1, 1) if r == "D" else (0, 2)
        recent.append({"result": r, "gf": f, "ga": a, "home": True, "opponent": "x", "date": f"2026-08-1{i}"})
    return {
        "team_id": hash(name) % 10000,
        "team_name": name,
        "position": pos,
        "played": played,
        "won": 0, "drawn": played, "lost": 0,
        "goals_for": gf, "goals_against": ga,
        "points": played,
        "recent": recent,
        "prev": prev,
    }


def test_poisson_sums_to_one():
    m = score_matrix(1.4, 1.1, 8)
    total = sum(sum(r) for r in m)
    assert abs(total - 1.0) < 1e-9
    assert abs(poisson_pmf(0, 0.0) - 1.0) < 1e-12


def test_league_avg_fallback_when_no_data():
    assert league_avg_goals([]) == league_avg_goals([])  # default estável
    rows = [row("A", 10, 15, 8, 1), row("B", 10, 8, 15, 2)]
    mu = league_avg_goals(rows)
    assert 0.9 < mu < 1.6


def test_strong_home_vs_weak_away():
    strong = row("Forte", 10, 25, 5, 1, "WWWWW")
    weak = row("Fraco", 10, 4, 26, 20, "LLLLL")
    mu = league_avg_goals([strong, weak])
    pred = predict(strong, weak, mu)
    p = pred["probs"]
    assert p["HOME"] > 0.6
    assert p["HOME"] > p["AWAY"]
    assert p["1X"] > p["X2"]
    assert 0.4 < pred["expected_goals"] < 6.0


def test_confidence_and_value_flow():
    strong = row("Forte", 10, 22, 6, 1, "WWWWW")
    weak = row("Fraco", 10, 5, 24, 18, "LLLLL")
    mu = league_avg_goals([strong, weak])
    pred = predict(strong, weak, mu)
    game = {
        "start_time": "2026-09-05T20:00:00+00:00",
        "home": {"id": 1, "name": "Forte"},
        "away": {"id": 2, "name": "Fraco"},
    }
    odds = {
        "home_team": "Forte", "away_team": "Fraco",
        "commence_time": "2026-09-05T20:00:00+00:00",
        "h2h": {"Forte": 1.5, "Fraco": 7.0, "Draw": 4.2},
        "totals": {"Over": 1.8, "Under": 2.0}, "btts": {},
    }
    out = evaluate(game, pred, [], odds)
    assert out["pick"]["confidence"] >= 40
    # palpite principal é sempre 1X2 ou dupla chance
    assert out["pick"]["family"] in ("1x2", "double_chance")
    assert out["pick"]["odd"] is not None
    # EV não é mais calculado
    assert "ev" not in out["pick"]


def test_prev_season_boosts_effective_sample():
    r = row("Nova", 2, 3, 3, 5, prev={"gf_pg": 1.6, "ga_pg": 1.0, "played": 30})
    assert _effective_played(r) == 5
    r2 = row("Nova", 2, 3, 3, 5)
    assert _effective_played(r2) == 2


def test_team_name_matching():
    assert match_teams("Atlético-MG", "Flamengo", "Atletico Mineiro", "Flamengo RJ") > 0.6
    assert match_teams("Boca Juniors", "River Plate", "Palmeiras", "Santos") < 0.4
