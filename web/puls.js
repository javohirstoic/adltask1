/* Puls — rahbar paneli. Freymvorksiz: tez ochiladi, kuchsiz qurilmada ham yengil. */
"use strict";

/* ================= yordamchilar ================= */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const I = (n, cls = "") => `<svg class="i ${cls}" aria-hidden="true"><use href="static/vendor/icons.svg#i-${n}"/></svg>`;
const nf = (n, d = 0) => (n == null ? "—" : Number(n).toLocaleString("ru-RU", { maximumFractionDigits: d }));
const MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr"];
const WEEK = ["yakshanba", "dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba"];
const parseTs = (ts) => new Date(ts.replace(" ", "T") + "+05:00");
const parseDay = (d) => new Date(d + "T12:00:00+05:00");
const isoDay = (dt) => new Date(dt.getTime() + 5 * 3600e3).toISOString().slice(0, 10);
const uzDate = (dt) => dt.getDate() + "-" + MONTHS[dt.getMonth()];
const initials = (n) => (String(n || "?").replace(/^@/, "").split(/\s+/).map((w) => (w.match(/[\p{L}\p{N}]/u) || [""])[0]).filter(Boolean).slice(0, 2).join("") || "?").toUpperCase();
const first = (n) => String(n || "").split(" ")[0];
// Vazifa yonidagi belgi: o'z muddati bo'lsa muddat (o'tgani qizil), bo'lmasa necha kundan beri ochiq
const ageState = (t) => t.state || (t.age < 3 ? "new" : t.age < 7 ? "slow" : "stuck");
const dueText = (t) => t.due_in == null ? t.age + " kun" : t.due_in < 0 ? -t.due_in + " kun kechikdi" : t.due_in === 0 ? "bugun" : t.due_label + "gacha";
const dueTag = (t, style) => `<span class="age ${t.due_in == null ? ageState(t) : t.due_in < 0 ? "stuck" : t.due_in <= 1 ? "slow" : "new"}"${style ? ` style="${style}"` : ""}${t.due_in != null ? ` title="Muddat: ${t.due_label}"` : ""}>${dueText(t)}</span>`;
// Rol: /api/meta -> me. Ruxsatlarni server hal qiladi, bu yerda faqat keraksiz tugmalar ko'rsatilmaydi
const ME = () => S.meta?.me || {};
const isRole = (...r) => r.includes(ME().role);
const canAct = () => isRole("admin", "rahbar");   // qarorlar, guruhga xabar, shaxsiy aloqa, AI tuzatish
const can = (res, letter) => (ME().access?.[res] || "").includes(letter);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function ago(ts) {
  if (!ts) return "—";
  const ref = S.asof && S.data ? parseTs(S.data.now) : new Date();
  const s = (ref - parseTs(ts)) / 1000;
  if (s < 60) return "hozirgina";
  if (s < 3600) return Math.floor(s / 60) + " daqiqa oldin";
  if (s < 86400) return Math.floor(s / 3600) + " soat oldin";
  const d = Math.floor(s / 86400);
  return d === 1 ? "kecha" : d + " kun oldin";
}
const clock = (ts) => { const d = parseTs(ts); return uzDate(d) + ", " + String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"); };

const DEPT_ICON = { AI: "magic", Backend: "server", Frontend: "palette", Fullstack: "programming", DevOps: "routing", Dizayn: "palette", "Test (QA)": "bug", Belgilanmagan: "user" };
const hash = (s) => { let h = 0; for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) | 0; return Math.abs(h); };
// Bo'lim — rang emas, matn: panelda ranglar faqat holat (istisno) uchun ishlatiladi
const deptColor = () => "#8e8e93";
const STATE = {
  overloaded: { label: "Ishi ko'p", icon: "fire", color: "var(--risk)", order: 0 },
  silent: { label: "Jim", icon: "chat-dots", color: "var(--orange)", order: 1 },
  stuck: { label: "Cho'zilgan", icon: "clock", color: "var(--warn)", order: 2 },
  ok: { label: "Me'yorida", icon: "check", color: "var(--ok)", order: 3 },
  idle: { label: "Bo'sh", icon: "cup", color: "var(--idle)", order: 4 },
};
const STATE_ORDER = ["ok", "stuck", "silent", "overloaded", "idle"];
const LEVEL = { 4: "Kritik", 3: "Xavf", 2: "Diqqat", 1: "Kuzatuv", 0: "Me'yorda" };
const LEVEL_ICON = { 4: "danger", 3: "danger", 2: "info", 1: "eye", 0: "check" };
const KIND = { task: "Vazifa", done: "Bajarildi", blocker: "Muammo", deadline: "Muddat" };
const SRC = { ai: ["AI", "stars"], format: ["Teg", ""], taxmin: ["Kalit so'z", ""], tuzatildi: ["Tuzatildi", "check"] };
const TABS = [
  ["brifing", "brifing", "Brifing", "brifing"], ["ofis", "ofis", "Ofis", "office"], ["xodimlar", "xodimlar", "Xodimlar", "people"],
  ["loyihalar", "loyihalar", "Loyihalar", "projects"], ["bolimlar", "bolimlar", "Bo'limlar", "depts"],
  ["malumotlar", "malumotlar", "Ma'lumotlar", "doc"],
];
const EXPORT_VIEW = { brifing: "projects", ofis: "people", xodimlar: "people", loyihalar: "projects", bolimlar: "departments", malumotlar: "projects" };

/* ================= holat ================= */
const S = {
  tab: "brifing", period: "week", start: "", end: "", chat: "", asof: "",
  data: null, meta: null, version: 0, ui: 0,
  pf: { q: "", dept: "", state: "", sort: "attention" }, faceState: "", officeDept: "", officeState: "",
  prSort: { key: "level", asc: false }, showAllDecs: false,
  office: null, officeKey: "", charts: {}, tv: null, playing: false, counted: {}, open: "",
};

function readHash() {
  const [path, q] = location.hash.replace(/^#\/?/, "").split("?");
  if (TABS.some((t) => t[1] === path)) S.tab = TABS.find((t) => t[1] === path)[0];
  const p = new URLSearchParams(q || "");
  if (["day", "week", "month", "custom"].includes(p.get("d"))) S.period = p.get("d");
  S.start = p.get("s") || ""; S.end = p.get("e") || ""; S.chat = p.get("g") || ""; S.asof = p.get("t") || "";
  S.open = p.get("x") || "";
}
function writeHash() {
  const p = new URLSearchParams();
  if (S.period !== "week") p.set("d", S.period);
  if (S.period === "custom") { p.set("s", S.start); p.set("e", S.end); }
  if (S.chat) p.set("g", S.chat);
  if (S.asof) p.set("t", S.asof);
  if (S.open) p.set("x", S.open);
  const h = "#/" + TABS.find((t) => t[0] === S.tab)[1] + (p.toString() ? "?" + p : "");
  if (location.hash !== h) history.replaceState(null, "", h);
}
function query(extra) {
  const p = new URLSearchParams({ period: S.period });
  if (S.period === "custom") { p.set("start", S.start); p.set("end", S.end); }
  if (S.chat) p.set("chat", S.chat);
  if (S.asof) p.set("asof", S.asof);
  Object.entries(extra || {}).forEach(([k, v]) => p.set(k, v));
  return p.toString();
}

/* ================= ma'lumot ================= */
const csrf = () => (document.cookie.match(/(?:^|; )csrftoken=([^;]+)/) || [])[1] || "";

async function api(path, opt) {
  const o = Object.assign({ headers: { Accept: "application/json" } }, opt || {});
  o.headers = Object.assign({ "X-CSRFToken": csrf() }, o.headers);
  if (o.json !== undefined) { o.method = o.method || "POST"; o.body = JSON.stringify(o.json); o.headers["Content-Type"] = "application/json"; delete o.json; }
  const r = await fetch(path, o);
  if (r.status === 401) { location.href = "login"; throw new Error("Kirish kerak"); }
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    // DRF: {detail} yoki maydon xatolari {maydon: ["xabar"]}
    const fields = Object.entries(j).filter(([k]) => k !== "detail").map(([k, v]) => `${k}: ${[].concat(v).join(", ")}`).join("; ");
    throw new Error(j.detail || fields || "Server javob bermadi");
  }
  return r.status === 204 ? null : r.json();
}

async function load(silent) {
  try {
    const d = await api("api/summary?" + query());
    const prev = S.data;
    S.data = d; S.version = d.version;
    renderAll();
    if (silent && prev && !S.asof) announce(prev.feed, d.feed);
    live(true);
  } catch (e) {
    live(false);
    if (!silent) toast(esc(e.message), "danger");
  }
}

function announce(oldFeed, newFeed) {
  const seen = new Set(oldFeed.map((f) => f.id));
  const fresh = newFeed.filter((f) => !seen.has(f.id));
  fresh.slice(0, 2).reverse().forEach((f) => toast(`<b>${esc(f.author || "Kimdir")}</b>, ${esc(KIND[f.kind] || "xabar")}${f.project ? ", " + esc(f.project) : ""}`, "send"));
  fresh.forEach((f) => { const el = $(`.fi[data-mid="${f.id}"]`); if (el) el.classList.add("fresh"); });
}

setInterval(async () => {
  if (document.hidden) return;
  try {
    const { v, ui } = await api("api/version");
    if (S.ui && ui !== S.ui) { location.reload(); return; }
    S.ui = ui;
    if (v !== S.version && !S.asof) load(true);
    live(true);
  } catch (e) { live(false); }
}, 4000);

function live(ok) {
  const el = $("#live");
  if (!el) return;
  el.classList.toggle("off", !ok);
  el.classList.toggle("past", !!S.asof);
  $("span", el).textContent = S.asof ? uzDate(parseDay(S.asof)) + " holati" : ok ? "Jonli" : "Aloqa yo'q";
}

/* ================= navigatsiya ================= */
function buildNav() {
  $("#nav").innerHTML = TABS.map((t) => `<button data-tab="${t[0]}" title="${t[2]}">${I(t[3])}<span>${t[2]}</span></button>`).join("");
  $("#bnav").innerHTML = TABS.map((t) => `<button data-tab="${t[0]}">${I(t[3])}${t[2]}</button>`).join("");
  $$("[data-tab]").forEach((b) => b.addEventListener("click", () => go(b.dataset.tab)));
}
function go(tab) {
  S.tab = tab;
  $$("[data-tab]").forEach((b) => { if (b.dataset.tab === tab) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current"); });
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === "v-" + tab));
  writeHash();
  if (S.data) renderView(tab);
  if (!S.tv) window.scrollTo({ top: 0 });
}
function renderAll() { renderHist(); renderView(S.tab); }
function renderView(tab) {
  if (!S.data) return;
  ({ brifing: renderBrifing, ofis: renderOffice, xodimlar: renderPeople, loyihalar: renderProjects, bolimlar: renderDepts, malumotlar: renderData })[tab](S.data);
}

/* sahifa sarlavhasi va filtrlar (hamma ekranda bir xil joyda) */
function pageHead(title, sub) {
  const chats = S.meta?.chats || [];
  const tmLabel = S.asof ? uzDate(parseDay(S.asof)) : "Bugun";
  return `<div class="ph"><div><h1>${title}</h1><div class="sub">${sub}</div></div>
    <div class="filters">
      <div class="seg" role="group" aria-label="Davr">
        <button data-p="day" aria-pressed="${S.period === "day"}">Bugun</button><button data-p="week" aria-pressed="${S.period === "week"}">7 kun</button>
        <button data-p="month" aria-pressed="${S.period === "month"}">30 kun</button><button data-p="custom" aria-pressed="${S.period === "custom"}" title="Oraliq">${I("calendar")}</button>
      </div>
      ${chats.length > 1 ? `<select class="ctl" data-chat aria-label="Guruh"><option value="">Barcha guruhlar</option>${chats.map((c) => `<option value="${c.id}" ${String(c.id) === S.chat ? "selected" : ""}>${esc(c.title)}</option>`).join("")}</select>` : ""}
      <button class="ctl ${S.asof ? "active" : ""}" data-tm title="Vaqt mashinasi: o'tgan kunni ko'rish">${I("history")}<span>${tmLabel}</span></button>
      <a class="icon-btn" href="api/export.xlsx?${query({ view: EXPORT_VIEW[S.tab] })}" title="Excel">${I("download")}</a>
    </div></div>`;
}
function bindHead(root) {
  $$("[data-p]", root).forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.p === "custom") { openRange(); return; }
    S.period = b.dataset.p; writeHash(); load();
  }));
  const sel = $("[data-chat]", root);
  if (sel) sel.addEventListener("change", () => { S.chat = sel.value; S.officeKey = ""; writeHash(); load(); });
  const tm = $("[data-tm]", root);
  if (tm) tm.addEventListener("click", (e) => { e.stopPropagation(); toggleTM(tm); });
}
function periodText(d) {
  return d.period.key === "custom" ? d.period.range_label : d.period.key === "day" ? "Bugun, " + d.period.range_label : d.period.label + ", " + d.period.range_label;
}

/* ================= kichik qismlar ================= */
function ava(name, dept, state, cls = "") {
  return `<span class="ava ${state ? "ring st-" + state : ""} ${cls}">${esc(initials(name))}</span>`;
}
function statePill(st, fact, sm) {
  const s = STATE[st];
  return `<span class="pill p-${st} ${sm ? "sm" : ""}"><span><b>${s.label}</b>${fact ? ", " + esc(fact) : ""}</span></span>`;
}
const levelPill = (lv, sm) => `<span class="pill p-l${lv} ${sm ? "sm" : ""}">${I(LEVEL_ICON[lv])}${LEVEL[lv]}</span>`;
function scoreRing(score, cls = "") {
  if (score == null) return `<div class="score na ${cls}" title="30 kunda kamida 3 ta vazifa bo'lsa baho chiqadi"><span>—</span></div>`;
  const c = score >= 50 ? "var(--ink)" : "var(--risk)";
  return `<div class="score ${cls}" style="--p:${score};--c:${c}"><span>${score}</span></div>`;
}
function src(s) {
  const x = SRC[s] || [s, ""];
  return `<span class="src s-${s}" title="${s === "ai" ? "Formatsiz xabarni AI tushundi" : s === "format" ? "#teg bilan yozilgan" : s === "tuzatildi" ? "Rahbar tuzatgan" : "Kalit so'zlar bo'yicha"}">${x[1] ? I(x[1]) : ""}${x[0]}</span>`;
}
function emptyBox(text, icon = "check") { return `<div class="empty">${I(icon)}<span>${text}</span></div>`; }


/* ================= 1. Brifing ================= */
function greeting(d) {
  const h = parseTs(d.now).getHours();
  return h < 5 ? "Xayrli tun" : h < 12 ? "Xayrli tong" : h < 18 ? "Xayrli kun" : "Xayrli kech";
}
// Hero: holat kartalari. Har karta — bitta savolga javob (umumiy holat, loyihalar, xodimlar, muddatlar, muammolar)
function kRows(rows) {
  return `<span class="kc-list">${rows.filter((r) => r[2] !== null).map((r) => `<span class="${r[0]}"><i></i>${esc(r[1])}<b>${r[2]}</b></span>`).join("")}</span>`;
}
function kNote(title, name, value) {
  return `<span class="kc-note"><em>${esc(title)}</em><span><span>${esc(name)}</span><b>${esc(value)}</b></span></span>`;
}
function kBar(parts) {
  const total = parts.reduce((a, x) => a + x[0], 0);
  return total ? `<span class="kc-bar">${parts.filter((x) => x[0]).map((x) => `<i style="flex:${x[0]};background:${x[1]}"></i>`).join("")}</span>` : "";
}
function heroCards(d) {
  const k = d.kpi, pr = d.projects, st = countStates(d.people);
  const risk = pr.filter((x) => x.level >= 3).length, attn = pr.filter((x) => x.level === 2).length;
  const has = (x, code) => x.risks.some((r) => r.code === code);
  const overdue = pr.filter((x) => has(x, "overdue")).length;
  const late = pr.filter((x) => !has(x, "overdue") && (has(x, "forecast") || has(x, "deadline"))).length;
  const next = pr.filter((x) => x.deadline && x.days_left >= 0 && x.open_total).sort((a, b) => a.days_left - b.days_left)[0];
  const bl = pr.flatMap((x) => x.blocker_list.map((b) => ({ ...b, project: x.name }))).sort((a, b) => b.age - a.age);
  return `<section class="kpis">
    <button class="kc kc-main" data-go="loyihalar">
      <span class="kc-l">Vazifalar, ${esc(d.period.label.toLowerCase())}</span>
      <span class="kc-v"><span data-count="${k.done}">${k.done}</span><small>bajarildi</small></span>
      ${kRows([["n", "Yangi berilgan", k.created], ["n", "Hozir ochiq", pr.reduce((a, x) => a + x.open_total, 0)],
        ["n", "Bitta vazifaga o'rtacha", k.cycle == null ? "—" : nf(k.cycle, 1) + " kun"]])}
    </button>
    <button class="kc" data-go="loyihalar">
      <span class="kc-l">Loyihalar</span>
      <span class="kc-v"><span data-count="${pr.length}">${pr.length}</span></span>
      ${kBar([[risk, "var(--risk)"], [attn, "var(--warn)"], [pr.length - risk - attn, "var(--line-2)"]])}
      ${kRows([["r", "Xavf ostida", risk], ["w", "Diqqat kerak", attn], ["n", "Me'yorda", pr.length - risk - attn]])}
    </button>
    <button class="kc" data-go="xodimlar">
      <span class="kc-l">Xodimlar</span>
      <span class="kc-v"><span data-count="${d.people.length}">${d.people.length}</span></span>
      ${kBar([[st.overloaded, "var(--risk)"], [st.silent + st.stuck, "var(--warn)"], [st.ok, "var(--line-2)"], [st.idle, "var(--surface-3)"]])}
      ${kRows([["r", "Ishi ko'p", st.overloaded], ["w", "Jim", st.silent], ["w", "Cho'zilgan", st.stuck], ["h", "Bo'sh", st.idle]])}
    </button>
    <button class="kc" data-go="loyihalar">
      <span class="kc-l">Muddatlar</span>
      <span class="kc-v ${overdue ? "bad" : ""}"><span data-count="${overdue}">${overdue}</span><small>${overdue ? "loyiha kechikdi" : "kechikkan yo'q"}</small></span>
      ${kRows([["w", "Ulgurmaydi", late]])}
      ${next ? kNote("Eng yaqin muddat", next.name, next.days_left ? next.days_left + " kun qoldi" : "bugun") : ""}
    </button>
    <button class="kc" data-go="loyihalar">
      <span class="kc-l">Ochiq muammolar</span>
      <span class="kc-v ${bl.length ? "bad" : ""}"><span data-count="${bl.length}">${bl.length}</span></span>
      ${kRows([["r", "3 kundan eski", bl.filter((b) => b.age >= 3).length]])}
      ${bl[0] ? kNote("Eng eskisi", bl[0].project, bl[0].age + " kun") : ""}
    </button>
  </section>`;
}

function renderBrifing(d) {
  const el = $("#v-brifing"), k = d.kpi, now = parseTs(d.now);
  const mgr = isRole("menejer");
  const headline = mgr ? `Loyihalaringiz: ${d.projects.length} ta, xavf ostida ${d.kpi.at_risk} ta.`
    : d.decisions.length ? `Bugun ${d.decisions.length} ta masala qaroringizni kutmoqda.` : "Bugun qaror talab qiladigan masala yo'q.";
  const decs = S.showAllDecs ? d.decisions : d.decisions.slice(0, 5);
  const states = countStates(d.people);
  const day = WEEK[now.getDay()][0].toUpperCase() + WEEK[now.getDay()].slice(1);
  el.innerHTML = pageHead(greeting(d), `${day}, ${uzDate(now)}${S.asof ? ", kun oxiridagi holat" : ""}`) + `
    ${heroCards(d)}

    <div class="sec-title"><h2>${headline}</h2></div>
    ${mgr ? "" : `<div class="agenda">${decs.length ? decs.map(agRow).join("") : `<div class="dec-done"><span class="ic lv0">${I("check")}</span><span>Qaror talab qiladigan masala yo'q.</span></div>`}
      ${d.decisions.length > 5 ? `<div class="ag-more"><button class="more-link" data-alldec>${S.showAllDecs ? "Kamroq ko'rsatish" : `Yana ${d.decisions.length - 5} ta`}</button></div>` : ""}</div>`}

    <div class="grid" style="margin-top:20px">
      <section class="card s7"><div class="ch"><h3>Jamoa</h3><span class="count">${d.people.length}</span>
        <div class="right">${stateChips(states, S.faceState, "face")}</div></div>
        <div class="cb">${teamFaces(d.people, S.faceState)}</div></section>
      <section class="card s5"><div class="ch"><h3>Loyihalar</h3><span class="count">${d.projects.length}</span>
        <div class="right road-legend"><span>${I("flag")}muddat</span><span><i class="o"></i>prognoz</span><span><i class="t"></i>bugun</span></div></div>
        <div class="cb"><div class="roads">${d.projects.slice(0, 8).map((x) => roadRow(x, d)).join("") || emptyBox("Hali loyiha yo'q", "projects")}</div>
          ${d.projects.length > 8 ? `<div style="margin-top:12px"><button class="more-link" data-go="loyihalar">Barcha ${d.projects.length} loyiha</button></div>` : ""}</div></section>
      <section class="card s8"><div class="ch"><h3>Dinamika</h3><div class="right road-legend"><span><i class="sq" style="background:color-mix(in srgb,var(--azure) 30%,transparent)"></i>yangi</span><span><i class="o" style="border-color:var(--ok)"></i>bajarildi</span></div></div>
        <div class="cb"><div style="height:280px"><canvas id="cTrend"></canvas></div></div></section>
      <section class="card s4"><div class="ch"><h3>Jonli lenta</h3></div>
        <div class="cb" style="padding-top:6px"><div class="feed">${d.feed.map(feedItem).join("") || emptyBox("Guruhga birinchi xabar yozilishi bilan shu yerda ko'rinadi", "chat-dots")}</div></div></section>
      ${d.decision_log.length ? `<section class="card s12"><div class="ch"><h3>Bajarilgan qarorlar</h3><span class="count">${d.decision_log.length}</span></div>
        <div class="cb" style="padding-top:6px"><div class="log">${d.decision_log.map(logItem).join("")}</div></div></section>` : ""}
    </div>`;
  bindHead(el);
  bindCommon(el);
  $$("[data-alldec]", el).forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); S.showAllDecs = !S.showAllDecs; renderBrifing(S.data); }));
  $$("[data-fs]", el).forEach((b) => b.addEventListener("click", () => { S.faceState = S.faceState === b.dataset.fs ? "" : b.dataset.fs; renderBrifing(S.data); }));
  drawTrend($("#cTrend"), d.series);
  countUp(el, "brifing");
}

const ACT_ICON = { deadline: "deadline", reassign: "transfer", ping_person: "chat-dots", ping_project: "chat-dots", ping_blocker: "bell", dm_person: "letter" };
function agRow(x, i) {
  const tgt = x.target.type === "project" ? `data-project="${x.target.id}"` : `data-person="${esc(x.target.name)}"`;
  return `<div class="ag lv${x.level}" ${tgt}><span class="ag-n">${i + 1}</span><span class="ag-bar"></span><span class="ic">${I(x.icon)}</span>
    <div class="ag-main"><b>${esc(x.title)}</b><span title="${esc(x.fact)}">${esc(x.fact)}</span></div>
    <div class="acts">${x.action ? `<button class="btn btn-line" data-act='${esc(JSON.stringify(x.action))}'>${I(ACT_ICON[x.action.type] || "check")}<span>${esc(x.button)}</span></button>` : ""}</div></div>`;
}
function countStates(people) {
  const c = { ok: 0, stuck: 0, silent: 0, overloaded: 0, idle: 0 };
  people.forEach((p) => c[p.state]++);
  return c;
}
function stateChips(c, active, kind) {
  return `<div class="legend">${STATE_ORDER.filter((k) => c[k]).map((k) => `<button class="chip" data-${kind === "face" ? "fs" : kind === "office" ? "os" : "ps"}="${k}" aria-pressed="${active === k}">
    <span class="dot" style="background:${STATE[k].color}"></span>${STATE[k].label} <b>${c[k]}</b></button>`).join("")}</div>`;
}
function teamFaces(people, only) {
  const groups = {};
  people.forEach((p) => (groups[p.department] = groups[p.department] || []).push(p));
  const names = Object.keys(groups).sort((a, b) => (a === "Belgilanmagan") - (b === "Belgilanmagan") || a.localeCompare(b));
  if (!names.length) return emptyBox("Xodimlar guruhga yozishi bilan shu yerda paydo bo'ladi", "people");
  return names.map((n) => `<div class="drow"><div class="dname">${esc(n)}</div>
    <div class="faces">${groups[n].map((p) => `<button class="face st-${p.state} ${only && p.state !== only ? "dim" : ""}" data-person="${esc(p.name)}" data-tip-person="${esc(p.name)}" aria-label="${esc(p.name)}">${esc(initials(p.name))}</button>`).join("")}</div></div>`).join("");
}
function roadRow(p, d, big) {
  const today = parseTs(d.now);
  const start = parseDay(p.start_date || d.period.from);
  const dl = p.deadline ? parseDay(p.deadline) : null, eta = p.eta_date ? parseDay(p.eta_date) : null;
  const end = new Date(Math.max(today, dl || 0, eta || 0) + 3 * 864e5);
  const span = Math.max(1, end - start), pos = (t) => Math.max(0, Math.min(100, ((t - start) / span) * 100));
  const late = dl && eta && eta > dl;
  const meta = `<b>${p.progress}%</b>${p.deadline ? (p.days_left < 0 ? `<span style="color:var(--risk-ink)">${-p.days_left} kun o'tdi</span>` : p.days_left + " kun qoldi") : "muddatsiz"}`;
  return `<div class="road lv${p.level}" data-project="${p.id}" title="${esc(p.name)}: ${p.deadline_label ? "muddat " + p.deadline_label + ", " : ""}${p.eta_label ? "prognoz " + p.eta_label : ""}">
    <div class="nm"><span class="dot"></span><span>${esc(p.name)}</span></div><div class="meta">${meta}</div>
    <div class="track lv${p.level}" ${big ? 'style="height:12px"' : ""}><div class="work" style="width:${pos(today).toFixed(1)}%"></div>
      ${late ? `<div class="late" style="left:${pos(dl).toFixed(1)}%;width:${(pos(eta) - pos(dl)).toFixed(1)}%"></div>` : ""}
      <div class="today" style="left:${pos(today).toFixed(1)}%"></div>
      ${dl ? `<span class="flag" style="left:${pos(dl).toFixed(1)}%">${I("flag")}</span>` : ""}
      ${eta ? `<span class="eta" style="left:${pos(eta).toFixed(1)}%;--ec:${late ? "var(--risk)" : "var(--ok)"}"></span>` : ""}</div></div>`;
}
function feedItem(f) {
  return `<div class="fi" data-mid="${f.id}">${ava(f.author || "?", f.department)}
    <div style="min-width:0"><div class="fi-h"><b>${esc(f.author || "Noma'lum")}</b><span class="t">${ago(f.date)}</span></div>
      <div class="fi-m"><span class="kind k-${f.kind}">${KIND[f.kind] || f.kind}</span>${f.project ? `<span class="pj">${esc(f.project)}</span>` : `<span class="unknown">loyiha?</span>`}${src(f.source)}</div>
      <p>${esc(f.text)}</p></div>
    ${S.asof || !canAct() ? "" : `<button class="fix" data-fix="${f.id}" title="AI noto'g'ri tushungan bo'lsa">${I("pen")}Tuzatish</button>`}</div>`;
}
const LOG_ICON = { reassign: "transfer", deadline: "deadline", ping_person: "chat-dots", ping_project: "chat-dots", ping_blocker: "bell", dm_person: "letter", keep: "danger" };
function logItem(x) {
  const group = x.origin === "guruh", warn = x.type === "keep";
  const pill = group ? `<span class="pill p-l1 sm">${I("people")}Guruhda</span>`
    : x.sent ? `<span class="pill p-ok sm">${I("send")}${esc(x.note || "Yuborildi")}</span>` : `<span class="pill p-l1 sm">Panelda</span>`;
  const note = group || !x.sent ? x.note : "";
  return `<div class="log-i"><span class="ic ${warn ? "lv2" : "lv0"}" ${warn ? "" : `style="--ls:var(--azure-soft);--lc:var(--azure)"`}>${I(LOG_ICON[x.type] || "check")}</span>
    <div><b>${esc(x.title)}</b><span>${clock(x.created_at)}${note ? ", " + esc(note) : ""}</span></div>${pill}</div>`;
}

/* ================= 2. Ofis ================= */
function renderOffice(d) {
  const el = $("#v-ofis");
  const people = d.people.map((p) => Object.assign({}, p, { color: deptColor(p.department) }));
  const states = countStates(people);
  const key = S.version + "|" + query() + "|" + document.documentElement.dataset.theme;
  if (!$("#stage", el)) {
    el.innerHTML = pageHead("Ofis", "") + `<div class="office">
      <section class="card stage" id="stage"><div class="stage-top" id="otop"></div>
        <div class="stage-tools"><button class="icon-btn" id="oIn" title="Yaqinlashtirish">${I("zoom-in")}</button>
          <button class="icon-btn" id="oOut" title="Uzoqlashtirish">${I("zoom-out")}</button><button class="icon-btn" id="oFit" title="Hammasi">${I("fit")}</button></div>
        <div id="scene" style="position:absolute;inset:0"></div></section>
      <section class="card side"><div class="ch"><h3>E'tibor kerak</h3><span class="count" id="oCount"></span></div>
        <div class="cb" style="padding-bottom:4px" id="oBar"></div><div class="plist" id="oList"></div></section></div>`;
    S.office = Office.create($("#scene"), {
      onPick: (p) => { officePick(p.name); openPerson(p.name); },
      onHover: (p, e) => (p ? showTip(personTip(p), e, e.target.closest && e.target.closest(".ws")) : hideTip()),
    });
    $("#oIn").onclick = () => S.office.zoomIn();
    $("#oOut").onclick = () => S.office.zoomOut();
    $("#oFit").onclick = () => S.office.fit();
    S.officeKey = "";
  }
  const ph = $(".ph", el);
  ph.outerHTML = pageHead("Ofis", `${people.length} xodim, ${new Set(people.map((p) => p.department)).size} bo'lim, ${esc(periodText(d))}`);
  bindHead(el);
  const depts = [...new Set(people.map((p) => p.department))];
  $("#otop").innerHTML = depts.map((x) => `<button class="chip" data-od="${esc(x)}" aria-pressed="${S.officeDept === x}">${esc(x)}</button>`).join("")
    + `<span style="width:8px"></span>` + stateChips(states, S.officeState, "office");
  $$("#otop [data-od]").forEach((b) => b.onclick = () => { S.officeDept = S.officeDept === b.dataset.od ? "" : b.dataset.od; S.officeState = ""; officeFilter(); renderOffice(S.data); });
  $$("#otop [data-os]").forEach((b) => b.onclick = () => { S.officeState = S.officeState === b.dataset.os ? "" : b.dataset.os; S.officeDept = ""; officeFilter(); renderOffice(S.data); });
  const attention = people.filter((p) => p.state !== "ok").sort(byAttention);
  $("#oCount").textContent = attention.length;
  $("#oBar").innerHTML = stateBar(states);
  $("#oList").innerHTML = attention.map((p) => `<div class="prow" data-focus="${esc(p.name)}">${ava(p.name, p.department, p.state)}
      <div><b>${esc(p.name)}</b><span>${esc(p.fact)}</span></div>${statePill(p.state, "", true)}</div>`).join("") || emptyBox("Hamma me'yorida ishlayapti");
  $$("#oList [data-focus]").forEach((r) => r.onclick = () => {
    if (innerWidth < 1100) $("#stage").scrollIntoView({ behavior: "smooth", block: "center" });
    officePick(r.dataset.focus);
    setTimeout(() => openPerson(r.dataset.focus), innerWidth < 1100 ? 900 : 250);
  });
  if (S.officeKey !== key) { S.office.draw(people); S.officeKey = key; }
  officeFilter();
}
// Tanlangan xodim sahnada ajralib turadi va yon oyna yopmaydigan qismga suriladi
function officePick(name) {
  if (!S.office) return;
  S.office.select(name);
  S.office.focus(name, { right: innerWidth >= 1100 ? Math.min(600, innerWidth) : 0 });
}
function officeFilter() {
  if (!S.office) return;
  if (S.officeDept) S.office.filter(S.officeDept);
  else if (S.officeState) S.office.filter((p) => p.state === S.officeState);
  else S.office.filter(null);
}
function stateBar(c) {
  return `<div class="sbar">${STATE_ORDER.filter((k) => c[k]).map((k) => `<span class="c-${k}" style="flex:${c[k]}" title="${STATE[k].label}: ${c[k]}"></span>`).join("")}</div>`;
}
const byAttention = (a, b) => STATE[a.state].order - STATE[b.state].order || (a.score ?? 100) - (b.score ?? 100);
function personTip(p) {
  const t = p.open_tasks[0];
  return `<b>${esc(p.name)}</b><div class="row">${statePill(p.state, p.fact, true)}</div>
    <div class="row">${I(DEPT_ICON[p.department] || "user")}${esc(p.department)}${p.score != null ? `, baho <b style="display:inline;font-size:13px">${p.score}</b>` : ""}</div>
    ${t ? `<div class="row">${I("clock")}<span>${esc(t.title)}, ${dueText(t)}</span></div>` : ""}`;
}

/* ================= 3. Xodimlar ================= */
function renderPeople(d) {
  const el = $("#v-xodimlar"), f = S.pf, c = countStates(d.people);
  const depts = [...new Set(d.people.map((p) => p.department))];
  const scored = d.people.filter((p) => p.score != null).sort((a, b) => b.score - a.score);
  const best = scored[0], worst = scored[scored.length - 1];
  const avg = scored.length ? Math.round(scored.reduce((a, p) => a + p.score, 0) / scored.length) : null;
  const sorts = {
    attention: byAttention, score: (a, b) => (b.score ?? -1) - (a.score ?? -1), low: (a, b) => (a.score ?? 101) - (b.score ?? 101),
    load: (a, b) => b.open - a.open, oldest: (a, b) => b.oldest - a.oldest,
  };
  const list = d.people.filter((p) => (!f.dept || p.department === f.dept) && (!f.state || p.state === f.state)
    && (!f.q || p.name.toLowerCase().includes(f.q.toLowerCase()))).sort(sorts[f.sort]);
  const maxOpen = Math.max(8, ...d.people.map((p) => p.open));
  el.innerHTML = pageHead("Xodimlar", `${d.people.length} xodim, ${esc(periodText(d))}`) + `
    <div class="minis">
      ${miniTile("fire", "lv3", c.overloaded, "Ishi ko'p", "overloaded")}
      ${miniTile("cup", "lv1", c.idle, "Bo'sh, ish berish mumkin", "idle")}
      ${best ? miniTile("cup-star", "lv0", esc(first(best.name)) + ", " + best.score, "Eng samarali", "", best.name) : ""}
      ${worst && worst !== best ? miniTile("graph-down", "lv2", esc(first(worst.name)) + ", " + worst.score, "Eng past samaradorlik", "", worst.name) : miniTile("chart", "lv0", avg ?? "—", "O'rtacha baho")}
    </div>
    <div class="toolbar">
      <label class="searchbox">${I("search")}<input id="pq" type="search" placeholder="Xodimni qidirish" value="${esc(f.q)}" autocomplete="off"></label>
      <span class="vsep"></span>
      ${depts.map((x) => `<button class="chip" data-pd="${esc(x)}" aria-pressed="${f.dept === x}">${esc(x)}</button>`).join("")}
      <span class="vsep"></span>${stateChips(c, f.state, "people")}
      ${canAct() ? `<button class="ctl" id="pLinks" style="margin-left:auto">${I("user-plus")}Botga ulash</button>` : ""}
      <select class="ctl" id="psort">
        <option value="attention">Avval muammolilar</option><option value="score">Baho bo'yicha</option><option value="low">Baho: pastdan</option>
        <option value="load">Ochiq vazifa ko'p</option><option value="oldest">Eng eski vazifa</option></select>
    </div>
    <div class="pgrid">${list.map((p) => personCard(p, maxOpen)).join("") || `<div class="card" style="grid-column:1/-1">${emptyBox("Bu filtrga mos xodim yo'q", "search")}</div>`}</div>`;
  bindHead(el);
  $("#psort").value = f.sort;
  const links = $("#pLinks"); if (links) links.onclick = openLinks;
  $("#psort").onchange = (e) => { f.sort = e.target.value; renderPeople(S.data); };
  const q = $("#pq");
  q.oninput = () => { f.q = q.value; clearTimeout(q._t); q._t = setTimeout(() => { renderPeople(S.data); const n = $("#pq"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }, 160); };
  $$("[data-pd]", el).forEach((b) => b.onclick = () => { f.dept = f.dept === b.dataset.pd ? "" : b.dataset.pd; renderPeople(S.data); });
  $$("[data-ps]", el).forEach((b) => b.onclick = () => { f.state = f.state === b.dataset.ps ? "" : b.dataset.ps; renderPeople(S.data); });
  $$("[data-mini]", el).forEach((b) => b.onclick = () => { f.state = f.state === b.dataset.mini ? "" : b.dataset.mini; renderPeople(S.data); });
  bindCommon(el);
  countUp(el, "xodimlar");
}
function miniTile(icon, lv, value, label, filter, person) {
  const attr = person ? `data-person="${esc(person)}"` : filter ? `data-mini="${filter}"` : "";
  return `<div class="card mini ${attr ? "lift" : ""} ${lv}" ${attr}><span class="ic">${I(icon)}</span><div style="min-width:0"><b>${value}</b><span>${label}</span></div></div>`;
}
function personCard(p, maxOpen) {
  const lc = p.state === "overloaded" ? "var(--risk)" : p.open === 0 ? "var(--idle)" : "var(--azure)";
  return `<article class="card pc lift" data-person="${esc(p.name)}">
    <div class="pc-h"><span class="ava-wrap">${ava(p.name, p.department, p.state, "md")}${p.role === "rahbar" ? `<span class="ava-crown" title="Rahbar">${I("crown")}</span>` : ""}</span>
      <div class="who"><b>${esc(p.name)}</b><span class="dept">${esc(p.department)}${p.grade ? ", " + p.grade : ""}</span></div>
      ${scoreRing(p.score)}</div>
    <div>${statePill(p.state, p.fact)}</div>
    <div class="mets"><div><b class="num">${p.open}</b><span>ochiq</span></div><div><b class="num">${p.done}</b><span>bajardi</span></div>
      <div><b class="num">${p.cycle != null ? nf(p.cycle, 1) : "—"}</b><span>kunda 1 ta</span></div></div>
    <div class="load"><div class="bar"><i style="width:${Math.round((100 * p.open) / maxOpen)}%;background:${lc}"></i></div></div>
    ${p.open_tasks.length ? `<div class="tl">${p.open_tasks.slice(0, 2).map((t) => `<div class="tr"><span title="${esc(t.title)}">${esc(t.title)}</span>${dueTag(t)}</div>`).join("")}</div>` : ""}
  </article>`;
}

/* ================= 4. Loyihalar ================= */
function renderProjects(d) {
  const el = $("#v-loyihalar"), s = S.prSort;
  const rows = d.projects.slice().sort((a, b) => {
    let x = a[s.key], y = b[s.key];
    if (x == null) x = s.asc ? Infinity : -Infinity;
    if (y == null) y = s.asc ? Infinity : -Infinity;
    const r = typeof x === "string" ? x.localeCompare(y) : x - y;
    return s.asc ? r : -r;
  });
  const blockers = d.projects.flatMap((p) => p.blocker_list.map((b) => ({ ...b, project: p.name, id: p.id })));
  const th = (key, label, cls = "") => `<th data-sort="${key}" class="${cls} ${s.key === key ? "on" + (s.asc ? " asc" : "") : ""}">${label}</th>`;
  el.innerHTML = pageHead("Loyihalar", `${d.projects.length} loyiha, ${esc(periodText(d))}`) + `
    <div class="grid">
      <section class="card s12"><div class="cb" style="padding-top:8px"><div class="tw"><table class="t cards"><thead><tr>
        ${th("name", "Loyiha")}${th("start_date", "Yo'l", "hide-m")}${th("progress", "Bajarilgan")}${th("days_left", "Muddat")}${th("late_days", "Prognoz", "hide-m")}${th("level", "Holat")}
        </tr></thead><tbody>${rows.map((p) => `<tr data-project="${p.id}">
          <td class="pname"><b>${esc(p.name)}</b><span>${p.risks[0] ? esc(p.risks[0].text) : esc(p.chat_title || "")}</span></td>
          <td class="hide-m road-cell">${trackOnly(p, d)}</td>
          <td><b class="num" style="font:650 16px var(--display)">${p.progress}%</b><div style="font-size:12px;color:var(--ink-3)">${p.open_total} ta ochiq</div></td>
          <td>${p.deadline ? `<b style="font-weight:600">${esc(p.deadline_label)}</b><div style="font-size:12px;color:${p.days_left < 0 ? "var(--risk-ink)" : p.days_left <= 3 ? "var(--warn-ink)" : "var(--ink-3)"}">${p.days_left < 0 ? -p.days_left + " kun o'tdi" : p.days_left + " kun qoldi"}</div>` : `<span style="color:var(--ink-3)">—</span>`}</td>
          <td class="hide-m">${p.eta_label ? `<b style="font-weight:600">${esc(p.eta_label)}</b><div style="font-size:12px;color:${p.late_days ? "var(--risk-ink)" : "var(--ok-ink)"}">${p.late_days ? p.late_days + " kun kech" : "o'z vaqtida"}</div>` : "—"}</td>
          <td>${levelPill(p.level)}</td></tr>`).join("")}</tbody></table></div></div></section>
      <section class="card s6"><div class="ch"><h3>Ochiq muammolar</h3><span class="count">${blockers.length}</span></div>
        <div class="cb"><div class="why">${blockers.map((b) => `<div class="why-i lv${b.age >= 3 ? 3 : 2}" data-project="${b.id}" style="cursor:pointer"><div><b>${esc(b.project)}, ${b.age} kun</b>${esc(b.text)}</div></div>`).join("") || emptyBox("Ochiq muammo yo'q")}</div></div></section>
      <section class="card s6"><div class="ch"><h3>Kam faol loyihalar</h3><span class="count">${d.low_activity.length}</span></div>
        <div class="cb"><div class="why">${d.low_activity.map((x) => `<div class="why-i lv1" data-project="${x.id}" style="cursor:pointer"><div><b>${esc(x.name)}</b>${x.created} ta vazifa, o'rtacha ${nf(x.median, 1)}</div></div>`).join("") || emptyBox("Hamma loyihada ish bir maromda")}</div></div></section>
    </div>`;
  bindHead(el);
  $$("th[data-sort]", el).forEach((h) => h.onclick = (e) => {
    e.stopPropagation();
    if (s.key === h.dataset.sort) s.asc = !s.asc; else { s.key = h.dataset.sort; s.asc = ["name", "days_left", "start_date"].includes(h.dataset.sort); }
    renderProjects(S.data);
  });
  bindCommon(el);
}
function trackOnly(p, d) { const html = roadRow(p, d); return html.slice(html.indexOf('<div class="track'), html.lastIndexOf("</div>")); }

/* ================= 5. Bo'limlar ================= */
function renderDepts(d) {
  const el = $("#v-bolimlar");
  el.innerHTML = pageHead("Bo'limlar", `${d.departments.length} bo'lim, ${esc(periodText(d))}`) + `
    <div class="grid">
      <section class="card s12"><div class="ch"><h3>Taqqoslama</h3><div class="right road-legend"><span><i class="o" style="border:0;background:var(--azure)"></i>Bajarildi</span><span><i class="o" style="border:0;background:var(--surface-3)"></i>Ochiq</span></div></div>
        <div class="cb"><div style="height:${Math.max(200, d.departments.length * 50)}px"><canvas id="cDept"></canvas></div></div></section>
      <div class="s12 dgrid">${d.departments.map((x) => deptCard(x, d.people.filter((p) => p.department === x.name))).join("")}</div>
    </div>`;
  bindHead(el);
  drawDepts($("#cDept"), d.departments);
  bindCommon(el);
}
function deptCard(x, ppl) {
  const best = ppl.filter((p) => p.score != null).sort((a, b) => b.score - a.score)[0];
  return `<article class="card dc">
    <div class="dc-h"><span class="dico">${I(DEPT_ICON[x.name] || "user")}</span><div><b>${esc(x.name)}</b><span>${x.count} xodim</span></div><div style="margin-left:auto">${scoreRing(x.score)}</div></div>
    <div class="dstats"><div><b class="num">${x.open}</b><span>ochiq</span></div><div><b class="num">${x.created}</b><span>yangi</span></div>
      <div><b class="num">${x.done}</b><span>bajarildi</span></div><div><b class="num">${x.pct == null ? "—" : x.pct + "%"}</b><span>bajarilish</span></div></div>
    <div class="dbody">${stateBar(x.states)}
      <div class="plist">${ppl.sort(byAttention).map((p) => `<div class="prow" data-person="${esc(p.name)}">${ava(p.name, p.department, p.state)}
        <div><b>${esc(p.name)}${best && best.name === p.name ? ` <span class="pill p-ok sm" style="margin-left:4px">${I("cup-star")}eng yaxshi</span>` : ""}</b><span>${esc(p.fact)}</span></div>${scoreRing(p.score)}</div>`).join("")}</div>
    </div></article>`;
}

/* ================= grafiklar ================= */
function css() {
  const g = getComputedStyle(document.documentElement), v = (n) => g.getPropertyValue(n).trim();
  return { brand: v("--azure"), brand2: v("--ink"), ok: v("--ok"), ink: v("--ink"), ink3: v("--muted"), line: v("--line"), surface: v("--surface"), s3: v("--surface-3") };
}
function rgba(hex, a) { const n = parseInt(hex.replace("#", ""), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; }
function chartBase(c) {
  return {
    responsive: true, maintainAspectRatio: false, animation: { duration: 700, easing: "easeOutQuart" }, interaction: { mode: "index", intersect: false },
    plugins: { legend: { display: false }, tooltip: { backgroundColor: c.ink, titleColor: c.surface, bodyColor: c.surface, padding: 11, cornerRadius: 3, boxPadding: 5, titleFont: { family: "Onest", weight: "600" }, bodyFont: { family: "Onest" } } },
  };
}
const axis = (c, extra) => Object.assign({ grid: { color: c.line }, border: { display: false }, ticks: { color: c.ink3, font: { size: 11, family: "Onest" } } }, extra || {});
function drawTrend(canvas, series) {
  if (!canvas || !window.Chart) return;
  S.charts.trend?.destroy();
  const c = css(), g = canvas.getContext("2d").createLinearGradient(0, 0, 0, 280);
  g.addColorStop(0, rgba(c.ok, 0.22)); g.addColorStop(1, rgba(c.ok, 0));
  S.charts.trend = new Chart(canvas, {
    data: { labels: series.map((s) => s.label), datasets: [
      { type: "bar", label: "Yangi", data: series.map((s) => s.created), backgroundColor: rgba(c.brand, 0.16), hoverBackgroundColor: rgba(c.brand, 0.3), borderRadius: 2, maxBarThickness: 26, order: 2 },
      { type: "line", label: "Bajarildi", data: series.map((s) => s.done), borderColor: c.ok, backgroundColor: g, fill: true, cubicInterpolationMode: "monotone", pointRadius: 0, pointHoverRadius: 5, pointBackgroundColor: c.ok, borderWidth: 2.6, order: 1 },
    ] },
    options: Object.assign(chartBase(c), { scales: {
      x: axis(c, { grid: { display: false }, ticks: { color: c.ink3, maxRotation: 0, autoSkip: true, maxTicksLimit: 10, font: { size: 11 } } }),
      y: axis(c, { beginAtZero: true, ticks: { color: c.ink3, precision: 0, maxTicksLimit: 5, font: { size: 11 } } }) } }),
  });
}
function drawDepts(canvas, depts) {
  if (!canvas || !window.Chart) return;
  S.charts.dept?.destroy();
  const c = css();
  S.charts.dept = new Chart(canvas, {
    type: "bar",
    data: { labels: depts.map((x) => x.name), datasets: [
      { label: "Bajarildi", data: depts.map((x) => x.done), backgroundColor: c.brand, borderRadius: 2, maxBarThickness: 24 },
      { label: "Ochiq", data: depts.map((x) => x.open), backgroundColor: c.s3, borderRadius: 2, maxBarThickness: 24 } ] },
    options: Object.assign(chartBase(c), { indexAxis: "y", scales: {
      x: axis(c, { stacked: true, ticks: { color: c.ink3, precision: 0 } }),
      y: axis(c, { stacked: true, grid: { display: false }, ticks: { color: c.ink, font: { size: 13, weight: "600", family: "Onest" } } }) } }),
  });
}
function drawBars(canvas, series, color) {
  if (!canvas || !window.Chart) return null;
  const c = css();
  return new Chart(canvas, {
    type: "bar",
    data: { labels: series.map((s) => s.label), datasets: [{ label: "Bajarildi", data: series.map((s) => s.done), backgroundColor: series.map((s) => (s.weekend ? c.s3 : color)), borderRadius: 2, maxBarThickness: 18 }] },
    options: Object.assign(chartBase(c), { scales: {
      x: axis(c, { grid: { display: false }, ticks: { color: c.ink3, maxRotation: 0, autoSkip: true, maxTicksLimit: 7, font: { size: 10.5 } } }),
      y: axis(c, { beginAtZero: true, ticks: { color: c.ink3, precision: 0, maxTicksLimit: 4 } }) } }),
  });
}
function drawRadar(canvas, p) {
  if (!canvas || !window.Chart || !p.score_parts) return null;
  const c = css(), sp = p.score_parts;
  const vals = [p.completion ?? 0, Math.round((sp.speed / 25) * 100), p.regular ?? 0, Math.round((sp.fresh / 15) * 100)];
  return new Chart(canvas, {
    type: "radar",
    data: { labels: ["Bajarish", "Tezlik", "Muntazamlik", "Eskirmagan"], datasets: [{ data: vals, backgroundColor: rgba(c.brand, 0.16), borderColor: c.brand, borderWidth: 2, pointBackgroundColor: c.brand, pointRadius: 3 }] },
    options: Object.assign(chartBase(c), { interaction: { mode: "nearest", intersect: true }, scales: { r: { min: 0, max: 100, ticks: { display: false, stepSize: 25 }, grid: { color: c.line }, angleLines: { color: c.line },
      pointLabels: { color: c.ink, font: { size: 11.5, weight: "600", family: "Onest" } } } } }),
  });
}

/* ================= yon oyna: xodim ================= */
async function openPerson(name) {
  S.open = "p:" + name; writeHash();
  openDrawer(skelHead());
  let d;
  try { d = await api("api/person?" + new URLSearchParams({ name }) + "&" + query()); } catch (e) { closeDrawer(); toast(esc(e.message), "danger"); return; }
  const p = d.person, sp = p.score_parts;
  const bd = sp ? [
    ["Vazifani bajarish", sp.completion, 40, `30 kunda olgan vazifalarining ${p.completion}% ini yopgan (jamoada o'rtacha ${d.team_avg.completion}%)`],
    ["Tezlik", sp.speed, 25, p.cycle != null ? `Bitta vazifaga o'rtacha ${nf(p.cycle, 1)} kun` : "Hali yopilgan vazifa yo'q"],
    ["Muntazam hisobot", sp.regular, 20, `14 kunning ish kunlarida ${p.regular}% hisobot bergan (o'rtacha ${d.team_avg.regular}%)`],
    ["Eskirgan vazifa yo'qligi", sp.fresh, 15, p.stale ? `${p.stale} ta vazifa 7 kundan ortiq ochiq` : "7 kundan eski ochiq vazifa yo'q"],
  ] : [];
  const depts = [...new Set([...(d.departments || []), p.department])].filter((x) => x !== "Belgilanmagan");
  $("#drawer .sheet").innerHTML = `
    <div class="sh-head">${ava(p.name, p.department, p.state, "lg")}
      <div style="min-width:0"><div class="name-row"><h2>${esc(p.name)}${["rahbar", "admin"].includes(p.role) ? I("crown", "crown") : ""}</h2>${p.id && !S.asof && canAct() ? `<button class="icon-btn name-edit" id="nameBtn" title="Ism-familiyani yozish" aria-label="Ism-familiyani yozish">${I("pen")}</button>` : ""}</div><div class="meta">${statePill(p.state, p.fact, true)}
        ${p.id && canAct() ? `<select class="ctl" id="deptSel" style="height:28px;font-size:12.5px;padding-left:10px">${p.department === "Belgilanmagan" ? `<option value="">Bo'lim tanlang</option>` : ""}${depts.map((x) => `<option ${x === p.department ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>` : `<span>${esc(p.department)}</span>`}
        ${p.id && !S.asof && isRole("admin") ? `<select class="ctl" id="roleSel" title="Rol: panelga kirish huquqi va Telegramda vazifa berish" style="height:28px;font-size:12.5px;padding-left:10px">
          ${[["", "Rolsiz"], ["menejer", "Loyiha menejeri"], ["rahbar", "Rahbar"], ["admin", "Admin"]].map(([v, t]) => `<option value="${v}" ${(p.role || "") === v ? "selected" : ""}>${t}</option>`).join("")}</select>`
          : p.role ? `<span class="pill p-ok sm">${esc(ROLE_NAMES[p.role] || p.role)}</span>` : ""}
        ${p.username ? `<span>@${esc(p.username)}</span>` : ""}</div></div>
      <button class="icon-btn x" aria-label="Yopish">${I("close")}</button></div>
    <div class="sh-body">
      ${S.asof || !canAct() ? "" : `<div class="sh-acts">${p.open ? `<button class="btn btn-dark" id="pMove">${I("transfer")}Vazifa o'tkazish</button>` : ""}
        <button class="btn btn-line" id="pPing">${I("chat-dots")}Holatini so'rash</button></div>`}
      ${S.asof || !canAct() ? "" : `<section class="card"><div class="ch"><h3>Shaxsiy aloqa</h3></div><div class="cb" id="pContact"><div class="sk" style="height:36px"></div></div></section>`}
      <div class="tiles"><div class="tile"><b class="num">${p.open}</b><span>ochiq</span></div><div class="tile"><b class="num">${p.done}</b><span>bajardi</span></div>
        <div class="tile"><b class="num">${p.completion == null ? "—" : p.completion + "%"}</b><span>bajarish, 30 kun</span></div>
        <div class="tile"><b class="num">${p.cycle == null ? "—" : nf(p.cycle, 1)}</b><span>kunda 1 vazifa</span></div></div>
      <section class="card"><div class="cb"><div class="scorebox">${scoreRing(p.score, "xl")}
        <div><b style="font:640 17px var(--display)">${p.grade ? p.grade : "Baho uchun ma'lumot kam"}</b>
          <div style="font-size:13px;color:var(--ink-3);margin-top:2px">${p.score != null ? "100 ball" : "30 kunda kamida 3 ta vazifa kerak"}</div></div></div>
        ${sp ? `<div class="radar-row"><div style="height:200px"><canvas id="cRadar"></canvas></div>
          <div class="bd">${bd.map((r) => `<div class="bd-row" title="${esc(r[3])}"><span>${r[0]}</span><b>${r[1]}/${r[2]}</b><div class="bar"><i style="width:${Math.round((100 * r[1]) / r[2])}%"></i></div></div>`).join("")}</div></div>` : ""}
      </div></section>
      <section class="card"><div class="ch"><h3>Bajargan ishi</h3><span class="count">14 kun</span></div><div class="cb"><div style="height:150px"><canvas id="cPerson"></canvas></div></div></section>
      <section class="card"><div class="ch"><h3>Ochiq vazifalari</h3><span class="count">${p.open}</span></div>
        <div class="cb" style="padding-top:4px">${p.open_tasks.map((t) => `<div class="task"><span>${esc(t.title)}</span>${dueTag(t)}<small>${esc(t.project || "")}, ${clock(t.created_at)}${t.giver ? `, ${esc(first(t.giver))} berdi` : ""}</small></div>`).join("") || emptyBox("Ochiq vazifa yo'q")}</div></section>
      <section class="card"><div class="ch"><h3>Bajargan ishlari</h3><span class="count">${d.done_tasks.length}</span></div>
        <div class="cb" style="padding-top:4px">${d.done_tasks.map((t) => `<div class="task"><span>${esc(t.title)}</span><span class="age new">${nf(t.days, 1)} kunda</span><small>${esc(t.project || "")}, ${clock(t.done_at)}</small></div>`).join("") || emptyBox("Bu davrda yopilgan vazifa yo'q", "clock")}</div></section>
    </div>`;
  $("#drawer .x").onclick = closeDrawer;
  S.charts.person?.destroy(); S.charts.radar?.destroy();
  S.charts.person = drawBars($("#cPerson"), d.series, css().ok);
  S.charts.radar = drawRadar($("#cRadar"), p);
  const sel = $("#deptSel");
  if (sel) sel.onchange = async () => {
    try { await api("api/person/department", { json: { name: p.name, department: sel.value } }); toast(`${esc(first(p.name))}: ${esc(sel.value)}`, "check"); S.officeKey = ""; load(true); }
    catch (e) { toast(esc(e.message), "danger"); }
  };
  $("#pMove")?.addEventListener("click", () => openMove(p));
  $("#nameBtn")?.addEventListener("click", () => {
    const row = $("#drawer .name-row");
    row.innerHTML = `<form class="name-form"><input class="ctl" id="nameIn" value="${esc(p.name)}" maxlength="60" placeholder="Ism Familiya" autocomplete="off"><button class="btn btn-dark">Saqlash</button></form>`;
    const inp = $("#nameIn"); inp.focus(); inp.select();
    inp.onkeydown = (e) => { if (e.key === "Escape") openPerson(p.name); };
    row.querySelector("form").onsubmit = async (e) => {
      e.preventDefault();
      try { const r = await api("api/person/name", { json: { name: p.name, new_name: inp.value } });
        toast(`Ism saqlandi: ${esc(r.name)}`, "check"); S.officeKey = ""; await load(true); openPerson(r.name); }
      catch (err) { toast(esc(err.message), "danger"); }
    };
  });
  $("#roleSel")?.addEventListener("change", async (e) => {
    const role = e.target.value;
    try { await api("api/person/role", { json: { name: p.name, role } });
      toast(role ? `${esc(first(p.name))}: ${esc(ROLE_NAMES[role])}` : `${esc(first(p.name))} rolsiz`, "check"); load(true); }
    catch (err) { toast(esc(err.message), "danger"); openPerson(p.name); }
  });
  if (!S.asof && canAct()) loadContact(p);
  $("#pPing")?.addEventListener("click", () => openAction({ type: "ping_person", name: p.name }));
}

/* ================= yon oyna: loyiha ================= */
async function openProject(id) {
  S.open = "j:" + id; writeHash();
  openDrawer(skelHead());
  let d;
  try { d = await api(`api/project/${id}?` + query().replace(/&?chat=[^&]*/, "")); } catch (e) { closeDrawer(); toast(esc(e.message), "danger"); return; }
  const p = d.project;
  $("#drawer .sheet").innerHTML = `
    <div class="sh-head"><span class="ic lv${p.level}" style="width:52px;height:52px;border-radius:16px">${I("projects")}</span>
      <div style="min-width:0"><h2>${esc(p.name)}</h2><div class="meta">${levelPill(p.level, true)}<span>${esc(p.chat_title || "")}</span></div></div>
      <button class="icon-btn x" aria-label="Yopish">${I("close")}</button></div>
    <div class="sh-body">
      ${S.asof || !canAct() ? "" : `<div class="sh-acts"><button class="btn btn-dark" id="prDl">${I("deadline")}Muddatni o'zgartirish</button>
        <button class="btn btn-line" id="prPing">${I("chat-dots")}Holatni so'rash</button>
        ${p.blocker_list.length ? `<button class="btn btn-line" id="prBl">${I("bell")}Muammo bo'yicha eslatish</button>` : ""}</div>`}
      <div class="tiles"><div class="tile"><b class="num">${p.progress}%</b><span>bajarilgan</span></div><div class="tile"><b class="num">${p.open_total}</b><span>ochiq</span></div>
        <div class="tile"><b class="dt">${p.deadline_label ? esc(p.deadline_label) : "—"}</b><span>${p.deadline ? (p.days_left < 0 ? -p.days_left + " kun o'tdi" : p.days_left + " kun qoldi") : "muddat"}</span></div>
        <div class="tile"><b class="dt" style="color:${p.late_days ? "var(--risk-ink)" : "inherit"}">${p.eta_label ? esc(p.eta_label) : "—"}</b><span>${p.late_days ? p.late_days + " kun kech" : "prognoz"}</span></div></div>
      <section class="card"><div class="cb" style="padding-top:26px">${roadRow(p, S.data || { now: d.period.to + " 12:00:00", period: d.period }, true)}</div></section>
      ${p.risks.length ? `<section class="card"><div class="ch"><h3>Nega shu holatda</h3></div><div class="cb"><div class="why">${p.risks.map((r) => `<div class="why-i lv${r.level}"><div><b>${LEVEL[r.level]}</b>${esc(r.text)}</div></div>`).join("")}</div></div></section>` : ""}
      <section class="card"><div class="ch"><h3>Dinamika</h3><span class="count">kuniga ${nf(p.velocity, 1)} ta</span></div><div class="cb"><div style="height:170px"><canvas id="cProject"></canvas></div></div></section>
      ${progressCard(d.team_progress)}
      ${can("tasks", "c") && !S.asof ? `<div class="sh-acts"><button class="btn btn-line" id="prTasks">${I("checklist")}Vazifalarni boshqarish</button></div>` : ""}
      <section class="card"><div class="ch"><h3>Jamoa</h3><span class="count">${d.team.length}</span></div>
        <div class="cb" style="padding-top:6px"><div class="plist">${d.team.map((x) => { const pp = (S.data?.people || []).find((q) => q.name === x.name);
          return `<div class="prow" data-person="${esc(x.name)}">${ava(x.name, pp?.department, pp?.state)}<div><b>${esc(x.name)}</b><span>${x.open} ochiq, ${x.done} bajardi</span></div>${pp ? statePill(pp.state, "", true) : "<span></span>"}</div>`; }).join("") || emptyBox("Jamoa hali aniqlanmagan", "people")}</div></div></section>
      <section class="card"><div class="ch"><h3>Ochiq vazifalar</h3><span class="count">${d.open_tasks.length}</span></div>
        <div class="cb" style="padding-top:4px">${d.open_tasks.slice(0, 40).map((t) => `<div class="task"><span>${esc(t.title)}</span>${dueTag(t)}<small>${esc(t.assignee || "")}${t.giver ? `, ${esc(first(t.giver))} berdi` : ""}</small></div>`).join("") || emptyBox("Ochiq vazifa yo'q")}</div></section>
    </div>`;
  $("#drawer .x").onclick = closeDrawer;
  bindCommon($("#drawer .sheet"));
  S.charts.project?.destroy();
  const cv = $("#cProject");
  if (cv && window.Chart) {
    const c = css();
    S.charts.project = new Chart(cv, {
      data: { labels: d.series.map((s) => s.label), datasets: [
        { type: "bar", label: "Yangi", data: d.series.map((s) => s.created), backgroundColor: rgba(c.brand, 0.18), borderRadius: 2, maxBarThickness: 18 },
        { type: "line", label: "Bajarildi", data: d.series.map((s) => s.done), borderColor: c.ok, cubicInterpolationMode: "monotone", pointRadius: 0, borderWidth: 2.4 } ] },
      options: Object.assign(chartBase(c), { scales: {
        x: axis(c, { grid: { display: false }, ticks: { color: c.ink3, maxRotation: 0, autoSkip: true, maxTicksLimit: 7, font: { size: 10.5 } } }),
        y: axis(c, { beginAtZero: true, ticks: { color: c.ink3, precision: 0, maxTicksLimit: 4 } }) } }),
    });
  }
  $("#prTasks")?.addEventListener("click", () => { closeDrawer(); DT.res = "tasks"; DT.q = ""; DT.page = 1; DT.order = ""; DT.filters = { project: String(p.id) }; $("#v-malumotlar").innerHTML = ""; go("malumotlar"); });
  const tomorrow7 = new Date(Date.now() + 7 * 864e5);
  $("#prDl")?.addEventListener("click", () => openAction({ type: "deadline", project_id: p.id, date: p.eta_date || isoDay(tomorrow7) }));
  $("#prPing")?.addEventListener("click", () => openAction({ type: "ping_project", project_id: p.id }));
  $("#prBl")?.addEventListener("click", () => openAction({ type: "ping_blocker", project_id: p.id }));
}

// Loyihada kim qaysi vazifani qay darajada qilgan: bajarilgan ulushi, muddati o'tganlar, o'rtacha muddat, o'z vaqtida; ochilsa vazifalari
const TASK_STATE = { done: ["p-ok", "Bajarilgan"], open: ["p-l2", "Ochiq"], taklif: ["p-l1", "Taklif"] };
function progressCard(rows) {
  if (!rows || !rows.length) return "";
  return `<section class="card"><div class="ch"><h3>Kim qancha qildi</h3><span class="count">${rows.length}</span></div>
    <div class="cb" style="padding-top:4px">${rows.map((x) => `<details class="tp"><summary>
      <span class="tp-n"><b>${esc(x.name)}</b><small>${x.done} / ${x.total} bajargan${x.overdue ? `, <em>${x.overdue} ta muddati o'tgan</em>` : ""}</small></span>
      <span class="tp-bar" title="${x.pct}% bajarilgan"><i style="width:${x.pct}%"></i></span><b class="tp-p num">${x.pct}%</b></summary>
      <div class="tp-st"><span>O'rtacha <b>${x.avg_days == null ? "—" : nf(x.avg_days, 1) + " kun"}</b></span><span>Muddatida <b>${x.on_time == null ? "—" : x.on_time + "%"}</b></span><span>Ochiq <b>${x.open}</b></span></div>
      ${x.tasks.map((t) => `<div class="task"><span>${esc(t.title)}</span><span class="pill ${TASK_STATE[t.status][0]} sm">${TASK_STATE[t.status][1]}</span>
        <small>${t.deadline ? "muddat " + esc(t.deadline) + ", " : ""}${t.status === "done" && t.done_at ? "bajarilgan " + clock(t.done_at) : "berilgan " + clock(t.created_at)}</small></div>`).join("")}
    </details>`).join("")}</div></section>`;
}
const skelHead = () => `<div class="sh-head"><div class="sk" style="width:56px;height:56px;border-radius:50%"></div><div style="flex:1"><div class="sk" style="height:20px;width:55%"></div><div class="sk" style="height:13px;width:35%;margin-top:9px"></div></div></div>
  <div class="sh-body"><div class="sk" style="height:84px"></div><div class="sk" style="height:220px"></div><div class="sk" style="height:160px"></div></div>`;
function openDrawer(html) {
  const dr = $("#drawer");
  $(".sheet", dr).innerHTML = html;
  $(".sheet", dr).scrollTop = 0;
  dr.classList.toggle("clear", S.tab === "ofis");
  dr.classList.add("open"); dr.setAttribute("aria-hidden", "false");
  hideTip();
}
function closeDrawer() {
  const dr = $("#drawer"); dr.classList.remove("open"); dr.setAttribute("aria-hidden", "true");
  if (S.office) S.office.select(null);
  if (S.open) { S.open = ""; writeHash(); }
}

/* ================= shaxsiy aloqa: havola va eslatma ================= */
async function loadContact(p, reset) {
  const box = $("#pContact");
  if (!box) return;
  let c;
  try { c = reset ? await api("api/person/link/reset", { json: { name: p.name } }) : await api("api/person/link?" + new URLSearchParams({ name: p.name })); }
  catch (e) { box.innerHTML = emptyBox(esc(e.message), "info"); return; }
  box.innerHTML = c.linked
    ? `<div class="contact"><span class="pill p-ok">${I("check")}Botga ulangan</span><span style="color:var(--muted);font-size:14px">${c.linked_at ? clock(c.linked_at) : ""}</span>
        <button class="btn btn-dark" id="cWrite" style="margin-left:auto">${I("letter")}Eslatma yozish</button>
        <button class="icon-btn" id="cReset" title="Havolani yangilash: eski havola va ulanish bekor bo'ladi">${I("refresh")}</button></div>`
    : `<div class="contact"><span class="pill p-idle">${I("lock")}Ulanmagan</span><span class="lnk" title="${esc(c.link)}">${esc(c.link)}</span>
        <button class="btn btn-dark" id="cCopy">${I("copy")}Xodimga yuborish uchun nusxalash</button>
        <button class="icon-btn" id="cReset" title="Yangi havola: eskisi ishlamay qoladi">${I("refresh")}</button></div>`;
  $("#cCopy")?.addEventListener("click", () => copyText(c.link, "Havola nusxalandi"));
  $("#cWrite")?.addEventListener("click", () => openCompose(p));
  $("#cReset")?.addEventListener("click", () => loadContact(p, true));
}
function copyText(text, done) {
  const ok = () => toast(done || "Nusxalandi", "copy");
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(ok, () => fallbackCopy(text, ok));
  else fallbackCopy(text, ok);
}
function fallbackCopy(text, ok) {
  const t = document.createElement("textarea");
  t.value = text; t.style.position = "fixed"; t.style.opacity = "0";
  document.body.appendChild(t); t.select();
  try { document.execCommand("copy"); ok(); } catch (e) { toast("Nusxalab bo'lmadi", "danger"); }
  t.remove();
}
function openCompose(p) {
  const t = p.open_tasks[0];
  const draft = `Assalomu alaykum, ${first(p.name)}!\n` + (p.open ? `Sizda ${p.open} ta ochiq vazifa bor${t ? `, eng eskisi «${t.title}» (${t.age} kun)` : ""}. Bugun holatini guruhga yozib bering.` : "Bugungi ishlaringiz haqida guruhga qisqa yozib bering.");
  openModal(`${esc(p.name)} ga eslatma`, `<div class="field"><label for="cmpText">Xabar</label><textarea id="cmpText">${esc(draft)}</textarea></div>`,
    `<button class="btn btn-ghost" data-close>Bekor qilish</button><button class="btn btn-dark" id="cmpGo">${I("send")}Ko'rib chiqish</button>`);
  $("#cmpGo").onclick = () => { const text = $("#cmpText").value.trim(); if (text) openAction({ type: "dm_person", name: p.name, text }); };
}
async function openLinks() {
  openModal("Xodimlarni botga ulash", `<div class="sk" style="height:200px"></div>`);
  let r;
  try { r = await api("api/links"); } catch (e) { closeModal(); toast(esc(e.message), "danger"); return; }
  const rows = r.people;
  const people = S.data?.people || [];
  const unlinked = rows.filter((x) => !x.linked);
  openModal("Xodimlarni botga ulash", rows.length ? `<div class="links">${rows.map((x, i) => { const pp = people.find((q) => q.name === x.name);
      return `<div class="link-row">${ava(x.name, pp?.department, pp?.state)}<div style="min-width:0"><b>${esc(x.name)}</b><span>${x.linked ? "Ulangan" : "Havolani yuboring"}</span></div>
        ${x.linked ? `<span class="pill p-ok sm">${I("check")}Ulangan</span>` : `<span class="pill p-idle sm">Ulanmagan</span>`}
        <button class="icon-btn" data-cp="${i}" title="Havolani nusxalash">${I("copy")}</button></div>`; }).join("")}</div>` : emptyBox("Xodimlar guruhga yozishi bilan shu yerda paydo bo'ladi", "people"),
    unlinked.length ? `<button class="btn btn-dark" id="cpAll">${I("copy")}Ulanmaganlar havolalarini nusxalash</button>` : "", true);
  $$("[data-cp]").forEach((b) => b.addEventListener("click", () => copyText(rows[+b.dataset.cp].link, `${first(rows[+b.dataset.cp].name)} havolasi nusxalandi`)));
  $("#cpAll")?.addEventListener("click", () => copyText(unlinked.map((x) => `${x.name}: ${x.link}`).join("\n"), `${unlinked.length} ta havola nusxalandi`));
}

/* ================= qaror: oldindan ko'rish va tasdiq ================= */
async function openAction(action) {
  openModal("", `<div class="sk" style="height:22px;width:60%"></div><div class="sk" style="height:120px;margin-top:14px"></div>`);
  let pv;
  try { pv = await api("api/actions/preview", { json: { action } }); } catch (e) { closeModal(); toast(esc(e.message), "danger"); return; }
  const people = S.data?.people || [];
  const pdept = (n) => people.find((p) => p.name === n);
  let body = "";
  if (action.type === "reassign") {
    const a = pdept(action.from), b = pdept(action.to);
    body += `<div class="flow"><div class="who">${ava(action.from, a?.department, a?.state)}<div><b>${esc(action.from)}</b><span>${a ? a.open + " ochiq" : ""}</span></div></div>
      <span class="arr">${I("arrow")}</span><div class="who">${ava(action.to, b?.department, b?.state)}<div><b>${esc(action.to)}</b><span>${b ? b.open + " ochiq" : ""}</span></div></div></div>
      <div class="checks">${pv.items.map((t, i) => `<label><input type="checkbox" data-tid="${pv.task_ids[i]}" checked>${esc(t)}</label>`).join("")}</div>`;
  }
  if (action.type === "deadline") {
    body += `<div class="field"><label for="dlIn">Yangi muddat</label><input type="date" id="dlIn" value="${esc(action.date)}"></div>`;
  }
  body += `<div class="tg"><div class="tg-b"><b>Puls</b>${esc(pv.message)}</div></div>
    <div class="note">${I(pv.will_send ? "send" : "info")}${esc(pv.note)}</div>`;
  openModal(esc(pv.title), body, `<button class="btn btn-ghost" data-close>Bekor qilish</button><button class="btn btn-dark" id="doAct">${I("check")}Tasdiqlash</button>`);
  $$("[data-tid]").forEach((c) => c.addEventListener("change", () => {
    action.task_ids = $$("[data-tid]").filter((x) => x.checked).map((x) => +x.dataset.tid);
    $("#doAct").disabled = !action.task_ids.length;
  }));
  $("#dlIn")?.addEventListener("change", (e) => { action.date = e.target.value; openAction(action); });
  $("#doAct").addEventListener("click", async () => {
    const b = $("#doAct"); b.disabled = true; b.innerHTML = I("refresh") + "Bajarilmoqda";
    try {
      const r = await api("api/actions/execute", { json: { action } });
      closeModal(); closeDrawer();
      toast(`<b>${esc(r.title)}</b>, ${esc(r.note)}`, r.sent ? "send" : "check");
      S.officeKey = ""; load(true);
    } catch (e) { b.disabled = false; b.innerHTML = I("check") + "Tasdiqlash"; toast(esc(e.message), "danger"); }
  });
}
function openMove(p) {
  const fits = new Set([p.department, ...(["Backend", "Frontend"].includes(p.department) ? ["Fullstack"] : [])]);
  const cands = (S.data?.people || []).filter((q) => q.name !== p.name).sort((a, b) => (fits.has(b.department) - fits.has(a.department)) || a.open - b.open);
  openModal(`${esc(first(p.name))}dan vazifa o'tkazish`, `
    <div class="field"><label for="mvTo">Kimga</label><select id="mvTo">${cands.map((q) => `<option value="${esc(q.name)}">${esc(q.name)}, ${esc(q.department)}, ${q.open} ochiq</option>`).join("")}</select></div>
    <div class="checks">${p.open_tasks.map((t, i) => `<label><input type="checkbox" data-mt="${t.id}" ${i >= p.open_tasks.length - 3 ? "checked" : ""}>${esc(t.title)} ${dueTag(t, "margin-left:auto")}</label>`).join("")}</div>`,
    `<button class="btn btn-ghost" data-close>Bekor qilish</button><button class="btn btn-dark" id="mvGo">${I("transfer")}Davom etish</button>`);
  $("#mvGo").onclick = () => {
    const ids = $$("[data-mt]").filter((x) => x.checked).map((x) => +x.dataset.mt);
    if (!ids.length) { toast("Kamida bitta vazifani belgilang", "info"); return; }
    openAction({ type: "reassign", from: p.name, to: $("#mvTo").value, task_ids: ids });
  };
}

/* ================= boshqa oynalar ================= */
function openModal(title, body, foot, wide) {
  const m = $("#modal");
  $(".mbox", m).className = "mbox" + (wide ? " wide" : "");
  $(".mbox", m).innerHTML = `${title !== null ? `<div class="mh"><h3>${title}</h3><button class="icon-btn x" data-close aria-label="Yopish">${I("close")}</button></div>` : ""}
    <div class="mb">${body}</div>${foot ? `<div class="mf">${foot}</div>` : ""}`;
  m.classList.add("open");
  $$("[data-close]", m).forEach((b) => (b.onclick = closeModal));
}
function closeModal() { $("#modal").classList.remove("open"); }


async function openSettings() {
  let s;
  try { s = await api("api/settings"); } catch (e) { toast(esc(e.message), "danger"); return; }
  openModal("Sozlamalar", s.schema.map((g) => `<div class="sgroup"><h4>${esc(g.group)}</h4>${g.items.map((it) => `<div class="srow"><span>${esc(it.label)}</span>
      ${it.type === "time" ? `<div class="stepper"><input type="time" data-set="${it.key}" value="${esc(s.values[it.key])}"></div>`
        : it.type === "choice" ? `<div class="seg" data-choice>${it.options.map((o) => `<button type="button" data-v="${esc(o.value)}" aria-pressed="${s.values[it.key] === o.value}">${esc(o.label)}</button>`).join("")}<input type="hidden" data-set="${it.key}" value="${esc(s.values[it.key])}"></div>`
        : `<div class="stepper"><button data-dec="${it.key}" aria-label="Kamaytirish">−</button><input type="number" data-set="${it.key}" value="${s.values[it.key]}" min="${it.min}" max="${it.max}" step="${it.step}"><button data-inc="${it.key}" aria-label="Oshirish">+</button></div>`}</div>`).join("")}</div>`).join(""),
    `<button class="btn btn-ghost" data-close>Bekor qilish</button><button class="btn btn-dark" id="setSave">${I("check")}Saqlash</button>`, true);
  const step = (k, dir) => { const inp = $(`[data-set="${k}"]`); const st = +inp.step || 1; inp.value = Math.round((+inp.value + dir * st) * 10) / 10; };
  $$("[data-dec]").forEach((b) => (b.onclick = () => step(b.dataset.dec, -1)));
  $$("[data-inc]").forEach((b) => (b.onclick = () => step(b.dataset.inc, 1)));
  $$("[data-choice]").forEach((g) => $$("button", g).forEach((b) => (b.onclick = () => {
    $$("button", g).forEach((x) => x.setAttribute("aria-pressed", x === b)); $("input", g).value = b.dataset.v; })));
  $("#setSave").onclick = async () => {
    const ch = {};
    $$("[data-set]").forEach((i) => { if (String(s.values[i.dataset.set]) !== i.value) ch[i.dataset.set] = i.value; });
    if (!Object.keys(ch).length) { closeModal(); return; }
    try { await api("api/settings", { method: "PUT", json: ch }); closeModal(); toast("Sozlamalar saqlandi", "check"); S.officeKey = ""; load(true); }
    catch (e) { toast(esc(e.message), "danger"); }
  };
}

function openFix(mid) {
  const f = (S.data?.feed || []).find((x) => String(x.id) === String(mid));
  if (!f) return;
  const kinds = [["task", "Vazifa"], ["done", "Bajarildi"], ["blocker", "Muammo"], ["none", "Ish xabari emas"]];
  let kind = f.kind === "deadline" ? "task" : f.kind;
  openModal("Xabarni to'g'rilash", `<div class="tg" style="margin-top:0"><div class="tg-b"><b>${esc(f.author || "")}</b>${esc(f.text)}</div></div>
    <div class="field"><label>Turi</label><div class="seg" id="fxKind" style="width:fit-content">${kinds.map((k) => `<button data-k="${k[0]}" aria-pressed="${kind === k[0]}">${k[1]}</button>`).join("")}</div></div>
    <div class="field"><label for="fxProj">Loyiha</label><select id="fxProj"><option value="">—</option>${(S.meta?.projects || []).map((p) => `<option value="${p.id}" ${p.id === f.project_id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></div>`,
    `<button class="btn btn-ghost" data-close>Bekor qilish</button><button class="btn btn-dark" id="fxSave">${I("check")}Saqlash</button>`);
  $$("#fxKind [data-k]").forEach((b) => (b.onclick = () => { kind = b.dataset.k; $$("#fxKind [data-k]").forEach((x) => x.setAttribute("aria-pressed", x === b)); }));
  $("#fxSave").onclick = async () => {
    const pid = $("#fxProj").value ? +$("#fxProj").value : null;
    try { const r = await api(`api/messages/${mid}/correct`, { json: { kind, project_id: pid } }); closeModal(); toast(`Saqlandi, o'qitish to'plamida ${r.corrections} ta tuzatish`, "check"); load(true); }
    catch (e) { toast(esc(e.message), "danger"); }
  };
}

function openRange() {
  const today = isoDay(new Date());
  openModal("Oraliq", `<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px"><div class="field"><label for="rS">Boshi</label><input type="date" id="rS" max="${today}" value="${S.start || isoDay(new Date(Date.now() - 13 * 864e5))}"></div>
    <div class="field"><label for="rE">Oxiri</label><input type="date" id="rE" max="${today}" value="${S.end || today}"></div></div>`,
    `<button class="btn btn-ghost" data-close>Bekor qilish</button><button class="btn btn-dark" id="rGo">${I("check")}Ko'rsatish</button>`);
  $("#rGo").onclick = () => { const s = $("#rS").value, e = $("#rE").value; if (!s || !e) return; S.period = "custom"; S.start = s; S.end = e; closeModal(); writeHash(); load(); };
}

function openGuide() {
  const rows = [["#task #Portal Login sahifasi @ali", "yangi vazifa"], ["#done #Portal Login sahifasi", "bajarildi"], ["#muammo #Portal Serverga ruxsat yo'q", "muammo"], ["#deadline #Portal 15.11.2026", "muddat"]];
  openModal("Guruhda yozish formati", rows.map((r) => `<div class="code"><span>${esc(r[0])}</span><small>${r[1]}</small><button class="icon-btn" data-copy="${esc(r[0])}" title="Nusxa" style="width:30px;height:30px">${I("copy")}</button></div>`).join("")
    + `<div class="note" style="margin-top:12px">${I("stars")}Teg qo'yilmasa ham AI tushunadi, bot: @${esc(S.meta?.bot || "puls_loyiha_bot")}</div>`);
  $$("[data-copy]").forEach((b) => (b.onclick = () => { navigator.clipboard?.writeText(b.dataset.copy); toast("Nusxa olindi", "copy"); }));
}
function openKeys() {
  openModal("Tezkor tugmalar", [["1 – 6", "bo'limlar"], ["Ctrl + K", "qidirish"], ["T", "yorug' / qorong'i"], ["Esc", "yopish"]].map((r) => `<div class="code"><span>${r[0]}</span><small>${r[1]}</small></div>`).join(""));
}
function openImport() {
  openModal("Guruh tarixini yuklash", `<label class="drop" id="drop">${I("upload")}<b style="color:var(--ink)">result.json</b><span>Telegram Desktop → Export chat history → JSON</span><input type="file" accept=".json,application/json" hidden id="file"></label>`);
  const drop = $("#drop"), input = $("#file");
  const send = async (file) => {
    if (!file) return;
    drop.innerHTML = `<div class="sk" style="height:14px;width:60%"></div><span>Yuklanmoqda</span>`;
    const fd = new FormData(); fd.append("file", file);
    try { const r = await api("api/import", { method: "POST", body: fd }); closeModal(); toast(`<b>${esc(r.chat)}</b>, ${r.added} ta xabar qo'shildi`, "check"); S.officeKey = ""; S.meta = await api("api/meta"); load(); }
    catch (e) { closeModal(); toast(esc(e.message), "danger"); }
  };
  input.onchange = () => send(input.files[0]);
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => send(e.dataTransfer.files[0]));
}
function openPalette() {
  if (!S.data) return;
  openModal(null, `<label class="searchbox" style="display:block">${I("search")}<input id="pal" placeholder="Xodim, loyiha yoki bo'lim" style="width:100%;height:46px;font-size:15px" autocomplete="off"></label><div class="plist" id="palList" style="max-height:56vh;overflow:auto;margin-top:10px"></div>`);
  const items = [
    ...S.data.people.map((p) => ({ t: p.name, s: p.department + ", " + STATE[p.state].label, ic: ava(p.name, p.department, p.state), act: () => openPerson(p.name) })),
    ...S.data.projects.map((p) => ({ t: p.name, s: "Loyiha, " + LEVEL[p.level], ic: `<span class="ic lv${p.level}" style="width:34px;height:34px;border-radius:10px">${I("projects")}</span>`, act: () => openProject(p.id) })),
    ...TABS.map((t) => ({ t: t[2], s: "Bo'lim", ic: `<span class="ic lv1" style="width:34px;height:34px;border-radius:10px">${I(t[3])}</span>`, act: () => go(t[0]) })),
  ];
  let sel = 0, shown = items;
  const draw = () => {
    $("#palList").innerHTML = shown.slice(0, 30).map((x, i) => `<div class="prow" data-i="${i}" style="${i === sel ? "background:var(--surface-3)" : ""}">${x.ic}<div><b>${esc(x.t)}</b><span>${esc(x.s)}</span></div><span></span></div>`).join("") || emptyBox("Topilmadi", "search");
    $$("#palList [data-i]").forEach((r) => (r.onclick = () => { closeModal(); shown[+r.dataset.i].act(); }));
  };
  const inp = $("#pal");
  inp.oninput = () => { const q = inp.value.toLowerCase(); shown = items.filter((x) => (x.t + " " + x.s).toLowerCase().includes(q)); sel = 0; draw(); };
  inp.onkeydown = (e) => {
    if (e.key === "ArrowDown") { sel = Math.min(sel + 1, shown.length - 1); draw(); e.preventDefault(); }
    if (e.key === "ArrowUp") { sel = Math.max(sel - 1, 0); draw(); e.preventDefault(); }
    if (e.key === "Enter" && shown[sel]) { closeModal(); shown[sel].act(); }
  };
  draw(); setTimeout(() => inp.focus(), 40);
}

/* ================= vaqt mashinasi ================= */
function toggleTM(btn) {
  const tm = $("#tm");
  if (tm.classList.contains("open")) { tm.classList.remove("open"); return; }
  const tl = S.meta.timeline, a = parseDay(tl.first), b = parseDay(tl.today);
  const days = Math.round((b - a) / 864e5), cur = S.asof ? Math.round((parseDay(S.asof) - a) / 864e5) : days;
  const label = (i) => { const d = new Date(a.getTime() + i * 864e5); return [uzDate(d), WEEK[d.getDay()]]; };
  tm.innerHTML = `<div class="tm-date" id="tmD">${label(cur)[0]}</div><div class="tm-sub" id="tmS">${cur === days ? "bugun" : label(cur)[1]}</div>
    <input type="range" id="tmR" min="0" max="${days}" value="${cur}" aria-label="Sana">
    <div class="tm-scale"><span>${uzDate(a)}</span><span>bugun</span></div>
    <div class="tm-acts"><button class="btn btn-dark" id="tmPlay" style="flex:1">${I(S.playing ? "pause" : "play")}${S.playing ? "To'xtatish" : "Ijro etish"}</button>
      <button class="btn btn-line" id="tmNow">${I("refresh")}Bugun</button></div>`;
  const r = btn.getBoundingClientRect();
  if (innerWidth > 760) { tm.style.top = r.bottom + 8 + "px"; tm.style.left = Math.max(12, Math.min(innerWidth - 392, r.right - 380)) + "px"; tm.style.right = "auto"; }
  tm.classList.add("open");
  const rng = $("#tmR");
  rng.oninput = () => { const [d, w] = label(+rng.value); $("#tmD").textContent = d; $("#tmS").textContent = +rng.value === days ? "bugun" : w; };
  rng.onchange = () => setAsof(+rng.value === days ? "" : isoDay(new Date(a.getTime() + +rng.value * 864e5)));
  $("#tmNow").onclick = () => { S.playing = false; setAsof(""); tm.classList.remove("open"); };
  $("#tmPlay").onclick = () => (S.playing ? (S.playing = false) : play(a, days, rng));
}
async function play(a, days, rng) {
  S.playing = true;
  $("#tmPlay").innerHTML = I("pause") + "To'xtatish";
  let i = +rng.value >= days ? 0 : +rng.value;
  while (S.playing && i <= days) {
    rng.value = i; rng.oninput();
    await setAsof(i === days ? "" : isoDay(new Date(a.getTime() + i * 864e5)));
    await sleep(650);
    i++;
  }
  S.playing = false;
  const pb = $("#tmPlay"); if (pb) pb.innerHTML = I("play") + "Ijro etish";
}
async function setAsof(day) {
  S.asof = day; S.officeKey = ""; writeHash(); await load(); live(true);
}
function renderHist() {
  const h = $("#hist");
  if (!S.asof) { h.hidden = true; return; }
  const d = parseDay(S.asof);
  h.hidden = false;
  h.innerHTML = `<div class="hist-in">${I("history")}<span>${uzDate(d)}, ${WEEK[d.getDay()]}, o'sha kun oxiridagi holat</span><button class="btn" id="histBack">${I("refresh")}Bugunga qaytish</button></div>`;
  $("#histBack").onclick = () => { S.playing = false; $("#tm").classList.remove("open"); setAsof(""); };
}

/* ================= umumiy bosishlar ================= */
function bindCommon(root) {
  $$("[data-person]", root).forEach((el) => el.addEventListener("click", (e) => { if (e.target.closest("[data-act]")) return; e.stopPropagation(); openPerson(el.dataset.person); }));
  $$("[data-project]", root).forEach((el) => el.addEventListener("click", (e) => { if (e.target.closest("[data-act]")) return; e.stopPropagation(); openProject(el.dataset.project); }));
  $$("[data-go]", root).forEach((el) => el.addEventListener("click", () => go(el.dataset.go)));
  $$("[data-act]", root).forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); openAction(JSON.parse(b.dataset.act)); }));
  $$("[data-fix]", root).forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); openFix(b.dataset.fix); }));
  $$("[data-tip-person]", root).forEach((el) => {
    const show = () => { const p = S.data.people.find((x) => x.name === el.dataset.tipPerson); if (p) showTip(personTip(p), null, el); };
    el.addEventListener("mouseenter", show);
    el.addEventListener("focus", show);
    el.addEventListener("mouseleave", hideTip);
    el.addEventListener("blur", hideTip);
  });
}
function countUp(root, key) {
  if (S.counted[key] || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  S.counted[key] = true;
  $$("[data-count]", root).forEach((el) => {
    const to = parseFloat(el.dataset.count);
    if (!to) return;
    const dec = String(el.dataset.count).includes(".") ? 1 : 0, t0 = performance.now();
    (function step(now) {
      const k = Math.min(1, (now - t0) / 900), e = 1 - Math.pow(1 - k, 3);
      el.textContent = nf(to * e, dec);
      if (k < 1) requestAnimationFrame(step); else el.textContent = nf(to, dec);
    })(t0);
  });
}

/* ================= toast va tooltip ================= */
function toast(html, icon = "info") {
  const t = document.createElement("div");
  t.className = "toast";
  t.innerHTML = I(icon) + `<span>${html}</span>`;
  $("#toasts").appendChild(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 350); }, 4400);
}
function showTip(html, e, anchor) {
  if (matchMedia("(hover: none)").matches) return;
  const tip = $("#tip");
  tip.innerHTML = html; tip.classList.add("show");
  const w = tip.offsetWidth, h = tip.offsetHeight;
  let x, y;
  if (anchor) {
    // Narsaning tagida, sig'masa tepasida: tooltip ko'rsatilayotgan narsaning o'zini yopmaydi
    const r = anchor.getBoundingClientRect();
    x = Math.min(Math.max(8, r.left), innerWidth - w - 8);
    y = r.bottom + 8;
    if (y + h > innerHeight - 8) y = Math.max(8, r.top - h - 8);
  } else {
    x = e.clientX + 16; y = e.clientY + 16;
    if (x + w > innerWidth - 10) x = e.clientX - w - 16;
    if (y + h > innerHeight - 10) y = e.clientY - h - 16;
  }
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
function hideTip() { $("#tip").classList.remove("show"); }

/* ================= TV rejimi ================= */
function startTV() {
  const order = TABS.map((t) => t[0]).filter((t) => t !== "malumotlar"); // TV'da faqat ko'rsatiladigan ekranlar
  document.body.classList.add("tv");
  document.documentElement.requestFullscreen?.().catch(() => {});
  let i = order.indexOf(S.tab), left = 20;
  const bar = document.createElement("div");
  bar.className = "tv-bar";
  document.body.appendChild(bar);
  const tick = () => {
    if (--left <= 0) { i = (i + 1) % order.length; go(order[i]); left = 20; }
    bar.innerHTML = `${I("tv")}<span>${TABS.find((t) => t[0] === order[i])[2]}, ${left}</span><button class="btn" id="tvX">${I("close")}Chiqish</button>`;
    $("#tvX").onclick = stopTV;
  };
  tick();
  S.tv = setInterval(tick, 1000);
}
function stopTV() {
  clearInterval(S.tv); S.tv = null;
  document.body.classList.remove("tv");
  $(".tv-bar")?.remove();
  if (document.fullscreenElement) document.exitFullscreen?.();
}

/* ================= menyu, mavzu, klaviatura ================= */
function toggleTheme() {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("puls-theme", t); } catch (e) {}
  $("#themeItem").innerHTML = I(t === "dark" ? "sun" : "moon") + (t === "dark" ? "Yorug' rejim" : "Qorong'i rejim");
  S.officeKey = "";
  renderView(S.tab);
}
async function logout() {
  try { await api("api/logout", { json: {} }); } catch (e) { /* baribir kirish sahifasiga */ }
  location.href = "login";
}
// Rolga qarab menyu: nomi, roli, faqat ruxsat etilgan buyruqlar
function applyRole() {
  const me = ME();
  $("#meMenu").innerHTML = `<b>${esc(me.name || me.username || "")}</b><span>${esc(me.role_label || "")}</span>`;
  $('#menu [data-m="import"]').hidden = !isRole("admin");
  $('#menu [data-m="settings"]').hidden = !isRole("admin");
}
function initMenu() {
  $("#menuBtn").addEventListener("click", (e) => { e.stopPropagation(); $("#menu").classList.toggle("open"); });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#menu")) $("#menu").classList.remove("open");
    if (!e.target.closest("#tm") && !e.target.closest("[data-tm]")) $("#tm").classList.remove("open");
  });
  $$("#menu [data-m]").forEach((b) => b.addEventListener("click", () => {
    $("#menu").classList.remove("open");
    ({ excel: () => (location.href = "api/export.xlsx?" + query({ view: EXPORT_VIEW[S.tab] })), import: openImport, settings: openSettings, tv: startTV,
       guide: openGuide, keys: openKeys, theme: toggleTheme, logout })[b.dataset.m]();
  }));
  const dark = document.documentElement.dataset.theme === "dark";
  $("#themeItem").innerHTML = I(dark ? "sun" : "moon") + (dark ? "Yorug' rejim" : "Qorong'i rejim");
  $("#searchBtn").addEventListener("click", openPalette);
  $("#drawer .scrim").addEventListener("click", closeDrawer);
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
}
document.addEventListener("keydown", (e) => {
  const typing = /INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName);
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); return; }
  if (e.key === "Escape") {
    if ($("#modal").classList.contains("open")) closeModal();
    else if ($("#tm").classList.contains("open")) $("#tm").classList.remove("open");
    else if ($("#drawer").classList.contains("open")) closeDrawer();
    else if (S.tv) stopTV();
    return;
  }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (/^[1-6]$/.test(e.key)) go(TABS[+e.key - 1][0]);
  else if (e.key.toLowerCase() === "t") toggleTheme();
});

/* ================= ishga tushirish ================= */
function skeleton() {
  $("#v-brifing").innerHTML = `<div class="ph"><div><div class="sk" style="height:30px;width:180px"></div><div class="sk" style="height:14px;width:260px;margin-top:10px"></div></div></div>
    <div class="sk" style="height:300px;border-radius:20px"></div>
    <div class="decs" style="margin-top:52px">${'<div class="sk" style="height:206px;border-radius:20px"></div>'.repeat(3)}</div>`;
}
(async function init() {
  readHash();
  buildNav();
  initMenu();
  go(S.tab);
  skeleton();
  try { S.meta = await api("api/meta"); } catch (e) { return; }
  applyRole();
  await load();
  try { S.ui = (await api("api/version")).ui; } catch (e) {}
  if (S.open.startsWith("p:")) openPerson(S.open.slice(2));
  else if (S.open.startsWith("j:")) openProject(S.open.slice(2));
  else if (S.open.startsWith("a:")) { const x = S.data.decisions[+S.open.slice(2)]; S.open = ""; writeHash(); if (x && x.action) openAction(x.action); }
  else if (S.open === "tm") { S.open = ""; writeHash(); const b = $("[data-tm]", $(".view.on")); if (b) toggleTM(b); }
  addEventListener("hashchange", () => { const t = S.tab; readHash(); if (t !== S.tab) go(S.tab); });
})();
