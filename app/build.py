"""Orquestrador: coleta dados, roda o modelo e escreve docs/data/*.json.

Uso:
    python -m app.build                 # hoje + 3 dias
    python -m app.build --date 2026-09-05 --days 2
    python -m app.build --no-odds       # ignora a the-odds-api
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import __version__
from .config import ODDS as ODDS_CFG
from .config import S365, SCORING, BANKROLL, enabled_leagues
from .model import league_avg_goals, predict
from .recommend import evaluate
from .sources.odds_api import OddsApi, find_match
from .sources.scores365 import Scores365, status_ended, status_scheduled
from .trends import (
    consolidate,
    last5_string,
    merge_recent,
    streaks,
    table_gap_trend,
    team_trends,
)
from .util import name_similarity

TZ = ZoneInfo(S365["timezone_name"])


def _local_date(iso_utc: str) -> date:
    return datetime.fromisoformat(iso_utc).astimezone(TZ).date()


def _safe_count(path: Path) -> int:
    try:
        return int(json.loads(path.read_text()).get("count", 0))
    except (json.JSONDecodeError, OSError):
        return 0


def _team_history(finished: list[dict]) -> dict[int, list[dict]]:
    """team_id -> lista de resultados (mais recente primeiro)."""
    hist: dict[int, list[dict]] = {}
    for g in finished:
        hs, as_ = g["home_score"], g["away_score"]
        if hs is None or as_ is None:
            continue
        for team, opp, gf, ga, is_home in (
            (g["home"], g["away"], hs, as_, True),
            (g["away"], g["home"], as_, hs, False),
        ):
            tid = team["id"]
            if tid is None:
                continue
            hist.setdefault(tid, []).append({
                "date": g["start_time"],
                "home": is_home,
                "gf": gf,
                "ga": ga,
                "result": "W" if gf > ga else ("D" if gf == ga else "L"),
                "opponent": opp["name"],
            })
    for lst in hist.values():
        lst.sort(key=lambda x: x["date"] or "", reverse=True)
    return hist


def _row_lookup(rows: list[dict]):
    by_id = {r["team_id"]: r for r in rows if r["team_id"] is not None}

    def find(team: dict) -> dict | None:
        r = by_id.get(team["id"])
        if r:
            return r
        best, best_s = None, 0.0
        for cand in rows:
            s = name_similarity(team["name"], cand["team_name"])
            if s > best_s:
                best, best_s = cand, s
        return best if best_s >= 0.8 else None

    return find


def _team_summary(team: dict, row: dict | None, recent: list[dict]) -> dict:
    return {
        "id": team["id"],
        "name": team["name"],
        "position": row["position"] if row else None,
        "played": row["played"] if row else None,
        "points": row["points"] if row else None,
        "record": (
            f'{row["won"]}V {row["drawn"]}E {row["lost"]}D' if row else None
        ),
        "last5": last5_string(recent),
        "recent": [
            {
                "result": m["result"],
                "score": f'{int(m["gf"])}-{int(m["ga"])}' if m["gf"] == int(m["gf"]) else f'{m["gf"]}-{m["ga"]}',
                "home": m["home"],
                "opponent": m["opponent"],
                "date": (m["date"] or "")[:10],
            }
            for m in recent[:5]
        ],
        "streaks": streaks(recent) if recent else {},
    }


def build(target: date, days: int, *, out_dir: Path, use_odds: bool, cache_dir: str) -> dict:
    leagues = enabled_leagues()
    league_by_s365 = {lg.s365_id: lg for lg in leagues}
    window_start = target - timedelta(days=S365["history_days"])
    window_end = target + timedelta(days=days)

    s365 = Scores365(cache_dir=cache_dir)
    odds_api = OddsApi(cache_dir=cache_dir)
    odds_on = use_odds and odds_api.enabled

    print(f"→ buscando jogos {window_start} … {window_end}")
    all_games = s365.games(window_start, window_end)
    our_games = [g for g in all_games if g["s365_competition_id"] in league_by_s365]

    finished = [g for g in our_games if status_ended(g)]
    history = _team_history(finished)

    target_dates = [target + timedelta(days=i) for i in range(days)]
    fixtures = [
        g for g in our_games
        if status_scheduled(g) and g["start_time"]
        and _local_date(g["start_time"]) in target_dates
    ]
    print(f"  {len(our_games)} jogos nas ligas cobertas · {len(fixtures)} partidas futuras")

    by_league: dict[int, list[dict]] = {}
    for g in fixtures:
        by_league.setdefault(g["s365_competition_id"], []).append(g)

    # p/ economizar créditos da odds-api, busca odds só das ligas com jogo no 1º dia
    odds_league_ids = {
        g["s365_competition_id"] for g in fixtures
        if not ODDS_CFG["only_primary_day"] or _local_date(g["start_time"]) == target
    }

    enriched: list[dict] = []
    for s365_id, games in by_league.items():
        lg = league_by_s365[s365_id]
        try:
            rows = s365.standings(s365_id)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! tabela indisponível p/ {lg.name}: {exc}")
            rows = []
        if not rows:
            print(f"  ! sem tabela p/ {lg.name} — pulando {len(games)} jogo(s)")
            continue
        mu = league_avg_goals(rows)
        find_row = _row_lookup(rows)

        odds_events: list[dict] = []
        if odds_on and lg.odds_key and s365_id in odds_league_ids:
            odds_events = odds_api.events(lg.odds_key)

        for g in games:
            try:
                hr = find_row(g["home"])
                ar = find_row(g["away"])
                if not hr or not ar:
                    print(f"  ! sem linha na tabela p/ {g['home']['name']} x {g['away']['name']}")
                    continue
                h_recent = merge_recent(history.get(g["home"]["id"], []), hr["recent"])
                a_recent = merge_recent(history.get(g["away"]["id"], []), ar["recent"])

                model = predict(hr, ar, mu)
                trends = (
                    team_trends(h_recent, side="HOME", team_name=g["home"]["name"])
                    + team_trends(a_recent, side="AWAY", team_name=g["away"]["name"])
                )
                gap = table_gap_trend(hr, ar)
                if gap:
                    trends.append(gap)
                trends = consolidate(trends)

                odds_match = find_match(g, odds_events) if odds_events else None
                item = evaluate(g, model, trends, odds_match)
                item["league"] = {"key": lg.key, "name": lg.name, "country": lg.country}
                item["home_team"] = _team_summary(g["home"], hr, h_recent)
                item["away_team"] = _team_summary(g["away"], ar, a_recent)
                item["kickoff_local"] = datetime.fromisoformat(g["start_time"]).astimezone(TZ).isoformat()
                item["has_odds"] = odds_match is not None
                enriched.append(item)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! erro em {g['home']['name']} x {g['away']['name']}: {exc}")
                traceback.print_exc()

    # ── escreve um arquivo por data ──────────────────────────────────────────
    out_dir.mkdir(parents=True, exist_ok=True)
    written_dates: list[str] = []
    floor = SCORING["min_confidence_listed"]
    for d in target_dates:
        day_games = [
            g for g in enriched
            if _local_date(g["start_time"]) == d and g["confidence"] >= floor
        ]
        day_games.sort(key=lambda g: (-g["confidence"], g["kickoff_local"]))
        payload = {
            "date": d.isoformat(),
            "generated_at": datetime.now(TZ).isoformat(),
            "version": __version__,
            "bankroll": BANKROLL,
            "count": len(day_games),
            "games": day_games,
        }
        (out_dir / f"{d.isoformat()}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1)
        )
        written_dates.append(d.isoformat())
        print(f"  ✓ {d.isoformat()}: {len(day_games)} jogo(s) listado(s)")

    # remove arquivos de dias sem jogo (alvos vazios e testes antigos),
    # mantendo sempre ao menos o primeiro dia alvo p/ o site não quebrar
    keep = written_dates[0]
    for p in list(out_dir.glob("20*.json")):
        if _safe_count(p) == 0 and p.stem != keep:
            p.unlink()

    # latest = primeiro dia alvo com jogo, senão o primeiro dia alvo
    remaining = sorted(p.stem for p in out_dir.glob("20*.json"))
    latest_date = next(
        (d for d in remaining if d >= keep and _safe_count(out_dir / f"{d}.json") > 0),
        keep,
    )
    (out_dir / "latest.json").write_text((out_dir / f"{latest_date}.json").read_text())

    # index de datas disponíveis (só as que têm ao menos 1 jogo)
    all_files = sorted(
        p.stem for p in out_dir.glob("20*.json")
        if _safe_count(p) > 0
    )
    (out_dir / "index.json").write_text(json.dumps({
        "dates": all_files,
        "generated_at": datetime.now(TZ).isoformat(),
        "odds_enabled": odds_on,
        "odds_credits_remaining": odds_api.credits_remaining if odds_on else None,
        "leagues": [{"name": lg.name, "country": lg.country} for lg in leagues],
    }, ensure_ascii=False, indent=1))

    return {"dates": written_dates, "games": len(enriched)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera as sugestões diárias.")
    parser.add_argument("--date", help="data inicial YYYY-MM-DD (padrão: hoje em SP)")
    parser.add_argument("--days", type=int, default=3, help="quantos dias à frente")
    parser.add_argument("--out", default="docs/data", help="pasta de saída")
    parser.add_argument("--cache-dir", default=".cache")
    parser.add_argument("--no-odds", action="store_true")
    args = parser.parse_args(argv)

    target = (
        date.fromisoformat(args.date) if args.date
        else datetime.now(TZ).date()
    )
    summary = build(
        target, max(1, args.days),
        out_dir=Path(args.out),
        use_odds=not args.no_odds,
        cache_dir=args.cache_dir,
    )
    print(f"\nPronto: {summary['games']} jogos processados, datas {summary['dates']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
