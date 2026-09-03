"""Escolhe o mercado recomendado, calcula confiança (0–100) e valor (EV)."""
from __future__ import annotations

from .config import SCORING
from .util import clamp

# alvos de tendência que cada seleção considera a favor / contra
_ALIGN = {
    "HOME":    ({"HOME"}, {"AWAY"}),
    "AWAY":    ({"AWAY"}, {"HOME"}),
    "1X":      ({"HOME"}, {"AWAY"}),
    "X2":      ({"AWAY"}, {"HOME"}),
    "OVER25":  ({"OVER", "BTTS_YES"}, {"UNDER", "BTTS_NO"}),
    "UNDER25": ({"UNDER", "BTTS_NO"}, {"OVER", "BTTS_YES"}),
    "BTTS_YES": ({"BTTS_YES", "OVER"}, {"BTTS_NO", "UNDER"}),
    "BTTS_NO":  ({"BTTS_NO", "UNDER"}, {"BTTS_YES", "OVER"}),
}
_FAMILY = {
    "HOME": "1x2", "AWAY": "1x2",
    "1X": "double_chance", "X2": "double_chance",
    "OVER25": "over_under", "UNDER25": "over_under",
    "BTTS_YES": "btts", "BTTS_NO": "btts",
}
_NEUTRAL = {"1x2": 0.34, "double_chance": 0.55, "over_under": 0.50, "btts": 0.50}
# dupla chance é mais "segura" (odd baixa) → leve desconto na confiança
_FAMILY_WEIGHT = {"1x2": 1.0, "double_chance": 0.92, "over_under": 1.0, "btts": 1.0}


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


def _odd_for(sel: str, game: dict, odds: dict | None) -> float | None:
    if not odds:
        return None
    h2h = odds.get("h2h") or {}
    tot = odds.get("totals") or {}
    btts = odds.get("btts") or {}
    home_odd = h2h.get(odds.get("home_team"))
    away_odd = h2h.get(odds.get("away_team"))
    draw_odd = h2h.get("Draw")

    def dc(a: float | None, b: float | None) -> float | None:
        if a and b:
            return round(1.0 / (1.0 / a + 1.0 / b), 3)
        return None

    return {
        "HOME": home_odd,
        "AWAY": away_odd,
        "1X": dc(home_odd, draw_odd),
        "X2": dc(away_odd, draw_odd),
        "OVER25": tot.get("Over"),
        "UNDER25": tot.get("Under"),
        "BTTS_YES": btts.get("Yes"),
        "BTTS_NO": btts.get("No"),
    }.get(sel)


def _kelly_stake(prob: float, odd: float) -> float:
    if odd <= 1:
        return 0.0
    f = (prob * odd - 1) / (odd - 1)
    return round(clamp(SCORING["kelly_fraction"] * f, 0.0, SCORING["kelly_cap"]), 4)


def evaluate(game: dict, model: dict, trends: list[dict], odds: dict | None) -> dict:
    """Retorna o dict do jogo enriquecido com a recomendação."""
    probs = model["probs"]
    sample = model["sample_factor"]
    home, away = game["home"]["name"], game["away"]["name"]
    candidates = []

    for sel in ("HOME", "AWAY", "1X", "X2", "OVER25", "UNDER25", "BTTS_YES", "BTTS_NO"):
        family = _FAMILY[sel]
        prob = probs[sel]
        neutral = _NEUTRAL[family]
        edge = clamp((prob - neutral) / (1 - neutral), 0.0, 1.0)
        align = _trend_alignment(sel, trends)
        raw = SCORING["w_prob"] * edge + SCORING["w_trend"] * align
        confidence = round(100 * raw * sample * _FAMILY_WEIGHT[family])
        odd = _odd_for(sel, game, odds)
        eligible = prob >= SCORING["prob_floor"][family]

        entry = {
            "selection": sel,
            "family": family,
            "label": _label(sel, home, away),
            "model_prob": round(prob, 4),
            "trend_alignment": round(align, 3),
            "confidence": confidence,
            "eligible": eligible,
            "odd": odd,
        }
        if odd:
            ev = prob * odd - 1
            entry.update(
                implied_prob=round(1 / odd, 4),
                ev=round(ev, 4),
                value=ev >= SCORING["value_threshold"],
                stake_fraction=_kelly_stake(prob, odd),
            )
        candidates.append(entry)

    eligible = [c for c in candidates if c["eligible"]]
    pool = eligible or candidates
    # desempate: confiança, depois valor, depois prob
    pick = max(pool, key=lambda c: (c["confidence"], c.get("ev", -1), c["model_prob"]))
    pick = dict(pick)
    pick["low_conviction"] = not eligible or pick["confidence"] < SCORING["min_confidence_listed"]

    aligned_trends = [
        t for t in trends
        if t.get("favors") in _ALIGN[pick["selection"]][0]
    ]

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
        (c for c in candidates if c["selection"] != pick["selection"]),
        key=lambda c: c["confidence"], reverse=True,
    )[:3]
    game["trends"] = trends
    game["aligned_trends"] = aligned_trends
    game["confidence"] = pick["confidence"]
    return game
