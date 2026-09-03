"""Escolhe o mercado recomendado e calcula o score de confiança (0–100).

Prioridade: resultado final (1X2) e dupla chance são SEMPRE o palpite principal.
Over/Under 2.5 e Ambos Marcam só viram principal se a tendência for muito forte;
caso contrário ficam em 'outros mercados'.
"""
from __future__ import annotations

from .config import CLEAR_EDGE, SCORING
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
    # aceita chaves "1"/"X"/"2" (365scores) ou nomes de time (the-odds-api)
    home_odd = h2h.get("1") or h2h.get(odds.get("home_team"))
    away_odd = h2h.get("2") or h2h.get(odds.get("away_team"))
    draw_odd = h2h.get("X") or h2h.get("Draw")

    def dc(a: float | None, b: float | None) -> float | None:
        """Odd de dupla chance a partir das 3 odds 1X2 (de-vig + margem da casa)."""
        if not (a and b and home_odd and draw_odd and away_odd):
            return None
        total = 1 / home_odd + 1 / draw_odd + 1 / away_odd  # > 1 (overround)
        prob = (1 / a + 1 / b) / total                       # prob real da dupla
        return round(max(1.01, 0.96 / prob), 2)              # 0.96 ≈ margem típica de DC

    # odds de over/under só valem se a linha for 2.5
    ou_ok = abs((tot.get("line") or 2.5) - 2.5) < 0.01

    return {
        "HOME": round(home_odd, 2) if home_odd else None,
        "AWAY": round(away_odd, 2) if away_odd else None,
        "1X": dc(home_odd, draw_odd),
        "X2": dc(away_odd, draw_odd),
        "OVER25": tot.get("Over") if ou_ok else None,
        "UNDER25": tot.get("Under") if ou_ok else None,
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


def form_ppg(recent: list[dict], n: int = 5) -> float | None:
    g = recent[:n]
    if not g:
        return None
    pts = sum(3 if m["result"] == "W" else 1 if m["result"] == "D" else 0 for m in g)
    return pts / len(g)


def clear_edge(
    selection: str, home_row: dict, away_row: dict,
    h_recent: list[dict], a_recent: list[dict], *, table_size: int, is_cup: bool,
) -> bool:
    """True só quando é claramente 'time bem x time mal': tabela + forma dos dois lados."""
    if selection in ("HOME", "1X"):
        fav_recent, dog_recent, fav_is_home = h_recent, a_recent, True
    elif selection in ("AWAY", "X2"):
        fav_recent, dog_recent, fav_is_home = a_recent, h_recent, False
    else:
        return False  # over/under/btts não é "mismatch" nesse sentido

    c = CLEAR_EDGE
    if len(fav_recent[:5]) < 3 or len(dog_recent[:5]) < 3:
        return False  # amostra curta demais p/ afirmar "fase" (início de temporada)
    fav_ppg, dog_ppg = form_ppg(fav_recent), form_ppg(dog_recent)
    if fav_ppg is None or dog_ppg is None:
        return False

    hp, ap = home_row.get("position"), away_row.get("position")
    if is_cup or not hp or not ap:
        return fav_ppg >= c["cup_fav_form_ppg"] and dog_ppg <= c["cup_dog_form_ppg"]

    fav_pos, dog_pos = (hp, ap) if fav_is_home else (ap, hp)
    size = table_size or max(hp, ap, 18)
    gap_ok = (
        dog_pos - fav_pos >= c["min_table_gap"]
        and fav_pos <= size * c["fav_pos_frac"]
        and dog_pos >= size * c["dog_pos_frac"]
    )
    form_ok = fav_ppg >= c["fav_form_ppg"] and dog_ppg <= c["dog_form_ppg"]
    return gap_ok and form_ok


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

    # dupla chance que paga quase nada → troca pelo resultado seco do mesmo lado
    if (
        pick["family"] == "double_chance"
        and pick["odd"] and pick["odd"] < SCORING["min_dc_odd"]
    ):
        want = "HOME" if pick["selection"] == "1X" else "AWAY"
        straight = next((c for c in cands if c["selection"] == want), None)
        if straight and straight["model_prob"] >= SCORING["straight_switch_prob"]:
            straight = dict(straight)
            straight["confidence"] = pick["confidence"]  # mantém o ranking do jogo
            pick = straight

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
