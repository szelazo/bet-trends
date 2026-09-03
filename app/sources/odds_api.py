"""Cliente da the-odds-api.com.

Chave via variável de ambiente ODDS_API_KEY. Sem chave → devolve vazio (modo "sem odds").
Free tier: 500 requisições/mês. Fazemos 1 requisição por liga que tem jogo no dia.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from ..config import ODDS
from ..util import match_teams
from ._http import HttpClient


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


class OddsApi:
    def __init__(self, cache_dir: str | None = ".cache") -> None:
        self.api_key = os.environ.get("ODDS_API_KEY", "").strip()
        self.http = HttpClient(cache_dir=cache_dir, cache_ttl_s=ODDS["cache_ttl_s"], gap_s=0.2)
        self._base = ODDS["base_url"]
        self.last_credits: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def credits_remaining(self) -> str | None:
        return self.http.last_headers.get("x-requests-remaining")

    def events(self, sport_key: str) -> list[dict]:
        """Odds agregadas (mediana das casas) por evento de uma liga."""
        if not self.enabled:
            return []
        params = {
            "apiKey": self.api_key,
            "regions": ODDS["regions"],
            "markets": ODDS["markets"],
            "oddsFormat": ODDS["odds_format"],
        }
        try:
            data = self.http.get_json(
                f"{self._base}/sports/{sport_key}/odds/", params, host_key="odds"
            )
        except RuntimeError:
            return []
        return [self._agg_event(ev) for ev in data if isinstance(ev, dict)]

    @staticmethod
    def _agg_event(ev: dict) -> dict:
        """Consolida as casas: mediana das odds por seleção/mercado."""
        home, away = ev.get("home_team", ""), ev.get("away_team", "")
        buckets: dict[tuple[str, str], list[float]] = {}
        totals_points: dict[float, dict[str, list[float]]] = {}
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                key = mk.get("key")
                for oc in mk.get("outcomes", []):
                    price = oc.get("price")
                    if not price:
                        continue
                    if key == "totals":
                        pt = oc.get("point")
                        if pt is None:
                            continue
                        totals_points.setdefault(float(pt), {}).setdefault(
                            oc.get("name", ""), []
                        ).append(price)
                    else:
                        buckets.setdefault((key, oc.get("name", "")), []).append(price)

        def med(xs: list[float]) -> float | None:
            if not xs:
                return None
            xs = sorted(xs)
            n = len(xs)
            return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2

        h2h = {name: med(v) for (k, name), v in buckets.items() if k == "h2h"}
        btts = {name: med(v) for (k, name), v in buckets.items() if k == "btts"}
        totals = {}
        if 2.5 in totals_points:
            totals = {name: med(v) for name, v in totals_points[2.5].items()}
        elif totals_points:
            nearest = min(totals_points, key=lambda p: abs(p - 2.5))
            totals = {name: med(v) for name, v in totals_points[nearest].items()}
            totals["_point"] = nearest

        return {
            "home_team": home,
            "away_team": away,
            "commence_time": ev.get("commence_time"),
            "h2h": h2h,          # {home_team: odd, away_team: odd, "Draw": odd}
            "totals": totals,    # {"Over": odd, "Under": odd, "_point": 2.5}
            "btts": btts,        # {"Yes": odd, "No": odd}
        }


def find_match(game: dict, odds_events: list[dict]) -> dict | None:
    """Casa um jogo do 365scores com um evento da odds-api por nome + horário."""
    if not odds_events:
        return None
    g_start = _parse_dt(game["start_time"]) if game.get("start_time") else None
    best, best_score = None, 0.0
    for ev in odds_events:
        score = match_teams(
            game["home"]["name"], game["away"]["name"],
            ev["home_team"], ev["away_team"],
        )
        if g_start and ev.get("commence_time"):
            delta_h = abs((_parse_dt(ev["commence_time"]) - g_start).total_seconds()) / 3600
            if delta_h > ODDS["match_window_h"]:
                continue
        if score > best_score:
            best, best_score = ev, score
    return best if best_score >= ODDS["match_ratio"] else None
