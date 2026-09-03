"""Escolhe o mercado recomendado e calcula o score de confiança (0–100).

Prioridade: resultado final (1X2) e dupla chance são SEMPRE o palpite principal.
Over/Under 2.5 e Ambos Marcam só viram principal se a tendência for muito forte;
caso contrário ficam em 'outros mercados'.
"""
from __future__ import annotations

from .config import SCORING
from .util import clamp

_ALIGN = {
    "HOME":     ({"HOME"}, {"AWAY"}),
    "AWAY":     ({"AWAY"}, {"HOME"}),
    "1X":       ({"HOME"}, {"AWAY"}),
    "X2":       ({"AWAY"}, {"HOME"}),
    "OVER25":   ({"OVER", "BTTS_YES"}, {"UNDER", "BTTS_NO"}),
    "UNDER25":  ({"UNDER", "BTTS_NO"}, {"OVER", "BTTS_YES"}),
    "BTTS_YES": ({"BTTS_YES", "OVER"}, {"BTTS_NO", "UNDER"}),
    "BTTS_NO":  ({"BTTS_NO", "UNDER"}, {"BTTS_YES", "OVER"}),
}
_FAMILY = {
    "HOME": "1x2", "AWAY": "1x2",
    "1X": "double_chance", "X2": "double_chance",
    "OVER25": "over_under", "UNDER25": "over_under",
    "BTTS_YES": "btts", "BTTS_NO": "btts",
}
_PRIMARY_FAMILIES = {"1x2", "double_chance"}
_NEUTRAL = {"1x2": 0.34, "double_chance": 0.55, "over_under": 0.50, "btts": 0.50}
# entre os principais, leve preferência pelo resultado seco sobre a dupla chance
_FAMILY_WEIGHT = {"1x2": 1.0, "double_chance": 0.94, "over_under": 1.0, "btts": 1.0}


def _label(sel: str, home: str, away: str) -> str:
    return {
        "HOME": f"Vitória do {home}",
        "AWAY": f"Vitória do {away}",
        "1X": f"Dupla chance: {home} ou empate (1X)",
        "X2": f"Dupla chance: {away} ou empate (X2)",
        "OVER25": "Mais de 2.5 gols",
        "UNDER25": "Menos de 2.5 gols",
        "BTTS_YES": "Ambos os times marcam",
        "BTTS_NO": "Ambos marcam: não",
    }[sel]


def _trend_alignment(sel: str, trends: list[dict]) -> float:
    good, bad = _ALIGN[sel]
    pos = sum(t["strength"] for t in trends if t.get("favors") in good)
    neg = sum(t["strength"] for t in trends if t.get("favors") in bad)
    return clamp(pos / 1.5 - 0.6 * neg, 0.0, 1.0)


def _odd_for(sel: str, odds: dict | None) -> float | None:
    if not odds:
        return None
    h2h = odds.get("h2h") or {}
    tot = odds.get("totals") or {}
    btts = odds.get("btts") or {}
    home_odd = h2h.get(odds.get("home_team"))
    away_odd = h2h.get(odds.get("away_team"))
    draw_odd = h2h.get("Draw")

    def dc(a: float | None, b: float | None) -> float | None:
        return round(1.0 / (1.0 / a + 1.0 / b), 2) if (a and b) else None

    return {
        "HOME": round(home_odd, 2) if home_odd else None,
        "AWAY": round(away_odd, 2) if away_odd else None,
        "1X": dc(home_odd, draw_odd),
        "X2": dc(away_odd, draw_odd),
        "OVER25": tot.get("Over"),
        "UNDER25": tot.get("Under"),
        "BTTS_YES": btts.get("Yes"),
        "BTTS_NO": btts.get("No"),
    }.get(sel)


def _candidate(sel, probs, sample, trends, odds) -> dict:
    family = _FAMILY[sel]
    prob = probs[sel]
    edge = clamp((prob - _NEUTRAL[family]) / (1 - _NEUTRAL[family]), 0.0, 1.0)
    align = _trend_alignment(sel, trends)
    raw = SCORING["w_prob"] * edge + SCORING["w_trend"] * align
    return {
        "selection": sel,
        "family": family,
        "label": None,  # preenchido depois
        "model_prob": round(prob, 4),
        "trend_alignment": round(align, 3),
        "confidence": round(100 * raw * sample * _FAMILY_WEIGHT[family]),
        "eligible": prob >= SCORING["prob_floor"][family],
        "odd": _odd_for(sel, odds),
    }


def evaluate(game: dict, model: dict, trends: list[dict], odds: dict | None) -> dict:
    probs = model["probs"]
    sample = model["sample_factor"]
    home, away = game["home"]["name"], game["away"]["name"]

    cands = [
        _candidate(s, probs, sample, trends, odds)
        for s in ("HOME", "AWAY", "1X", "X2", "OVER25", "UNDER25", "BTTS_YES", "BTTS_NO")
    ]
    for c in cands:
        c["label"] = _label(c["selection"], home, away)

    primary = [c for c in cands if c["family"] in _PRIMARY_FAMILIES]
    secondary = [c for c in cands if c["family"] not in _PRIMARY_FAMILIES]

    elig_primary = [c for c in primary if c["eligible"]]
    pool = elig_primary or primary
    pick = max(pool, key=lambda c: (c["confidence"], c["model_prob"]))

    # secundário só assume se for MUITO mais forte
    override = SCORING["secondary_override_prob"]
    margin = SCORING["secondary_override_margin"]
    strong = [
        c for c in secondary
        if c["model_prob"] >= override and c["confidence"] >= pick["confidence"] + margin
    ]
    if strong:
        pick = max(strong, key=lambda c: c["confidence"])

    pick = dict(pick)
    pick["low_conviction"] = (
        not pick["eligible"] or pick["confidence"] < SCORING["min_confidence_listed"]
    )

    aligned = [t for t in trends if t.get("favors") in _ALIGN[pick["selection"]][0]]

    game = dict(game)
    game["model"] = {
        "lambda_home": model["lambda_home"],
        "lambda_away": model["lambda_away"],
        "expected_goals": model["expected_goals"],
        "sample_factor": sample,
        "probs": {k: round(v, 4) for k, v in probs.items()},
    }
    game["pick"] = pick
    game["alt_markets"] = sorted(
        (c for c in cands if c["selection"] != pick["selection"]),
        key=lambda c: c["confidence"], reverse=True,
    )[:4]
    game["trends"] = trends
    game["aligned_trends"] = aligned
    game["confidence"] = pick["confidence"]
    return game
