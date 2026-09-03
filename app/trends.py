"""Detecção de tendências a partir do histórico recente, dos recortes casa/fora
e da posição/campanha na tabela.

`recent` é a lista de jogos do time, do mais recente p/ o mais antigo:
    {"result": "W"/"D"/"L", "gf": float, "ga": float, "home": bool, "opponent": str, ...}
"""
from __future__ import annotations

from .util import clamp

# alvos que uma tendência pode favorecer
HOME, AWAY = "HOME", "AWAY"
OVER, UNDER = "OVER", "UNDER"
BTTS_YES, BTTS_NO = "BTTS_YES", "BTTS_NO"

# grupos de exibição
FORMA, SEQUENCIA, CASA_FORA, TEMPORADA, TABELA = (
    "forma", "sequencia", "casa_fora", "temporada", "tabela"
)
LONG_STREAK = 6  # a partir daqui a sequência é "longa"


def last5_string(recent: list[dict]) -> str:
    return "".join(m["result"] for m in recent[:5])


def _lead_streak(games: list[dict], predicate) -> int:
    n = 0
    for m in games:
        if predicate(m):
            n += 1
        else:
            break
    return n


def streaks(games: list[dict]) -> dict[str, int]:
    return {
        "unbeaten": _lead_streak(games, lambda m: m["result"] != "L"),
        "winless": _lead_streak(games, lambda m: m["result"] != "W"),
        "winning": _lead_streak(games, lambda m: m["result"] == "W"),
        "losing": _lead_streak(games, lambda m: m["result"] == "L"),
        "scoring": _lead_streak(games, lambda m: m["gf"] >= 1),
        "no_score": _lead_streak(games, lambda m: m["gf"] == 0),
        "clean_sheet": _lead_streak(games, lambda m: m["ga"] == 0),
        "conceding": _lead_streak(games, lambda m: m["ga"] >= 1),
    }


def _trend(label, kind, strength, favors, team, group) -> dict:
    return {
        "label": label,
        "kind": kind,
        "strength": round(clamp(strength, 0.0, 1.0), 3),
        "favors": favors,
        "team": team,
        "group": group,
    }


def team_trends(recent: list[dict], *, side: str, team_name: str) -> list[dict]:
    """Forma recente + sequências (curtas em 'forma', longas em 'sequencia')."""
    if len(recent) < 3:
        return []
    opp = AWAY if side == HOME else HOME
    s = streaks(recent)
    n = len(recent)
    r5 = recent[:5]
    out: list[dict] = []

    def grp(count: int) -> str:
        return SEQUENCIA if count >= LONG_STREAK else FORMA

    if s["unbeaten"] >= 3:
        cap = "+" if s["unbeaten"] >= n else ""
        out.append(_trend(f"Invicto há {s['unbeaten']}{cap} jogos", "unbeaten",
                          (s["unbeaten"] - 2) / 6, side, team_name, grp(s["unbeaten"])))
    if s["winning"] >= 3:
        out.append(_trend(f"{s['winning']} vitórias seguidas", "winning",
                          (s["winning"] - 1) / 4, side, team_name, grp(s["winning"])))
    if s["winless"] >= 4:
        cap = "+" if s["winless"] >= n else ""
        out.append(_trend(f"Não vence há {s['winless']}{cap} jogos", "winless",
                          (s["winless"] - 3) / 6, opp, team_name, grp(s["winless"])))
    if s["losing"] >= 3:
        out.append(_trend(f"{s['losing']} derrotas seguidas", "losing",
                          (s["losing"] - 1) / 4, opp, team_name, grp(s["losing"])))

    over5 = sum(1 for m in r5 if m["gf"] + m["ga"] >= 3)
    under5 = sum(1 for m in r5 if m["gf"] + m["ga"] <= 2)
    btts5 = sum(1 for m in r5 if m["gf"] >= 1 and m["ga"] >= 1)
    if len(r5) == 5 and over5 >= 4:
        out.append(_trend(f"Over 2.5 em {over5} dos últimos 5", "over", (over5 - 2) / 3, OVER, team_name, FORMA))
    if len(r5) == 5 and under5 >= 4:
        out.append(_trend(f"Under 2.5 em {under5} dos últimos 5", "under", (under5 - 2) / 3, UNDER, team_name, FORMA))
    if len(r5) == 5 and btts5 >= 4:
        out.append(_trend(f"Ambos marcam em {btts5} dos últimos 5", "btts", (btts5 - 2) / 3, BTTS_YES, team_name, FORMA))
    if s["scoring"] >= 5:
        out.append(_trend(f"Marcou nos últimos {s['scoring']}", "scoring", (s["scoring"] - 3) / 5, OVER, team_name, grp(s["scoring"])))
    if s["no_score"] >= 3:
        out.append(_trend(f"Não marca há {s['no_score']} jogos", "no_score", (s["no_score"] - 2) / 3, BTTS_NO, team_name, FORMA))
    if s["clean_sheet"] >= 3:
        out.append(_trend(f"{s['clean_sheet']} jogos sem sofrer gol", "clean_sheet", (s["clean_sheet"] - 2) / 3, UNDER, team_name, grp(s["clean_sheet"])))
    if s["conceding"] >= 5:
        out.append(_trend(f"Sofre gol há {s['conceding']} jogos", "conceding", (s["conceding"] - 3) / 5, OVER, team_name, FORMA))

    return out


def venue_trends(recent: list[dict], *, side: str, team_name: str) -> list[dict]:
    """Recorte casa/fora — só o mando relevante p/ este jogo."""
    is_home = side == HOME
    venue_games = [m for m in recent if m["home"] == is_home]
    if len(venue_games) < 3:
        return []
    where = "em casa" if is_home else "fora de casa"
    opp = AWAY if is_home else HOME
    s = streaks(venue_games)
    n = len(venue_games)
    out: list[dict] = []

    if s["unbeaten"] >= 3:
        cap = "+" if s["unbeaten"] >= n else ""
        out.append(_trend(f"Invicto há {s['unbeaten']}{cap} jogos {where}", "venue_unbeaten",
                          (s["unbeaten"] - 2) / 5, side, team_name, CASA_FORA))
    if s["winning"] >= 3:
        out.append(_trend(f"{s['winning']} vitórias seguidas {where}", "venue_winning",
                          (s["winning"] - 1) / 3, side, team_name, CASA_FORA))
    if s["winless"] >= 3:
        cap = "+" if s["winless"] >= n else ""
        out.append(_trend(f"Não vence {where} há {s['winless']}{cap} jogos", "venue_winless",
                          (s["winless"] - 2) / 5, opp, team_name, CASA_FORA))
    if s["losing"] >= 3:
        out.append(_trend(f"{s['losing']} derrotas seguidas {where}", "venue_losing",
                          (s["losing"] - 1) / 3, opp, team_name, CASA_FORA))
    return out


def season_trends(row: dict, all_rows: list[dict], *, side: str, team_name: str) -> list[dict]:
    """Campanha e rankings na liga (sinal 'longo' mais confiável)."""
    played = row.get("played") or 0
    if played < 6 or not all_rows:
        return []
    opp = AWAY if side == HOME else HOME
    out: list[dict] = []

    # ranking de ataque / defesa por jogo
    def rank(metric, reverse):
        vals = sorted(
            ((r["team_id"], metric(r)) for r in all_rows if (r.get("played") or 0) >= 3),
            key=lambda kv: kv[1], reverse=reverse,
        )
        for i, (tid, _) in enumerate(vals, 1):
            if tid == row["team_id"]:
                return i, len(vals)
        return None, len(all_rows)

    ga_pg = row["goals_against"] / played
    gf_pg = row["goals_for"] / played
    def_rank, ntot = rank(lambda r: r["goals_against"] / max(r["played"], 1), reverse=False)
    atk_rank, _ = rank(lambda r: r["goals_for"] / max(r["played"], 1), reverse=True)

    if def_rank and def_rank <= 3:
        ord_ = {1: "melhor", 2: "2ª melhor", 3: "3ª melhor"}[def_rank]
        out.append(_trend(f"{ord_} defesa da liga ({ga_pg:.1f} sofridos/jogo)", "def_top",
                          0.5 if def_rank == 1 else 0.38, side, team_name, TEMPORADA))
    if atk_rank and atk_rank <= 3:
        ord_ = {1: "melhor", 2: "2º melhor", 3: "3º melhor"}[atk_rank]
        out.append(_trend(f"{ord_} ataque da liga ({gf_pg:.1f} marcados/jogo)", "atk_top",
                          0.45 if atk_rank == 1 else 0.34, side, team_name, TEMPORADA))
    if def_rank and def_rank >= ntot - 2:
        out.append(_trend(f"Pior defesa da liga ({ga_pg:.1f} sofridos/jogo)", "def_bottom",
                          0.35, OVER, team_name, TEMPORADA))

    # campanha: poucas derrotas / muitas derrotas
    losses = row.get("lost") or 0
    wins = row.get("won") or 0
    if played >= 10 and losses <= max(2, played // 8):
        out.append(_trend(f"Só {losses} derrota(s) em {played} jogos", "few_losses",
                          clamp(0.5 - losses * 0.08, 0.25, 0.5), side, team_name, TEMPORADA))
    if played >= 10 and wins <= max(1, played // 10):
        out.append(_trend(f"Só {wins} vitória(s) em {played} jogos", "few_wins",
                          0.35, opp, team_name, TEMPORADA))
    return out


def table_gap_trend(home_row: dict | None, away_row: dict | None) -> dict | None:
    if not home_row or not away_row:
        return None
    hp, ap = home_row.get("position"), away_row.get("position")
    if not hp or not ap:
        return None
    gap = ap - hp  # positivo → mandante melhor colocado
    if abs(gap) < 4:
        return None
    better_side = HOME if gap > 0 else AWAY
    better, worse = (home_row, away_row) if gap > 0 else (away_row, home_row)
    return _trend(
        f"{better['team_name']} {min(hp, ap)}º × {max(hp, ap)}º {worse['team_name']} "
        f"({abs(gap)} posições)",
        "table_gap", clamp(abs(gap) / 14, 0.15, 0.85), better_side,
        better["team_name"], TABELA,
    )


def consolidate(trends: list[dict], cap: int = 9) -> list[dict]:
    """Remove duplicatas e ordena por grupo e força."""
    order = {FORMA: 0, SEQUENCIA: 1, CASA_FORA: 2, TEMPORADA: 3, TABELA: 4}
    seen: set[tuple] = set()
    out: list[dict] = []
    for t in sorted(trends, key=lambda x: (order.get(x.get("group"), 9), -x["strength"])):
        key = (t["label"], t.get("team"))
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out[:cap]


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
