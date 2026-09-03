"""Modelo Poisson 'força de time' — transparente e ajustável via config.MODEL."""
from __future__ import annotations

import math
from statistics import fmean

from .config import MODEL, SCORING
from .util import clamp, score_matrix


def league_avg_goals(rows: list[dict]) -> float:
    total_goals = sum(r["goals_for"] for r in rows)
    total_games = sum(r["played"] for r in rows)
    if total_games < 20:
        return MODEL["default_league_avg"]
    return clamp(total_goals / total_games, 0.7, 2.4)


def _team_strength(row: dict, mu: float) -> tuple[float, float]:
    """Retorna (ataque, defesa) relativos à média da liga (1.0 = média)."""
    reg = MODEL["reg_games"]
    played = row["played"] or 0
    gf_total, ga_total, eff_played = row["goals_for"], row["goals_against"], played

    # reforço com a temporada anterior enquanto a atual tem poucos jogos
    prev = row.get("prev")
    if prev and played < MODEL["prev_blend_until"]:
        w = (MODEL["prev_blend_until"] - played) / MODEL["prev_blend_until"]
        prev_games = MODEL["prev_blend_weight"] * w * prev["played"]
        gf_total += prev["gf_pg"] * prev_games
        ga_total += prev["ga_pg"] * prev_games
        eff_played += prev_games

    season_gf = (gf_total + mu * reg) / (eff_played + reg)
    season_ga = (ga_total + mu * reg) / (eff_played + reg)

    recent = row.get("recent") or []
    r5 = recent[:5]
    if len(r5) >= 2:
        recent_gf = fmean(m["gf"] for m in r5)
        recent_ga = fmean(m["ga"] for m in r5)
    else:
        recent_gf, recent_ga = season_gf, season_ga

    w_s, w_r = MODEL["w_season"], MODEL["w_recent"]
    gf_pg = w_s * season_gf + w_r * recent_gf
    ga_pg = w_s * season_ga + w_r * recent_ga

    lo, hi = MODEL["rating_clamp"]
    exp = MODEL["rating_exp"]
    attack = clamp((gf_pg / mu) ** exp, lo, hi)
    defense = clamp((ga_pg / mu) ** exp, lo, hi)
    return attack, defense


def _effective_played(row: dict) -> float:
    p = row["played"] or 0
    if row.get("prev") and p < MODEL["prev_blend_until"]:
        p += 3  # a temporada anterior vale ~3 jogos de amostra
    return p


def predict(home_row: dict, away_row: dict, mu: float) -> dict:
    atk_h, def_h = _team_strength(home_row, mu)
    atk_a, def_a = _team_strength(away_row, mu)

    hfa = math.sqrt(MODEL["home_advantage"])
    lo, hi = MODEL["lambda_clamp"]
    lam_home = clamp(mu * atk_h * def_a * hfa, lo, hi)
    lam_away = clamp(mu * atk_a * def_h / hfa, lo, hi)

    m = score_matrix(lam_home, lam_away, MODEL["max_goals"])
    ng = len(m)

    p_home = sum(m[i][j] for i in range(ng) for j in range(ng) if i > j)
    p_draw = sum(m[i][i] for i in range(ng))
    p_away = sum(m[i][j] for i in range(ng) for j in range(ng) if i < j)
    p_over = sum(m[i][j] for i in range(ng) for j in range(ng) if i + j >= 3)
    p_btts = sum(m[i][j] for i in range(1, ng) for j in range(1, ng))

    min_played = min(_effective_played(home_row), _effective_played(away_row))
    sample_factor = clamp(min_played / SCORING["sample_full_games"], 0.45, 1.0)

    return {
        "lambda_home": round(lam_home, 2),
        "lambda_away": round(lam_away, 2),
        "expected_goals": round(lam_home + lam_away, 2),
        "sample_factor": round(sample_factor, 3),
        "probs": {
            "HOME": p_home,
            "DRAW": p_draw,
            "AWAY": p_away,
            "1X": p_home + p_draw,
            "X2": p_away + p_draw,
            "12": p_home + p_away,
            "OVER25": p_over,
            "UNDER25": 1.0 - p_over,
            "BTTS_YES": p_btts,
            "BTTS_NO": 1.0 - p_btts,
        },
    }
