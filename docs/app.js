"use strict";

const $ = (s) => document.querySelector(s);
const PREF_KEY = "bettrends.filters";

const state = {
  index: null,
  day: null,          // objeto do arquivo do dia
  date: null,         // "YYYY-MM-DD"
  filters: loadPrefs(),
};

function loadPrefs() {
  const def = { minConf: 0, league: "", market: "" };
  try {
    return { ...def, ...JSON.parse(localStorage.getItem(PREF_KEY) || "{}") };
  } catch {
    return def;
  }
}
function savePrefs() {
  try { localStorage.setItem(PREF_KEY, JSON.stringify(state.filters)); } catch { /* modo privado */ }
}

async function fetchJSON(path) {
  const res = await fetch(`${path}?t=${Date.now()}`);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

// ── formatação ────────────────────────────────────────────────────────────────
const fmtDate = (d) =>
  new Intl.DateTimeFormat("pt-BR", { weekday: "short", day: "2-digit", month: "short" })
    .format(new Date(`${d}T12:00:00`));

const kickoff = (iso) => (iso.match(/T(\d\d:\d\d)/) || [, "--:--"])[1];

const pct = (p) => `${Math.round(p * 100)}%`;

function confClass(c) {
  return c >= 65 ? "hi" : c >= 50 ? "mid" : "lo";
}

const GROUP_LABEL = {
  forma: "Forma recente",
  sequencia: "Sequências longas",
  casa_fora: "Casa / fora",
  temporada: "Na temporada",
  tabela: "Tabela",
};
const GROUP_ORDER = ["sequencia", "casa_fora", "temporada", "tabela", "forma"];

// ── render ────────────────────────────────────────────────────────────────────
function pills(recent) {
  const items = (recent || []).slice(0, 5).map(
    (m) => `<span class="pill ${m.result}" title="${m.home ? "" : "@"}${m.opponent} ${m.score}">${m.result}</span>`
  );
  while (items.length < 5) items.push('<span class="pill empty"></span>');
  return `<span class="pills">${items.join("")}</span>`;
}

function standRow(t) {
  const gd = t.goals_for != null ? ` · ${t.goals_for}:${t.goals_against}` : "";
  const rec = t.record ? ` · ${t.record}` : "";
  const pts = t.points != null ? `${t.points} pts` : "—";
  return `<div class="strow">
    <span class="spos">${t.position ? `${t.position}º` : "–"}</span>
    <span class="sname">${t.name}</span>
    <span class="sstat">${pts}${rec}${gd}</span>
  </div>`;
}

function trendGroups(trends) {
  const by = {};
  for (const t of trends || []) (by[t.group || "forma"] ||= []).push(t);
  return GROUP_ORDER.filter((g) => by[g] && by[g].length).map((g) => `
    <div class="tgroup">
      <h4>${GROUP_LABEL[g]}</h4>
      <ul class="trendlist">
        ${by[g].map((t) => `<li><span class="dot">▸</span><span>${t.label}</span>${t.team ? `<span class="team">${t.team}</span>` : ""}</li>`).join("")}
      </ul>
    </div>`).join("");
}

function card(g) {
  const p = g.pick;
  const conf = g.confidence;
  const oddTxt = p.odd ? p.odd.toFixed(2) : "sem odd";

  const badges = [];
  if (p.low_conviction) badges.push('<span class="badge lowconv">baixa convicção</span>');
  for (const t of (g.aligned_trends || []).slice(0, 3)) badges.push(`<span class="badge">${t.label}</span>`);

  const probs = g.model.probs;
  const probbar = `
    <div class="probbar">
      <span class="h" style="flex:${probs.HOME}">${pct(probs.HOME)}</span>
      <span class="d" style="flex:${probs.DRAW}">${pct(probs.DRAW)}</span>
      <span class="a" style="flex:${probs.AWAY}">${pct(probs.AWAY)}</span>
    </div>`;

  const alts = (g.alt_markets || []).map((a) => `
    <div class="row"><span>${a.label}</span><span>${pct(a.model_prob)} · conf ${a.confidence}${a.odd ? ` · ${a.odd.toFixed(2)}` : ""}</span></div>`).join("");

  const tg = trendGroups(g.trends);

  return `
  <details class="card">
    <summary>
      <div class="card-head">
        <span class="comp">${g.league.name} · ${kickoff(g.kickoff_local)}</span>
        <span class="meter" title="confiança ${conf}/100">
          <span class="track"><span class="fill ${confClass(conf)}" style="width:${Math.max(6, conf)}%"></span></span>
          <span class="val">${conf}</span>
        </span>
      </div>
      <div class="match">
        <span>${g.home_team.name}</span><span class="pos">${g.home_team.position ? `${g.home_team.position}º` : ""}</span><span class="x">×</span><span>${g.away_team.name}</span><span class="pos">${g.away_team.position ? `${g.away_team.position}º` : ""}</span>
      </div>
      <div class="pick">
        <span class="label">${p.label}</span>
        <span class="odd${p.odd ? "" : " none"}">${oddTxt}</span>
      </div>
      ${badges.length ? `<div class="badges">${badges.join("")}</div>` : ""}
    </summary>
    <div class="detail">
      <div>
        <h3>Fase recente (últimos 5)</h3>
        <div class="teamform">
          <span class="name">${g.home_team.name}</span>${pills(g.home_team.recent)}
          <span class="name">${g.away_team.name}</span>${pills(g.away_team.recent)}
        </div>
      </div>
      <div>
        <h3>Tabela</h3>
        <div class="standings">
          ${standRow(g.home_team)}
          ${standRow(g.away_team)}
        </div>
      </div>
      <div>
        <h3>Tendências</h3>
        ${tg || '<p class="muted-note">Sem tendência forte detectada.</p>'}
      </div>
      <div>
        <h3>Probabilidades do modelo</h3>
        ${probbar}
        <div class="kv" style="margin-top:.45rem"><span>Gols esperados</span><b>${g.model.expected_goals}</b></div>
        <div class="kv"><span>Over 2.5 / Ambos marcam</span><b>${pct(probs.OVER25)} / ${pct(probs.BTTS_YES)}</b></div>
      </div>
      ${alts ? `<div><h3>Outros mercados</h3><div class="altmarkets">${alts}</div></div>` : ""}
    </div>
  </details>`;
}

function applyFilters(games) {
  const f = state.filters;
  return games.filter((g) => {
    if (f.minConf && g.confidence < +f.minConf) return false;
    if (f.league && g.league.name !== f.league) return false;
    if (f.market && g.pick.family !== f.market) return false;
    return true;
  });
}

function render() {
  const list = $("#list");
  const empty = $("#empty");
  if (!state.day) {
    list.innerHTML = '<p class="loading">Carregando…</p>';
    return;
  }
  const games = applyFilters(state.day.games || []);
  list.innerHTML = games.map((g) => card(g)).join("");
  empty.hidden = games.length > 0;

  const gen = state.day.generated_at ? new Date(state.day.generated_at) : null;
  $("#meta").textContent = [
    `${state.day.count} jogo(s) no dia`,
    gen ? `atualizado ${gen.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}` : "",
    state.index && state.index.odds_enabled ? `odds: ${state.index.odds_credits_remaining ?? "?"} créditos` : "odds desligadas",
  ].filter(Boolean).join(" · ");

  $("#subtitle").textContent = fmtDate(state.date);
}

async function loadDate(date) {
  state.date = date;
  $("#dateSelect").value = date;
  location.hash = date;
  try {
    state.day = await fetchJSON(`data/${date}.json`);
  } catch {
    state.day = { date, count: 0, games: [] };
  }
  populateLeagueFilter();
  render();
}

function populateLeagueFilter() {
  const sel = $("#leagueFilter");
  const leagues = [...new Set((state.day.games || []).map((g) => g.league.name))].sort();
  sel.innerHTML = '<option value="">Todas as ligas</option>' +
    leagues.map((l) => `<option value="${l}">${l}</option>`).join("");
  sel.value = state.filters.league;
}

function stepDay(dir) {
  const dates = state.index.dates;
  const i = dates.indexOf(state.date);
  const next = dates[i + dir];
  if (next) loadDate(next);
}

function wire() {
  $("#prevDay").onclick = () => stepDay(-1);
  $("#nextDay").onclick = () => stepDay(1);
  $("#dateSelect").onchange = (e) => loadDate(e.target.value);

  const bind = (id, key, transform = (v) => v) => {
    const el = $("#" + id);
    if (el.type === "checkbox") {
      el.checked = state.filters[key];
      el.onchange = () => { state.filters[key] = el.checked; savePrefs(); render(); };
    } else {
      el.value = state.filters[key];
      el.onchange = () => { state.filters[key] = transform(el.value); savePrefs(); render(); };
    }
  };
  bind("minConf", "minConf");
  bind("leagueFilter", "league");
  bind("marketFilter", "market");
}

async function boot() {
  try {
    state.index = await fetchJSON("data/index.json");
  } catch (e) {
    $("#list").innerHTML = `<p class="loading">Não consegui carregar os dados.<br><small>${e.message}</small></p>`;
    return;
  }
  const dates = state.index.dates || [];
  $("#dateSelect").innerHTML = dates.map((d) => `<option value="${d}">${fmtDate(d)}</option>`).join("");

  wire();

  const wanted = location.hash.slice(1);
  const latest = await fetchJSON("data/latest.json").catch(() => null);
  const start = dates.includes(wanted) ? wanted : (latest ? latest.date : dates[dates.length - 1]);
  loadDate(start);
}

boot();
