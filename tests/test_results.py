import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.results import compute_stats, grade_history, grade_selection

TZ = ZoneInfo("America/Sao_Paulo")


def test_grade_selection():
    assert grade_selection("HOME", 2, 1) is True
    assert grade_selection("HOME", 1, 1) is False
    assert grade_selection("1X", 1, 1) is True
    assert grade_selection("X2", 0, 2) is True
    assert grade_selection("OVER25", 2, 1) is True
    assert grade_selection("UNDER25", 2, 1) is False
    assert grade_selection("BTTS_YES", 1, 0) is False
    assert grade_selection("BTTS_NO", 1, 0) is True
    assert grade_selection("UNKNOWN", 1, 0) is False


def _write_day(tmp_path, day, games):
    (tmp_path / f"{day}.json").write_text(json.dumps({"date": day, "games": games}))


def _game(gid, selection, ko_offset_days=0, result="pending"):
    ko = (datetime.now(TZ) - timedelta(days=ko_offset_days)).isoformat()
    return {
        "id": gid, "pick": {"selection": selection},
        "home_score": None, "away_score": None,
        "kickoff_local": ko, "result": result,
    }


def test_grade_history_marks_hit_and_miss(tmp_path):
    _write_day(tmp_path, "2026-09-03", [
        _game(1, "HOME"), _game(2, "AWAY"),
    ])
    grade_history(tmp_path, TZ, {1: (2, 0), 2: (2, 0)})
    d = json.loads((tmp_path / "2026-09-03.json").read_text())
    g1, g2 = d["games"]
    assert g1["result"] == "hit" and g1["home_score"] == 2
    assert g2["result"] == "miss"


def test_grade_history_voids_stale_pending(tmp_path):
    _write_day(tmp_path, "2026-09-01", [_game(9, "HOME", ko_offset_days=5)])
    grade_history(tmp_path, TZ, {})
    d = json.loads((tmp_path / "2026-09-01.json").read_text())
    assert d["games"][0]["result"] == "void"


def test_grade_history_never_regrades(tmp_path):
    _write_day(tmp_path, "2026-09-01", [_game(9, "HOME", result="hit")])
    grade_history(tmp_path, TZ, {9: (0, 5)})  # placar contrário — não devia mudar
    d = json.loads((tmp_path / "2026-09-01.json").read_text())
    assert d["games"][0]["result"] == "hit"
    assert d["games"][0]["home_score"] is None  # não reescreveu


def test_compute_stats_buckets(tmp_path):
    today = date(2026, 9, 10)
    _write_day(tmp_path, "2026-09-10", [_game(1, "HOME", result="hit")])
    _write_day(tmp_path, "2026-09-09", [_game(2, "HOME", result="miss")])
    _write_day(tmp_path, "2026-09-04", [_game(3, "HOME", result="hit")])  # dentro da semana
    _write_day(tmp_path, "2026-08-01", [_game(4, "HOME", result="hit")])  # só no total
    _write_day(tmp_path, "2026-09-10", [])  # não deveria conflitar (mesmo nome, sobrescrito)

    stats = compute_stats(tmp_path, today)
    assert stats["today"]["total"] == 0  # o segundo write sobrescreveu com lista vazia
    assert stats["all_time"]["hits"] == 2   # 09-09 é miss, 09-04 e 08-01 são hit
    assert stats["all_time"]["misses"] == 1
    assert stats["since"] == "2026-08-01"


def test_compute_stats_excludes_pending_and_void(tmp_path):
    today = date(2026, 9, 10)
    _write_day(tmp_path, "2026-09-10", [
        _game(1, "HOME", result="pending"),
        _game(2, "HOME", result="void"),
        _game(3, "HOME", result="hit"),
    ])
    stats = compute_stats(tmp_path, today)
    assert stats["today"]["total"] == 1
    assert stats["today"]["voids"] == 1
