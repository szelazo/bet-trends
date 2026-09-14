"""Recalibração automática do critério de escolha — sem IA no loop.

Chamado a cada build, mas só AGE a cada `AUTOTUNE["interval_days"]` (padrão 14 dias).
Duas regras, cada uma com amostra mínima antes de mexer em qualquer coisa:

  1. Liga com acerto ruim (amostra mínima) → entra na lista de desativadas.
  2. Acerto geral abaixo do esperado (amostra mínima) → aperta fav_form_ppg e
     min_table_gap um passo (com teto).

Nunca afrouxa sozinho, nunca edita app/config.py — tudo fica em docs/data/autotune.json,
que dá pra inspecionar, editar ou apagar na mão (apagar = volta ao padrão do config.py).
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from .config import AUTOTUNE, CLEAR_EDGE

STATE_FILE = "autotune.json"


def _default_state() -> dict:
    return {
        "last_run": None,
        "disabled_leagues": {},      # key -> {"since", "reason", "hits", "total"}
        "clear_edge_overrides": {},  # ex.: {"fav_form_ppg": 1.6, "min_table_gap": 6}
        "log": [],
    }


def load_state(out_dir: Path) -> dict:
    p = out_dir / STATE_FILE
    if not p.exists():
        return _default_state()
    try:
        saved = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return _default_state()
    return {**_default_state(), **saved}


def save_state(out_dir: Path, state: dict) -> None:
    (out_dir / STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=1))


def effective_clear_edge(state: dict) -> dict:
    return {**CLEAR_EDGE, **state.get("clear_edge_overrides", {})}


def disabled_league_keys(state: dict) -> set[str]:
    return set(state.get("disabled_leagues", {}))


def _due(state: dict, today: date) -> bool:
    last = state.get("last_run")
    if not last:
        return True
    try:
        return (today - date.fromisoformat(last)).days >= AUTOTUNE["interval_days"]
    except ValueError:
        return True


def _collect_performance(out_dir: Path) -> tuple[dict[str, list[bool]], list[bool]]:
    """Resultados (True=acerto) por liga e no total — só palpites 'claros', sem filler."""
    by_league: dict[str, list[bool]] = defaultdict(list)
    for path in sorted(out_dir.glob("20*.json")):
        try:
            payload = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for g in payload.get("games") or []:
            if g.get("below_bar") or not g.get("clear"):
                continue
            result = g.get("result")
            if result not in ("hit", "miss"):
                continue
            key = (g.get("league") or {}).get("key")
            if key:
                by_league[key].append(result == "hit")
    everyone = [v for vs in by_league.values() for v in vs]
    return by_league, everyone


def maybe_run(out_dir: Path, today: date) -> dict:
    """Reavalia e ajusta o estado se já passou `interval_days` desde a última vez."""
    state = load_state(out_dir)
    if not AUTOTUNE["enabled"] or not _due(state, today):
        return state

    by_league, everyone = _collect_performance(out_dir)
    c = AUTOTUNE
    changes: list[str] = []

    for key, results in by_league.items():
        if key in state["disabled_leagues"]:
            continue
        n = len(results)
        if n < c["min_league_samples"]:
            continue
        rate = sum(results) / n
        if rate < c["league_disable_hitrate"]:
            reason = f"acerto {sum(results)}/{n} ({rate:.0%}) abaixo de {c['league_disable_hitrate']:.0%}"
            state["disabled_leagues"][key] = {
                "since": today.isoformat(), "hits": sum(results), "total": n, "reason": reason,
            }
            changes.append(f"liga '{key}' desativada — {reason}")

    n = len(everyone)
    if n >= c["min_global_samples"]:
        rate = sum(everyone) / n
        if rate < c["global_tighten_hitrate"]:
            ov = state["clear_edge_overrides"]
            cur_ppg = ov.get("fav_form_ppg", CLEAR_EDGE["fav_form_ppg"])
            cur_gap = ov.get("min_table_gap", CLEAR_EDGE["min_table_gap"])
            new_ppg = min(c["form_ppg_cap"], round(cur_ppg + c["form_ppg_step"], 2))
            new_gap = min(c["table_gap_cap"], cur_gap + c["table_gap_step"])
            if new_ppg != cur_ppg or new_gap != cur_gap:
                ov["fav_form_ppg"], ov["min_table_gap"] = new_ppg, new_gap
                changes.append(
                    f"acerto geral {sum(everyone)}/{n} ({rate:.0%}) abaixo de "
                    f"{c['global_tighten_hitrate']:.0%} — critério apertado "
                    f"(fav_form_ppg→{new_ppg}, min_table_gap→{new_gap})"
                )

    state["last_run"] = today.isoformat()
    state["log"].append({
        "date": today.isoformat(),
        "changes": changes or ["nada a ajustar — dentro do esperado"],
    })
    state["log"] = state["log"][-20:]

    save_state(out_dir, state)
    return state
