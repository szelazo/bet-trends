"""Detecção de tendências claras a partir do histórico recente e da tabela.

`recent` é a lista de jogos do time, do mais recente p/ o mais antigo, cada item:
    {"result": "W"/"D"/"L", "gf": float, "ga": float, "home": bool, "opponent": str, ...}
"""
from __future__ import annotations

from .util import clamp

# alvos que uma tendência pode favorecer
HOME, AWAY = "HOME", "AWAY"
OVER, UNDER = "OVER", "UNDER"
BTTS_YES, BTTS_NO = "BTTS_YES", "BTTS_NO"


def last5_string(recent: list[dict]) -> str:
    return "".join(m["result"] for m in recent[:5])


def _lead_streak(recent: list[dict], predicate) -> int:
    n = 0
    for m in recent:
        if predicate(m):
            n += 1
        else:
            break
    return n


def streaks(recent: list[dict]) -> dict[str, int]:
    return {
        "unbeaten": _lead_streak(recent, lambda m: m["result"] != "L"),
        "winless": _lead_streak(recent, lambda m: m["result"] != "W"),
        "winning": _lead_streak(recent, lambda m: m["result"] == "W"),
        "losing": _lead_streak(recent, lambda m: m["result"] == "L"),
        "scoring": _lead_streak(recent, lambda m: m["gf"] >= 1),
        "no_score": _lead_streak(recent, lambda m: m["gf"] == 0),
        "clean_sheet": _lead_streak(recent, lambda m: m["ga"] == 0),
        "conceding": _lead_streak(recent, lambda m: m["ga"] >= 1),
    }


def _trend(label: str, kind: str, strength: float, favors: str | None, team: str) -> dict:
    return {
        "label": label,
        "kind": kind,
        "strength": round(clamp(strength, 0.0, 1.0), 3),
        "favors": favors,
        "team": team,
    }


def team_trends(recent: list[dict], *, side: str, team_name: str) -> list[dict]:
    """Tendências de um time. `side` é HOME ou AWAY (p/ saber quem a tendência favorece)."""
    if len(recent) < 3:
        return []
    opp = AWAY if side == HOME else HOME
    s = streaks(recent)
    n = len(recent)
    r5 = recent[:5]
    out: list[dict] = []

    if s["unbeaten"] >= 3:
        cap = "" if s["unbeaten"] < n else "+"
        out.append(_trend(
            f"Invicto há {s['unbeaten']}{cap} jogos", "unbeaten",
            (s["unbeaten"] - 2) / 5, side, team_name))
    if s["winning"] >= 3:
        out.append(_trend(
            f"{s['winning']} vitórias seguidas", "winning",
            (s["winning"] - 1) / 4, side, team_name))
    if s["winless"] >= 4:
        cap = "" if s["winless"] < n else "+"
        out.append(_trend(
            f"Não vence há {s['winless']}{cap} jogos", "winless",
            (s["winless"] - 3) / 5, opp, team_name))
    if s["losing"] >= 3:
        out.append(_trend(
            f"{s['losing']} derrotas seguidas", "losing",
            (s["losing"] - 1) / 4, opp, team_name))

    # gols
    over5 = sum(1 for m in r5 if m["gf"] + m["ga"] >= 3)
    under5 = sum(1 for m in r5 if m["gf"] + m["ga"] <= 2)
    btts5 = sum(1 for m in r5 if m["gf"] >= 1 and m["ga"] >= 1)
    if len(r5) == 5 and over5 >= 4:
        out.append(_trend(f"Over 2.5 em {over5} dos últimos 5", "over", (over5 - 2) / 3, OVER, team_name))
    if len(r5) == 5 and under5 >= 4:
        out.append(_trend(f"Under 2.5 em {under5} dos últimos 5", "under", (under5 - 2) / 3, UNDER, team_name))
    if len(r5) == 5 and btts5 >= 4:
        out.append(_trend(f"Ambos marcam em {btts5} dos últimos 5", "btts", (btts5 - 2) / 3, BTTS_YES, team_name))
    if s["scoring"] >= 5:
        out.append(_trend(f"Marcou nos últimos {s['scoring']}", "scoring", (s["scoring"] - 3) / 5, OVER, team_name))
    if s["no_score"] >= 3:
        out.append(_trend(f"Não marca há {s['no_score']} jogos", "no_score", (s["no_score"] - 2) / 3, BTTS_NO, team_name))
    if s["clean_sheet"] >= 3:
        out.append(_trend(f"{s['clean_sheet']} jogos sem sofrer gol", "clean_sheet", (s["clean_sheet"] - 2) / 3, UNDER, team_name))
    if s["conceding"] >= 5:
        out.append(_trend(f"Sofre gol há {s['conceding']} jogos", "conceding", (s["conceding"] - 3) / 5, OVER, team_name))

    return out


def consolidate(trends: list[dict], cap: int = 6) -> list[dict]:
    """Remove duplicatas exatas e ordena por força."""
    seen: set[tuple] = set()
    out: list[dict] = []
    for t in sorted(trends, key=lambda x: x["strength"], reverse=True):
        key = (t["label"], t.get("team"))
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out[:cap]


def table_gap_trend(home_row: dict | None, away_row: dict | None) -> dict | None:
    if not home_row or not away_row:
        return None
    hp, ap = home_row.get("position"), away_row.get("position")
    if not hp or not ap:
        return None
    gap = ap - hp  # positivo → mandante melhor colocado
    if abs(gap) < 5:
        return None
    better_side = HOME if gap > 0 else AWAY
    better_row = home_row if gap > 0 else away_row
    return _trend(
        f"{better_row['team_name']} está {abs(gap)} posições à frente na tabela",
        "table_gap", clamp(abs(gap) / 14, 0.15, 0.9), better_side, better_row["team_name"],
    )


def merge_recent(*sources: list[dict], cap: int = 12) -> list[dict]:
    """Une históricos de fontes diferentes, deduplicando por (data, adversário)."""
    seen: set[tuple] = set()
    merged: list[dict] = []
    for src in sources:
        for m in src or []:
            key = ((m.get("date") or "")[:10], (m.get("opponent") or "").lower())
            if key in seen:
                continue
            seen.add(key)
            merged.append(m)
    merged.sort(key=lambda x: x.get("date") or "", reverse=True)
    return merged[:cap]
