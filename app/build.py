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
from .config import CLEAR_EDGE, S365, enabled_leagues
from .model import league_avg_goals, predict
from .recommend import clear_edge, evaluate
from .results import compute_stats, grade_history
from .sources.odds_api import OddsApi, find_match
from .sources.scores365 import Scores365, status_ended, status_scheduled
from .trends import compute_trends, last5_string, merge_recent
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
        "goals_for": row["goals_for"] if row else None,
        "goals_against": row["goals_against"] if row else None,
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
    }


def select_day_picks(day: list[dict], prev_games: list[dict], ce: dict) -> tuple[list[dict], list[dict]]:
    """Escolhe os palpites do dia, travando quem já saiu de 'agendado' na rodada anterior.

    `day` = candidatos atualmente agendados (recém-computados, com `id`/`confidence`/`clear`).
    `prev_games` = o que já estava publicado nesse dia (pode estar vazio).
    Retorna (picks, locked) — `locked` é o subconjunto de `prev_games` preservado tal
    e qual (já foi a jogo ou terminou, então não pode mais trocar de palpite).
    """
    scheduled_ids = {g["id"] for g in day}
    locked = [g for g in prev_games if g.get("id") not in scheduled_ids]

    by_conf = sorted(day, key=lambda g: -g["confidence"])
    room = max(0, ce["max_per_day"] - len(locked))
    clear = [g for g in by_conf if g["clear"]][:room]
    picks = locked + clear
    if len(picks) < ce["min_per_day"]:
        have = {g["id"] for g in picks}
        for g in by_conf:
            if g["id"] in have:
                continue
            g["below_bar"] = True
            picks.append(g)
            have.add(g["id"])
            if len(picks) >= ce["min_per_day"]:
                break
    picks.sort(key=lambda g: (0 if g.get("clear") else 1, -g["confidence"], g.get("kickoff_local", "")))
    return picks, locked


def build(target: date, days: int, *, out_dir: Path, use_odds: bool, cache_dir: str) -> dict:
    leagues = enabled_leagues()
    league_by_s365 = {lg.s365_id: lg for lg in leagues}
    window_start = target - timedelta(days=S365["history_days"])
    window_end = target + timedelta(days=days)

    s365 = Scores365(cache_dir=cache_dir)
    odds_api = OddsApi(cache_dir=cache_dir)
    odds_api_on = use_odds and odds_api.enabled  # fallback opcional

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

    def enrich(g, lg, hr, ar, mu, all_rows) -> dict:
        """Monta o jogo SEM odds — odds só são buscadas depois, e só p/ quem vira palpite."""
        h_recent = merge_recent(history.get(g["home"]["id"], []), hr["recent"])
        a_recent = merge_recent(history.get(g["away"]["id"], []), ar["recent"])
        model = predict(hr, ar, mu)
        trends = compute_trends(h_recent, a_recent, hr, ar, all_rows,
                                g["home"]["name"], g["away"]["name"])
        item = evaluate(g, model, trends, None)
        item["league"] = {"key": lg.key, "name": lg.name, "country": lg.country}
        item["home_team"] = _team_summary(g["home"], hr, h_recent)
        item["away_team"] = _team_summary(g["away"], ar, a_recent)
        item["kickoff_local"] = datetime.fromisoformat(g["start_time"]).astimezone(TZ).isoformat()
        item["has_odds"] = False
        item["odds_bookmaker"] = None
        item["is_cup"] = lg.cup
        item["result"] = "pending"  # vira "hit"/"miss"/"void" depois que o jogo termina
        item["clear"] = clear_edge(
            item["pick"]["selection"], hr, ar, h_recent, a_recent,
            table_size=len(all_rows), is_cup=lg.cup,
        )
        item["_ctx"] = (g, model, trends, lg)
        return item

    _odds_cache: dict[int, list[dict]] = {}  # s365_competition_id -> eventos the-odds-api

    def attach_odds(item: dict) -> None:
        """Busca odds só agora, p/ um jogo já selecionado como palpite do dia."""
        g, model, trends, lg = item.pop("_ctx")
        odds = s365.game_odds(g["id"]) if use_odds else None
        if not odds and odds_api_on and lg.odds_key:
            events = _odds_cache.setdefault(lg.s365_id, odds_api.events(lg.odds_key))
            odds = find_match(g, events) if events else None
        fresh = evaluate(g, model, trends, odds)
        item["pick"] = fresh["pick"]
        item["alt_markets"] = fresh["alt_markets"]
        item["aligned_trends"] = fresh["aligned_trends"]
        item["confidence"] = fresh["confidence"]
        item["has_odds"] = odds is not None
        item["odds_bookmaker"] = (odds or {}).get("bookmaker")

    enriched: list[dict] = []
    team_index: dict[int, dict] = {}   # team_id -> {"row", "mu"} (só 1ª divisão c/ tabela)
    cup_ids = {sid for sid, lg in league_by_s365.items() if lg.cup}

    # 1) ligas com tabela
    for s365_id, games in by_league.items():
        lg = league_by_s365[s365_id]
        if lg.cup:
            continue
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
        for r in rows:
            if r["team_id"] is not None:
                team_index[r["team_id"]] = {"row": r, "mu": mu}

        for g in games:
            try:
                hr, ar = find_row(g["home"]), find_row(g["away"])
                if not hr or not ar:
                    print(f"  ! sem linha na tabela p/ {g['home']['name']} x {g['away']['name']}")
                    continue
                enriched.append(enrich(g, lg, hr, ar, mu, rows))
            except Exception as exc:  # noqa: BLE001
                print(f"  ! erro em {g['home']['name']} x {g['away']['name']}: {exc}")
                traceback.print_exc()

    # 2) copas — só jogos em que os DOIS times estão numa 1ª divisão coberta
    for s365_id in cup_ids & by_league.keys():
        lg = league_by_s365[s365_id]
        skipped = 0
        for g in by_league[s365_id]:
            hi = team_index.get(g["home"]["id"])
            ai = team_index.get(g["away"]["id"])
            if not hi or not ai:
                skipped += 1
                continue
            try:
                mu = (hi["mu"] + ai["mu"]) / 2
                enriched.append(enrich(g, lg, hi["row"], ai["row"], mu, []))
            except Exception as exc:  # noqa: BLE001
                print(f"  ! erro (copa) em {g['home']['name']} x {g['away']['name']}: {exc}")
        if skipped:
            print(f"  · {lg.name}: {skipped} jogo(s) fora (time de divisão inferior)")

    # jogos do dia (qualquer status) — só p/ o número informativo "de N jogos"
    day_total_all: dict[date, int] = {}
    for g in our_games:
        if g["start_time"]:
            dd = _local_date(g["start_time"])
            day_total_all[dd] = day_total_all.get(dd, 0) + 1

    # ── escreve um arquivo por data ──────────────────────────────────────────
    out_dir.mkdir(parents=True, exist_ok=True)
    written_dates: list[str] = []
    ce = CLEAR_EDGE
    for d in target_dates:
        day = [g for g in enriched if _local_date(g["start_time"]) == d]

        # jogos já publicados nesse dia que saíram da lista de "agendados" (foram
        # a jogo ou terminaram) ficam TRAVADOS — nunca somem nem trocam de palpite,
        # só recebem o placar/resultado depois (via grade_history)
        prev_games: list[dict] = []
        existing_path = out_dir / f"{d.isoformat()}.json"
        if existing_path.exists():
            try:
                prev_games = json.loads(existing_path.read_text()).get("games", [])
            except (json.JSONDecodeError, OSError):
                prev_games = []

        picks, locked = select_day_picks(day, prev_games, ce)
        for g in picks:
            if "_ctx" in g:  # só os recém-computados; os travados já têm tudo pronto
                attach_odds(g)

        clear_count = sum(1 for g in picks if g.get("clear"))
        payload = {
            "date": d.isoformat(),
            "generated_at": datetime.now(TZ).isoformat(),
            "version": __version__,
            "count": len(picks),
            "clear_count": clear_count,
            "day_total": day_total_all.get(d, len(day)),
            "games": picks,
        }
        (out_dir / f"{d.isoformat()}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1)
        )
        written_dates.append(d.isoformat())
        print(
            f"  ✓ {d.isoformat()}: {clear_count} clara(s) + {len(picks) - clear_count} de reserva "
            f"({len(locked)} já travado(s), {day_total_all.get(d, len(day))} jogos no dia)"
        )

    # confere o placar de quem já jogou (inclui os que já terminaram hoje) e
    # atualiza o histórico inteiro — feito depois de escrever, p/ não perder
    # a checagem de hoje quando o build re-escreve o arquivo do dia
    final_scores = {
        g["id"]: (g["home_score"], g["away_score"])
        for g in finished
        if g["home_score"] is not None and g["away_score"] is not None
    }
    grade_history(out_dir, TZ, final_scores)

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
    odds_count = sum(
        1 for p in out_dir.glob("20*.json")
        for g in json.loads(p.read_text()).get("games", []) if g.get("has_odds")
    )
    (out_dir / "index.json").write_text(json.dumps({
        "dates": all_files,
        "generated_at": datetime.now(TZ).isoformat(),
        "odds_enabled": use_odds,
        "odds_source": "365scores",
        "games_with_odds": odds_count,
        "leagues": [{"name": lg.name, "country": lg.country} for lg in leagues],
    }, ensure_ascii=False, indent=1))

    stats = compute_stats(out_dir, target)
    (out_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1))
    print(
        f"  stats: hoje {stats['today']['hits']}/{stats['today']['total']} · "
        f"semana {stats['week']['hits']}/{stats['week']['total']} · "
        f"total {stats['all_time']['hits']}/{stats['all_time']['total']}"
    )

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
