from app.trends import (
    HOME,
    AWAY,
    OVER,
    consolidate,
    last5_string,
    streaks,
    table_gap_trend,
    team_trends,
)


def mk(results, gf=1, ga=1):
    """results: string tipo 'WWDLL' (mais recente primeiro)."""
    out = []
    for i, r in enumerate(results):
        f, a = (2, 0) if r == "W" else (1, 1) if r == "D" else (0, 2)
        out.append({"result": r, "gf": f, "ga": a, "home": i % 2 == 0, "opponent": f"T{i}", "date": f"2026-08-{20 - i:02d}"})
    return out


def test_last5_and_streaks():
    recent = mk("WWWDL")
    assert last5_string(recent) == "WWWDL"
    s = streaks(recent)
    assert s["winning"] == 3
    assert s["unbeaten"] == 4
    assert s["losing"] == 0


def test_unbeaten_trend_favors_own_side():
    recent = mk("WWDWW")  # 5 invicto
    ts = team_trends(recent, side=HOME, team_name="Casa")
    kinds = {t["kind"]: t for t in ts}
    assert "unbeaten" in kinds
    assert kinds["unbeaten"]["favors"] == HOME
    assert kinds["unbeaten"]["strength"] > 0


def test_winless_trend_favors_opponent():
    recent = mk("LDLDL")  # não vence há 5
    ts = team_trends(recent, side=HOME, team_name="Casa")
    winless = next(t for t in ts if t["kind"] == "winless")
    assert winless["favors"] == AWAY


def test_over_trend_from_goals():
    recent = [
        {"result": "W", "gf": 3, "ga": 2, "home": True, "opponent": "x", "date": f"2026-08-2{i}"}
        for i in range(5)
    ]
    ts = team_trends(recent, side=AWAY, team_name="Fora")
    assert any(t["favors"] == OVER for t in ts)


def test_table_gap_trend():
    hr = {"team_name": "Líder", "position": 2}
    ar = {"team_name": "Lanterna", "position": 18}
    t = table_gap_trend(hr, ar)
    assert t and t["favors"] == HOME
    # gap pequeno → sem tendência
    assert table_gap_trend({"team_name": "A", "position": 5}, {"team_name": "B", "position": 7}) is None


def test_consolidate_dedupes_and_caps():
    dup = [{"label": "x", "team": "A", "strength": 0.5, "kind": "k", "favors": None}] * 4
    assert len(consolidate(dup)) == 1
    many = [
        {"label": f"l{i}", "team": "A", "strength": i / 10, "kind": "k", "favors": None}
        for i in range(10)
    ]
    assert len(consolidate(many, cap=3)) == 3
    assert consolidate(many, cap=3)[0]["label"] == "l9"  # ordenado por força
