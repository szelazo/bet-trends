"""Configuração central: ligas cobertas e parâmetros do modelo.

Para adicionar uma liga:
  1. rode  `python -m app.discover "nome da liga"`  para achar o competitionId do 365scores;
  2. acrescente uma entrada em LEAGUES abaixo (odds_key pode ficar None);
  3. o sport_key da the-odds-api sai de  https://the-odds-api.com/sports-odds-data/sports-apis.html
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class League:
    key: str            # identificador curto interno
    name: str           # nome exibido
    country: str        # país / âmbito
    s365_id: int        # competitionId no 365scores
    odds_key: str | None  # sport_key na the-odds-api (None = sem odds)
    enabled: bool = True


# ── Ligas cobertas ────────────────────────────────────────────────────────────
# IDs do 365scores verificados em 09/2026. Ajuste/expanda à vontade.
LEAGUES: list[League] = [
    # ── América ──────────────────────────────────────────────────────────────
    League("br_serie_a", "Brasileirão Série A", "Brasil", 113, "soccer_brazil_campeonato"),
    League("br_serie_b", "Brasileirão Série B", "Brasil", 116, "soccer_brazil_serie_b", enabled=False),
    League("ar_primera", "Liga Profesional", "Argentina", 72, "soccer_argentina_primera_division"),
    League("mx_ligamx", "Liga MX", "México", 141, "soccer_mexico_ligamx"),
    League("co_primera", "Liga BetPlay", "Colômbia", 620, None),
    League("ec_ligapro", "Liga Pro", "Equador", 5062, None),
    League("uy_primera", "Primera División", "Uruguai", 617, None),
    League("py_primera", "Copa de Primera", "Paraguai", 621, None),
    League("mls", "MLS", "EUA/Canadá", 104, "soccer_usa_mls"),
    # ── Inglaterra / Espanha / Itália / Alemanha / França ────────────────────
    League("epl", "Premier League", "Inglaterra", 7, "soccer_epl"),
    League("championship", "Championship", "Inglaterra", 1, "soccer_efl_champ"),
    League("laliga", "LaLiga", "Espanha", 11, "soccer_spain_la_liga"),
    League("laliga2", "LaLiga 2", "Espanha", 12, "soccer_spain_segunda_division"),
    League("serie_a_ita", "Serie A", "Itália", 17, "soccer_italy_serie_a"),
    League("serie_b_ita", "Serie B", "Itália", 18, "soccer_italy_serie_b"),
    League("bundesliga", "Bundesliga", "Alemanha", 25, "soccer_germany_bundesliga"),
    League("bundesliga2", "2. Bundesliga", "Alemanha", 26, "soccer_germany_bundesliga2"),
    League("ligue1", "Ligue 1", "França", 35, "soccer_france_ligue_one"),
    League("ligue2", "Ligue 2", "França", 36, "soccer_france_ligue_two"),
    # ── Resto da Europa ─────────────────────────────────────────────────────
    League("liga_pt", "Liga Portugal", "Portugal", 73, "soccer_portugal_primeira_liga"),
    League("eredivisie", "Eredivisie", "Holanda", 57, "soccer_netherlands_eredivisie"),
    League("belgium", "Jupiler Pro League", "Bélgica", 98, "soccer_belgium_first_div"),
    League("turkey", "Süper Lig", "Turquia", 78, "soccer_turkey_super_league"),
    League("turkey2", "1. Lig", "Turquia", 81, None),
    League("scotland", "Scottish Premiership", "Escócia", 61, "soccer_spl"),
    League("denmark", "Superliga", "Dinamarca", 119, "soccer_denmark_superliga"),
    League("swiss", "Super League", "Suíça", 95, "soccer_switzerland_superleague"),
    # ── Ásia / África ──────────────────────────────────────────────────────
    League("saudi", "Saudi Pro League", "Arábia Saudita", 649, None),
    League("qatar", "Qatar Stars League", "Catar", 408, None),
    League("uae", "UAE Pro League", "Emirados Árabes", 549, None),
    League("south_africa", "Premier League", "África do Sul", 414, None),
    League("egypt", "Premier League", "Egito", 552, None),
    # ── Continentais ───────────────────────────────────────────────────────
    League("libertadores", "CONMEBOL Libertadores", "América do Sul", 102, "soccer_conmebol_copa_libertadores"),
    League("sudamericana", "CONMEBOL Sul-Americana", "América do Sul", 389, "soccer_conmebol_copa_sudamericana"),
    League("ucl", "UEFA Champions League", "Europa", 572, "soccer_uefa_champs_league"),
    League("uel", "UEFA Europa League", "Europa", 573, "soccer_uefa_europa_league"),
    League("uecl", "UEFA Conference League", "Europa", 7685, "soccer_uefa_europa_conference_league"),
    League("caf_cl", "CAF Champions League", "África", 624, None),
]

LEAGUES_BY_S365 = {lg.s365_id: lg for lg in LEAGUES}


def enabled_leagues() -> list[League]:
    return [lg for lg in LEAGUES if lg.enabled]


# ── 365scores ─────────────────────────────────────────────────────────────────
S365 = {
    "base_url": "https://webws.365scores.com",
    "app_type_id": 5,
    "lang_id": 1,              # 1 = inglês (nomes estáveis). 29 ≈ pt-BR.
    "timezone_name": "America/Sao_Paulo",
    "user_country_id": 21,     # Brasil
    "history_days": 18,        # janela passada p/ montar histórico (máx ~20 antes de 504)
    "request_gap_s": 0.35,     # pausa entre requisições
    "cache_ttl_s": 1800,
}

# ── the-odds-api ──────────────────────────────────────────────────────────────
# Custo do free tier: 1 crédito por região POR mercado. 500/mês.
# Com ~26 ligas c/ odds, "eu" + "h2h" gasta ~1 crédito/liga/dia ≈ 300-400/mês.
# Adicionar região ou mercado (totals, btts) multiplica o gasto — cuidado.
ODDS = {
    "base_url": "https://api.the-odds-api.com/v4",
    "regions": "eu",
    "markets": "h2h",
    "odds_format": "decimal",
    "cache_ttl_s": 1800,
    "only_primary_day": True,  # busca odds só p/ jogos do 1º dia (economiza créditos)
    "match_ratio": 0.55,       # similaridade mínima de nome p/ casar jogo
    "match_window_h": 30,      # diferença máx. de horário entre os dois provedores
}

# ── Modelo (Poisson força-de-time) ────────────────────────────────────────────
MODEL = {
    "home_advantage": 1.28,   # multiplicador de gols esperados do mandante
    "w_season": 0.60,         # peso da temporada vs. últimos jogos
    "w_recent": 0.40,
    "reg_games": 5.0,         # regularização: jogos "fantasma" na média da liga
    "max_goals": 8,           # teto da matriz de placares
    "default_league_avg": 1.35,  # gols/time/jogo quando não dá p/ calcular
    "prev_blend_until": 10,   # nº de jogos da temporada atual a partir do qual ignora a anterior
    "prev_blend_weight": 0.5,  # peso máx. da temporada anterior (quando 0 jogos jogados)
    "rating_exp": 0.82,            # <1 comprime forças extremas (evita xG irreal)
    "rating_clamp": (0.7, 1.5),    # limites p/ ataque/defesa relativos
    "lambda_clamp": (0.25, 2.9),   # limites p/ gols esperados de cada lado
}

# ── Score de confiança e valor ────────────────────────────────────────────────
SCORING = {
    # probabilidade mínima do modelo p/ um mercado ser recomendável
    "prob_floor": {
        "1x2": 0.46,
        "double_chance": 0.62,
        "over_under": 0.58,
        "btts": 0.58,
    },
    "w_prob": 0.65,           # peso da prob. do modelo na confiança
    "w_trend": 0.35,          # peso da concordância das tendências
    "sample_full_games": 5,   # nº de jogos p/ confiança "cheia" (abaixo disso, penaliza)
    "value_threshold": 0.05,  # EV mínimo p/ marcar "VALOR"
    "kelly_fraction": 0.25,   # fração de Kelly
    "kelly_cap": 0.02,        # teto de stake (fração da banca)
    "min_confidence_listed": 33,  # abaixo disso o jogo não entra na lista
}

# Banca p/ converter stake em dinheiro (None = mostrar só %).
BANKROLL: float | None = None

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.365scores.com/",
}
