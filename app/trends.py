"""Tendências no estilo 365scores: uma frase por time, com contagem sobre uma janela.

Ex: "Venceu 8 dos últimos 10", "Não vence fora de casa há 5 jogos",
    "Ambos marcaram em 7 dos últimos 10".

`recent` = jogos do time do mais recente p/ o mais antigo:
    {"result": "W"/"D"/"L", "gf": float, "ga": float, "home": bool, "opponent": str}
"""
from __future__ import annotations

import math

from .util import clamp

HOME, AWAY = "HOME", "AWAY"
OVER, UNDER = "OVER", "UNDER"
BTTS_YES, BTTS_NO = "BTTS_YES", "BTTS_NO"

GERAL, CASA_FORA, SEQUENCIA, TEMPORADA, CONFRONTO = (
    "geral", "casa_fora", "sequencia", "temporada", "confronto"
)


def last5_string(recent: list[dict]) -> str:
    return "".join(m["result"] for m in recent[:5])


def _t(label, *, strength, favors, team, side, group, kind) -> dict:
    return {
        "label": label,
        "strength": round(clamp(strength, 0.0, 1.0), 3),
        "favors": favors,
        "team": team,
        "side": side,
        "group": group,
        "kind": kind,
    }


def _lead_streak(games, predicate) -> int:
    n = 0
    for m in games:
        if predicate(m):
            n += 1
        else:
            break
    return n


def _count_trends(games: list[dict], *, team: str, side: str, scope: str, group: str) -> list[dict]:
    """Frases 'X em N dos últimos M' quando a proporção é forte."""
    n = len(games)
    if n < 4:
        return []
    opp = AWAY if side == HOME else HOME
    w = sum(1 for m in games if m["result"] == "W")
    d = sum(1 for m in games if m["result"] == "D")
    ll = sum(1 for m in games if m["result"] == "L")
    unbeaten = w + d
    winless = d + ll
    cs = sum(1 for m in games if m["ga"] == 0)
    concd = sum(1 for m in games if m["ga"] >= 1)
    scored = sum(1 for m in games if m["gf"] >= 1)
    noscore = sum(1 for m in games if m["gf"] == 0)
    over = sum(1 for m in games if m["gf"] + m["ga"] >= 3)
    under = sum(1 for m in games if m["gf"] + m["ga"] <= 2)
    btts = sum(1 for m in games if m["gf"] >= 1 and m["ga"] >= 1)

    hi = math.ceil(0.7 * n)
    almost = n - 1
    out: list[dict] = []

    def add(cond, label, strength, favors, kind):
        if cond:
            out.append(_t(label + scope, strength=strength, favors=favors,
                          team=team, side=side, group=group, kind=kind))

    # resultado — uma frase só, a mais marcante
    if w >= hi:
        add(True, f"Venceu {w} dos últimos {n}", 0.25 + 0.5 * w / n, side, "wins")
    elif ll >= math.ceil(0.6 * n):
        add(True, f"Perdeu {ll} dos últimos {n}", 0.25 + 0.45 * ll / n, opp, "losses")
    elif unbeaten >= max(hi, n - 1) and w >= max(1, n // 4):
        add(True, f"Invicto em {unbeaten} dos últimos {n}", 0.2 + 0.35 * unbeaten / n, side, "unbeaten")
    elif winless >= max(hi, n - 1):
        txt = f"Não venceu nenhum dos últimos {n}" if w == 0 else f"Só venceu {w} dos últimos {n}"
        add(True, txt, 0.2 + 0.35 * winless / n, opp, "winless")

    # gols / defesa
    add(cs >= math.ceil(0.6 * n), f"Não sofreu gol em {cs} dos últimos {n}", 0.15 + 0.4 * cs / n, UNDER, "clean_sheets")
    add(concd == n and n >= 5, f"Sofreu gol em todos os últimos {n}", 0.4, OVER, "always_concede")
    add(noscore >= math.ceil(0.5 * n), f"Não marcou em {noscore} dos últimos {n}", 0.2 + 0.3 * noscore / n, opp, "no_score")
    add(scored == n and n >= 5, f"Marcou em todos os últimos {n}", 0.3, OVER, "always_score")
    add(over >= hi, f"Mais de 2.5 gols em {over} dos últimos {n}", 0.15 + 0.4 * over / n, OVER, "over")
    add(under >= hi, f"Menos de 2.5 gols em {under} dos últimos {n}", 0.15 + 0.4 * under / n, UNDER, "under")
    add(btts >= hi, f"Ambos marcaram em {btts} dos últimos {n}", 0.15 + 0.35 * btts / n, BTTS_YES, "btts")
    add(n - btts >= hi, f"Ambos marcaram só {btts}x nos últimos {n}", 0.15 + 0.3 * (n - btts) / n, BTTS_NO, "no_btts")
    return out


def _streak_trends(recent: list[dict], *, team: str, side: str) -> list[dict]:
    n = len(recent)
    opp = AWAY if side == HOME else HOME
    ub = _lead_streak(recent, lambda m: m["result"] != "L")
    wl = _lead_streak(recent, lambda m: m["result"] != "W")
    win = _lead_streak(recent, lambda m: m["result"] == "W")
    out: list[dict] = []
    if win >= 3:
        out.append(_t(f"{win} vitórias seguidas", strength=(win - 1) / 4, favors=side,
                      team=team, side=side, group=SEQUENCIA, kind="win_streak"))
    elif ub >= 5:
        cap = "+" if ub >= n else ""
        out.append(_t(f"Invicto há {ub}{cap} jogos", strength=(ub - 3) / 6, favors=side,
                      team=team, side=side, group=SEQUENCIA, kind="unbeaten_streak"))
    if wl >= 5:
        cap = "+" if wl >= n else ""
        out.append(_t(f"Não vence há {wl}{cap} jogos", strength=(wl - 3) / 6, favors=opp,
                      team=team, side=side, group=SEQUENCIA, kind="winless_streak"))
    return out


def _season_trends(row: dict, all_rows: list[dict], *, team: str, side: str) -> list[dict]:
    played = row.get("played") or 0
    if played < 8 or not all_rows:
        return []
    opp = AWAY if side == HOME else HOME
    out: list[dict] = []

    def rank(metric, reverse):
        vals = sorted(
            (r["team_id"] for r in all_rows if (r.get("played") or 0) >= 3),
            key=lambda tid: metric(next(r for r in all_rows if r["team_id"] == tid)),
            reverse=reverse,
        )
        return (vals.index(row["team_id"]) + 1) if row["team_id"] in vals else None, len(vals)

    ga_pg = row["goals_against"] / played
    gf_pg = row["goals_for"] / played
    dr, ntot = rank(lambda r: r["goals_against"] / max(r["played"], 1), False)
    ar_, _ = rank(lambda r: r["goals_for"] / max(r["played"], 1), True)

    if dr and dr <= 3:
        ordn = {1: "Melhor", 2: "2ª melhor", 3: "3ª melhor"}[dr]
        out.append(_t(f"{ordn} defesa da liga ({ga_pg:.1f} sofridos/jogo)",
                      strength=0.5 if dr == 1 else 0.36, favors=side, team=team, side=side,
                      group=TEMPORADA, kind="def_rank"))
    if ar_ and ar_ <= 3:
        ordn = {1: "Melhor", 2: "2º melhor", 3: "3º melhor"}[ar_]
        out.append(_t(f"{ordn} ataque da liga ({gf_pg:.1f} marcados/jogo)",
                      strength=0.44 if ar_ == 1 else 0.32, favors=side, team=team, side=side,
                      group=TEMPORADA, kind="atk_rank"))
    if dr and dr >= ntot - 2:
        out.append(_t(f"Pior defesa da liga ({ga_pg:.1f} sofridos/jogo)",
                      strength=0.34, favors=OVER, team=team, side=side,
                      group=TEMPORADA, kind="def_bottom"))

    losses = row.get("lost") or 0
    if played >= 10 and losses <= max(2, played // 8):
        out.append(_t(f"Só {losses} derrota(s) em {played} jogos no campeonato",
                      strength=clamp(0.5 - losses * 0.08, 0.25, 0.5), favors=side, team=team,
                      side=side, group=TEMPORADA, kind="few_losses"))
    return out


def table_context(home_row: dict | None, away_row: dict | None) -> list[dict]:
    if not home_row or not away_row:
        return []
    hp, ap = home_row.get("position"), away_row.get("position")
    if not hp or not ap:
        return []
    out = [_t(f"{home_row['team_name']} é {hp}º · {away_row['team_name']} é {ap}º",
              strength=0.0, favors=None, team=None, side=None, group=CONFRONTO, kind="positions")]
    gap = abs(hp - ap)
    if gap >= 4:
        better = HOME if hp < ap else AWAY
        name = home_row["team_name"] if hp < ap else away_row["team_name"]
        out.append(_t(f"{name} está {gap} posições à frente",
                      strength=clamp(gap / 14, 0.15, 0.8), favors=better,
                      team=None, side=None, group=CONFRONTO, kind="table_gap"))
    return out


def _dedupe_by_kind(trends: list[dict], *, per_team_scope: int = 2) -> list[dict]:
    """Mantém no máx. N tendências por (time, grupo), priorizando força."""
    from collections import defaultdict
    buckets = defaultdict(list)
    for t in sorted(trends, key=lambda x: -x["strength"]):
        buckets[(t["team"], t["group"])].append(t)
    kept: list[dict] = []
    for (team, group), items in buckets.items():
        limit = 99 if group in (TEMPORADA, CONFRONTO) else per_team_scope
        kept.extend(items[:limit])
    return kept


def compute_trends(
    h_recent: list[dict], a_recent: list[dict],
    home_row: dict | None, away_row: dict | None, all_rows: list[dict],
    home_name: str, away_name: str,
) -> list[dict]:
    trends: list[dict] = []
    for recent, side, name, row in (
        (h_recent, HOME, home_name, home_row),
        (a_recent, AWAY, away_name, away_row),
    ):
        n = min(len(recent), 10)
        trends += _count_trends(recent[:n], team=name, side=side, scope="", group=GERAL)
        venue = [m for m in recent if m["home"] == (side == HOME)][:6]
        vscope = " em casa" if side == HOME else " fora de casa"
        trends += _count_trends(venue, team=name, side=side, scope=vscope, group=CASA_FORA)
        trends += _streak_trends(recent, team=name, side=side)
        if row:
            trends += _season_trends(row, all_rows, team=name, side=side)
    trends = _dedupe_by_kind(trends)
    trends += table_context(home_row, away_row)
    return trends


def aligned_to(selection_targets: set[str], trends: list[dict]) -> list[dict]:
    return [t for t in trends if t.get("favors") in selection_targets]


def merge_recent(*sources: list[dict], cap: int = 15) -> list[dict]:
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
