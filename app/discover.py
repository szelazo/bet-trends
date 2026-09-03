"""Descobre competitionIds do 365scores p/ adicionar novas ligas ao config.

Uso:
    python -m app.discover "brasileirão"
    python -m app.discover               # lista tudo que tem jogo nos próximos 10 dias
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

from .util import norm_name
from .sources.scores365 import Scores365


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    query = norm_name(argv[0]) if argv else ""

    s365 = Scores365(cache_dir=".cache")
    today = date.today()
    games = s365.games(today - timedelta(days=3), today + timedelta(days=10))

    seen: dict[int, str] = {}
    for g in games:
        cid = g["s365_competition_id"]
        if cid and cid not in seen:
            seen[cid] = g["competition_name"]

    rows = sorted(seen.items(), key=lambda kv: kv[1].lower())
    for cid, name in rows:
        if not query or query in norm_name(name):
            print(f"{cid:>7}  {name}")
    print(f"\n{len(rows)} competições com jogos na janela.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
