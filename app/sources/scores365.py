"""Cliente do 365scores (API web pública, sem chave).

Endpoints usados (verificados 09/2026):
  - web/games/allscores/  → jogos (passados e futuros) numa janela de datas.
      OBS: o parâmetro `competitions` é ignorado pelo servidor; filtramos no cliente.
      Janelas > ~20 dias retornam 504, então quebramos em pedaços.
  - web/standings/        → tabela + detailedRecentForm (últimos 5 jogos com placar).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from ..config import S365
from ._http import HttpClient

_ENDED = 4
_SCHEDULED = 2


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _num(x: Any) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _norm_competitor(c: dict) -> dict:
    return {"id": c.get("id"), "name": c.get("name", "").strip()}


def _norm_game(g: dict) -> dict:
    h, a = g.get("homeCompetitor", {}), g.get("awayCompetitor", {})
    return {
        "id": g.get("id"),
        "s365_competition_id": g.get("competitionId"),
        "competition_name": g.get("competitionDisplayName", ""),
        "start_time": _parse_dt(g["startTime"]).isoformat() if g.get("startTime") else None,
        "status_group": g.get("statusGroup"),
        "round": g.get("roundName") or g.get("stageName") or "",
        "home": _norm_competitor(h),
        "away": _norm_competitor(a),
        "home_score": _num(h.get("score")),
        "away_score": _num(a.get("score")),
    }


class Scores365:
    def __init__(self, cache_dir: str | None = ".cache") -> None:
        self.http = HttpClient(
            cache_dir=cache_dir,
            cache_ttl_s=S365["cache_ttl_s"],
            gap_s=S365["request_gap_s"],
        )
        self._base = S365["base_url"]
        self._common = {
            "appTypeId": S365["app_type_id"],
            "langId": S365["lang_id"],
            "timezoneName": S365["timezone_name"],
            "userCountryId": S365["user_country_id"],
        }

    # ── jogos ────────────────────────────────────────────────────────────────
    def games(self, start: date, end: date, *, chunk_days: int = 0) -> list[dict]:
        """Todos os jogos (qualquer liga) entre `start` e `end`, deduplicados.

        O endpoint tem um teto de ~850 jogos por resposta e, quando a janela
        pedida tem mais que isso no total, ele TRUNCA silenciosamente — sem erro,
        sem aviso — priorizando os dias mais próximos de "agora". Pedir um dia por
        vez (chunk_days=0 → janela [cur, cur]) evita cair nesse teto mesmo em dias
        cheios (~850 jogos globais num dia de meio de semana movimentado).
        """
        seen: dict[int, dict] = {}
        cur = start
        while cur <= end:
            stop = min(cur + timedelta(days=chunk_days), end)
            for g in self._allscores(cur, stop):
                gid = g.get("id")
                if gid is not None:
                    seen[gid] = g
            cur = stop + timedelta(days=1)
        return list(seen.values())

    def _allscores(self, start: date, end: date) -> list[dict]:
        params = {
            **self._common,
            "sports": 1,
            "startDate": start.strftime("%d/%m/%Y"),
            "endDate": end.strftime("%d/%m/%Y"),
        }
        data = self.http.get_json(
            f"{self._base}/web/games/allscores/", params, host_key="s365"
        )
        return [_norm_game(g) for g in data.get("games", [])]

    # ── odds ─────────────────────────────────────────────────────────────────
    def game_odds(self, game_id: int) -> dict | None:
        """Odds do jogo (sem chave). Só existem perto do jogo / ligas grandes.

        Retorna {"h2h": {"1","X","2"}, "totals": {"Over","Under","line"},
                 "btts": {"Yes","No"}, "bookmaker": str, "source": "365scores"}
        """
        params = {**self._common, "gameId": game_id}
        try:
            data = self.http.get_json(f"{self._base}/web/game/", params, host_key="s365")
        except RuntimeError:
            return None
        game = data.get("game") or {}
        lines = list(game.get("bestOdds") or [])
        pp = (game.get("promotedPredictions") or {}).get("predictions") or []
        lines += [p["odds"] for p in pp if isinstance(p.get("odds"), dict)]
        if not lines:
            return None

        h2h: dict[str, list[float]] = {}
        totals: dict[str, list[float]] = {}
        totals_line: float | None = None
        btts: dict[str, list[float]] = {}
        books: set[str] = set()

        for ln in lines:
            lt = ln.get("lineType") or {}
            name = (lt.get("name") or "").lower()
            short = (lt.get("shortName") or "").lower()
            bk = (ln.get("bookmaker") or {}).get("name")
            for opt in ln.get("options") or []:
                dec = (opt.get("rate") or {}).get("decimal")
                if not dec:
                    continue
                onm = (opt.get("name") or "").strip()
                if short == "1x2" or "full time result" in name:
                    key = {"1": "1", "x": "X", "2": "2", "home": "1", "draw": "X", "away": "2"}.get(onm.lower())
                    if key:
                        h2h.setdefault(key, []).append(dec)
                        if bk:
                            books.add(bk)
                elif "total goals" in name or short == "o/u":
                    if onm.lower() in ("over", "under"):
                        totals.setdefault(onm.capitalize(), []).append(dec)
                        if opt.get("line") is not None:
                            totals_line = float(opt["line"])
                elif "both teams to score" in name or "btts" in short:
                    key = {"yes": "Yes", "no": "No"}.get(onm.lower())
                    if key:
                        btts.setdefault(key, []).append(dec)

        def med(xs: list[float]) -> float | None:
            if not xs:
                return None
            xs = sorted(xs)
            n = len(xs)
            return round(xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2, 2)

        h2h_m = {k: med(v) for k, v in h2h.items() if med(v)}
        if len(h2h_m) < 3:
            return None
        out: dict = {"h2h": h2h_m, "source": "365scores"}
        if books:
            out["bookmaker"] = f"{len(books)} casas" if len(books) > 1 else next(iter(books))
        tot_m = {k: med(v) for k, v in totals.items() if med(v)}
        if tot_m.get("Over") and tot_m.get("Under"):
            out["totals"] = {**tot_m, "line": totals_line or 2.5}
        btts_m = {k: med(v) for k, v in btts.items() if med(v)}
        if btts_m.get("Yes") and btts_m.get("No"):
            out["btts"] = btts_m
        return out

    # ── tabela ───────────────────────────────────────────────────────────────
    def _standings_raw(self, comp_id: int, season_num: int | None) -> dict:
        params = {**self._common, "competitions": comp_id, "live": "false"}
        if season_num is not None:
            params["seasonNum"] = season_num
        return self.http.get_json(
            f"{self._base}/web/standings/", params, host_key="s365"
        )

    def standings(self, s365_competition_id: int) -> list[dict]:
        data = self._standings_raw(s365_competition_id, None)
        rows: list[dict] = []
        season: int | None = None
        for group in data.get("standings", []):
            season = season or group.get("seasonNum")
            for r in group.get("rows", []):
                rows.append(self._norm_row(r, s365_competition_id))

        prev = self._prev_season_aggregate(s365_competition_id, season)
        for row in rows:
            row["prev"] = prev.get(row["team_id"])
        return rows

    def _prev_season_aggregate(self, comp_id: int, season: int | None) -> dict[int, dict]:
        """Médias da temporada anterior por time (p/ reforçar amostras curtas)."""
        if not season:
            return {}
        try:
            data = self._standings_raw(comp_id, season - 1)
        except RuntimeError:
            return {}
        out: dict[int, dict] = {}
        for group in data.get("standings", []):
            for r in group.get("rows", []):
                c = r.get("competitor", {})
                gp = r.get("gamePlayed") or 0
                if gp >= 5 and c.get("id"):
                    out[c["id"]] = {
                        "gf_pg": (r.get("for") or 0) / gp,
                        "ga_pg": (r.get("against") or 0) / gp,
                        "played": gp,
                    }
        return out

    @staticmethod
    def _norm_row(r: dict, comp_id: int) -> dict:
        comp = r.get("competitor", {})
        played = r.get("gamePlayed") or 0
        return {
            "team_id": comp.get("id"),
            "team_name": comp.get("name", "").strip(),
            "s365_competition_id": comp_id,
            "position": r.get("position"),
            "played": played,
            "won": r.get("gamesWon") or 0,
            "drawn": r.get("gamesEven") or 0,
            "lost": r.get("gamesLost") or 0,
            "goals_for": r.get("for") or 0,
            "goals_against": r.get("against") or 0,
            "points": r.get("points") or 0,
            "recent": Scores365._recent_from_detailed(
                r.get("detailedRecentForm") or [], comp.get("id")
            ),
        }

    @staticmethod
    def _recent_from_detailed(matches: Iterable[dict], team_id: Any) -> list[dict]:
        """Converte detailedRecentForm em resultados do ponto de vista do time.

        Retorna do mais recente p/ o mais antigo:
          {date, home (bool), gf, ga, result ('W'/'D'/'L'), opponent}
        """
        out: list[dict] = []
        for m in matches:
            if m.get("statusGroup") != _ENDED:
                continue
            h, a = m.get("homeCompetitor", {}), m.get("awayCompetitor", {})
            hs, as_ = _num(h.get("score")), _num(a.get("score"))
            if hs is None or as_ is None:
                continue
            is_home = h.get("id") == team_id
            gf, ga = (hs, as_) if is_home else (as_, hs)
            result = "W" if gf > ga else ("D" if gf == ga else "L")
            out.append(
                {
                    "date": _parse_dt(m["startTime"]).isoformat() if m.get("startTime") else None,
                    "home": is_home,
                    "gf": gf,
                    "ga": ga,
                    "result": result,
                    "opponent": (a if is_home else h).get("name", ""),
                }
            )
        out.sort(key=lambda x: x["date"] or "", reverse=True)
        return out


def status_scheduled(g: dict) -> bool:
    return g.get("status_group") == _SCHEDULED


def status_ended(g: dict) -> bool:
    return g.get("status_group") == _ENDED
