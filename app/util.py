"""Utilidades: normalização de nomes, casamento de times e Poisson."""
from __future__ import annotations

import math
import re
import unicodedata
from difflib import SequenceMatcher

# tokens genéricos que atrapalham o casamento de nomes de clubes
_NOISE = {
    "fc", "cf", "sc", "ec", "afc", "ac", "as", "ss", "us", "cd", "ca", "sd",
    "club", "calcio", "clube", "aa", "fk", "if", "sk", "bk", "de", "do", "da",
    "the", "1", "04", "05", "09", "1846", "1899", "1900", "1904", "1909",
}


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def norm_name(name: str) -> str:
    """Forma canônica p/ comparar nomes de times de provedores diferentes."""
    s = strip_accents(name or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    tokens = [t for t in s.split() if t and t not in _NOISE]
    return " ".join(tokens) or s.strip()


def name_similarity(a: str, b: str) -> float:
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    if ta and (ta <= tb or tb <= ta):
        return 0.92
    jaccard = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    return max(jaccard, ratio)


def match_teams(home: str, away: str, cand_home: str, cand_away: str) -> float:
    """Similaridade média do par (mesma ordem casa/fora)."""
    return (name_similarity(home, cand_home) + name_similarity(away, cand_away)) / 2


# ── Poisson ───────────────────────────────────────────────────────────────────
def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam**k / math.factorial(k)


def score_matrix(lam_home: float, lam_away: float, max_goals: int = 8) -> list[list[float]]:
    """Matriz P(placar) assumindo independência entre os dois ataques."""
    ph = [poisson_pmf(i, lam_home) for i in range(max_goals + 1)]
    pa = [poisson_pmf(j, lam_away) for j in range(max_goals + 1)]
    # normaliza a cauda perdida
    sh, sa = sum(ph), sum(pa)
    ph = [x / sh for x in ph]
    pa = [x / sa for x in pa]
    return [[ph[i] * pa[j] for j in range(max_goals + 1)] for i in range(max_goals + 1)]


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))
