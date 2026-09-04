"""Confere o placar dos jogos já feitos e mantém as estatísticas de acerto.

Cada jogo escrito em docs/data/<data>.json nasce com `result: "pending"`. A cada
build, `grade_history` procura o placar final de quem já tem `id` conhecido e
marca `"hit"` / `"miss"`; quem passa muito tempo sem placar (adiado/cancelado)
vira `"void"` e sai das contas. `compute_stats` soma tudo em hoje/3 dias/semana/total.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

VOID_AFTER_DAYS = 2  # sem placar depois disso → assume adiado/cancelado

_HIT = {
    "HOME": lambda h, a: h > a,
    "AWAY": lambda h, a: a > h,
    "1X": lambda h, a: h >= a,
    "X2": lambda h, a: a >= h,
    "OVER25": lambda h, a: h + a >= 3,
    "UNDER25": lambda h, a: h + a <= 2,
    "BTTS_YES": lambda h, a: h >= 1 and a >= 1,
    "BTTS_NO": lambda h, a: h == 0 or a == 0,
}


def grade_selection(selection: str, hs: float, as_: float) -> bool:
    fn = _HIT.get(selection)
    return bool(fn and fn(hs, as_))


def grade_history(
    out_dir: Path, tz: ZoneInfo, final_scores: dict[int, tuple[float, float]],
) -> None:
    """Atualiza in-loco os arquivos de dia com placar/resultado de quem já acabou."""
    now = datetime.now(tz)
    for path in sorted(out_dir.glob("20*.json")):
        try:
            payload = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        changed = False
        for g in payload.get("games") or []:
            if g.get("result") in ("hit", "miss", "void"):
                continue
            gid = g.get("id")
            if gid in final_scores:
                hs, as_ = final_scores[gid]
                g["home_score"], g["away_score"] = hs, as_
                g["result"] = "hit" if grade_selection(g["pick"]["selection"], hs, as_) else "miss"
                changed = True
            else:
                kdt = _parse_dt(g.get("kickoff_local"))
                if kdt and (now - kdt) > timedelta(days=VOID_AFTER_DAYS):
                    g["result"] = "void"
                    changed = True
        if changed:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))


def _parse_dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def compute_stats(out_dir: Path, target: date) -> dict:
    """Agrega hit/miss/void em hoje, últimos 3 dias, semana e total histórico."""
    windows = {"today": 0, "last3": 2, "week": 6, "all_time": None}
    counts = {k: {"hits": 0, "misses": 0, "voids": 0, "total": 0} for k in windows}
    earliest: date | None = None

    for path in sorted(out_dir.glob("20*.json")):
        try:
            d = date.fromisoformat(path.stem)
        except ValueError:
            continue
        try:
            payload = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        age = (target - d).days
        if age < 0:
            continue
        for g in payload.get("games") or []:
            result = g.get("result", "pending")
            if result not in ("hit", "miss", "void"):
                continue
            earliest = d if earliest is None or d < earliest else earliest
            for name, max_age in windows.items():
                if max_age is not None and age > max_age:
                    continue
                bucket = counts[name]
                if result == "void":
                    bucket["voids"] += 1
                else:
                    bucket[f"{result}es" if result == "miss" else f"{result}s"] += 1
                    bucket["total"] += 1

    return {
        "generated_for": target.isoformat(),
        "since": earliest.isoformat() if earliest else None,
        **counts,
    }
