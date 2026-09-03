"use strict";

const $ = (s) => document.querySelector(s);

const state = {
  index: null,
  day: null,
  date: null,
  counts: {},          // date -> nº de palpites
};


async function fetchJSON(path) {
  const res = await fetch(`${path}?t=${Date.now()}`);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

// ── formatação ───────────────────────────────────────────────────────────────
const asDate = (d) => new Date(`${d}T12:00:00`);
const fmtLong = (d) =>
  new Intl.DateTimeFormat("pt-BR", { weekday: "long", day: "numeric", month: "long" }).format(asDate(d));
const fmtDow = (d) =>
  new Intl.DateTimeFormat("pt-BR", { weekday: "short" }).format(asDate(d)).replace(".", "");
const kickoff = (iso) => (iso.match(/T(\d\d:\d\d)/) || [, "--:--"])[1];
const pct = (p) => `${Math.round(p * 100)}%`;

const GROUP_RANK = { geral: 0, casa_fora: 1, sequencia: 2, temporada: 3 };
const FAV_TARGETS = {
  HOME: new Set(["HOME"]), AWAY: new Set(["AWAY"]),
  "1X": new Set(["HOME"]), X2: new Set(["AWAY"]),
  OVER25: new Set(["OVER", "BTTS_YES"]), UNDER25: new Set(["UNDER", "BTTS_NO"]),
  BTTS_YES: new Set(["BTTS_YES", "OVER"]), BTTS_NO: new Set(["BTTS_NO", "UNDER"]),
};
const CHEV = '<span class="chev"><svg viewBox="0 0 12 12" fill="none"><path d="M2 4l4 4 4-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></span>';

// ── render: card ─────────────────────────────────────────────────────────────
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
  const pts = t.points != null ? `${t.points} pts` : "sem tabela";
  return `<div class="strow">
    <span class="p">${t.position ? t.position : "–"}</span>
    <span class="n">${t.name}</span>
    <span class="s">${pts}${rec}${gd}</span>
  </div>`;
}

function trendItems(list, fav) {
  return list
    .slice()
    .sort((a, b) => (GROUP_RANK[a.group] - GROUP_RANK[b.group]) || (b.strength - a.strength))
    .map((t) => `<li class="${fav.has(t.favors) ? "aligned" : ""}"><span class="dot">▸</span><span>${t.label}</span></li>`)
    .join("");
}

function trendColumns(g) {
  const fav = FAV_TARGETS[g.pick.selection] || new Set();
  const byTeam = { [g.home_team.name]: [], [g.away_team.name]: [], _: [] };
  for (const t of g.trends || []) (byTeam[t.team] || byTeam._).push(t);

  const col = (name) => {
    const items = byTeam[name] || [];
    const body = items.length
      ? `<ul class="trendlist">${trendItems(items, fav)}</ul>`
      : '<p class="muted-note">Sem tendência forte.</p>';
    return `<div class="tcol"><h4>${name}</h4>${body}</div>`;
  };
  const matchup = byTeam._.length
    ? `<div class="matchup"><ul class="trendlist">${trendItems(byTeam._, fav)}</ul></div>`
    : "";
  return `<div class="tcols">${col(g.home_team.name)}${col(g.away_team.name)}</div>${matchup}`;
}

function side(t, cls) {
  const rk = t.position ? `<span class="rk">${t.position}º</span>` : "";
  return `<span class="side ${cls}"><span class="tn">${t.name}</span>${rk}</span>`;
}

function card(g) {
  const p = g.pick;
  const oddTxt = p.odd ? p.odd.toFixed(2) : "sem odd";
  const filler = !!g.below_bar;
  const pk = filler ? "Fora dos critérios do dia" : `Palpite${p.low_conviction ? " · pouca convicção" : ""}`;

  const top = (g.aligned_trends || []).slice().sort((a, b) => b.strength - a.strength)[0];
  const why = top
    ? `<p class="why"><span class="m">▸</span> ${top.team ? `<b>${top.team}:</b> ` : ""}${top.label}</p>`
    : (filler ? '<p class="why">Sem mismatch claro — entrou só por não ter opção melhor hoje.</p>' : "");

  const probs = g.model.probs;
  const probbar = `
    <div>
      <div class="probbar">
        <span class="h" style="flex:${probs.HOME}">${pct(probs.HOME)}</span>
        <span class="d" style="flex:${probs.DRAW}">${pct(probs.DRAW)}</span>
        <span class="a" style="flex:${probs.AWAY}">${pct(probs.AWAY)}</span>
      </div>
      <div class="probkeys"><span>${g.home_team.name}</span><span>Empate</span><span>${g.away_team.name}</span></div>
    </div>`;

  const alts = (g.alt_markets || []).map((a) => `
    <div class="row"><span>${a.label}</span><b>${pct(a.model_prob)}${a.odd ? ` · ${a.odd.toFixed(2)}` : ""}</b></div>`).join("");

  return `
  <details class="card${filler ? " filler" : ""}">
    <summary>
      <div class="card-top">
        <span class="comp">${g.league.name}${g.is_cup ? " · copa" : ""}</span>
        <span class="ko">${kickoff(g.kickoff_local)}</span>
      </div>
      <div class="match">
        ${side(g.home_team, "home")}
        <span class="vs">×</span>
        ${side(g.away_team, "away")}
      </div>
      <div class="pick">
        <span class="pl">
          <span class="pk">${pk}</span>
          <span class="plabel">${p.label}</span>
        </span>
        <span class="odd${p.odd ? "" : " none"}">${oddTxt}</span>
      </div>
      ${why}
      ${CHEV}
    </summary>
    <div class="detail">
      <section>
        <h3>Fase recente</h3>
        <div class="teamform">
          <span class="nm">${g.home_team.name}</span>${pills(g.home_team.recent)}
          <span class="nm">${g.away_team.name}</span>${pills(g.away_team.recent)}
        </div>
      </section>
      <section>
        <h3>Tabela</h3>
        <div class="standings">${standRow(g.home_team)}${standRow(g.away_team)}</div>
      </section>
      <section>
        <h3>Tendências</h3>
        ${trendColumns(g)}
      </section>
      <section>
        <h3>Probabilidades do modelo</h3>
        ${probbar}
        <div class="kv" style="margin-top:.5rem"><span>Gols esperados</span><b>${g.model.expected_goals}</b></div>
        <div class="kv"><span>Over 2.5 / Ambos marcam</span><b>${pct(probs.OVER25)} / ${pct(probs.BTTS_YES)}</b></div>
      </section>
      ${alts ? `<section><h3>Outros mercados</h3><div class="altmarkets">${alts}</div></section>` : ""}
    </div>
  </details>`;
}

// ── filtros / lista ──────────────────────────────────────────────────────────
function render() {
  const list = $("#list");
  if (!state.day) { list.innerHTML = '<p class="loading">Carregando…</p>'; return; }

  const games = state.day.games || [];
  const clearCount = state.day.clear_count ?? games.filter((g) => g.clear).length;
  const note = clearCount === 0 && games.length
    ? '<p class="daynote">Nenhum jogo bateu os critérios hoje (time claramente melhor × time mal, com forma confirmando). Abaixo, os menos arriscados — pense duas vezes.</p>'
    : "";
  list.innerHTML = note + games.map(card).join("");
  $("#empty").hidden = games.length > 0;
  $("#dayHeading").textContent = state.date ? fmtLong(state.date) : "—";

  const gen = state.day.generated_at ? new Date(state.day.generated_at) : null;
  $("#meta").textContent = [
    `${clearCount} clara${clearCount === 1 ? "" : "s"}`,
    state.day.day_total ? `de ${state.day.day_total} jogos` : null,
    gen ? gen.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) : null,
  ].filter(Boolean).join(" · ");
}

function checkFreshness() {
  const b = $("#banner");
  const iso = state.index && state.index.generated_at;
  const ageH = iso ? (Date.now() - new Date(iso).getTime()) / 36e5 : 999;
  if (ageH > 40) {
    b.textContent = `⚠ Dados de ${new Date(iso).toLocaleDateString("pt-BR")} — a atualização automática pode ter falhado.`;
    b.hidden = false;
  } else {
    b.hidden = true;
  }
}

function renderDateStrip() {
  const strip = $("#dateStrip");
  strip.innerHTML = (state.index.dates || []).map((d) => `
    <button class="date-chip" role="tab" data-d="${d}" aria-selected="${d === state.date}">
      <span class="dow">${fmtDow(d)}</span>
      <span class="dnum">${asDate(d).getDate()}</span>
      <span class="cnt">${state.counts[d] != null ? state.counts[d] : ""}</span>
    </button>`).join("");
  const active = strip.querySelector('[aria-selected="true"]');
  if (active) active.scrollIntoView({ inline: "center", block: "nearest" });
}

async function loadDate(date) {
  state.date = date;
  location.hash = date;
  try {
    state.day = await fetchJSON(`data/${date}.json`);
  } catch {
    state.day = { date, count: 0, games: [] };
  }
  state.counts[date] = state.day.clear_count ?? state.day.count;
  renderDateStrip();
  render();
}

function wire() {
  $("#dateStrip").addEventListener("click", (e) => {
    const b = e.target.closest("[data-d]");
    if (b) loadDate(b.dataset.d);
  });
}

async function boot() {
  try {
    state.index = await fetchJSON("data/index.json");
  } catch (e) {
    $("#list").innerHTML = `<p class="loading">Não consegui carregar os dados.<br><small>${e.message}</small></p>`;
    return;
  }
  wire();
  checkFreshness();

  const dates = state.index.dates || [];
  const wanted = location.hash.slice(1);
  const latest = await fetchJSON("data/latest.json").catch(() => null);
  const start = dates.includes(wanted) ? wanted : (latest ? latest.date : dates[dates.length - 1]);
  renderDateStrip();
  loadDate(start);
}

boot();
