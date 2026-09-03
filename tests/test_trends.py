from app.trends import (
    AWAY,
    HOME,
    OVER,
    UNDER,
    compute_trends,
    last5_string,
    merge_recent,
    table_context,
    _count_trends,
    _streak_trends,
)


def mk(results, gf=None, ga=None, home_pattern=None):
    """results: 'WWDLL' (mais recente primeiro)."""
    out = []
    for i, r in enumerate(results):
        f, a = (2, 0) if r == "W" else (1, 1) if r == "D" else (0, 2)
        if gf is not None:
            f, a = gf, ga
        out.append({
            "result": r, "gf": f, "ga": a,
            "home": (i % 2 == 0) if home_pattern is None else home_pattern[i],
            "opponent": f"T{i}", "date": f"2026-08-{25 - i:02d}",
        })
    return out


def test_last5_string():
    assert last5_string(mk("WWDLW")) == "WWDLW"


def test_count_trend_wins():
    ts = _count_trends(mk("WWWWWDL"), team="A", side=HOME, scope="", group="geral")
    labels = [t["label"] for t in ts]
    assert any("Venceu 5 dos últimos 7" in x for x in labels)
    assert all(t["team"] == "A" for t in ts)
    won = next(t for t in ts if "Venceu" in t["label"])
    assert won["favors"] == HOME


def test_count_trend_winless_favors_opponent():
    # 6 jogos sem vitória, todos empate → cai no ramo "não venceu nenhum"
    ts = _count_trends(mk("DDDDDD"), team="A", side=HOME, scope="", group="geral")
    wl = next(t for t in ts if "venceu" in t["label"].lower())
    assert wl["favors"] == AWAY
    assert "Não venceu nenhum dos últimos 6" in wl["label"]

    # 4 derrotas em 6 → ramo "perdeu N", favorece o adversário
    ts2 = _count_trends(mk("LDLLDL"), team="A", side=HOME, scope="", group="geral")
    assert any(t["favors"] == AWAY and "Perdeu 4 dos últimos 6" in t["label"] for t in ts2)
    assert not any("Invicto" in t["label"] for t in ts2)


def test_count_trend_clean_sheets_and_scope():
    games = [{"result": "W", "gf": 1, "ga": 0, "home": True, "opponent": "x", "date": f"2026-08-1{i}"} for i in range(6)]
    ts = _count_trends(games, team="Fort", side=HOME, scope=" em casa", group="casa_fora")
    cs = next(t for t in ts if "Não sofreu gol" in t["label"])
    assert cs["label"].endswith("em casa")
    assert cs["favors"] == UNDER


def test_count_trend_over_under():
    over_games = [{"result": "D", "gf": 2, "ga": 2, "home": True, "opponent": "x", "date": f"2026-08-1{i}"} for i in range(5)]
    ts = _count_trends(over_games, team="A", side=AWAY, scope="", group="geral")
    assert any(t["favors"] == OVER and "Mais de 2.5" in t["label"] for t in ts)


def test_streak_trends():
    ts = _streak_trends(mk("WWWWWW"), team="A", side=HOME)
    assert any("vitórias seguidas" in t["label"] for t in ts)
    ts2 = _streak_trends(mk("LDLDLD"), team="B", side=AWAY)
    assert any("Não vence há" in t["label"] and t["favors"] == HOME for t in ts2)


def test_table_context_shows_both_positions():
    hr = {"team_name": "Líder", "position": 1}
    ar = {"team_name": "Zebra", "position": 15}
    ctx = table_context(hr, ar)
    assert any("1º" in t["label"] and "15º" in t["label"] for t in ctx)
    gap = next(t for t in ctx if t["kind"] == "table_gap")
    assert gap["favors"] == HOME


def test_compute_trends_groups_by_team():
    hr = {"team_id": 1, "team_name": "Casa", "position": 3, "played": 12, "won": 8, "drawn": 2,
          "lost": 2, "goals_for": 20, "goals_against": 8, "points": 26}
    ar = {"team_id": 2, "team_name": "Fora", "position": 14, "played": 12, "won": 2, "drawn": 3,
          "lost": 7, "goals_for": 9, "goals_against": 21, "points": 9}
    h = mk("WWWWWWDD")
    a = mk("LLLLLDW")
    trends = compute_trends(h, a, hr, ar, [hr, ar], "Casa", "Fora")
    teams = {t["team"] for t in trends}
    assert "Casa" in teams and "Fora" in teams
    assert any(t["team"] is None for t in trends)  # confronto


def test_merge_recent_dedupes():
    a = [{"date": "2026-08-20", "opponent": "X", "result": "W", "gf": 1, "ga": 0, "home": True}]
    b = [{"date": "2026-08-20", "opponent": "x", "result": "W", "gf": 1, "ga": 0, "home": True},
         {"date": "2026-08-10", "opponent": "Y", "result": "L", "gf": 0, "ga": 2, "home": False}]
    assert len(merge_recent(a, b)) == 2
