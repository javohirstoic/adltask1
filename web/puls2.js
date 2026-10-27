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
  silent: { label: "Hisobot yo'q", icon: "chat-dots", color: "var(--orange)", order: 1 },
  stuck: { label: "Kechikyapti", icon: "clock", color: "var(--warn)", order: 2 },
  ok: { label: "Yaxshi", icon: "check", color: "var(--ok)", order: 3 },
  idle: { label: "Bo'sh", icon: "cup", color: "var(--idle)", order: 4 },
};
const STATE_ORDER = ["ok", "stuck", "silent", "overloaded", "idle"];
const LEVEL = { 4: "Kechikdi", 3: "Xavf ostida", 2: "E'tibor kerak", 1: "Kuzatuvda", 0: "Rejada" };
const LEVEL_ICON = { 4: "danger", 3: "danger", 2: "info", 1: "eye", 0: "check" };
const KIND = { task: "Vazifa", done: "Bajarildi", blocker: "Muammo", deadline: "Muddat" };
const SRC = { ai: ["AI", "stars"], format: ["Teg", ""], taxmin: ["Kalit so'z", ""], tuzatildi: ["Tuzatildi", "check"] };
// Rahbar ishini bitta sahifada bitiradi: "Kunlik holat". Chap menyu — shu sahifaning bo'limlari (bosilsa o'sha joyga o'tadi).
// Loyiha va xodim tafsiloti yon oynada ochiladi. Qolgan ko'rinishlar (doska, hisobotlar...) faqat "…" menyusidan.
const TABS = [
  ["holat", "holat", "Kunlik holat", "pulse"],
  ["jamoa", "jamoa", "Xodimlar ro'yxati", "people"], ["hisobot", "hisobotlar", "Kunlik hisobotlar", "doc"],
  ["doska", "vazifalar", "Vazifalar doskasi", "checklist"], ["bolimlar", "bolimlar", "Bo'limlar reytingi", "depts"],
  ["brifing", "brifing", "Brifing", "brifing"], ["ofis", "ofis", "Ofis", "office"], ["xodimlar", "xodimlar", "Xodimlar jadvali", "people"],
];
const SECTIONS = [["umumiy", "Umumiy holat", "pulse"], ["matritsa", "Hisobot matritsasi", "chart"], ["xodimlar", "Xodimlar", "people"],
  ["loyihalar", "Loyihalar", "projects"], ["murojaatlar", "Murojaatlar", "chat-dots"], ["muammolar", "Muammolar", "danger"],
  ["guruhlar", "Guruhlar", "send"]];
const NAV = SECTIONS;
const EXTRA_VIEWS = ["doska", "hisobot", "jamoa", "bolimlar"];  // "…" menyusidagi qo'shimcha ko'rinishlar
// eski manzillar (#/loyihalar, #/muammolar ...) shu sahifaning bo'limiga olib boradi
const SEC_ROUTES = { loyihalar: "loyihalar", loyiha: "loyihalar", murojaatlar: "murojaatlar", muammolar: "muammolar", guruhlar: "guruhlar" };
const EXPORT_VIEW = { holat: "projects", jamoa: "people", brifing: "projects", hisobot: "people", doska: "projects", ofis: "people", xodimlar: "people",
  bolimlar: "departments" };


/* ================= qidiruvli tanlash: 7 tadan ko'p variantli har bir <select> avtomatik ================= */
// Asl <select> yashirin qoladi va qiymati o'shanda turadi: mavjud kod (onchange, .value) o'zgarmasdan ishlayveradi
const fold = (t) => String(t || "").toLowerCase().replace(/[ʻ’‘'`]/g, "").replace(/\s+/g, " ");
let ssOpen = null;
function ssLabel(sel) { const o = sel.options[sel.selectedIndex]; return o ? o.textContent : ""; }
function enhanceSelect(sel) {
  if (sel.dataset.ss || sel.multiple || sel.options.length < 7 || sel.closest(".ss-pop")) return;
  sel.dataset.ss = "1";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "ss-btn " + (sel.classList.contains("ctl") ? "ctl" : "ss-field");
  btn.setAttribute("aria-haspopup", "listbox");
  btn.setAttribute("aria-label", sel.getAttribute("aria-label") || sel.previousElementSibling?.textContent || "Tanlash");
  btn.innerHTML = `<span></span>${I("chevron-down")}`;
  btn.style.cssText = sel.style.cssText;
  const sync = () => {  // faqat o'zgarganda yoziladi: aks holda kuzatuvchi o'zini qayta-qayta chaqiradi
    const span = $("span", btn), label = ssLabel(sel);
    if (span.textContent !== label) span.textContent = label;
    if (btn.disabled !== sel.disabled) btn.disabled = sel.disabled;
    if (btn.hidden !== sel.hidden) btn.hidden = sel.hidden;
  };
  sync();
  sel.addEventListener("change", sync);
  sel._ssSync = sync;
  sel.after(btn);
  sel.classList.add("ss-hidden");
  btn.addEventListener("click", (e) => { e.stopPropagation(); ssOpen && ssOpen.sel === sel ? ssClose() : ssShow(sel, btn); });
}
function ssClose() { if (ssOpen) { ssOpen.pop.remove(); ssOpen.btn.setAttribute("aria-expanded", "false"); ssOpen = null; } }
function ssShow(sel, btn) {
  ssClose();
  const opts = [...sel.options].map((o, i) => ({ i, text: o.textContent, value: o.value, off: o.disabled }));
  const pop = document.createElement("div");
  pop.className = "ss-pop";
  pop.innerHTML = `<label class="ss-q">${I("search")}<input placeholder="Qidirish" autocomplete="off" spellcheck="false"></label><div class="ss-list" role="listbox"></div>`;
  document.body.appendChild(pop);
  const r = btn.getBoundingClientRect(), w = Math.max(r.width, 260);
  const below = innerHeight - r.bottom > 320 || r.top < 320;
  Object.assign(pop.style, { left: Math.max(8, Math.min(innerWidth - w - 8, r.left)) + "px", width: w + "px",
    [below ? "top" : "bottom"]: (below ? r.bottom + 4 : innerHeight - r.top + 4) + "px" });
  const inp = $("input", pop), list = $(".ss-list", pop);
  let shown = opts, cur = Math.max(0, opts.findIndex((o) => o.i === sel.selectedIndex));
  const draw = () => {
    list.innerHTML = shown.map((o, k) => `<div class="ss-opt ${k === cur ? "on" : ""} ${o.i === sel.selectedIndex ? "sel" : ""} ${o.off ? "off" : ""}" role="option" data-k="${k}">${esc(o.text)}</div>`).join("")
      || `<div class="ss-none">Topilmadi</div>`;
    const on = $(".ss-opt.on", list); if (on) on.scrollIntoView({ block: "nearest" });
  };
  const pick = (o) => {
    if (!o || o.off) return;
    sel.selectedIndex = o.i;
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    sel._ssSync?.();
    ssClose(); btn.focus();
  };
  inp.oninput = () => { const q = fold(inp.value); shown = opts.filter((o) => !q || fold(o.text).includes(q)); cur = shown.findIndex((o) => !o.off); draw(); };
  inp.onkeydown = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); cur = Math.min(shown.length - 1, cur + 1); draw(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); cur = Math.max(0, cur - 1); draw(); }
    else if (e.key === "Enter") { e.preventDefault(); pick(shown[cur]); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); ssClose(); btn.focus(); }
    else if (e.key === "Tab") ssClose();
  };
  list.onmousedown = (e) => e.preventDefault();
  list.onclick = (e) => { const el = e.target.closest("[data-k]"); if (el) pick(shown[+el.dataset.k]); };
  pop.onclick = (e) => e.stopPropagation();
  btn.setAttribute("aria-expanded", "true");
  ssOpen = { sel, btn, pop };
  draw();
  inp.focus();
}
document.addEventListener("click", () => ssClose());
addEventListener("resize", () => ssClose());
document.addEventListener("scroll", (e) => { if (ssOpen && !ssOpen.pop.contains(e.target)) ssClose(); }, true);
new MutationObserver((muts) => {
  if (muts.every((m) => m.target.closest?.(".ss-btn, .ss-pop") || m.target.parentElement?.closest(".ss-btn, .ss-pop"))) return;
  for (const m of muts) for (const n of m.addedNodes) {
    if (n.nodeType !== 1) continue;
    if (n.tagName === "SELECT") enhanceSelect(n);
    else n.querySelectorAll?.("select").forEach(enhanceSelect);
  }
  // kod qiymatni keyin o'rnatgan bo'lsa (sel.value = ...), yozuv ham yangilansin
  $$("select[data-ss]").forEach((sel) => sel._ssSync?.());
}).observe(document.documentElement, { childList: true, subtree: true });

/* ================= holat ================= */
const S = {
  tab: "holat", pid: "", period: "day", start: "", end: "", chat: "", asof: "",  // asosiy savol: bugun kim yozdi, kim yozmadi
  data: null, meta: null, version: 0, ui: 0,
  pf: { q: "", dept: "", state: "", sort: "rank" }, faceState: "", officeDept: "", officeState: "",
  prSort: { key: "level", asc: false }, showAllDecs: false,
  office: null, officeKey: "", charts: {}, tv: null, playing: false, counted: {}, open: "",
};

function readHash() {
  const [path, q] = location.hash.replace(/^#\/?/, "").split("?");
  const p = new URLSearchParams(q || "");
  if (TABS.some((t) => t[1] === path)) S.tab = TABS.find((t) => t[1] === path)[0];
  else if (SEC_ROUTES[path]) {
    S.tab = "holat"; S.sec = SEC_ROUTES[path];
    if (path === "loyiha" && p.get("id")) p.set("x", "j:" + p.get("id"));
  }
  if (["day", "week", "month", "custom"].includes(p.get("d"))) S.period = p.get("d");
  S.start = p.get("s") || ""; S.end = p.get("e") || ""; S.chat = p.get("g") || "";
  S.asof = p.get("t") || (S.asofAuto ? S.asof : "");  // dam olish kuni avtomatik tanlangan ish kuni sahifadan sahifaga o'tganda saqlanadi
  S.open = p.get("x") || "";
  S.dept = p.get("b") || "";
}
function writeHash() {
  const p = new URLSearchParams();
  if (S.period !== "day") p.set("d", S.period);
  if (S.period === "custom") { p.set("s", S.start); p.set("e", S.end); }
  if (S.chat) p.set("g", S.chat);
  if (S.asof && !S.asofAuto) p.set("t", S.asof);  // dam olish kuni avtomatik tanlangan ish kuni havolada saqlanmaydi
  if (S.open) p.set("x", S.open);
  if (S.dept) p.set("b", S.dept);
  const h = "#/" + TABS.find((t) => t[0] === S.tab)[1] + (p.toString() ? "?" + p : "");
  if (location.hash !== h) history.replaceState(null, "", h);
}
function query(extra) {
  const p = new URLSearchParams({ period: S.period });
  if (S.period === "custom") { p.set("start", S.start); p.set("end", S.end); }
  if (S.chat) p.set("chat", S.chat);
  if (S.asof) p.set("asof", S.asof);
  if (S.dept) p.set("dept", S.dept);
  Object.entries(extra || {}).forEach(([k, v]) => p.set(k, v));
  return p.toString();
}

/* ================= ma'lumot ================= */
async function api(path, opt) {
  const o = Object.assign({ headers: { Accept: "application/json" } }, opt || {});
  if (o.json !== undefined) { o.method = o.method || "POST"; o.body = JSON.stringify(o.json); o.headers["Content-Type"] = "application/json"; delete o.json; }
  if (S.dept && /^api\/(board|reports|assistant)/.test(path)) {  // qolganlari query() orqali oladi
    path += (path.includes("?") ? "&" : "?") + "dept=" + encodeURIComponent(S.dept);
  }
  const r = await fetch(path, o);
  if (r.status === 401) { location.href = "login"; throw new Error("Kirish kerak"); }
  if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.detail || "Server javob bermadi"); }
  return r.json();
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

// Realtime: server o'zgarishni o'zi aytadi (SSE). Ulanish bo'lmasa eski usul: har 4 soniyada so'rash
let liveStream = null, liveAt = 0;
function startStream() {
  if (!window.EventSource || liveStream) return;
  liveStream = new EventSource("api/events");
  liveStream.onmessage = (e) => {
    live(true);
    const v = +e.data;
    if (v === S.version || S.asof) return;
    clearTimeout(startStream.t);  // tez-tez o'zgarsa ham panel soniyasiga ko'pi bilan bir marta yangilanadi
    startStream.t = setTimeout(() => { liveAt = Date.now(); load(true); }, Math.max(0, 900 - (Date.now() - liveAt)));
  };
  liveStream.onerror = () => { live(false); };
}
let pollN = 0;
setInterval(async () => {
  if (document.hidden) return;
  if (liveStream && liveStream.readyState === 1 && ++pollN % 5) return; // oqim ishlayapti: faqat har 20 soniyada (yangi dizayn bormi)
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
// Chap menyu — bitta sahifaning bo'limlari, yonida son (qizil — e'tibor kerak). Telefonda pastki 5 ta tugma ham shu bo'limlar
function navCount(key) {
  const d = S.data;
  if (!d) return null;
  if (key === "loyihalar") { const bad = d.projects.filter((p) => p.pstate === "kritik").length; return [d.projects.length, bad > 0]; }
  if (key === "xodimlar") return [d.people.length, false];
  if (key === "murojaatlar") { const k = AP.data?.kpi; return k && !AP.data.sample && k.n ? [k.n, k.waiting > 0] : null; }
  if (key === "muammolar") { const n = d.projects.reduce((a, p) => a + p.blocker_list.length, 0); return n ? [n, d.projects.some((p) => p.blocker_list.some((b) => b.age >= 3))] : null; }
  if (key === "guruhlar") { const n = (S.meta?.chats || []).filter((c) => !c.demo).length; return n ? [n, false] : null; }
  return null;
}
function buildNav() {
  $("#nav").innerHTML = `<div class="grp">Boshqaruv</div>` + SECTIONS.map((t) => {
    const c = navCount(t[0]);
    return `<button data-sec="${t[0]}">${I(t[2])}<span>${t[1]}</span>${c ? `<b class="cnt ${c[1] ? "hot" : ""}">${c[0]}</b>` : ""}</button>`;
  }).join("");
  $("#bnav").innerHTML = SECTIONS.filter((t) => t[0] !== "matritsa").map((t) => `<button data-sec="${t[0]}">${I(t[2])}${t[0] === "umumiy" ? "Holat" : t[1]}</button>`).join("");
  $$("#nav [data-sec], #bnav [data-sec]").forEach((b) => b.addEventListener("click", () => goSection(b.dataset.sec)));
  markNav();
}
function markNav(sec) {
  if (sec !== undefined) S.secOn = sec;
  const on = S.tab === "holat" ? S.secOn || "umumiy" : "";
  $$("#nav [data-sec], #bnav [data-sec]").forEach((b) => { if (b.dataset.sec === on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current"); });
}
// bo'limga o'tish: boshqa ko'rinishda bo'lsa avval Kunlik holat ochiladi
function goSection(id) {
  document.body.classList.remove("side-open");
  if (S.tab !== "holat") { S.sec = id; go("holat"); return; }
  scrollSection(id);
}
function scrollSection(id) {
  const el = $(`[data-secid="${id}"]`);
  if (!el) return;
  if (id === "umumiy") window.scrollTo({ top: 0, behavior: "smooth" }); else el.scrollIntoView({ behavior: "smooth", block: "start" });
  markNav(id);
}
function go(tab) {
  if (!TABS.some((t) => t[0] === tab)) { if (SEC_ROUTES[tab]) S.sec = SEC_ROUTES[tab]; tab = "holat"; }
  S.tab = tab;
  markNav();
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === "v-" + tab));
  document.body.classList.remove("side-open");
  writeHash();
  crumbs();
  if (S.data) renderView(tab);
  if (!S.tv && !S.sec) window.scrollTo({ top: 0 });
}
function crumbs() {
  const t = TABS.find((x) => x[0] === S.tab);
  const el = $("#crumbs");
  if (!el || !t) return;
  el.innerHTML = S.tab === "holat" ? `<span>Boshqaruv</span>${I("chevron")}<b>Kunlik holat</b>`
    : `<button data-crumb="holat">Kunlik holat</button>${I("chevron")}<b>${esc(t[2])}</b>`;
  $("[data-crumb]", el)?.addEventListener("click", () => go("holat"));
}
function renderAll() { renderHist(); buildNav(); sideFoot(); crumbs(); renderView(S.tab); }
function renderView(tab) {
  if (!S.data) return;
  ({ holat: renderHolat, jamoa: renderTeam, brifing: renderBrifing, hisobot: renderReports, doska: renderBoard, ofis: renderOffice, xodimlar: renderPeople,
     bolimlar: renderDepts })[tab](S.data);
}

/* sahifa sarlavhasi: nomi, izohi va o'ng tomonda bir xil asboblar — sana (kunma-kun), davr, PDF va Excel */
const WD_SHORT = ["Ya", "Du", "Se", "Ch", "Pa", "Ju", "Sh"];
const dotDate = (day) => day.slice(8, 10) + "." + day.slice(5, 7) + "." + day.slice(0, 4);
const todayIso = () => S.meta?.timeline?.today || isoDay(new Date());
const selDay = () => S.asof || todayIso();
const isWeekend = (day) => [0, 6].includes(parseDay(day).getDay());
function workdayShift(day, n) {
  let d = parseDay(day);
  do { d = new Date(d.getTime() + Math.sign(n) * 864e5); } while ([0, 6].includes(d.getDay()));
  return isoDay(d);
}
function dateNav() {
  const day = selDay(), today = todayIso();
  return `<div class="datenav" role="group" aria-label="Kun">
      <button data-dn="-1" aria-label="Oldingi ish kuni">${I("arrow-left")}</button>
      <label>${I("calendar")}<span>${dotDate(day)}, ${WD_SHORT[parseDay(day).getDay()]}</span><input type="date" data-dnpick value="${day}" max="${today}" aria-label="Sanani tanlash"></label>
      <button data-dn="1" aria-label="Keyingi ish kuni" ${day >= today ? "disabled" : ""}>${I("arrow")}</button>
    </div>${S.asof ? `<button class="btn btn-ghost sm" data-dn="0">Bugun</button>` : ""}`;
}
function pageHead(title, sub, opts = {}) {
  return `<div class="ph"><div class="ph-t"><h1>${title}</h1>${sub ? `<div class="sub">${sub}</div>` : ""}</div>
    <div class="filters">
      ${opts.noDate ? "" : dateNav()}
      ${opts.noPeriod ? "" : `<div class="seg" role="group" aria-label="Davr">
        <button data-p="day" aria-pressed="${S.period === "day"}">Kun</button><button data-p="week" aria-pressed="${S.period === "week"}">Hafta</button>
        <button data-p="month" aria-pressed="${S.period === "month"}">Oy</button><button data-p="custom" aria-pressed="${S.period === "custom"}" title="Oraliq" aria-label="Oraliq">${I("calendar")}</button>
      </div>`}
      ${opts.extra || ""}
      <button class="btn btn-line no-print" data-print title="Chop etish yoki PDF saqlash">${I("download")}PDF</button>
      <a class="icon-btn no-print" href="api/export.xlsx?${query({ view: EXPORT_VIEW[S.tab] })}" title="Excelga yuklab olish" aria-label="Excelga yuklab olish">${I("doc")}</a>
    </div></div>`;
}
function bindHead(root) {
  $$("[data-p]", root).forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.p === "custom") { openRange(); return; }
    S.period = b.dataset.p; writeHash(); load();
  }));
  $$("[data-dn]", root).forEach((b) => b.addEventListener("click", () => {
    const n = +b.dataset.dn, today = todayIso();
    if (!n) { setAsof(""); return; }
    const next = workdayShift(selDay(), n);
    setAsof(next >= today ? "" : next);
  }));
  $("[data-dnpick]", root)?.addEventListener("change", (e) => { const v = e.target.value; if (v) setAsof(v >= todayIso() ? "" : v); });
  $("[data-print]", root)?.addEventListener("click", () => print());
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
function scoreRing(score, cls = "", p = null) {
  if (score == null) return `<div class="score na ${cls}" title="4 haftada kamida 3 ta ish bo'lsa reyting chiqadi"><span>—</span></div>`;
  const c = score >= 50 ? "var(--ink)" : "var(--risk)", prov = p && p.new;
  return `<div class="score ${cls} ${prov ? "prov" : ""}" style="--p:${score};--c:${c}" title="${prov ? `Taxminiy reyting: ${p.evidence} ish kuni kuzatildi` : "Reyting, 100 dan"}"><span>${score}${prov ? "<i>?</i>" : ""}</span></div>`;
}
// Haftalik o'rin o'zgarishi: bir hafta oldin ham reytingda bo'lganlar orasida
const mv = (p) => (p.move ? `<span class="mv ${p.move > 0 ? "up" : "down"}" title="Bir haftada ${Math.abs(p.move)} o'rin ${p.move > 0 ? "ko'tarildi" : "tushdi"}">${p.move > 0 ? "▲" : "▼"}${Math.abs(p.move)}</span>` : "");
const ratio = (x) => (x == null ? "—" : nf(x, 1) + "×");
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
  const headline = d.decisions.length ? `Bugun ${d.decisions.length} ta masala qaroringizni kutmoqda.` : "Bugun qaror talab qiladigan masala yo'q.";
  const decs = S.showAllDecs ? d.decisions : d.decisions.slice(0, 5);
  const day = WEEK[now.getDay()][0].toUpperCase() + WEEK[now.getDay()].slice(1);
  const dm = !S.dept && d.departments.filter((x) => x.rank).length > 1;
  el.innerHTML = pageHead(greeting(d), `${day}, ${uzDate(now)}${S.asof ? ", kun oxiridagi holat" : ""}`) + `
    ${heroCards(d)}
    <div class="cc-top ${S.asof ? "solo" : ""}">
      <div class="cc-dec"><div class="sec-title"><h2>${headline}</h2></div>
        <div class="agenda">${decs.length ? decs.map(agRow).join("") : `<div class="dec-done"><span class="ic lv0">${I("check")}</span><span>Qaror talab qiladigan masala yo'q.</span></div>`}
          ${d.decisions.length > 5 ? `<div class="ag-more"><button class="more-link" data-alldec>${S.showAllDecs ? "Kamroq ko'rsatish" : `Yana ${d.decisions.length - 5} ta`}</button></div>` : ""}</div></div>
      ${S.asof ? "" : `<section class="card yd" id="yd"></section>`}
    </div>

    ${unlinkedBar(d)}
    ${honesty(d)}
    <section class="card tn" id="tn"></section>

    <div class="grid" style="margin-top:20px">
      <section class="card s7"><div class="ch"><h3>Loyihalar</h3><span class="count">${d.projects.length}</span>
        <div class="right road-legend"><span>${I("flag")}muddat</span><span><i class="o"></i>prognoz</span><span><i class="t"></i>bugun</span></div></div>
        <div class="cb"><div class="roads">${d.projects.slice(0, 8).map((x) => roadRow(x, d)).join("") || emptyBox("Hali loyiha yo'q", "projects")}</div>
          ${d.projects.length > 8 ? `<div style="margin-top:12px"><button class="more-link" data-go="loyihalar">Barcha ${d.projects.length} loyiha</button></div>` : ""}</div></section>
      <section class="card s5"><div class="ch"><h3>Jonli lenta</h3></div>
        <div class="cb" style="padding-top:6px"><div class="feed">${d.feed.map(feedItem).join("") || emptyBox("Guruhga birinchi xabar yozilishi bilan shu yerda ko'rinadi", "chat-dots")}</div></div></section>
      <section class="card ${dm ? "s7" : "s12"}"><div class="ch"><h3>Dinamika</h3><div class="right road-legend"><span><i class="sq" style="background:color-mix(in srgb,var(--azure) 30%,transparent)"></i>yangi</span><span><i class="o" style="border-color:var(--ok)"></i>bajarildi</span></div></div>
        <div class="cb"><div style="height:280px"><canvas id="cTrend"></canvas></div></div></section>
      ${dm ? deptMini(d) : ""}
      ${d.decision_log.length ? `<section class="card s12"><div class="ch"><h3>Bajarilgan qarorlar</h3><span class="count">${d.decision_log.length}</span></div>
        <div class="cb" style="padding-top:6px"><div class="log">${d.decision_log.map(logItem).join("")}</div></div></section>` : ""}
    </div>`;
  bindHead(el);
  bindCommon(el);
  $$("[data-alldec]", el).forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); S.showAllDecs = !S.showAllDecs; renderBrifing(S.data); }));
  $$("[data-enter]", el).forEach((b) => (b.onclick = (e) => { e.stopPropagation(); setDept(b.dataset.enter, "brifing"); }));
  $("#ulOpen")?.addEventListener("click", openLinks);
  drawTn();
  drawTrend($("#cTrend"), d.series);
  countUp(el, "brifing");
  if (!S.asof) loadYd(false);
}


/* ================= Jamoa hozir: har xodim bitta qatorda — o'rni, hozir nima qilyapti, bugun nima yozdi, holati ================= */
const TN = { q: "", f: "", sort: "rank", dept: "", all: false };
const TN_STAGE = { jarayon: "Jarayonda", tekshiruv: "Tekshiruvda", qabul: "Qabul qildi", yangi: "Navbatda" };
const tnWrote = (p) => p.today.items > 0;
const tnAlarm = (p) => p.today.repeats > 0 || ["overloaded", "silent", "stuck"].includes(p.state);
const TN_FILTER = {
  "": () => true,
  silent: (p) => !tnWrote(p),
  alarm: tnAlarm,
  new: (p) => p.new && p.evidence,
};
const TN_SORT = {
  rank: (a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9) || (b.pace ?? 0) - (a.pace ?? 0) || a.name.localeCompare(b.name),
  today: (a, b) => b.today.items - a.today.items || (b.today.hours || 0) - (a.today.hours || 0) || (a.rank ?? 1e9) - (b.rank ?? 1e9),
  alarm: (a, b) => tnAlarm(b) - tnAlarm(a) || byAttention(a, b),
  output: (a, b) => (b.pace ?? -1) - (a.pace ?? -1),
};
function tnNow(p) {
  const c = p.current;
  if (c) return `<span class="tn-cur" data-bcard="${c.id}" title="${esc(c.title)}"><b>${esc(c.title)}</b>
    <small>${TN_STAGE[c.stage] || "Navbatda"}${c.stage === "jarayon" && c.progress ? " " + c.progress + "%" : ""}${c.flag ? `, <em>${c.flag === "q" ? "savoli bor" : "to'siq bor"}</em>` : ""}${c.project ? ", " + esc(c.project) : ""}${c.age ? ", " + c.age + " kun" : ""}</small></span>`;
  if (p.today.last) return `<span class="tn-cur done" title="${esc(p.today.last)}"><b>${esc(p.today.last)}</b><small>Bajardi, ${p.today.last_at.slice(11, 16)}</small></span>`;
  return `<span class="tn-cur none">—</span>`;
}
function tnToday(p) {
  const t = p.today;
  if (!t.items) return `<span class="tn-day none">${p.silent_days ? `${p.silent_days} ish kuni jim` : "Hali yozmagan"}</span>`;
  return `<span class="tn-day"><b>${t.items} ta ish</b>${t.hours ? `<small>taxminan ${fmtH(t.hours)}</small>` : ""}
    ${t.repeats ? `<span class="bd-chip risk">${t.repeats} takror</span>` : t.items >= 5 && t.small / t.items >= 0.6 ? `<span class="bd-chip warn">ko'pi mayda</span>` : ""}</span>`;
}
function tnRow(p, maxPace) {
  return `<div class="tn-row st-${p.state}" data-person="${esc(p.name)}">
    <span class="tn-rk">${p.rank ? `<span class="rk">${p.rank}</span>${mv(p)}` : `<span class="rk na">—</span>`}</span>
    <span class="tn-who">${ava(p.name, p.department, p.state)}<span><b>${esc(p.name)}</b><small>${esc(p.department)}${p.q28.repeats ? `, <em title="4 haftada eski ishni qayta yozgan">${p.q28.repeats} takror</em>` : ""}</small></span></span>
    ${tnNow(p)}
    ${tnToday(p)}
    <span class="tn-out" title="Kunlik ish hajmi, jamoa o'rtachasiga nisbatan"><span class="dl-bar"><i style="width:${maxPace ? Math.round((100 * (p.pace || 0)) / maxPace) : 0}%"></i></span><b>${ratio(p.pace_ratio)}</b></span>
    <span class="tn-sc">${scoreRing(p.score, "sm", p)}</span>
    <span class="tn-st">${statePill(p.state, "", true)}</span>
  </div>`;
}
function drawTn() {
  const box = $("#tn"), d = S.data;
  if (!box || !d) return;
  const ppl = d.people, q = fold(TN.q);
  const depts = [...new Set(ppl.map((p) => p.department))].sort();
  const inDept = ppl.filter((p) => !TN.dept || p.department === TN.dept);
  const cnt = (k) => inDept.filter(TN_FILTER[k]).length;
  const list = inDept.filter((p) => TN_FILTER[TN.f](p) && (!q || fold(p.name).includes(q))).sort(TN_SORT[TN.sort]);
  const LIMIT = 12, shown = TN.all || q ? list : list.slice(0, LIMIT);
  const maxPace = Math.max(0, ...ppl.map((p) => p.pace || 0));
  const wrote = inDept.filter(tnWrote).length;
  const focus = document.activeElement?.id === "tnQ";
  const chip = (k, label) => `<button class="chip ${k === "silent" || k === "alarm" ? (cnt(k) ? "alarm" : "") : ""}" data-tnf="${k}" aria-pressed="${TN.f === k}" ${cnt(k) || TN.f === k ? "" : "disabled"}>${label}<b>${cnt(k)}</b></button>`;
  const th = (k, label) => `<button data-tns="${k}" aria-pressed="${TN.sort === k}">${label}</button>`;
  box.innerHTML = `<div class="ch"><h3>Jamoa hozir</h3><span class="count">${wrote} / ${inDept.length} bugun yozdi</span>
      <div class="right"><div class="seg" role="group" aria-label="Tartib">${th("rank", "Reyting")}${th("today", "Bugun")}${th("alarm", "Muammolilar")}</div></div></div>
    <div class="tn-tools">
      <label class="searchbox">${I("search")}<input id="tnQ" type="search" placeholder="Xodimni qidirish" value="${esc(TN.q)}" autocomplete="off"></label>
      ${!S.dept && depts.length > 1 ? `<select class="ctl" id="tnDept" aria-label="Bo'lim"><option value="">Barcha bo'limlar</option>${depts.map((x) => `<option ${TN.dept === x ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>` : ""}
      <div class="legend">${chip("", "Hammasi")}${chip("silent", "Bugun yozmagan")}${chip("alarm", "Diqqat")}${cnt("new") ? chip("new", "Yangi") : ""}</div>
    </div>
    <div class="tn-head"><span>O'rin</span><span>Xodim</span><span>Hozir nima qilyapti</span><span>Bugun</span><span>Ish hajmi</span><span>Reyting</span><span>Holat</span></div>
    <div class="tn-list">${shown.map((p) => tnRow(p, maxPace)).join("") || emptyBox(q ? "Bu ismli xodim yo'q" : "Bu filtrda xodim yo'q", q ? "search" : "check")}</div>
    ${list.length > shown.length || (TN.all && list.length > LIMIT) ? `<div class="tn-more"><button class="more-link" id="tnAll">${TN.all ? "Kamroq ko'rsatish" : `Barcha ${list.length} xodim`}</button></div>` : ""}`;
  bindCommon(box);
  $$("[data-bcard]", box).forEach((x) => (x.onclick = (e) => { e.stopPropagation(); openBoardCard(+x.dataset.bcard); }));
  $$("[data-tnf]", box).forEach((b) => (b.onclick = () => { TN.f = TN.f === b.dataset.tnf ? "" : b.dataset.tnf; drawTn(); }));
  $$("[data-tns]", box).forEach((b) => (b.onclick = () => { TN.sort = b.dataset.tns; drawTn(); }));
  $("#tnAll")?.addEventListener("click", () => { TN.all = !TN.all; drawTn(); });
  $("#tnDept")?.addEventListener("change", (e) => { TN.dept = e.target.value; drawTn(); });
  const qi = $("#tnQ");
  qi.oninput = () => { TN.q = qi.value; clearTimeout(qi._t); qi._t = setTimeout(drawTn, 140); };
  if (focus) { qi.focus(); qi.setSelectionRange(qi.value.length, qi.value.length); }
}
/* Hisobotlar haqqoniyligi (4 hafta): kim eski ishni qayta yozyapti, kim asosan mayda ish yozyapti, kim og'ir ishlarni qilyapti.
   Bot xodimga hech narsa demaydi — bu faqat rahbar ko'radigan joy. */
function honesty(d) {
  const ppl = d.people.filter((p) => p.q28);
  const share = (p) => p.q28.small / p.q28.rated;
  const rep = ppl.filter((p) => p.q28.repeats).sort((a, b) => b.q28.repeats - a.q28.repeats || a.name.localeCompare(b.name));
  const small = ppl.filter((p) => p.q28.rated >= 6 && share(p) >= 0.5).sort((a, b) => share(b) - share(a) || b.q28.rated - a.q28.rated);
  // og'ir ishlar: jamoaning eng og'ir chorakida (o'rtacha og'irligi yuqori 25%) bo'lganlar
  const rated = ppl.filter((p) => p.q28.rated >= 5 && p.q28.avg_weight != null), ws = rated.map((p) => p.q28.avg_weight).sort((x, y) => x - y);
  const q75 = ws.length ? ws[Math.round(0.75 * (ws.length - 1))] : 0;
  const heavy = rated.filter((p) => p.q28.avg_weight >= q75).sort((a, b) => b.q28.avg_weight - a.q28.avg_weight || (b.pace ?? 0) - (a.pace ?? 0));
  const row = (p, sub, val, cls = "") => `<div class="hq-row" data-person="${esc(p.name)}">${ava(p.name, p.department, p.state)}
    <span class="hq-n"><b>${esc(p.name)}</b><small title="${esc(sub)}">${esc(sub)}</small></span><span class="hq-v ${cls}">${val}</span></div>`;
  const repSub = (p) => { const x = p.q28.example; if (!x) return ""; const when = x.old_at ? uzDate(parseTs(x.old_at)) : "";
    return x.kind === "nusxa" && x.old_who ? `«${x.title}», ${first(x.old_who)}ning ishi${when ? ", " + when : ""}` : `«${x.title}», ${when ? when + "da" : "oldin"} ham yozilgan`; };
  const col = (title, list, html, empty) => `<div class="hq-col"><h4>${title}<span>${list.length}</span></h4>
    ${list.length ? list.slice(0, 5).map(html).join("") : `<div class="hq-empty">${I("check")}${empty}</div>`}
    ${list.length > 5 ? `<button class="more-link hq-more" data-go="xodimlar">Yana ${list.length - 5} kishi</button>` : ""}</div>`;
  return `<section class="card hq"><div class="ch"><h3>Hisobotlar haqqoniyligi</h3><span class="count">4 hafta</span>
      <div class="right"><button class="more-link" data-go="hisobot">Kunlik hisobotlar</button></div></div>
    <div class="hq-cols">
      ${col("Eski ishni qayta yozgan", rep, (p) => row(p, repSub(p), `${p.q28.repeats} ta`, "risk"), "Hech kim eski ishni qayta yozmagan")}
      ${col("Asosan mayda ish yozadi", small, (p) => row(p, `${p.q28.rated} ta ishdan ${p.q28.small} tasi mayda`, Math.round(100 * share(p)) + "%", "warn"), "Mayda ish bilan to'ldirilgan hisobot yo'q")}
      ${col("Og'ir ishlarni qilyapti", heavy, (p) => row(p, `o'rtacha og'irlik ${nf(p.q28.avg_weight, 1)}, kunlik ish hajmi ${ratio(p.pace_ratio)}`, wt(Math.round(p.q28.avg_weight))), "Hali yetarli baholangan ish yo'q")}
    </div></section>`;
}
// Botga ulanmagan, lekin guruhga yozayotganlar: hisobotlari qabul qilinmayapti — rahbar havolani yuborishi kerak
function unlinkedBar(d) {
  const u = d.unlinked || [];
  if (!u.length || S.asof) return "";
  const skipped = u.reduce((a, x) => a + (x.skipped || 0), 0);
  const names = u.slice(0, 3).map((x) => esc(first(x.name))).join(", ") + (u.length > 3 ? ` va yana ${u.length - 3} kishi` : "");
  return `<div class="ul-bar"><span class="ic">${I("user-plus")}</span>
    <div><b>${u.length} ta yangi odam guruhda: ism-familiyasi va bo'limini tasdiqlang</b><span>${names}${skipped ? `, ${skipped} ta xabari hali qabul qilinmagan` : ""}</span></div>
    <button class="btn btn-dark" id="ulOpen">${I("user-check")}Tasdiqlash</button></div>`;
}
function deptMini(d) {
  const list = d.departments.filter((x) => x.rank).sort((a, b) => a.rank - b.rank);
  return `<section class="card s5 dm"><div class="ch"><h3>Bo'limlar reytingi</h3><span class="count">${list.length}</span>
      <div class="right"><button class="more-link" data-go="bolimlar">Batafsil</button></div></div>
    <div class="cb" style="padding-top:2px">${list.slice(0, 6).map((x) => `<div class="dm-row" data-enter="${esc(x.name)}" title="${esc(x.name)} bo'limi paneliga kirish">
      <span class="rk">${x.rank}</span><span class="dm-n"><b>${esc(x.name)}</b><small>${x.count} xodim${x.best ? `, eng kuchlisi ${esc(first(x.best.name))}` : ""}</small></span>
      <span class="dm-o" title="Kunlik ish hajmi, 1 xodimga, jamoa o'rtachasiga nisbatan">${ratio(x.pace_ratio)}</span>${scoreRing(x.score, "sm")}</div>`).join("")}</div></section>`;
}

/* ================= rahbar yordamchisi: o'zi vaziyatni ko'rsatadi va savolga javob beradi ================= */
const YD = { data: null, at: 0, loading: false, q: "", ans: null, asking: false };
const ydTarget = (x) => (x.person ? `data-person="${esc(x.person)}"` : x.project ? (() => { const pr = (S.data?.projects || []).find((p) => p.name === x.project); return pr ? `data-project="${pr.id}"` : ""; })() : "");
function ydHtml() {
  const d = YD.data;
  const list = YD.loading && !d ? `<div class="sk" style="height:132px"></div>`
    : d && d.items?.length ? d.items.map((x) => `<div class="yd-it lv${x.level} ${ydTarget(x) ? "go" : ""}" ${ydTarget(x)}><i></i><div><b>${esc(x.title)}</b><span>${esc(x.text)}</span></div></div>`).join("")
    : `<div class="yd-empty">${esc(d?.error || "Hozircha aytadigan muhim gap yo'q")}</div>`;
  const a = YD.ans;
  return `<div class="yd-h"><div><h2>Yordamchi</h2><span>${d?.at ? `${clock(d.at).split(", ")[1]} da yozildi` : YD.loading ? "Jamoa ma'lumotini o'qiyapti" : ""}</span></div>
      <button class="icon-btn" id="ydRe" title="Qayta yozish" aria-label="Qayta yozish" ${YD.loading ? "disabled" : ""}>${I("refresh")}</button></div>
    <div class="yd-list">${list}</div>
    <form class="yd-ask" id="ydF"><input id="ydQ" value="${esc(YD.q)}" placeholder="Savol bering: masalan, bu hafta kim eng og'ir ishlarni qildi?" autocomplete="off" maxlength="500">
      <button class="btn btn-dark" ${YD.asking ? "disabled" : ""}>${YD.asking ? "O'ylayapti" : I("send") + "So'rash"}</button></form>
    ${a ? `<div class="yd-ans"><p>${esc(a.answer)}</p>
      ${(a.groups || []).map((g) => `<div class="yd-grp"><h4>${esc(g.title)}<span>${g.people.length}</span></h4><div class="traits">${g.people.map((n) => `<button class="chip" data-person="${esc(n)}">${esc(n)}</button>`).join("")}</div></div>`).join("")}
      ${a.projects.length ? `<div class="traits">${a.projects.map((n) => { const pr = (S.data?.projects || []).find((p) => p.name === n); return pr ? `<button class="chip" data-project="${pr.id}">${esc(n)}</button>` : ""; }).join("")}</div>` : ""}</div>` : ""}`;
}
function drawYd() {
  const box = $("#yd");
  if (!box) return;
  const focus = document.activeElement?.id === "ydQ";
  box.innerHTML = ydHtml();
  bindCommon(box);
  $("#ydRe").onclick = () => loadYd(true);
  const q = $("#ydQ");
  q.oninput = () => (YD.q = q.value);
  if (focus) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
  $("#ydF").onsubmit = async (e) => {
    e.preventDefault();
    const question = q.value.trim();
    if (question.length < 3 || YD.asking) return;
    YD.asking = true; drawYd();
    try { YD.ans = await api("api/assistant/ask", { json: { question } }); }
    catch (err) { toast(esc(err.message), "danger"); }
    YD.asking = false; drawYd();
  };
}
async function loadYd(refresh) {
  if (YD.loading) return;
  if (!refresh && YD.data && Date.now() - YD.at < 10 * 60e3) { drawYd(); return; }
  YD.loading = true; drawYd();
  try { YD.data = await api("api/assistant/brief" + (refresh ? "?refresh=1" : "")); YD.at = Date.now(); }
  catch (e) { if (refresh) toast(esc(e.message), "danger"); }
  YD.loading = false; drawYd();
}

const ACT_ICON = { thank_person: "cup-star", open_report: "doc", deadline: "deadline", reassign: "transfer", ping_person: "chat-dots", ping_project: "chat-dots", ping_blocker: "bell", dm_person: "letter" };
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
    ${S.asof || !can("correct") ? "" : `<button class="fix" data-fix="${f.id}" title="AI noto'g'ri tushungan bo'lsa">${I("pen")}Tuzatish</button>`}</div>`;
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
    <div class="row">${I(DEPT_ICON[p.department] || "user")}${esc(p.department)}${p.rank ? `, <b style="display:inline;font-size:13px">${p.rank}-o'rin</b>` : ""}</div>
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
    rank: (a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9) || (b.pace ?? 0) - (a.pace ?? 0),
    rankLow: (a, b) => (b.rank ?? -1) - (a.rank ?? -1) || (a.pace ?? 0) - (b.pace ?? 0),
    attention: byAttention, score: (a, b) => (b.score ?? -1) - (a.score ?? -1), low: (a, b) => (a.score ?? 101) - (b.score ?? 101),
    load: (a, b) => b.open - a.open, oldest: (a, b) => b.oldest - a.oldest, output: (a, b) => (b.pace ?? -1) - (a.pace ?? -1),
  };
  const list = d.people.filter((p) => (!f.dept || p.department === f.dept) && (!f.state || p.state === f.state)
    && (!f.q || p.name.toLowerCase().includes(f.q.toLowerCase()))).sort(sorts[f.sort]);
  const maxOpen = Math.max(8, ...d.people.map((p) => p.open));
  el.innerHTML = pageHead("Xodimlar", `${d.people.length} xodim, ${esc(periodText(d))}`) + `
    <div class="minis">
      ${miniTile("fire", "lv3", c.overloaded, "Ishi ko'p", "overloaded")}
      ${miniTile("cup", "lv1", c.idle, "Bo'sh, ish berish mumkin", "idle")}
      ${best ? miniTile("cup-star", "lv0", esc(first(best.name)), "1-o'rin, " + scored.length + " xodim ichida", "", best.name) : ""}
      ${worst && worst !== best ? miniTile("graph-down", "lv2", esc(first(worst.name)), "Oxirgi o'rin", "", worst.name) : miniTile("chart", "lv0", avg ?? "—", "O'rtacha reyting")}
    </div>
    <div class="toolbar">
      <label class="searchbox">${I("search")}<input id="pq" type="search" placeholder="Xodimni qidirish" value="${esc(f.q)}" autocomplete="off"></label>
      <span class="vsep"></span>
      ${S.dept ? "" : `<select class="ctl" id="pDept" aria-label="Bo'lim"><option value="">Barcha bo'limlar</option>${depts.map((x) => `<option ${f.dept === x ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>`}
      ${stateChips(c, f.state, "people")}
      <div class="pp-sort-wrap"><div class="seg pp-sort" role="group" aria-label="Tartib">
        <button data-sort="rank" aria-pressed="${f.sort === "rank"}" title="Eng zoridan eng pastigacha">Reyting</button>
        <button data-sort="output" aria-pressed="${f.sort === "output"}">Ish hajmi</button>
        <button data-sort="attention" aria-pressed="${f.sort === "attention"}">Muammolilar</button></div>
      <select class="ctl" id="psort" aria-label="Boshqa tartib">
        <option value="" disabled ${["rank", "output", "attention"].includes(f.sort) ? "selected" : ""}>Boshqa tartib</option>
        <option value="rankLow">Reyting: pastdan</option><option value="load">Ochiq vazifa ko'p</option><option value="oldest">Eng eski vazifa</option></select></div>
    </div>
    <div class="pgrid">${headCard(d, f) + list.map((p) => personCard(p, maxOpen)).join("") || `<div class="card" style="grid-column:1/-1">${emptyBox("Bu filtrga mos xodim yo'q", "search")}</div>`}</div>`;
  bindHead(el);
  if (!["rank", "output", "attention"].includes(f.sort)) $("#psort").value = f.sort;
  $$("[data-sort]", el).forEach((b) => (b.onclick = () => { f.sort = b.dataset.sort; renderPeople(S.data); }));
  $(".ph .filters", el).insertAdjacentHTML("beforeend", `<button class="icon-btn" id="pLinks" title="Xodimlarni botga ulash" aria-label="Xodimlarni botga ulash">${I("user-plus")}</button>`);
  $("#pLinks").onclick = openLinks;
  $("#pDept")?.addEventListener("change", (e) => { f.dept = e.target.value; renderPeople(S.data); });
  $$("[data-headrep]", el).forEach((b) => (b.onclick = () => openAction({ type: "open_report", name: b.dataset.headrep })));
  $("#psort").onchange = (e) => { f.sort = e.target.value; renderPeople(S.data); };
  const q = $("#pq");
  q.oninput = () => { f.q = q.value; clearTimeout(q._t); q._t = setTimeout(() => { renderPeople(S.data); const n = $("#pq"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }, 160); };
  $$("[data-pd]", el).forEach((b) => b.onclick = () => { f.dept = f.dept === b.dataset.pd ? "" : b.dataset.pd; renderPeople(S.data); });
  $$("[data-ps]", el).forEach((b) => b.onclick = () => { f.state = f.state === b.dataset.ps ? "" : b.dataset.ps; renderPeople(S.data); });
  $$("[data-mini]", el).forEach((b) => b.onclick = () => { f.state = f.state === b.dataset.mini ? "" : b.dataset.mini; renderPeople(S.data); });
  bindCommon(el);
  countUp(el, "xodimlar");
}
// Rahbar reytingga kirmaydi; qidiruvda uning ismi yozilsa alohida kartochka chiqadi
function headCard(d, f) {
  const h = d.head;
  if (!h || !f.q || !fold(h.name).includes(fold(f.q)) || f.state) return "";
  return `<article class="card pc head-card"><div class="pc-h"><span class="ava-wrap">${ava(h.name, h.department, null, "md")}<span class="ava-crown" title="Rahbar">${I("crown")}</span></span>
      <div class="who"><b>${esc(h.name)}</b><span class="dept">Panel egasi, rahbar</span></div></div>
    <div><span class="pill p-idle"><span><b>Xodimlar reytingiga kirmaydi</b></span></span></div>
    <button class="btn btn-line" data-headrep="${esc(h.name)}">${I("doc")}Hisobotlarini ko'rish</button></article>`;
}
function miniTile(icon, lv, value, label, filter, person) {
  const attr = person ? `data-person="${esc(person)}"` : filter ? `data-mini="${filter}"` : "";
  return `<div class="card mini ${attr ? "lift" : ""} ${lv}" ${attr}><span class="ic">${I(icon)}</span><div style="min-width:0"><b>${value}</b><span>${label}</span></div></div>`;
}
function personCard(p, maxOpen) {
  const lc = p.state === "overloaded" ? "var(--risk)" : p.open === 0 ? "var(--idle)" : "var(--azure)";
  return `<article class="card pc lift" data-person="${esc(p.name)}">
    <div class="pc-h"><span class="ava-wrap">${ava(p.name, p.department, p.state, "md")}${p.role === "rahbar" ? `<span class="ava-crown" title="Rahbar">${I("crown")}</span>` : ""}</span>
      <div class="who"><b>${p.rank ? `<span class="rk" title="${p.rank}-o'rin, ${p.rank_of} xodim ichida">${p.rank}</span>` : ""}${esc(p.name)}${mv(p)}</b><span class="dept">${esc(p.department)}${p.dept_rank && p.dept_rank_of > 1 ? `, bo'limida ${p.dept_rank}-o'rin` : ""}</span></div>
      ${scoreRing(p.score, "", p)}</div>
    <div>${statePill(p.state, p.fact)}</div>
    <div class="mets"><div><b class="num">${p.open}</b><span>ochiq</span></div><div><b class="num">${p.done}</b><span>bajardi</span></div>
      <div title="Kunlik ish hajmi, jamoa o'rtachasiga nisbatan"><b class="num">${ratio(p.pace_ratio)}</b><span>ish hajmi</span></div></div>
    ${(p.traits || []).length ? `<div class="traits">${p.traits.slice(0, 3).map((t) => `<span class="bd-chip ${t.tone === "risk" ? "risk" : t.tone === "warn" ? "warn" : ""}">${esc(t.label)}</span>`).join("")}</div>` : ""}
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
        ${th("name", "Loyiha")}${th("people_count", S.period === "day" ? "Bugun yozdi" : "Kim yozyapti")}${th("start_date", "Yo'l", "hide-m")}${th("progress", "Bajarilgan")}${th("days_left", "Muddat")}${th("late_days", "Prognoz", "hide-m")}${th("level", "Holat")}
        </tr></thead><tbody>${rows.map((p) => `<tr data-project="${p.id}">
          <td class="pname"><b>${esc(p.name)}</b><span>${p.risks[0] ? esc(p.risks[0].text) : p.chat_title && p.chat_title !== p.name ? esc(p.chat_title) : ""}</span></td>
          <td class="pwho">${prPeople(p)}</td>
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
/* Loyihaga (guruhga) shu davrda yozganlar: yuzlar va ismlar. "Bugun"da guruhda yozib turgan, lekin bugun yozmaganlar ham */
function prPeople(p) {
  const ppl = S.data?.people || [], shown = p.people.slice(0, 4), names = (xs) => xs.slice(0, 4).map(first).join(", ") + (xs.length > 4 ? ` va yana ${xs.length - 4}` : "");
  const miss = S.period === "day" && p.absent?.length ? `<span class="pr-miss" title="${esc(p.absent.join(", "))}">Yozmadi: ${esc(names(p.absent))}</span>` : "";
  const wrote = p.people.length ? `<span class="pr-ppl" title="${esc(p.people.join(", "))}"><span class="pr-faces">${shown.map((n) => { const q = ppl.find((x) => x.name === n);
    return ava(n, q?.department, q?.state, "xs"); }).join("")}</span><span class="pr-names">${esc(names(p.people))}</span></span>`
    : `<span class="pr-ppl none">${S.period === "day" ? "Bugun hech kim yozmadi" : "Hali hech kim"}</span>`;
  return `<div class="pr-who">${wrote}${miss}</div>`;
}
function trackOnly(p, d) { const html = roadRow(p, d); return html.slice(html.indexOf('<div class="track'), html.lastIndexOf("</div>")); }

/* ================= 5. Bo'limlar ================= */
/* Bo'limlar reytingi: eng zoridan pastga; tartib baho, ish hajmi yoki o'sish bo'yicha */
const DK = { sort: "rank" };
const DK_SORT = {
  rank: (a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9),
  output: (a, b) => (b.per_person ?? -1) - (a.per_person ?? -1),
  trend: (a, b) => (b.trend ?? -1e9) - (a.trend ?? -1e9),
  weight: (a, b) => (b.avg_weight ?? -1) - (a.avg_weight ?? -1),
};
function deptLeaders(d) {
  const list = d.departments.slice().sort(DK_SORT[DK.sort]);
  const maxPP = Math.max(1, ...list.map((x) => x.per_person || 0));
  const th = (k, t) => `<button data-dk="${k}" aria-pressed="${DK.sort === k}">${t}</button>`;
  return `<section class="card s12 dl"><div class="ch"><h3>Bo'limlar reytingi</h3>
      <div class="right"><div class="seg" role="group" aria-label="Tartib">${th("rank", "Reyting")}${th("output", "Ish hajmi")}${th("weight", "Og'ir ishlar")}${th("trend", "O'sish")}</div></div></div>
    <div class="cb"><div class="dl-head"><span></span><span>Bo'lim</span><span>Reyting</span><span>Kunlik ish hajmi, 1 xodimga</span><span>Og'irlik</span><span>Bajarilish</span><span>4 haftada</span><span>Eng kuchli</span><span></span></div>
      ${list.map((x, i) => `<div class="dl-row ${x.rank ? "" : "na"}" data-dept="${esc(x.name)}">
        <span class="dl-n">${DK.sort === "rank" ? (x.rank ?? "—") : i + 1}</span>
        <span class="dl-name"><span class="dico">${I(DEPT_ICON[x.name] || "user")}</span><span><b>${esc(x.name)}</b><small>${x.count} xodim${x.repeats30 ? `, <em>${x.repeats30} ta qayta yozilgan</em>` : ""}</small></span></span>
        <span class="dl-score">${scoreRing(x.score)}</span>
        <span class="dl-out" title="Jamoa o'rtachasiga nisbatan"><span class="dl-bar"><i style="width:${Math.round((100 * (x.per_person || 0)) / maxPP)}%"></i></span><b>${ratio(x.pace_ratio)}</b></span>
        <span class="dl-w">${x.avg_weight != null ? `${wt(Math.round(x.avg_weight))}<b>${nf(x.avg_weight, 1)}</b>${x.small_share != null ? `<small>${x.small_share}% mayda</small>` : ""}` : "—"}</span>
        <span class="dl-pct">${x.pct == null ? "—" : x.pct + "%"}</span>
        <span class="dl-tr ${x.trend == null ? "" : x.trend >= 0 ? "up" : "down"}">${x.trend == null ? "—" : (x.trend > 0 ? "+" : "") + x.trend + "%"}</span>
        <span class="dl-best">${x.best ? `<span data-person="${esc(x.best.name)}">${esc(x.best.name)}<small>${x.best.rank}-o'rin</small></span>` : "—"}</span>
        <button class="icon-btn dl-go" data-enter="${esc(x.name)}" title="${esc(x.name)} bo'limi paneliga kirish" aria-label="Bo'lim paneliga kirish">${I("arrow")}</button>
      </div>`).join("")}</div></section>`;
}
function renderDepts(d) {
  const el = $("#v-bolimlar");
  const top = d.departments.find((x) => x.rank === 1);
  el.innerHTML = pageHead("Bo'limlar", `${d.departments.length} bo'lim, ${esc(periodText(d))}${top ? `. Eng kuchlisi: ${esc(top.name)}` : ""}`) + `
    <div class="grid">
      ${deptLeaders(d)}
      <section class="card s12"><div class="ch"><h3>Taqqoslama</h3><div class="right road-legend"><span><i class="o" style="border:0;background:var(--azure)"></i>Bajarildi</span><span><i class="o" style="border:0;background:var(--surface-3)"></i>Ochiq</span></div></div>
        <div class="cb"><div style="height:${Math.max(200, d.departments.length * 50)}px"><canvas id="cDept"></canvas></div></div></section>
      <div class="s12 dgrid">${d.departments.slice().sort(DK_SORT.rank).map((x) => deptCard(x, d.people.filter((p) => p.department === x.name))).join("")}</div>
    </div>`;
  bindHead(el);
  drawDepts($("#cDept"), d.departments);
  bindCommon(el);
  $$("[data-dk]", el).forEach((b) => (b.onclick = () => { DK.sort = b.dataset.dk; renderDepts(S.data); }));
  $$("[data-enter]", el).forEach((b) => (b.onclick = (e) => { e.stopPropagation(); setDept(b.dataset.enter, "brifing"); }));
  $$(".dl-row", el).forEach((r) => (r.onclick = (e) => {
    if (e.target.closest("[data-person], [data-enter]")) return;
    const card = $(`.dc[data-dc="${CSS.escape(r.dataset.dept)}"]`, el);
    if (card) { card.scrollIntoView({ behavior: "smooth", block: "start" }); card.classList.add("flash"); setTimeout(() => card.classList.remove("flash"), 1200); }
  }));
}
function deptCard(x, ppl) {
  const best = ppl.filter((p) => p.score != null).sort((a, b) => b.score - a.score)[0];
  return `<article class="card dc" data-dc="${esc(x.name)}">
    ${x.rank ? `<span class="pc-rank" title="${x.rank_of} bo'lim ichida">${x.rank}</span>` : ""}
    <div class="dc-h"><span class="dico">${I(DEPT_ICON[x.name] || "user")}</span><div><b>${esc(x.name)}</b><span>${x.count} xodim${x.rank ? `, ${x.rank}-o'rin ${x.rank_of} bo'lim ichida` : ""}</span></div><div style="margin-left:auto">${scoreRing(x.score)}</div></div>
    ${S.dept ? "" : `<button class="btn btn-line dc-go" data-enter="${esc(x.name)}">${I("arrow")}Bo'lim paneliga kirish</button>`}
    <div class="dstats"><div><b class="num">${x.open}</b><span>ochiq</span></div><div><b class="num">${x.created}</b><span>yangi</span></div>
      <div><b class="num">${x.done}</b><span>bajarildi</span></div><div><b class="num">${x.pct == null ? "—" : x.pct + "%"}</b><span>bajarilish</span></div></div>
    <div class="dbody">${stateBar(x.states)}
      <div class="plist">${ppl.sort((a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9)).map((p, i) => `<div class="prow" data-person="${esc(p.name)}">${ava(p.name, p.department, p.state)}
        <div><b>${p.rank ? `<span class="in-rank">${i + 1}</span>` : ""}${esc(p.name)}${mv(p)}${best && best.name === p.name ? ` <span class="pill p-ok sm" style="margin-left:4px">${I("cup-star")}eng yaxshi</span>` : ""}</b><span>${p.rank ? `Umumiy ${p.rank}-o'rin, ` : ""}${esc(p.fact)}</span></div>${scoreRing(p.score, "", p)}</div>`).join("")}</div>
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
  const c = css(), sp = p.score_parts, W = p.weights || {};
  const pct = (k) => (W[k] && sp[k] != null ? Math.round((100 * sp[k]) / W[k]) : null);
  const vals = [p.completion ?? 0, pct("output"), pct("speed"), p.regular ?? 0, pct("fresh")];
  return new Chart(canvas, {
    type: "radar",
    data: { labels: ["Bajarish", "Ish hajmi", "Tezlik", "Muntazamlik", "Eskirmagan"], datasets: [{ data: vals, backgroundColor: rgba(c.brand, 0.16), borderColor: c.brand, borderWidth: 2, pointBackgroundColor: c.brand, pointRadius: 3 }] },
    options: Object.assign(chartBase(c), { interaction: { mode: "nearest", intersect: true }, scales: { r: { min: 0, max: 100, ticks: { display: false, stepSize: 25 }, grid: { color: c.line }, angleLines: { color: c.line },
      pointLabels: { color: c.ink, font: { size: 11.5, weight: "600", family: "Onest" } } } } }),
  });
}

/* ================= yon oyna: xodim ================= */
async function openPersonOld(name) {
  S.open = "p:" + name; writeHash();
  openDrawer(skelHead());
  let d;
  try { d = await api("api/person?" + new URLSearchParams({ name }) + "&" + query()); } catch (e) { closeDrawer(); toast(esc(e.message), "danger"); return; }
  const p = d.person, sp = p.score_parts;
  const bd = sp ? [
    ["Vazifani bajarish", sp.completion, d.weights.completion, `4 haftada olgan vazifalarining ${p.completion}% ini yopgan (jamoada o'rtacha ${d.team_avg.completion}%)`],
    ["Ish hajmi", sp.output, d.weights.output, `Kunlik ish hajmi, jamoa o'rtachasiga nisbatan: ${ratio(p.pace_ratio)}. Har ishni AI 1 dan 5 gacha baholaydi, bir kunda 3 tadan ortiq mayda ish chorak hisoblanadi`],
    ["Tezlik", sp.speed, d.weights.speed, p.cycle != null ? `Berilgan vazifaga o'rtacha ${nf(p.cycle, 1)} kun` : ""],
    ["Muntazam hisobot", sp.regular, d.weights.regular, `Oxirgi 2 haftaning ish kunlarida ${p.regular}% hisobot bergan (o'rtacha ${d.team_avg.regular}%)`],
    ["Eskirgan vazifa yo'qligi", sp.fresh, d.weights.fresh, p.stale ? `${p.stale} ta vazifa 7 kundan ortiq ochiq` : "7 kundan eski ochiq vazifa yo'q"],
  ].filter((r) => r[2] > 0 && r[1] != null) : [];
  const depts = [...new Set([...(d.departments || []), p.department])].filter((x) => x !== "Belgilanmagan");
  $("#drawer .sheet").innerHTML = `
    <div class="sh-head">${ava(p.name, p.department, p.state, "lg")}
      <div style="min-width:0"><div class="name-row"><h2>${esc(p.name)}${p.role === "rahbar" ? I("crown", "crown") : ""}</h2>${p.id && !S.asof && can("people") ? `<button class="icon-btn name-edit" id="nameBtn" title="Ism-familiyani yozish" aria-label="Ism-familiyani yozish">${I("pen")}</button>` : ""}</div><div class="meta">${statePill(p.state, p.fact, true)}
        ${p.id && can("people") ? `<select class="ctl" id="deptSel" style="height:28px;font-size:12.5px;padding-left:10px">${p.department === "Belgilanmagan" ? `<option value="">Bo'lim tanlang</option>` : ""}${depts.map((x) => `<option ${x === p.department ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>` : `<span>${esc(p.department)}</span>`}
        ${p.id && !S.asof && can("people") ? `<button class="role-btn" id="roleBtn" aria-pressed="${p.role === "rahbar"}" title="Rahbar boshqalarga vazifa bera oladi va botning guruhdagi savollarini hal qiladi">${I("crown")}Rahbar</button>` : ""}
        ${p.username ? `<span>@${esc(p.username)}</span>` : ""}</div></div>
      <button class="icon-btn x" aria-label="Yopish">${I("close")}</button></div>
    <div class="sh-body">
      ${S.asof || !can("decide") ? "" : `<div class="sh-acts">${p.open ? `<button class="btn btn-dark" id="pMove">${I("transfer")}Vazifa o'tkazish</button>` : ""}
        <button class="btn btn-line" id="pPing">${I("chat-dots")}Holatini so'rash</button></div>`}
      ${S.asof || !can("people") ? "" : `<section class="card"><div class="ch"><h3>Shaxsiy aloqa</h3></div><div class="cb" id="pContact"><div class="sk" style="height:36px"></div></div></section>`}
      <div class="tiles"><div class="tile"><b class="num">${p.open}</b><span>ochiq</span></div><div class="tile"><b class="num">${p.done}</b><span>bajardi</span></div>
        <div class="tile" title="Kunlik ish hajmi, jamoa o'rtachasiga nisbatan${p.hours ? ". Bu davrda taxminan " + fmtH(p.hours) + " mehnat" : ""}"><b class="num">${ratio(p.pace_ratio)}</b><span>ish hajmi${p.avg_weight ? ", og'irlik " + nf(p.avg_weight, 1) : ""}</span></div>
        <div class="tile ${p.repeats ? "bad" : ""}"><b class="num">${p.trust == null ? "—" : p.trust + "%"}</b><span>${p.repeats ? p.repeats + " ta qayta yozilgan" : "hisobot haqqoniy"}</span></div></div>
      <section class="card"><div class="cb"><div class="scorebox">${scoreRing(p.score, "xl", p)}
        <div><b style="font:640 17px var(--display)">${p.rank ? `${p.rank}-o'rin, ${p.rank_of} xodim ichida` : "Reyting uchun ma'lumot kam"}${mv(p)}</b>
          <div style="font-size:13px;color:var(--ink-3);margin-top:2px">${p.score != null ? [esc(p.grade), p.dept_rank_of > 1 ? `bo'limida ${p.dept_rank}-o'rin` : "",
            `ish hajmi bo'yicha ${p.out_rank}-o'rin`, p.trend != null ? `oldingi 4 haftaga nisbatan ${p.trend > 0 ? "+" : ""}${p.trend}%` : "",
            p.new ? `taxminiy, ${p.evidence} ish kuni kuzatildi` : ""].filter(Boolean).join(", ") : "4 haftada kamida 3 ta ish kerak"}</div>
          ${(p.traits || []).length ? `<div class="traits" style="margin-top:8px">${p.traits.map((t) => `<span class="bd-chip ${t.tone === "risk" ? "risk" : t.tone === "warn" ? "warn" : ""}">${esc(t.label)}</span>`).join("")}</div>` : ""}</div></div>
        ${sp ? `<div class="radar-row"><div style="height:200px"><canvas id="cRadar"></canvas></div>
          <div class="sb">${bd.map((r) => `<div class="sb-row" title="${esc(r[3])}"><span>${r[0]}</span><b>${r[1]}/${r[2]}</b><div class="bar"><i style="width:${Math.round((100 * r[1]) / r[2])}%"></i></div></div>`).join("")}
            ${sp.penalty ? `<div class="sb-row pen" title="${p.repeats30} ta eski ish yangi deb qayta yozilgan (30 kunda)"><span>Qayta yozilgan ish</span><b>${sp.penalty}</b></div>` : ""}</div></div>` : ""}
      </div></section>
      <section class="card"><div class="ch"><h3>Bajargan ishi</h3><span class="count">14 kun</span></div><div class="cb"><div style="height:150px"><canvas id="cPerson"></canvas></div></div></section>
      <section class="card"><div class="ch"><h3>Ochiq vazifalari</h3><span class="count">${p.open}</span></div>
        <div class="cb" style="padding-top:4px">${p.open_tasks.map((t) => `<div class="task"><span>${esc(t.title)}</span>${dueTag(t)}<small>${esc(t.project || "")}, ${clock(t.created_at)}${t.giver ? `, ${esc(first(t.giver))} berdi` : ""}</small></div>`).join("") || emptyBox("Ochiq vazifa yo'q")}</div></section>
      <section class="card"><div class="ch"><h3>Bajargan ishlari</h3><span class="count">${d.done_tasks.length}</span></div>
        <div class="cb" style="padding-top:4px">${d.done_tasks.map((t) => `<div class="task ${t.dup_kind === "takror" || t.dup_kind === "nusxa" ? "dup" : ""}"><span>${wt(t.weight, t.wnote)} ${esc(t.title)}</span><span class="age new">${nf(t.days, 1)} kunda</span><small>${esc(t.project || "")}, ${clock(t.done_at)}${t.dup_kind === "takror" || t.dup_kind === "nusxa" ? ". Oldin ham yozilgan" : t.hours ? ", taxminan " + fmtH(t.hours) : ""}</small></div>`).join("") || emptyBox("Bu davrda yopilgan vazifa yo'q", "clock")}</div></section>
    </div>`;
  $("#drawer .x").onclick = closeDrawer;
  S.charts.person?.destroy(); S.charts.radar?.destroy();
  S.charts.person = drawBars($("#cPerson"), d.series, css().ok);
  S.charts.radar = drawRadar($("#cRadar"), Object.assign({ weights: d.weights }, p));
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
  $("#roleBtn")?.addEventListener("click", async (e) => {
    const b = e.currentTarget, on = b.getAttribute("aria-pressed") !== "true";
    try { await api("api/person/role", { json: { name: p.name, role: on ? "rahbar" : "" } }); b.setAttribute("aria-pressed", on);
      toast(on ? `${esc(first(p.name))} endi rahbar` : `${esc(first(p.name))} rahbar emas`, "check"); load(true); }
    catch (err) { toast(esc(err.message), "danger"); }
  });
  if (!S.asof && can("people")) loadContact(p);
  $("#pPing")?.addEventListener("click", () => openAction({ type: "ping_person", name: p.name }));
}

/* ================= yon oyna: loyiha ================= */
// Loyiha endi alohida sahifa (Loyihalar › nomi): kunlar, xabarlar, murojaatlar va jamoa bir joyda
function openProject(id) {
  if ($("#drawer").classList.contains("open")) closeDrawer();
  if ($("#modal").classList.contains("open")) closeModal();
  openProjectDrawer(id);
}
async function openProjectOld(id) {
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
      ${S.asof || !can("decide") ? "" : `<div class="sh-acts"><button class="btn btn-dark" id="prDl">${I("deadline")}Muddatni o'zgartirish</button>
        <button class="btn btn-line" id="prPing">${I("chat-dots")}Holatni so'rash</button>
        ${p.blocker_list.length ? `<button class="btn btn-line" id="prBl">${I("bell")}Muammo bo'yicha eslatish</button>` : ""}</div>`}
      <div class="tiles"><div class="tile"><b class="num">${p.progress}%</b><span>bajarilgan</span></div><div class="tile"><b class="num">${p.open_total}</b><span>ochiq</span></div>
        <div class="tile"><b class="dt">${p.deadline_label ? esc(p.deadline_label) : "—"}</b><span>${p.deadline ? (p.days_left < 0 ? -p.days_left + " kun o'tdi" : p.days_left + " kun qoldi") : "muddat"}</span></div>
        <div class="tile"><b class="dt" style="color:${p.late_days ? "var(--risk-ink)" : "inherit"}">${p.eta_label ? esc(p.eta_label) : "—"}</b><span>${p.late_days ? p.late_days + " kun kech" : "prognoz"}</span></div></div>
      <section class="card"><div class="cb" style="padding-top:26px">${roadRow(p, S.data || { now: d.period.to + " 12:00:00", period: d.period }, true)}</div></section>
      ${p.risks.length ? `<section class="card"><div class="ch"><h3>Nega shu holatda</h3></div><div class="cb"><div class="why">${p.risks.map((r) => `<div class="why-i lv${r.level}"><div><b>${LEVEL[r.level]}</b>${esc(r.text)}</div></div>`).join("")}</div></div></section>` : ""}
      <section class="card"><div class="ch"><h3>Dinamika</h3><span class="count">kuniga ${nf(p.velocity, 1)} ta</span></div><div class="cb"><div style="height:170px"><canvas id="cProject"></canvas></div></div></section>
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
  const tomorrow7 = new Date(Date.now() + 7 * 864e5);
  $("#prDl")?.addEventListener("click", () => openAction({ type: "deadline", project_id: p.id, date: p.eta_date || isoDay(tomorrow7) }));
  $("#prPing")?.addEventListener("click", () => openAction({ type: "ping_project", project_id: p.id }));
  $("#prBl")?.addEventListener("click", () => openAction({ type: "ping_blocker", project_id: p.id }));
}

const skelHead = () => `<div class="sh-head"><div class="sk" style="width:56px;height:56px;border-radius:50%"></div><div style="flex:1"><div class="sk" style="height:20px;width:55%"></div><div class="sk" style="height:13px;width:35%;margin-top:9px"></div></div></div>
  <div class="sh-body"><div class="sk" style="height:84px"></div><div class="sk" style="height:220px"></div><div class="sk" style="height:160px"></div></div>`;
function openDrawer(html) {
  const dr = $("#drawer");
  dr.classList.remove("wide", "xwide");
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
  const unlinked = rows.filter((x) => !x.linked && x.status !== "begona");
  // Guruhga yozgan har bir odam shu yerda: rahbar uni xodim qiladi (havolasiz ham hisobot qabul qilinadi, oldingi yozganlari
  // qayta o'qiladi), begona deydi (hisobga olinmaydi) yoki o'zi ulanishi uchun havolasini yuboradi
  const what = (x) => x.id < 0 ? "Panelda qo'shilgan, havolani hali ochmagan" : x.status === "begona" ? "Begona, hisobga olinmaydi" : x.owner ? "Rahbar, panel egasi" : x.lead ? "Rahbar: ismi aytilmagan topshirig'i jamoaga beriladi"
    : x.linked ? "Xodim, botga ulangan" : x.status === "xodim" ? "Xodim, tasdiqlangan"
    : x.skipped ? `Yangi, ${x.skipped} ta xabari hali qabul qilinmagan` : x.msgs === 0 ? "Yangi, guruhga qo'shilgan, hali yozmagan" : "Yangi, hisobotlari hisobga olinyapti";
  openModal("Guruhdagi odamlar", rows.length ? `<div class="links">${rows.map((x, i) => { const pp = people.find((q) => q.name === x.name);
      return `<div class="link-row ${x.status === "begona" ? "dim" : ""}">${ava(x.name, pp?.department, pp?.state)}<div style="min-width:0"><b>${esc(x.name)}</b><span>${what(x)}</span>
        <small class="tgid">${x.username ? `<a href="https://t.me/${esc(x.username)}" target="_blank" rel="noopener">@${esc(x.username)}</a>, ` : ""}ID ${x.id}${x.tg_name && x.tg_name !== x.name ? `, Telegramda: ${esc(x.tg_name)}` : ""}</small></div>
        <span class="link-acts">${x.status !== "begona" ? `<select class="ctl sm" data-dp="${i}" aria-label="Bo'lim"><option value="">Bo'lim</option>${(S.meta?.departments || []).map((d) => `<option ${pp?.department === d ? "selected" : ""}>${esc(d)}</option>`).join("")}</select>
          <button class="icon-btn" data-nm="${i}" title="Ism-familiyani tuzatish" aria-label="Ism-familiyani tuzatish">${I("pen")}</button>` : ""}
          ${x.status !== "begona" && !x.owner ? `<button class="btn btn-line sm" data-rl="${i}" aria-pressed="${!!x.lead}">${I("crown")}Rahbar</button>` : ""}
          ${!x.linked && !x.lead && x.status !== "xodim" ? `<button class="btn btn-dark sm" data-st="xodim" data-i="${i}">${I("user-check")}Xodim qilish</button>` : ""}
          ${!x.linked && x.status !== "begona" ? `<button class="btn btn-ghost sm" data-st="begona" data-i="${i}">Begona</button>` : ""}
          ${x.status === "xodim" && !x.linked ? `<button class="btn btn-ghost sm" data-st="" data-i="${i}">Bekor qilish</button>` : ""}
          <button class="icon-btn" data-cp="${i}" title="Ulanish havolasini nusxalash" aria-label="Ulanish havolasini nusxalash">${I("copy")}</button></span></div>`; }).join("")}</div>` : emptyBox("Odamlar guruhga yozishi bilan shu yerda paydo bo'ladi", "people"),
    `${can("people") ? `<button class="btn btn-line" id="lkAdd">${I("user-plus")}Xodim qo'shish</button>` : ""}${unlinked.length ? `<button class="btn btn-dark" id="cpAll">${I("copy")}Ulanmaganlar havolalarini nusxalash</button>` : ""}`, true);
  $("#lkAdd")?.addEventListener("click", openAddPerson);
  $$("[data-cp]").forEach((b) => b.addEventListener("click", () => copyText(rows[+b.dataset.cp].link, `${first(rows[+b.dataset.cp].name)} havolasi nusxalandi`)));
  $$("[data-dp]").forEach((s) => s.addEventListener("change", async () => {
    const x = rows[+s.dataset.dp];
    try { await api("api/person/department", { json: { name: x.name, department: s.value } }); toast(`<b>${esc(x.name)}</b>: ${esc(s.value || "bo'lim olib tashlandi")}`, "check"); load(true); }
    catch (e) { toast(esc(e.message), "danger"); }
  }));
  $$("[data-nm]").forEach((b) => b.addEventListener("click", () => {
    const x = rows[+b.dataset.nm];
    openModal("Ism-familiya", `<div class="field"><label for="nmIn">${esc(x.name)}</label><input id="nmIn" value="${esc(x.name)}" maxlength="60" autocomplete="off"></div>`,
      `<button class="btn btn-ghost" id="nmBack">Orqaga</button><button class="btn btn-dark" id="nmGo">${I("check")}Saqlash</button>`);
    $("#nmIn").focus(); $("#nmIn").select();
    $("#nmBack").onclick = openLinks;
    const save = async () => {
      const v = $("#nmIn").value.trim();
      if (v.length < 2 || v === x.name) { openLinks(); return; }
      try { await api("api/person/name", { json: { name: x.name, new_name: v } }); toast(`Saqlandi: <b>${esc(v)}</b>`, "check"); await load(true); openLinks(); }
      catch (e) { toast(esc(e.message), "danger"); }
    };
    $("#nmGo").onclick = save;
    $("#nmIn").onkeydown = (e) => { if (e.key === "Enter") save(); };
  }));
  $$("[data-rl]").forEach((b) => b.addEventListener("click", async () => {
    const x = rows[+b.dataset.rl], on = !x.lead;
    b.disabled = true;
    try { await api("api/person/role", { json: { name: x.name, role: on ? "rahbar" : "" } }); } catch (e) { b.disabled = false; toast(esc(e.message), "danger"); return; }
    toast(on ? `<b>${esc(x.name)}</b> rahbar: ismi aytilmagan topshiriqlari jamoaga beriladi` : `<b>${esc(x.name)}</b> rahbar emas`, "check");
    await load(true);
    openLinks();
  }));
  $$("[data-st]").forEach((b) => b.addEventListener("click", async () => {
    const x = rows[+b.dataset.i], st = b.dataset.st;
    b.disabled = true;
    try { await api("api/person/status", { json: { name: x.name, status: st } }); } catch (e) { b.disabled = false; toast(esc(e.message), "danger"); return; }
    toast(st === "xodim" ? `<b>${esc(x.name)}</b> xodim qilindi: oldin yozgan hisobotlari ham hisobga kiradi` : st === "begona" ? `<b>${esc(x.name)}</b> begona deb belgilandi` : "Bekor qilindi", "check");
    await load(true);
    openLinks();
  }));
  $("#cpAll")?.addEventListener("click", () => copyText(unlinked.map((x) => `${x.name}: ${x.link}`).join("\n"), `${unlinked.length} ta havola nusxalandi`));
}

/* ================= qaror: oldindan ko'rish va tasdiq ================= */
async function openAction(action) {
  if (action.type === "open_report") { RP.q = action.name; RP.day = ""; RP.last = action.name; RP.only = ""; RP.data = null; closeDrawer(); go("hisobot"); return; }
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
  const editable = action.type === "thank_person" || action.type === "dm_person" || (action.type === "ping_person" && pv.private);
  body += editable ? `<div class="field"><label for="actText">Xabar</label><textarea id="actText">${esc(pv.message)}</textarea></div>`
    : `<div class="tg"><div class="tg-b"><b>Puls</b>${esc(pv.message)}</div></div>`;
  body += `<div class="note">${I(pv.will_send ? "send" : "info")}${esc(pv.note)}</div>`;
  const verb = { reassign: "Vazifani o'tkazish", deadline: "Muddatni o'zgartirish", thank_person: "Rahmat yuborish" }[action.type] || (pv.will_send ? "Yuborish" : "Saqlash");
  openModal(esc(pv.title), body, `<button class="btn btn-ghost" data-close>Bekor qilish</button><button class="btn btn-dark" id="doAct">${I(ACT_ICON[action.type] || "check")}${verb}</button>`);
  $("#actText")?.addEventListener("input", (e) => { action.text = e.target.value; });
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
  openModal("Tezkor tugmalar", [["1 – 5", "bo'limlar"], ["Ctrl + K", "qidirish"], ["T", "yorug' / qorong'i"], ["Esc", "yopish"]].map((r) => `<div class="code"><span>${r[0]}</span><small>${r[1]}</small></div>`).join(""));
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
    ...(S.data.head ? [{ t: S.data.head.name, s: "Rahbar, hisobotlari", ic: ava(S.data.head.name), act: () => openAction({ type: "open_report", name: S.data.head.name }) }] : []),
    ...S.data.projects.map((p) => ({ t: p.name, s: "Loyiha, " + LEVEL[p.level], ic: `<span class="ic lv${p.level}" style="width:34px;height:34px;border-radius:10px">${I("projects")}</span>`, act: () => openProject(p.id) })),
    ...SECTIONS.map((t) => ({ t: t[1], s: "Kunlik holat bo'limi", ic: `<span class="ic lv1" style="width:34px;height:34px">${I(t[2])}</span>`, act: () => goSection(t[0]) })),
    ...TABS.filter((t) => EXTRA_VIEWS.includes(t[0])).map((t) => ({ t: t[2], s: "Qo'shimcha ko'rinish", ic: `<span class="ic lv1" style="width:34px;height:34px">${I(t[3])}</span>`, act: () => go(t[0]) })),
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
  S.asof = day; S.asofAuto = false; S.officeKey = ""; writeHash(); await load(); live(true);
}
function renderHist() {
  const h = $("#hist");
  // o'tgan kun sahifa sarlavhasidagi sana tugmasida ko'rinadi; alohida ogohlantirish qatori faqat sarlavhasiz eski sahifalarda
  if (!S.asof || !["brifing", "ofis", "xodimlar"].includes(S.tab)) { h.hidden = true; return; }
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
  $$("[data-rep]", root).forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); openRepeatProof(b.dataset.rep); }));
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
  const order = SECTIONS.map((t) => t[0]);
  document.body.classList.add("tv");
  document.documentElement.requestFullscreen?.().catch(() => {});
  if (S.tab !== "holat") go("holat");
  let i = Math.max(0, order.indexOf(S.secOn || "umumiy")), left = 20;
  const bar = document.createElement("div");
  bar.className = "tv-bar";
  document.body.appendChild(bar);
  const tick = () => {
    if (--left <= 0) { i = (i + 1) % order.length; scrollSection(order[i]); left = 20; }
    bar.innerHTML = `${I("tv")}<span>${SECTIONS[i][1]}, ${left}</span><button class="btn" id="tvX">${I("close")}Chiqish</button>`;
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
function initMenu() {
  $("#menuBtn").addEventListener("click", (e) => { e.stopPropagation(); $("#menu").classList.toggle("open"); });
  $("#sideBtn").addEventListener("click", () => document.body.classList.toggle("side-open"));
  $("#sideScrim").addEventListener("click", () => document.body.classList.remove("side-open"));
  $("#aiBtn").addEventListener("click", () => ($("#ag")?.classList.contains("open") ? agClose() : agOpen()));
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#menu")) $("#menu").classList.remove("open");
    if (!e.target.closest("#tm") && !e.target.closest("[data-tm]")) $("#tm").classList.remove("open");
  });
  $("#menu .pop").addEventListener("click", (e) => {
    const b = e.target.closest("[data-m]");
    if (!b) return;
    $("#menu").classList.remove("open");
    ({ excel: () => (location.href = "api/export.xlsx?" + query({ view: EXPORT_VIEW[S.tab] })), import: openImport, settings: openSettings, tv: startTV,
       doska: () => go("doska"), hisobot: () => go("hisobot"), bolimlar: () => go("bolimlar"), jamoa: () => go("jamoa"), bottest: openBotTest,
       addperson: openAddPerson, people: openLinks,
       guide: openGuide, keys: openKeys, theme: toggleTheme, accounts: openAccounts, password: openPassword, logout, telegram: openTelegram })[b.dataset.m]();
  });
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
    if (document.body.classList.contains("side-open")) document.body.classList.remove("side-open");
    else if ($("#modal").classList.contains("open")) closeModal();
    else if ($("#tm").classList.contains("open")) $("#tm").classList.remove("open");
    else if ($("#drawer").classList.contains("open")) closeDrawer();
    else if (S.tv) stopTV();
    return;
  }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (S.tab === "doska" && bdKey(e)) return;
  if (S.tab === "jamoa" && tmKey(e)) { e.preventDefault(); return; }
  if (/^[1-7]$/.test(e.key) && SECTIONS[+e.key - 1]) goSection(SECTIONS[+e.key - 1][0]);
  else if (e.key.toLowerCase() === "t") toggleTheme();
});

/* ================= hisobotlar: kim nima qildi, ish qanchalik og'ir va u haqiqatan yangimi ================= */
const RP = { day: "", q: "", only: "", data: null };
const WT = { 1: "Mayda", 2: "Kichik", 3: "O'rta", 4: "Katta", 5: "Juda katta" };
const fmtH = (h) => (h == null ? "" : h < 1 ? Math.round(h * 60) + " daqiqa" : nf(h, 1) + " soat");
// Og'irlik belgisi: 5 ta pog'ona, to'lgani — til modeli bergan daraja
const wt = (w, note) => (w ? `<span class="wt w${w}" title="${WT[w]}${note ? ": " + esc(note) : ""}" aria-label="Og'irligi: ${WT[w]}">${[1, 2, 3, 4, 5].map((i) => `<i class="${i <= w ? "on" : ""}"></i>`).join("")}</span>`
  : `<span class="wt none" title="Baholanmoqda">${[1, 2, 3, 4, 5].map(() => "<i></i>").join("")}</span>`);

async function renderReports() {
  const root = $("#v-hisobot");
  if (!RP.data) root.innerHTML = `<div class="ph"><div><h1>Hisobotlar</h1><div class="sub">Yuklanmoqda</div></div></div><div class="sk" style="height:420px"></div>`;
  const qs = RP.day ? "?day=" + RP.day : RP.last ? "?last_for=" + encodeURIComponent(RP.last) : "";
  try { RP.data = await api("api/reports" + qs); } catch (e) { toast(esc(e.message), "danger"); return; }
  if (RP.last) { RP.last = ""; if (RP.data.day !== RP.data.today) RP.day = RP.data.day; }
  drawReports();
}

function rpItem(it) {
  const dup = it.dup_kind === "takror" || it.dup_kind === "nusxa";
  const ver = it.versions || [];
  const del = !!it.deleted_at;
  return `<li class="rp-it ${dup ? "dup" : ""} ${del ? "del" : ""}">${wt(it.weight, it.wnote)}
    <div class="rp-tx"><b>${esc(it.title)}</b>
      <small>${esc(it.project)}${it.hours ? `, taxminan ${fmtH(it.hours)}` : ""}${it.wnote ? `. ${esc(it.wnote)}` : ""}</small>
      ${dup ? `<p class="rp-dup">${it.dup_kind === "nusxa" ? `${esc(first(it.old_assignee))}ning ishi` : "Oldin ham yozilgan"}, ${uzDate(parseTs(it.old_done_at))}: «${esc(it.old_title)}»${it.dup_note ? `. ${esc(it.dup_note)}` : ""}</p>` : ""}
      ${it.dup_kind === "muntazam" ? `<p class="rp-note">Muntazam ish: har kuni takrorlanishi tabiiy</p>` : ""}
      ${ver.length ? `<details class="rp-ver"><summary>${del ? "Hisobot xabari o'chirilgan" : "Hisobot keyin o'zgartirilgan"}, eski matni</summary>
        ${ver.map((v) => `<div><time>${clock(v.at)}${v.kind === "delete" ? ", o'chirildi" : ", o'zgartirildi"}</time><p>${esc(v.text || "")}</p></div>`).join("")}</details>` : ""}
    </div><time class="rp-time">${it.done_at.slice(11, 16)}</time></li>`;
}

function rpCard(p, max) {
  return `<article class="card rp-card ${p.flags.length ? "flag" : ""}">
    <header class="rp-h" data-person="${esc(p.name)}">${ava(p.name, p.department, null, "md")}
      <div class="rp-who"><b>${esc(p.name)}</b><span>${esc(p.department)}, ${p.count} ta ish</span></div>
      ${p.hours ? `<div class="rp-sum" title="AI bahosi bo'yicha taxminiy mehnat"><b>${nf(p.hours, 1)}</b><span>soat</span></div>` : ""}</header>
    <div class="rp-meter" title="Kunning eng katta ish hajmiga nisbatan"><i style="width:${max ? Math.round((100 * p.points) / max) : 0}%"></i></div>
    ${p.flags.length ? `<div class="rp-flags">${p.flags.map((f) => `<span class="bd-chip ${/oldin/.test(f) ? "risk" : "warn"}">${esc(f)}</span>`).join("")}</div>` : ""}
    <ul class="rp-items">${p.items.map(rpItem).join("")}</ul></article>`;
}

function drawReports() {
  const d = RP.data, root = $("#v-hisobot");
  const isToday = d.day === d.today, dt = parseDay(d.day);
  const q = RP.q.toLowerCase();
  const people = d.people.filter((p) => (!q || p.name.toLowerCase().includes(q)) && (RP.only !== "flag" || p.flags.length));
  const all = d.people;
  const sum = (k) => all.reduce((a, p) => a + p[k], 0);
  const items = sum("count"), rated = all.reduce((a, p) => a + p.items.filter((i) => i.weight).length, 0);
  const avgW = rated ? all.reduce((a, p) => a + p.items.reduce((b, i) => b + (i.weight || 0), 0), 0) / rated : null;
  const max = Math.max(1, ...all.map((p) => p.points));
  const dmax = Math.max(1, ...d.days.map((x) => x.points));
  const flagged = all.filter((p) => p.flags.length).length;
  root.innerHTML = `<div class="ph"><div><h1>Hisobotlar</h1><div class="sub">${WEEK[dt.getDay()][0].toUpperCase() + WEEK[dt.getDay()].slice(1)}, ${uzDate(dt)}${all.length ? `: ${all.length} xodim, ${items} ta ish` : ""}${d.pending && d.ai ? `. ${d.pending} ta ish baholanmoqda` : ""}</div></div>
      <div class="filters">
        <div class="seg"><button data-rd="-1" aria-label="Oldingi kun">${I("arrow-left")}</button><button data-rd="0" aria-pressed="${isToday}">Bugun</button><button data-rd="1" aria-label="Keyingi kun" ${isToday ? "disabled" : ""}>${I("arrow")}</button></div>
        <input type="date" class="ctl" id="rpDate" value="${d.day}" max="${d.today}" aria-label="Sana">
        <label class="ctl bd-search">${I("search")}<input id="rpQ" placeholder="Xodim" value="${esc(RP.q)}" autocomplete="off"></label>
      </div></div>
    <div class="rp-days" role="group" aria-label="Oxirgi 14 kun">${d.days.map((x) => { const t = parseDay(x.day), we = t.getDay() === 0 || t.getDay() === 6;
      return `<button class="rp-day ${x.day === d.day ? "on" : ""} ${we ? "we" : ""}" data-day="${x.day}" title="${uzDate(t)}: ${x.items} ta ish${x.repeats ? `, ${x.repeats} ta takror` : ""}">
        <span class="rp-bar"><i style="height:${Math.max(x.points ? 6 : 0, Math.round((100 * x.points) / dmax))}%"></i></span><span class="rp-dn">${t.getDate()}</span>${x.repeats ? `<b class="rp-dot"></b>` : ""}</button>`; }).join("")}</div>
    <div class="kpis rp-kpis">
      <div class="card kc"><span class="kc-l">Taxminiy mehnat</span><b class="kc-v num">${nf(sum("hours"), 1)}</b><span class="kc-s">soat${avgW ? `, o'rtacha og'irlik ${nf(avgW, 1)}` : ""}</span></div>
      <div class="card kc"><span class="kc-l">Bajarilgan ishlar</span><b class="kc-v num">${items}</b><span class="kc-s">${sum("small")} tasi mayda</span></div>
      <div class="card kc ${sum("repeats") ? "alarm" : ""}"><span class="kc-l">Qayta yozilgan</span><b class="kc-v num">${sum("repeats")}</b><span class="kc-s">eski ish yangi deb yozilgan</span></div>
      <div class="card kc ${d.missing.length && d.final ? "warn" : ""}"><span class="kc-l">${d.final ? "Hisobot bermagan" : "Hali yozmagan"}</span><b class="kc-v num">${d.missing.length}</b><span class="kc-s">${d.missing.length ? esc(d.missing.slice(0, 3).map((m) => first(m.name)).join(", ")) + (d.missing.length > 3 ? " va boshqalar" : "") : "hamma yozgan"}</span></div>
    </div>
    <div class="rp-grid">
      <div class="rp-main">
        <div class="rp-tabs" role="group" aria-label="Filtr"><button class="chip" data-only="" aria-pressed="${!RP.only}">Hammasi<b>${all.length}</b></button>
          <button class="chip ${flagged ? "alarm" : ""}" data-only="flag" aria-pressed="${RP.only === "flag"}" ${flagged || RP.only ? "" : "disabled"}>Diqqat talab<b>${flagged}</b></button>
          <span class="rp-legend">${wt(3)}<span>Og'irlik: AI har ishni 1 dan 5 gacha baholaydi</span></span></div>
        ${people.map((p) => rpCard(p, max)).join("") || `<div class="card">${emptyBox(all.length ? "Bu filtrda xodim yo'q" : isToday ? "Bugun hali hech kim bajarilgan ish yozmagan" : "Bu kuni bajarilgan ish yozilmagan", "doc")}</div>`}
      </div>
      <aside class="rp-side">
        <section class="card"><div class="ch"><h3>Qayta yozilgan ishlar</h3><span class="count">30 kun</span></div><div class="cb">
          ${d.suspicious.length ? d.suspicious.map((x) => `<div class="rp-sus" data-person="${esc(x.assignee)}">
            <div class="rp-sus-h"><b>${esc(x.assignee)}</b><time>${uzDate(parseTs(x.done_at))}</time></div>
            <p>«${esc(x.title)}»</p>
            <p class="old">${x.gap_days ? x.gap_days + " kun oldin" : "Shu kuni"}${x.dup_kind === "nusxa" ? `, ${esc(first(x.old_assignee))} yozgan` : ""}: «${esc(x.old_title)}»</p>
            ${x.dup_note ? `<small>${esc(x.dup_note)}</small>` : ""}</div>`).join("") : emptyBox("Eski ishni qayta yozish holati topilmadi", "check")}
        </div></section>
        <section class="card"><div class="ch"><h3>${d.final ? "Hisobot bermaganlar" : "Bugun hali yozmaganlar"}</h3><span class="count">${d.missing.length}</span></div><div class="cb">
          ${d.missing.length ? `<div class="plist">${d.missing.map((m) => `<div class="prow" data-person="${esc(m.name)}">${ava(m.name)}<div><b>${esc(m.name)}</b><span>Oxirgi hisobot ${ago(m.last)}</span></div><span></span></div>`).join("")}</div>`
            : emptyBox(dt.getDay() === 0 || dt.getDay() === 6 ? "Dam olish kuni" : "Ishlaganlarning hammasi hisobot yozgan", "check")}
        </div></section>
      </aside>
    </div>`;
  const shift = (n) => { const t = parseDay(d.day); RP.day = n ? isoDay(new Date(t.getTime() + n * 864e5)) : ""; if (RP.day >= d.today) RP.day = ""; renderReports(); };
  $$("[data-rd]", root).forEach((b) => (b.onclick = () => shift(+b.dataset.rd)));
  $("#rpDate").onchange = (e) => { RP.day = e.target.value && e.target.value < d.today ? e.target.value : ""; renderReports(); };
  $$("[data-day]", root).forEach((b) => (b.onclick = () => { RP.day = b.dataset.day === d.today ? "" : b.dataset.day; renderReports(); }));
  $$("[data-only]", root).forEach((b) => (b.onclick = () => { RP.only = b.dataset.only; drawReports(); }));
  const qi = $("#rpQ");
  qi.oninput = () => { RP.q = qi.value; const pos = qi.selectionStart; drawReports(); const n = $("#rpQ"); n.focus(); n.setSelectionRange(pos, pos); };
  bindCommon(root);
}

/* ================= doska: menejer vazifa beradi, xodim guruhda javob beradi ================= */
const BD_STAGES = [["yangi", "Yangi"], ["qabul", "Qabul qilindi"], ["jarayon", "Jarayonda"], ["tekshiruv", "Tekshiruvda"], ["bajarildi", "Bajarildi"]];
const BD_VIEWS = [["doska", "Doska", "board"], ["jadval", "Jadval", "list"], ["kalendar", "Kalendar", "calendar"]];
const bdOpen = (c) => c.stage !== "bajarildi";
const BD_QUICK = [
  ["late", "Kechikkan", (c) => bdOpen(c) && c.due_in != null && c.due_in < 0],
  ["soon", "Muddati yaqin", (c) => bdOpen(c) && c.due_in != null && c.due_in >= 0 && c.due_in <= 2],
  ["wait", "Javob yo'q", (c) => c.waiting],
  ["flag", "Savol yoki to'siq", (c) => bdOpen(c) && !!c.flag],
  ["hi", "Muhim", (c) => bdOpen(c) && c.priority === "yuqori"],
];
const BD = { project: "", dept: "", q: "", quick: "", who: "", view: "doska", sort: { key: "due", asc: true }, month: "",
  data: null, card: null, drag: null, open: 0, hover: 0, people: null, addOpen: false, addText: "" };
try { const v = localStorage.getItem("puls.doska"); if (BD_VIEWS.some((x) => x[0] === v)) BD.view = v; BD.calMode = localStorage.getItem("puls.kal") || "oy"; } catch (e) {}
const bdStage = (k) => BD_STAGES.find((s) => s[0] === k)[1];
const bdTg = (r) => (r && r.telegram ? ", " + esc(r.telegram.toLowerCase()) : "");
const bdProj = () => { const ps = BD.data?.projects || []; return ps.find((p) => String(p.id) === BD.project) || ps.find((p) => !p.demo) || ps[0]; };
const isoLocal = (dt) => `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
// Muddat tugmalari: bugun, ertaga, shu (yoki keyingi) juma, bir haftadan keyin
function bdPresets() {
  const t = parseDay(BD.data?.today || isoDay(new Date()));
  const plus = (n) => isoDay(new Date(t.getTime() + n * 864e5));
  return [["Bugun", plus(0)], ["Ertaga", plus(1)], ["Juma", plus((5 - t.getDay() + 7) % 7 || 7)], ["1 hafta", plus(7)]];
}

async function renderBoard() {
  const root = $("#v-doska");
  if (!BD.data) root.innerHTML = `<div class="ph"><div><h1>Doska</h1><div class="sub">Yuklanmoqda</div></div></div><div class="sk" style="height:420px"></div>`;
  try {
    const p = new URLSearchParams();
    if (BD.project) p.set("project", BD.project);
    if (BD.dept && !S.dept) p.set("dept", BD.dept);
    if (BD.q) p.set("q", BD.q);
    BD.data = await api("api/board?" + p);
  } catch (e) { toast(esc(e.message), "danger"); return; }
  if (BD.drag) return; // sudrab turilganda chizilmaydi, tashlangandan keyin yangilanadi
  drawBoard();
  if (BD.open && $("#drawer").classList.contains("open") && $("#drawer .bd-sheet")) openBoardCard(BD.open, true);
}

function bdVisible() {
  const q = BD_QUICK.find((x) => x[0] === BD.quick);
  return BD.data.cards.filter((c) => (!q || q[2](c)) && (!BD.who || c.assignee === BD.who));
}

function drawBoard() {
  const d = BD.data, root = $("#v-doska");
  const depts = (S.data?.departments || []).map((x) => x.name);
  const open = d.cards.filter(bdOpen).length;
  const sub = [`${open} ta ochiq vazifa`, d.waiting ? `${d.waiting} tasi javob kutmoqda` : "", d.flags ? `${d.flags} tasida savol yoki to'siq` : ""].filter(Boolean).join(", ");
  const focus = document.activeElement?.id;
  const whos = [...new Set(d.cards.map((c) => c.assignee).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  const active = BD.quick || BD.who || BD.q || BD.project || BD.dept;
  const cards = bdVisible();
  BD.hover = 0;
  root.innerHTML = `<div class="ph"><div><h1>Doska</h1><div class="sub">${sub}</div></div>
      <div class="filters">
        <div class="seg bd-views" role="group" aria-label="Ko'rinish">${BD_VIEWS.map(([k, t, ic]) => `<button data-bv="${k}" aria-pressed="${BD.view === k}">${I(ic)}${t}</button>`).join("")}</div>
        <select class="ctl" id="bdProject" aria-label="Loyiha"><option value="">Barcha loyihalar</option>${d.projects.map((p) => `<option value="${p.id}" ${String(p.id) === BD.project ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>
        <select class="ctl" id="bdDept" aria-label="Bo'lim" ${S.dept ? "hidden" : ""}><option value="">Barcha bo'limlar</option>${depts.map((x) => `<option ${x === BD.dept ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
        <label class="ctl bd-search">${I("search")}<input id="bdQ" placeholder="Vazifa yoki xodim" value="${esc(BD.q)}" autocomplete="off"></label>
        <button class="btn btn-dark" id="bdNew" title="Yangi vazifa (N)">${I("add")}Yangi vazifa</button>
      </div></div>
    <div class="bd-bar" role="group" aria-label="Tezkor filtr">
      ${BD_QUICK.map(([k, t, f]) => { const n = d.cards.filter(f).length; return `<button class="chip ${k === "late" || k === "flag" ? "alarm" : ""}" data-qf="${k}" aria-pressed="${BD.quick === k}" ${n || BD.quick === k ? "" : "disabled"}>${t}<b>${n}</b></button>`; }).join("")}
      <select class="ctl" id="bdWho" aria-label="Ijrochi"><option value="">Barcha ijrochilar</option>${whos.map((w) => `<option ${w === BD.who ? "selected" : ""}>${esc(w)}</option>`).join("")}</select>
      ${active ? `<button class="chip" id="bdClear" title="Filtrlarni tozalash (X)">${I("close")}Tozalash</button>` : ""}
      <button class="icon-btn bd-keys" id="bdKeys" title="Tezkor tugmalar (?)" aria-label="Tezkor tugmalar">${I("keyboard")}</button>
    </div>
    <div id="bdBody">${BD.view === "jadval" ? bdTable(cards) : BD.view === "kalendar" ? bdCalendar(cards) : bdColumns(cards)}</div>`;
  $$("[data-bv]", root).forEach((b) => (b.onclick = () => bdView(b.dataset.bv)));
  $("#bdProject").onchange = (e) => { BD.project = e.target.value; renderBoard(); };
  $("#bdDept").onchange = (e) => { BD.dept = e.target.value; renderBoard(); };
  $("#bdWho").onchange = (e) => { BD.who = e.target.value; drawBoard(); };
  let tmr;
  $("#bdQ").oninput = (e) => { clearTimeout(tmr); tmr = setTimeout(() => { BD.q = e.target.value.trim(); renderBoard(); }, 250); };
  if (focus === "bdQ") { const q = $("#bdQ"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
  $("#bdNew").onclick = () => openNewTask();
  $("#bdKeys").onclick = bdKeys;
  if ($("#bdClear")) $("#bdClear").onclick = bdClear;
  $$("[data-qf]", root).forEach((b) => (b.onclick = () => { BD.quick = BD.quick === b.dataset.qf ? "" : b.dataset.qf; drawBoard(); }));
  $$("[data-id]", $("#bdBody")).forEach((el) => {
    el.addEventListener("click", () => openBoardCard(+el.dataset.id));
    el.addEventListener("mouseenter", () => (BD.hover = +el.dataset.id));
    el.addEventListener("mouseleave", () => (BD.hover = 0));
    if (el.draggable) {
      el.addEventListener("dragstart", (e) => { BD.drag = +el.dataset.id; el.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", el.dataset.id); });
      el.addEventListener("dragend", () => { el.classList.remove("dragging"); BD.drag = null; $$(".over").forEach((c) => c.classList.remove("over")); });
    }
  });
  const drop = (zone, fn) => {
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
    zone.addEventListener("dragleave", (e) => { if (!zone.contains(e.relatedTarget)) zone.classList.remove("over"); });
    zone.addEventListener("drop", (e) => {
      e.preventDefault(); zone.classList.remove("over");
      const id = +e.dataTransfer.getData("text/plain"); BD.drag = null;
      const c = BD.data.cards.find((x) => x.id === id);
      if (c) fn(c);
    });
  };
  $$(".bd-col", root).forEach((col) => drop(col, (c) => c.stage !== col.dataset.stage && bdMove(c, col.dataset.stage)));
  $$("[data-day]", root).forEach((day) => drop(day, (c) => (c.deadline || "") !== day.dataset.day && bdDue(c, day.dataset.day)));
  $$("[data-sort]", root).forEach((th) => (th.onclick = () => {
    BD.sort = { key: th.dataset.sort, asc: BD.sort.key === th.dataset.sort ? !BD.sort.asc : th.dataset.sort !== "age" };
    drawBoard();
  }));
  $$("[data-cm]", root).forEach((b) => (b.onclick = () => {
    const step = +b.dataset.cm;
    if (BD.calMode === "hafta") {
      BD.week = step ? isoLocal(new Date(parseDay(bdMonday()).getTime() + step * 7 * 864e5)) : "";
    } else {
      const t = parseDay(BD.month ? BD.month + "-15" : BD.data.today);
      BD.month = step ? isoLocal(new Date(t.getFullYear(), t.getMonth() + step, 15)).slice(0, 7) : "";
    }
    drawBoard();
  }));
  $$("[data-calm]", root).forEach((b) => (b.onclick = () => { BD.calMode = b.dataset.calm; try { localStorage.setItem("puls.kal", BD.calMode); } catch (e) {} drawBoard(); }));
  $$("[data-more]", root).forEach((b) => (b.onclick = (e) => { e.stopPropagation(); bdDayList(b.dataset.more); }));
  bdBindAdd(focus);
}

/* ---- ustunlar ---- */
function bdColumns(cards) {
  return `<div class="bd">${BD_STAGES.map(([k, t]) => {
    const list = cards.filter((c) => c.stage === k);
    return `<section class="bd-col" data-stage="${k}"><header><span>${t}</span><b>${list.length}</b></header>
      <div class="bd-list">${k === "yangi" ? bdAddForm() : ""}${list.map(bdCard).join("") || (k === "yangi" ? "" : `<div class="bd-empty">Bo'sh</div>`)}</div></section>`;
  }).join("")}</div>`;
}

function bdCard(c) {
  const flag = c.flag === "savol" ? `<span class="bd-chip warn">Savol</span>` : c.flag === "toqiq" ? `<span class="bd-chip risk">To'siq</span>` : "";
  const wait = c.waiting ? `<span class="bd-chip warn" title="Xodim hali «Tushundim» demagan">Javob yo'q</span>` : "";
  const prog = ["jarayon", "tekshiruv"].includes(c.stage) && c.progress ? `<div class="bd-prog" title="${c.progress}%"><i style="width:${c.progress}%"></i></div>` : "";
  const [cd, cn] = c.checks || [0, 0];
  const badges = (c.grp_size > 1 ? `<span class="bd-b ${c.grp_done === c.grp_size ? "full" : ""}" title="${c.grp_size} kishiga berilgan, ${c.grp_done} tasi bajardi">${I("people")}${c.grp_done}/${c.grp_size}</span>` : "")
    + (cn ? `<span class="bd-b ${cd === cn ? "full" : ""}" title="Ichki ro'yxat">${I("checklist")}${cd}/${cn}</span>` : "")
    + (c.comments ? `<span class="bd-b" title="Izoh va javoblar">${I("chat-dots")}${c.comments}</span>` : "");
  return `<article class="bd-card ${c.priority === "yuqori" ? "hi" : ""}" draggable="true" data-id="${c.id}" tabindex="0">
    <div class="bd-t">${esc(c.title)}</div>
    <div class="bd-m">${esc(c.project)}${c.priority === "yuqori" ? ", muhim" : ""}</div>
    ${flag || wait ? `<div class="bd-chips">${flag}${wait}</div>` : ""}
    ${prog}
    <div class="bd-f">${c.assignee ? `<span class="bd-who">${ava(c.assignee, c.department, null, "xs")}<span>${esc(first(c.assignee))}</span></span>` : `<span class="bd-who none">Ijrochi yo'q</span>`}
      <span class="bd-r">${badges}${c.sent ? `<span class="bd-tg" title="Guruhga yuborilgan">${I("send")}</span>` : ""}${c.stage === "bajarildi" ? `<span class="age new">${clock(c.done_at || c.created_at).split(",")[0]}</span>` : c.due_in == null && c.age === 0 ? `<span class="age new">bugun</span>` : dueTag(c)}${["jarayon", "tekshiruv"].includes(c.stage) && c.progress ? `<span class="bd-pct">${c.progress}%</span>` : ""}</span></div>
  </article>`;
}

/* ---- "Yangi" ustunida tez qo'shish: "Hisobot tayyorlash @Sardor !" ---- */
function bdAddForm() {
  if (!BD.addOpen) return `<button class="bd-addbtn" id="bdAdd">${I("add")}Vazifa qo'shish</button>`;
  return `<form class="bd-add" id="bdAddF"><textarea id="bdAddT" rows="2" placeholder="Vazifa nomi" aria-label="Yangi vazifa nomi">${esc(BD.addText)}</textarea>
    <small>@ism yozsangiz o'sha xodimga beriladi, ! muhim deb belgilaydi. Loyiha: ${esc(bdProj()?.name || "")}</small>
    <div class="bd-add-f"><button class="btn btn-dark" type="submit">Qo'shish</button><button class="icon-btn" type="button" id="bdAddX" aria-label="Yopish">${I("close")}</button></div></form>`;
}

function bdBindAdd(focus) {
  const btn = $("#bdAdd");
  if (btn) btn.onclick = () => { BD.addOpen = true; drawBoard(); $("#bdAddT")?.focus(); };
  const f = $("#bdAddF");
  if (!f) return;
  const t = $("#bdAddT");
  if (focus === "bdAddT") { t.focus(); t.setSelectionRange(t.value.length, t.value.length); }
  t.oninput = () => (BD.addText = t.value);
  t.onkeydown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); bdQuickAdd(); }
    if (e.key === "Escape") { e.stopPropagation(); BD.addOpen = false; BD.addText = ""; drawBoard(); }
  };
  f.onsubmit = (e) => { e.preventDefault(); bdQuickAdd(); };
  $("#bdAddX").onclick = () => { BD.addOpen = false; BD.addText = ""; drawBoard(); };
}

async function bdQuickAdd() {
  const raw = ($("#bdAddT")?.value || "").trim();
  if (!raw) return;
  try {
    const people = BD.people || (BD.people = await api("api/board/people"));
    const whos = [];
    let hi = false;
    const words = raw.split(/\s+/).filter((w) => {
      if (w === "!") { hi = true; return false; }
      if (!w.startsWith("@") || w.length < 2) return true;
      const k = w.slice(1).toLowerCase();
      const m = people.filter((p) => (p.username || "").toLowerCase() === k || p.name.toLowerCase().split(/\s+/).some((x) => x.startsWith(k)));
      if (m.length !== 1) throw new Error(m.length ? `${w}: ${m.slice(0, 4).map((p) => p.name).join(", ")}. Aniqroq yozing` : `${w} degan xodim topilmadi`);
      whos.push(m[0].name);
      return false;
    });
    const p = bdProj();
    const r = await api("api/board/task", { json: { title: words.join(" "), project_id: p.id, assignees: whos, priority: hi ? "yuqori" : null } });
    BD.addText = "";
    toast(whos.length > 1 ? `${whos.length} kishiga berildi${bdTg(r)}` : whos.length ? `${esc(first(whos[0]))}ga berildi${bdTg(r)}` : "Vazifa qo'shildi, ijrochini kartochkada tanlang", "check");
    await renderBoard();
    $("#bdAddT")?.focus();
  } catch (e) { toast(esc(e.message), "danger"); }
}

/* ---- jadval ---- */
const BD_SORT = {
  title: (c) => c.title.toLowerCase(), who: (c) => (c.assignee || "￿").toLowerCase(), stage: (c) => BD_STAGES.findIndex((s) => s[0] === c.stage),
  pct: (c) => (c.stage === "bajarildi" ? 100 : c.progress), due: (c) => (c.due_in == null || !bdOpen(c) ? 9999 : c.due_in), age: (c) => c.created_at,
};
function bdTable(cards) {
  if (!cards.length) return emptyBox("Bu filtrda vazifa yo'q", "search");
  const { key, asc } = BD.sort;
  const rows = [...cards].sort((a, b) => { const x = BD_SORT[key](a), y = BD_SORT[key](b); return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1) || b.id - a.id; });
  const th = (k, t, cls = "") => `<th data-sort="${k}" class="${cls} ${key === k ? "on" + (asc ? " asc" : "") : ""}">${t}</th>`;
  return `<section class="card"><div class="tw"><table class="t cards bd-tbl"><thead><tr>${th("title", "Vazifa")}${th("who", "Ijrochi")}${th("stage", "Holat")}${th("pct", "Bajarilgani", "hide-m")}${th("due", "Muddat")}${th("age", "Berilgan", "hide-m")}</tr></thead>
    <tbody>${rows.map((c) => `<tr data-id="${c.id}" tabindex="0" class="${c.priority === "yuqori" ? "hi" : ""}">
      <td class="pname"><b>${esc(c.title)}</b><span>${esc(c.project)}${c.priority === "yuqori" ? ", muhim" : ""}${c.flag ? `, <em class="bd-flag ${c.flag}">${c.flag === "toqiq" ? "to'siq" : "savol"}</em>` : ""}${c.waiting ? `, <em class="bd-flag savol">javob yo'q</em>` : ""}</span></td>
      <td>${c.assignee ? `<span class="bd-who">${ava(c.assignee, c.department, null, "xs")}<span>${esc(c.assignee)}</span></span>` : `<span class="bd-who none">Ijrochi yo'q</span>`}</td>
      <td><span class="bd-st">${bdStage(c.stage)}</span></td>
      <td class="hide-m"><span class="bd-tp"><span class="bd-prog"><i style="width:${c.stage === "bajarildi" ? 100 : c.progress}%"></i></span>${c.stage === "bajarildi" ? 100 : c.progress}%</span></td>
      <td>${c.stage === "bajarildi" ? `<span class="age new">bajarildi</span>` : c.due_in != null ? dueTag(c) : `<span class="bd-none">yo'q</span>`}</td>
      <td class="hide-m bd-when">${clock(c.created_at)}</td></tr>`).join("")}</tbody></table></div></section>`;
}

/* ---- kalendar: muddat bo'yicha; kartochkani boshqa kunga sudrash muddatni o'zgartiradi ---- */
// Bir kunning hamma ishlari: qidiruv bilan (yuzlab ish bo'lsa ham topiladi), xodim bo'yicha guruhlangan
function bdDayList(k) {
  const all = BD.byDay[k] || [];
  const draw = (q) => {
    const list = all.filter((c) => !q || fold(c.title + " " + (c.assignee || "")).includes(fold(q)));
    $("#cdList").innerHTML = bdGrouped(list) || emptyBox("Topilmadi", "search");
    $$("#modal [data-id]").forEach((el) => (el.onclick = () => { closeModal(); openBoardCard(+el.dataset.id); }));
  };
  openModal(`${uzDate(parseDay(k))}, ${WEEK[parseDay(k).getDay()]}: ${all.length} ta ish`,
    `<label class="ctl bd-search wide">${I("search")}<input id="cdQ" placeholder="Vazifa yoki xodim" autocomplete="off"></label><div class="cal-day" id="cdList"></div>`, null, true);
  $("#cdQ").oninput = (e) => draw(e.target.value);
  draw("");
  $("#cdQ").focus();
}
function bdGrouped(list) {
  const by = {};
  list.forEach((c) => (by[c.assignee || "Ijrochi yo'q"] = by[c.assignee || "Ijrochi yo'q"] || []).push(c));
  return Object.keys(by).sort((a, b) => by[b].length - by[a].length || a.localeCompare(b))
    .map((n) => `<div class="cal-grp"><h5>${esc(n)}<b>${by[n].length}</b></h5>${by[n].map(bdCalChip).join("")}</div>`).join("");
}
function bdMonday() {
  const t = parseDay(BD.week || BD.data.today);
  return isoLocal(new Date(t.getTime() - ((t.getDay() + 6) % 7) * 864e5));
}
function bdWeek(cards) {
  const mon = parseDay(bdMonday());
  const byDay = {};
  cards.filter((c) => c.deadline).forEach((c) => (byDay[c.deadline] = byDay[c.deadline] || []).push(c));
  BD.byDay = byDay;
  const days = [...Array(7)].map((_, i) => isoLocal(new Date(mon.getTime() + i * 864e5)));
  const last = parseDay(days[6]);
  const title = `${uzDate(mon)} dan ${uzDate(last)} gacha`;
  return { title, html: `<div class="cal-week">${days.map((k) => { const list = byDay[k] || [], late = list.filter((c) => bdOpen(c) && c.due_in < 0).length, d = parseDay(k);
    return `<section class="cw-col ${k === BD.data.today ? "today" : ""}" data-day="${k}"><header><b>${WEEK[d.getDay()][0].toUpperCase() + WEEK[d.getDay()].slice(1)}, ${d.getDate()}</b><span>${list.length ? list.length + " ta" : ""}${late ? `, <em>${late} kechikkan</em>` : ""}</span></header>
      <div class="cw-list">${bdGrouped(list) || `<div class="bd-empty">Bo'sh</div>`}</div></section>`; }).join("")}</div>` };
}
function bdCalendar(cards) {
  if (BD.calMode === "hafta") {
    const w = bdWeek(cards), none = cards.filter((c) => !c.deadline && bdOpen(c));
    return `<div class="cal-head"><h2>${w.title}</h2><div class="cal-tools">${bdCalModes()}
        <div class="seg"><button data-cm="-1" aria-label="Oldingi hafta">${I("arrow-left")}</button><button data-cm="0" aria-pressed="${!BD.week}">Bu hafta</button><button data-cm="1" aria-label="Keyingi hafta">${I("arrow")}</button></div></div></div>
      ${w.html}
      <aside class="cal-none wide" data-day=""><h4>Muddatsiz<b>${none.length}</b></h4><div class="cal-list">${none.map(bdCalChip).join("") || `<div class="bd-empty">Hammasining muddati bor</div>`}</div></aside>`;
  }
  const today = parseDay(BD.data.today);
  const base = BD.month ? parseDay(BD.month + "-15") : today;
  const y = base.getFullYear(), m = base.getMonth();
  const lead = (new Date(y, m, 1).getDay() + 6) % 7; // haftaning birinchi kuni dushanba
  const cells = Math.ceil((lead + new Date(y, m + 1, 0).getDate()) / 7) * 7;
  const byDay = {};
  cards.filter((c) => c.deadline).forEach((c) => (byDay[c.deadline] = byDay[c.deadline] || []).push(c));
  const none = cards.filter((c) => !c.deadline && bdOpen(c));
  const mk = isoLocal(new Date(y, m, 15)).slice(0, 7);
  let grid = "";
  const peak = Math.max(1, ...Object.entries(byDay).filter(([k]) => k.startsWith(isoLocal(new Date(y, m, 15)).slice(0, 7))).map(([, v]) => v.length));
  for (let i = 0; i < cells; i++) {
    const dt = new Date(y, m, 1 - lead + i, 12), k = isoLocal(dt), list = byDay[k] || [];
    const late = list.filter((c) => bdOpen(c) && c.due_in < 0).length;
    const more = list.length > 3 ? `<button class="cal-more" data-more="${k}">Hammasi: ${list.length} ta</button>` : "";
    // zichlik: ish ko'p kun to'qroq (oyning eng band kuniga nisbatan), rang emas, kulrang
    const dens = list.length && dt.getMonth() === m ? Math.round((7 * list.length) / peak) : 0;
    grid += `<div class="cal-d ${dt.getMonth() !== m ? "out" : ""} ${k === BD.data.today ? "today" : ""}" data-day="${k}" style="${dens ? `--dens:${dens}%` : ""}">
      <span class="cal-top"><span class="cal-n">${dt.getDate()}</span>${list.length ? `<span class="cal-cnt">${list.length}${late ? `<em>${late}</em>` : ""}</span>` : ""}</span>
      ${(more ? list.slice(0, 2) : list).map(bdCalChip).join("")}${more}</div>`;
  }
  const agenda = Object.keys(byDay).filter((k) => k.startsWith(mk)).sort().map((k) => `<div class="cal-ag ${k === BD.data.today ? "today" : ""}"><h4>${uzDate(parseDay(k))}, ${WEEK[parseDay(k).getDay()]}</h4>${byDay[k].map(bdCalChip).join("")}</div>`).join("");
  BD.byDay = byDay;
  return `<div class="cal-head"><h2>${MONTHS[m][0].toUpperCase() + MONTHS[m].slice(1)} ${y}</h2><div class="cal-tools">${bdCalModes()}
      <div class="seg"><button data-cm="-1" aria-label="Oldingi oy">${I("arrow-left")}</button><button data-cm="0" aria-pressed="${!BD.month}">Bu oy</button><button data-cm="1" aria-label="Keyingi oy">${I("arrow")}</button></div></div></div>
    <div class="cal-agenda">${agenda || emptyBox("Bu oyda muddatli vazifa yo'q", "calendar")}</div>
    <div class="cal-wrap"><div class="cal">${["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"].map((w) => `<div class="cal-w">${w}</div>`).join("")}${grid}</div>
      <aside class="cal-none" data-day=""><h4>Muddatsiz<b>${none.length}</b></h4><div class="cal-list">${none.map(bdCalChip).join("") || `<div class="bd-empty">Hammasining muddati bor</div>`}</div></aside></div>`;
}
const bdCalModes = () => `<div class="seg" role="group" aria-label="Kalendar"><button data-calm="oy" aria-pressed="${BD.calMode !== "hafta"}">Oy</button><button data-calm="hafta" aria-pressed="${BD.calMode === "hafta"}">Hafta</button></div>`;
const bdCalChip = (c) => `<div class="cal-c ${c.stage === "bajarildi" ? "done" : c.due_in != null && c.due_in < 0 ? "late" : ""} ${c.priority === "yuqori" ? "hi" : ""}" draggable="true" data-id="${c.id}" tabindex="0" title="${esc(c.title)}, ${esc(c.assignee || "ijrochi yo'q")}"><span>${esc(c.title)}</span><small>${esc(first(c.assignee) || "Ijrochi yo'q")}${bdOpen(c) && c.progress ? ", " + c.progress + "%" : ""}</small></div>`;

/* ---- amallar ---- */
function bdView(v) {
  BD.view = v;
  try { localStorage.setItem("puls.doska", v); } catch (e) {}
  drawBoard();
}
function bdClear() {
  const reload = BD.q || BD.project || BD.dept;
  Object.assign(BD, { quick: "", who: "", q: "", project: "", dept: "" });
  if (reload) renderBoard(); else drawBoard();
}

async function bdMove(c, stage) {
  const prev = c.stage;
  c.stage = stage; if (stage === "bajarildi") c.progress = 100;
  drawBoard();
  try {
    const r = await api("api/board/task/" + c.id, { json: { stage } });
    toast(`«${esc(c.title)}»: ${bdStage(stage)}${bdTg(r)}`, "check");
  } catch (e) { c.stage = prev; drawBoard(); toast(esc(e.message), "danger"); }
}

async function bdDue(c, day) {
  try {
    const r = await api("api/board/task/" + c.id, { json: { deadline: day } });
    toast(`«${esc(c.title)}»: ${day ? "muddat " + uzDate(parseDay(day)) : "muddat olib tashlandi"}${bdTg(r)}`, "check");
    renderBoard();
  } catch (e) { toast(esc(e.message), "danger"); }
}

// O'zgarish saqlanadi, doska va ochiq kartochka yangilanadi
async function bdDo(id, req, msg, focus) {
  try {
    const r = await req();
    if (msg) toast(msg + bdTg(r), "check");
    await renderBoard();
    await openBoardCard(id);
    if (focus) $(focus)?.focus();
    return r;
  } catch (e) { toast(esc(e.message), "danger"); }
}
// Ustun va foiz tugmasi: natija darhol ko'rinadi (server javobini kutmaydi), saqlash fonda; xato bo'lsa qaytariladi
async function bdSave(id, change, msg) {
  const c = BD.data?.cards.find((x) => x.id === id);
  if (!c || (change.stage === undefined && change.progress === undefined)) return bdDo(id, () => api("api/board/task/" + id, { json: change }), msg);
  const prev = { stage: c.stage, progress: c.progress };
  if (change.stage) c.stage = change.stage;
  if (change.progress !== undefined) c.progress = change.progress;
  if (c.stage === "bajarildi") c.progress = 100;
  drawBoard();
  $$("#drawer [data-st]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.st === c.stage));
  $$("#drawer [data-pr]").forEach((b) => b.setAttribute("aria-pressed", +b.dataset.pr === (c.stage === "bajarildi" ? 100 : c.progress)));
  try {
    const r = await api("api/board/task/" + id, { json: change });
    toast(msg + bdTg(r), "check");
    renderBoard();
  } catch (e) {
    Object.assign(c, prev); drawBoard(); openBoardCard(id);
    toast(esc(e.message), "danger");
  }
}

/* ---- kartochka oynasi ---- */
const bdDirty = () => {
  const a = document.activeElement, dr = $("#drawer");
  if (a && dr.contains(a) && /INPUT|TEXTAREA/.test(a.tagName)) return true;
  const c = BD.card;
  return !!($("#bdC")?.value.trim() || $("#bdChk")?.value.trim()) || (c && $("#bdT") && ($("#bdT").value !== c.title || $("#bdN").value !== (c.note || "")));
};

function bdEvent(e) {
  const when = `<time title="${clock(e.at)}">${ago(e.at)}</time>`;
  if (e.kind === "comment" || e.kind === "telegram") {
    return `<li class="ev talk">${ava(e.who || "?", null, null, "xs")}<div><div class="ev-h"><b>${esc(e.who || "Kimdir")}</b>${e.kind === "telegram" ? `<span class="ev-tg">${I("send")}Telegramda</span>` : ""}${when}</div><p>${esc(e.text)}</p></div></li>`;
  }
  const who = esc(e.who || "Kimdir");
  const text = { create: `${who} vazifani yozdi. ${esc(e.text)}`, assign: `${who} vazifani ${esc(e.text)}ga berdi`, stage: `${who}: ${esc(e.text)}`,
    edit: `${who}: ${esc(e.text)}`, check: `${who} bajardi: ${esc(e.text)}`, remind: `Bot guruhda eslatdi: ${e.text.startsWith("javob") ? "vazifani qabul qilish" : "muddat ertaga"}${e.text.endsWith("yuborilmadi") ? " (yuborilmadi)" : ""}` }[e.kind] || esc(e.text);
  return `<li class="ev"><span class="ev-dot"></span><div><span>${text}</span>${when}</div></li>`;
}

async function openBoardCard(id, quiet) {
  if (quiet && bdDirty()) return;
  BD.open = id;
  let c;
  try { c = await api("api/board/task/" + id); } catch (e) { if (!quiet) toast(esc(e.message), "danger"); return; }
  if (BD.open !== id || (quiet && bdDirty())) return;
  BD.card = c;
  const keep = quiet || $("#drawer .bd-sheet[data-card='" + id + "']") ? $("#drawer .sheet").scrollTop : 0;
  const prog = c.stage === "bajarildi" ? 100 : c.progress;
  const done = c.checklist.filter((x) => x.done).length;
  openDrawer(`<div class="bd-sheet" data-card="${id}"><div class="sh-head"><div class="bd-dh">${I("checklist")}</div>
      <div style="min-width:0"><h2>${esc(c.title)}</h2><div class="meta"><span>${esc(c.project)}</span>${c.giver ? `<span>${esc(first(c.giver))} berdi, ${clock(c.created_at)}</span>` : `<span>${clock(c.created_at)}</span>`}</div></div>
      <button class="icon-btn x" aria-label="Yopish">${I("close")}</button></div>
    <div class="sh-body">
      ${c.flag ? `<section class="card bd-alert ${c.flag === "toqiq" ? "risk" : "warn"}"><div class="cb"><b>${c.flag === "toqiq" ? "To'siq" : "Savol"}</b><p>${c.flag_text ? esc(c.flag_text) : "Xodim hali yozmadi"}</p>
        <div class="bd-alert-f"><button class="btn btn-line" id="bdAns">${I("chat-dots")}Javob yozish</button><button class="btn btn-line" id="bdSolved">${I("check")}Hal bo'ldi</button></div></div></section>` : ""}
      <section class="card"><div class="ch"><h3>Holat</h3></div><div class="cb">
        <div class="seg bd-seg" role="group" aria-label="Ustun">${BD_STAGES.map(([k, t]) => `<button data-st="${k}" aria-pressed="${c.stage === k}">${t}</button>`).join("")}</div>
        <div class="bd-row"><span>Bajarilgani${c.checklist.length ? ", ro'yxatdan" : ""}</span><div class="seg" role="group">${[0, 25, 50, 75, 100].map((p) => `<button data-pr="${p}" aria-pressed="${prog === p}">${p}%</button>`).join("")}</div></div>
      </div></section>
      <section class="card"><div class="ch"><h3>Ijrochi</h3></div><div class="cb">
        <div class="bd-row">${c.assignee ? `<span class="bd-who">${ava(c.assignee, c.department, null, "sm")}<span><b>${esc(c.assignee)}</b><small>${esc(c.department || "")}${c.accepted_at ? ", qabul qildi " + clock(c.accepted_at) : c.sent ? ", hali javob bermadi" : ""}</small></span></span>` : "<span>Tanlanmagan</span>"}
          <button class="btn btn-line" id="bdRe">${I("transfer")}${c.assignee ? "Boshqaga berish" : "Tanlash"}</button></div>
        <div class="bd-tgline">${I("send")}${c.sent ? "Guruhda xabar bor: xodim tugma bosib yoki unga javob yozib holatni o'zgartiradi" : "Guruhga hali yuborilmagan"}</div>
      </div></section>
      ${c.siblings?.length ? `<section class="card"><div class="ch"><h3>Birgalikda</h3><span class="count">${c.siblings.length + 1} kishi</span></div><div class="cb bd-sib">
        ${c.siblings.map((s) => `<button class="bd-sib-row" data-sib="${s.id}">${ava(s.assignee, null, null, "xs")}<span>${esc(s.assignee)}</span><small>${bdStage(s.stage)}${["jarayon", "tekshiruv"].includes(s.stage) ? ", " + s.progress + "%" : ""}</small></button>`).join("")}</div></section>` : ""}
      <section class="card"><div class="ch"><h3>Muddat</h3>${c.deadline && bdOpen(c) ? dueTag(c) : ""}</div><div class="cb">
        <div class="bd-due">${bdPresets().map(([t, v]) => `<button class="chip" data-due="${v}" aria-pressed="${c.deadline === v}">${t}</button>`).join("")}
          <input type="date" class="ctl" id="bdD" value="${c.deadline || ""}" aria-label="Muddat sanasi">${c.deadline ? `<button class="chip" data-due="">${I("close")}Olib tashlash</button>` : ""}</div>
        <label class="bd-check">${`<input type="checkbox" id="bdP" ${c.priority === "yuqori" ? "checked" : ""}>`}Muhim vazifa</label>
      </div></section>
      <section class="card"><div class="ch"><h3>Ichki ro'yxat</h3>${c.checklist.length ? `<span class="bd-cnt">${done}/${c.checklist.length}</span>` : ""}</div><div class="cb">
        ${c.checklist.length ? `<div class="bd-prog big"><i style="width:${Math.round((100 * done) / c.checklist.length)}%"></i></div>` : ""}
        <ul class="chk">${c.checklist.map((x) => `<li class="${x.done ? "done" : ""}"><label><input type="checkbox" data-chk="${x.id}" ${x.done ? "checked" : ""}><span>${esc(x.text)}</span></label><button class="icon-btn" data-chkdel="${x.id}" aria-label="O'chirish">${I("close")}</button></li>`).join("")}</ul>
        <form class="chk-add" id="bdChkF"><input class="ctl" id="bdChk" placeholder="${c.checklist.length ? "Yana band qo'shish" : "Ishni bo'laklarga bo'ling: band yozib Enter bosing"}" autocomplete="off"><button class="btn btn-line" type="submit">${I("add")}Qo'shish</button></form>
      </div></section>
      <section class="card"><div class="ch"><h3>Tafsilot</h3></div><div class="cb">
        <div class="field"><label for="bdT">Vazifa</label><input id="bdT" value="${esc(c.title)}"></div>
        <div class="field"><label for="bdN">Izoh</label><textarea id="bdN" rows="3" placeholder="Topshiriq tafsiloti: guruhdagi xabarda ham ko'rinadi">${esc(c.note || "")}</textarea></div>
        <button class="btn btn-dark" id="bdSave">Saqlash</button>
      </div></section>
      <section class="card"><div class="ch"><h3>Faoliyat</h3></div><div class="cb">
        <form class="bd-cm" id="bdCF"><textarea id="bdC" rows="2" placeholder="${c.sent ? "Izoh yozing: guruhda xodimga javob bo'lib boradi" : "Izoh yozing"}"></textarea>
          <div class="bd-cm-f"><small>Ctrl+Enter</small><button class="btn btn-dark" type="submit">${c.sent ? I("send") + "Yuborish" : "Saqlash"}</button></div></form>
        <ul class="evs">${c.events.map(bdEvent).join("")}</ul>
      </div></section>
      <div class="bd-foot"><button class="btn btn-line" id="bdCopy">${I("copy")}Nusxa olish</button>${c.manual ? `<button class="btn btn-line danger" id="bdDel">${I("trash")}O'chirish</button>` : ""}</div>
    </div></div>`);
  $("#drawer .sheet").scrollTop = keep;
  $("#drawer .x").onclick = () => { BD.open = 0; closeDrawer(); };
  $$("[data-sib]").forEach((b) => (b.onclick = () => openBoardCard(+b.dataset.sib)));
  $$("[data-st]").forEach((b) => (b.onclick = () => bdSave(id, { stage: b.dataset.st }, bdStage(b.dataset.st))));
  $$("[data-pr]").forEach((b) => (b.onclick = () => bdSave(id, +b.dataset.pr >= 100 ? { stage: "bajarildi" } : { stage: +b.dataset.pr ? "jarayon" : c.stage === "bajarildi" ? "jarayon" : c.stage, progress: +b.dataset.pr }, b.dataset.pr + "%")));
  $("#bdRe").onclick = () => openNewTask(c);
  $$("[data-due]").forEach((b) => (b.onclick = () => bdSave(id, { deadline: b.dataset.due }, b.dataset.due ? "Muddat " + uzDate(parseDay(b.dataset.due)) : "Muddat olib tashlandi")));
  $("#bdD").onchange = (e) => e.target.value && bdSave(id, { deadline: e.target.value }, "Muddat " + uzDate(parseDay(e.target.value)));
  $("#bdP").onchange = (e) => bdSave(id, { priority: e.target.checked ? "yuqori" : "" }, e.target.checked ? "Muhim deb belgilandi" : "Muhim belgisi olindi");
  $$("[data-chk]").forEach((b) => (b.onchange = () => bdDo(id, () => api("api/board/check/" + b.dataset.chk, { json: { done: b.checked } }))));
  $$("[data-chkdel]").forEach((b) => (b.onclick = () => bdDo(id, () => api("api/board/check/" + b.dataset.chkdel, { method: "DELETE" }))));
  $("#bdChkF").onsubmit = (e) => {
    e.preventDefault();
    const text = $("#bdChk").value.trim();
    if (text) bdDo(id, () => api(`api/board/task/${id}/check`, { json: { text } }), "", "#bdChk").then(() => $("#bdChk")?.focus());
  };
  $("#bdSave").onclick = () => bdSave(id, { title: $("#bdT").value, note: $("#bdN").value }, "Saqlandi");
  const send = () => {
    const text = $("#bdC").value.trim();
    if (!text) { $("#bdC").focus(); return; }
    bdDo(id, () => api(`api/board/task/${id}/comment`, { json: { text } }), "Izoh yozildi");
  };
  $("#bdCF").onsubmit = (e) => { e.preventDefault(); send(); };
  $("#bdC").onkeydown = (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } };
  if ($("#bdAns")) $("#bdAns").onclick = () => { $("#bdC").scrollIntoView({ block: "center", behavior: "smooth" }); $("#bdC").focus({ preventScroll: true }); };
  if ($("#bdSolved")) $("#bdSolved").onclick = () => bdSave(id, { flag: "" }, c.flag === "toqiq" ? "To'siq hal bo'ldi" : "Savol hal bo'ldi");
  $("#bdCopy").onclick = async () => {
    try {
      const r = await api(`api/board/task/${id}/copy`, { json: {} });
      toast("Nusxa olindi: ijrochini tanlang", "check");
      await renderBoard();
      openBoardCard(r.id);
    } catch (e) { toast(esc(e.message), "danger"); }
  };
  if ($("#bdDel")) $("#bdDel").onclick = () => {
    openModal("Vazifani o'chirish", `<p class="bd-confirm">«${esc(c.title)}» butunlay o'chadi.${c.sent ? " Guruhdagi xabarda «Vazifa bekor qilindi» deb yoziladi." : ""}</p>`,
      `<button class="btn btn-ghost" data-close>Bekor qilish</button><button class="btn btn-dark danger" id="bdDelGo">${I("trash")}O'chirish</button>`);
    $("#bdDelGo").onclick = async () => {
      try {
        const r = await api("api/board/task/" + id, { method: "DELETE" });
        closeModal(); BD.open = 0; closeDrawer();
        toast(`«${esc(c.title)}» o'chirildi${bdTg(r)}`, "check");
        renderBoard();
      } catch (e) { toast(esc(e.message), "danger"); }
    };
  };
}

/* ---- tezkor tugmalar ---- */
function bdKeys() {
  const rows = [["N", "Yangi vazifa"], ["F", "Qidirish"], ["X", "Filtrlarni tozalash"], ["V", "Ko'rinish: Doska, Jadval, Kalendar"],
    ["1–5", "Sichqoncha turgan kartochkani shu ustunga o'tkazish"], ["Enter", "Kartochkani ochish"], ["Ctrl+Enter", "Izohni yuborish"], ["Esc", "Oynani yopish"]];
  openModal("Tezkor tugmalar", `<div class="keys">${rows.map(([k, t]) => `<div><kbd>${k}</kbd><span>${t}</span></div>`).join("")}</div>`, null);
}
function bdKey(e) {
  if ($("#modal").classList.contains("open") || !BD.data) return false;
  const k = e.key.toLowerCase();
  const el = document.activeElement?.closest?.("#v-doska [data-id]");
  const target = BD.hover || (el ? +el.dataset.id : 0);
  if (/^[1-5]$/.test(k) && target && BD.view === "doska") {
    const c = BD.data.cards.find((x) => x.id === target), st = BD_STAGES[+k - 1][0];
    if (c && c.stage !== st) bdMove(c, st);
    return true;
  }
  if (k === "enter" && el) { openBoardCard(+el.dataset.id); return true; }
  if (k === "n") { e.preventDefault(); openNewTask(); return true; }
  if (k === "f" || k === "/") { e.preventDefault(); $("#bdQ")?.focus(); return true; }
  if (k === "x") { bdClear(); return true; }
  if (k === "v") { bdView(BD_VIEWS[(BD_VIEWS.findIndex((x) => x[0] === BD.view) + 1) % BD_VIEWS.length][0]); return true; }
  if (e.key === "?") { bdKeys(); return true; }
  return false;
}

/* Yangi vazifa yoki boshqa xodimga berish: kim bo'sh, kim band — yonida ko'rinadi */
async function openNewTask(c) {
  const proj = c ? String(c.project_id) : String(bdProj()?.id || "");
  openModal(c ? `«${esc(c.title)}»: kimga beramiz` : "Yangi vazifa", `
    ${c ? "" : `<div class="field"><label for="ntT">Vazifa</label><input id="ntT" placeholder="Masalan, hisobot shaklini yangilash" autocomplete="off"></div>
    <div class="bd-2"><div class="field"><label for="ntP">Loyiha</label><select id="ntP">${BD.data.projects.map((p) => `<option value="${p.id}" ${String(p.id) === proj ? "selected" : ""}>${esc(p.name)}${p.demo ? " (namuna)" : ""}</option>`).join("")}</select></div>
      <div class="field"><label for="ntD">Muddat</label><input id="ntD" type="date"></div></div>
    <div class="bd-due nt">${bdPresets().map(([t, v]) => `<button type="button" class="chip" data-nd="${v}">${t}</button>`).join("")}<label class="bd-check"><input type="checkbox" id="ntH">Muhim</label></div>
    <div class="field"><label for="ntN">Izoh</label><textarea id="ntN" rows="2" placeholder="Ixtiyoriy"></textarea></div>
    <div class="field"><label for="ntL">Ichki ro'yxat</label><textarea id="ntL" rows="2" placeholder="Ixtiyoriy: har qatorga bitta band"></textarea></div>`}
    <div class="field"><label>${c ? "Ijrochi" : "Ijrochilar"}</label><label class="ctl bd-search wide">${I("search")}<input id="ntQ" placeholder="Xodimni qidirish" autocomplete="off"></label></div>
    <div class="bd-pick" id="ntList"><div class="sk" style="height:180px"></div></div>`,
    `<button class="btn btn-ghost" data-close>Bekor qilish</button><button class="btn btn-dark" id="ntGo">${I("send")}Berish va guruhga yuborish</button>`, true);
  let people = [], pick = c?.assignee || "";
  const picked = new Set();  // yangi vazifada bir nechta ijrochi
  const load = async () => {
    try { people = await api("api/board/people?project=" + ($("#ntP")?.value || proj)); } catch (e) { toast(esc(e.message), "danger"); return; }
    draw();
  };
  const draw = () => {
    const q = ($("#ntQ").value || "").toLowerCase();
    const list = people.filter((p) => !q || p.name.toLowerCase().includes(q) || (p.department || "").toLowerCase().includes(q));
    $("#ntList").innerHTML = list.map((p) => `<button class="bd-person ${(c ? p.name === pick : picked.has(p.name)) ? "on" : ""}" data-n="${esc(p.name)}" aria-pressed="${c ? p.name === pick : picked.has(p.name)}">
        ${ava(p.name, p.department, p.state, "sm")}<span class="bd-pn"><b>${esc(p.name)}</b><small>${esc(p.department)}${p.in_project ? ", shu loyihada" : ""}</small></span>
        ${p.suggest ? `<span class="bd-chip ok">Tavsiya</span>` : ""}<span class="pill p-${p.state} sm"><span><b>${esc(p.state_label)}</b></span></span><span class="bd-load">${p.open} ochiq</span></button>`).join("") || emptyBox("Xodim topilmadi", "search");
    $$(".bd-person").forEach((b) => (b.onclick = () => {
      if (c) pick = b.dataset.n;
      else if (picked.has(b.dataset.n)) picked.delete(b.dataset.n); else picked.add(b.dataset.n);
      draw();
    }));
    if (!c) $("#ntGo").innerHTML = I("send") + (picked.size > 1 ? `${picked.size} kishiga berish va guruhga yuborish` : "Berish va guruhga yuborish");
  };
  $("#ntQ").oninput = draw;
  $("#ntP")?.addEventListener("change", load);
  $$("[data-nd]").forEach((b) => (b.onclick = () => { $("#ntD").value = b.dataset.nd; $$("[data-nd]").forEach((x) => x.setAttribute("aria-pressed", x === b)); }));
  await load();
  $("#ntT")?.focus();
  $("#ntGo").onclick = async () => {
    if (c ? !pick : !picked.size) { toast("Ijrochini tanlang", "info"); return; }
    const btn = $("#ntGo"); btn.disabled = true;
    try {
      let r;
      if (c) r = await api("api/board/task/" + c.id, { json: { assignee: pick } });
      else r = await api("api/board/task", { json: { title: $("#ntT").value, project_id: +$("#ntP").value, assignees: [...picked],
        deadline: $("#ntD").value || null, priority: $("#ntH").checked ? "yuqori" : null, note: $("#ntN").value || null,
        checklist: $("#ntL").value.split("\n").map((x) => x.trim()).filter(Boolean) } });
      closeModal();
      toast(c || picked.size === 1 ? `${esc(first(c ? pick : [...picked][0]))}ga berildi${bdTg(r)}` : `${picked.size} kishiga berildi${bdTg(r)}`, "check");
      await renderBoard();
      if (c) openBoardCard(c.id);
    } catch (e) { toast(esc(e.message), "danger"); btn.disabled = false; }
  };
}

/* ================= kim kirgan: rol, ruxsatlar va foydalanuvchilar ================= */
const can = (p) => !!S.meta?.me?.can?.includes(p);
const ROLE_ORDER = ["admin", "rahbar", "menejer"];

// Rol panelning ko'rinishini belgilaydi: ruxsat yo'q tugma umuman ko'rinmaydi (bosib, rad javobini olish yo'q)
function setDept(d, tab) {
  S.dept = d || "";
  YD.data = null; RP.data = null; BD.data = null; BD.dept = "";
  S.pf.dept = "";
  drawScope();
  writeHash();
  if (tab) go(tab);
  load();
}
function drawScope() {
  const sel = $("#scopeSel");
  if (sel) {
    const depts = S.meta?.departments || [];
    sel.innerHTML = `<option value="">Hamma bo'limlar</option>` + depts.map((d) => `<option ${d === S.dept ? "selected" : ""}>${esc(d)}</option>`).join("")
      + `<option ${S.dept === "Belgilanmagan" ? "selected" : ""}>Belgilanmagan</option>`;
    sel.value = S.dept;
    sel._ssSync?.();
  }
  const bar = $("#scopeNote");
  if (bar) {
    bar.hidden = !S.dept;
    bar.innerHTML = S.dept ? `<div class="hist-in">${I(DEPT_ICON[S.dept] || "depts")}<span>${esc(S.dept)} bo'limi paneli: hamma ko'rsatkich shu bo'lim bo'yicha</span>
      <button class="btn btn-line" id="scopeOut">${I("close")}Hamma bo'limlar</button></div>` : "";
    $("#scopeOut")?.addEventListener("click", () => setDept(""));
  }
  document.documentElement.classList.toggle("in-dept", !!S.dept);
}
function applyRole() {
  const me = S.meta?.me;
  if (!me) return;
  const root = document.documentElement;
  ["board", "decide", "correct", "people", "settings", "import", "accounts"].forEach((p) => root.classList.toggle("can-" + p, can(p)));
  $("[data-m=settings]")?.toggleAttribute("hidden", !can("settings"));
  $("[data-m=import]")?.toggleAttribute("hidden", !can("import"));
  $("[data-m=addperson]")?.toggleAttribute("hidden", !can("people"));
  $("[data-m=people]")?.toggleAttribute("hidden", !can("people"));
  const scopeText = me.role === "menejer" ? (me.projects.length ? me.projects.map((p) => p.name).join(", ") : "Loyiha biriktirilmagan") : "Hamma loyiha";
  let head = $("#menu .pop-me");
  if (!head) {
    $("#menu .pop").insertAdjacentHTML("afterbegin", `<div class="pop-me"></div><div class="pop-acc"></div><hr>`);
    head = $("#menu .pop-me");
  }
  head.innerHTML = `${ava(me.name, null, null, "md")}<div><b>${esc(me.name)}</b><span>${esc(me.role_label)}${me.local ? "" : ", " + esc(me.login)}</span><small>${esc(scopeText)}</small></div>`;
  $("#menu .pop-acc").innerHTML = (can("accounts") ? `<button data-m="accounts">${I("people")}Foydalanuvchilar va rollar</button>` : "")
    + (can("settings") ? `<button data-m="telegram">${I("send")}Telegram ulanishi</button>` : "")
    + (me.local ? "" : `<button data-m="password">${I("lock")}Parolni o'zgartirish</button><button data-m="logout">${I("logout")}Chiqish</button>`);
  $("#menuBtn").innerHTML = `<span class="me-ini">${esc(initials(me.name))}</span>`;
  $("#menuBtn").setAttribute("title", `${me.name}, ${me.role_label}`);
  const note = $("#roleNote");
  if (note) {
    note.hidden = !(me.role === "menejer");
    note.innerHTML = me.role === "menejer" ? `<div class="hist-in">${I("eye")}<span>${me.projects.length ? `Siz loyiha menejerisiz: panelda faqat ${esc(scopeText)} ko'rinadi` : "Sizga hali loyiha biriktirilmagan. Admin biriktirgach shu yerda ko'rinadi"}</span></div>` : "";
  }
}

async function logout() {
  try { await api("api/logout", { json: {} }); } catch (e) {}
  location.href = "login";
}

/* parol: kuchli, eslab qolsa bo'ladigan, o'xshash belgisiz (0/O, 1/l) */
function genPassword() {
  const abc = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789", n = new Uint32Array(12);
  crypto.getRandomValues(n);
  const s = [...n].map((x) => abc[x % abc.length]).join("");
  return s.slice(0, 4) + "-" + s.slice(4, 8) + "-" + s.slice(8);
}
const pwRules = (p, login) => [["Kamida 8 belgi", p.length >= 8], ["Faqat raqam emas", !!p && !/^\d+$/.test(p)], ["Ichida login yo'q", !!p && (!login || !p.toLowerCase().includes(login.toLowerCase()))]];
const pwOk = (p, login) => pwRules(p, login).every((r) => r[1]);
function bindPwField(inputSel, rulesSel, loginOf) {
  const inp = $(inputSel), draw = () => { $(rulesSel).innerHTML = pwRules(inp.value, loginOf()).map(([t, ok]) => `<li class="${ok ? "ok" : ""}">${t}</li>`).join(""); };
  inp.addEventListener("input", draw); draw();
  return draw;
}

function openPassword() {
  openModal("Parolni o'zgartirish", `
    <div class="field"><label for="opOld">Hozirgi parol</label><input id="opOld" type="password" autocomplete="current-password"></div>
    <div class="field"><label for="opNew">Yangi parol</label><input id="opNew" type="password" autocomplete="new-password"></div>
    <ul class="pw-rules" id="opRules"></ul>
    <div class="field"><label for="opRep">Yangi parol, takroran</label><input id="opRep" type="password" autocomplete="new-password"></div>
    <p class="acc-hint">Boshqa qurilmalardagi kirishlar yopiladi, bu qurilmada qolasiz.</p>`,
    `<button class="btn btn-ghost" data-close>Bekor qilish</button><button class="btn btn-dark" id="opGo">${I("check")}Saqlash</button>`);
  bindPwField("#opNew", "#opRules", () => S.meta.me.login);
  $("#opOld").focus();
  $("#opGo").onclick = async () => {
    const nw = $("#opNew").value;
    if (!pwOk(nw, S.meta.me.login)) { toast("Yangi parol talablarini bajaring", "info"); return; }
    if (nw !== $("#opRep").value) { toast("Ikkala yangi parol bir xil bo'lsin", "info"); return; }
    try { await api("api/me/password", { json: { old: $("#opOld").value, new: nw } }); closeModal(); toast("Parol o'zgardi", "check"); }
    catch (e) { toast(esc(e.message), "danger"); }
  };
}

/* ---- foydalanuvchilar ro'yxati ---- */
const ACC = { data: null, q: "" };
async function openAccounts() {
  try { ACC.data = await api("api/accounts"); } catch (e) { toast(esc(e.message), "danger"); return; }
  drawAccounts();
}
function accScope(a) {
  if (a.role !== "menejer") return "Hamma loyiha";
  return a.projects.length ? (a.projects.length <= 2 ? a.projects.map((p) => p.name).join(", ") : `${a.projects.length} ta loyiha`) : "Loyiha biriktirilmagan";
}
function drawAccounts() {
  const d = ACC.data, q = ACC.q.toLowerCase();
  const list = d.accounts.filter((a) => !q || (a.name + " " + a.login).toLowerCase().includes(q));
  const count = (r) => d.accounts.filter((a) => a.role === r && a.active).length;
  openModal("Foydalanuvchilar va rollar", `
    <div class="acc-roles">${d.roles.map((r) => `<div class="acc-role"><b>${esc(r.label)}<em>${count(r.key)}</em></b><span>${esc(r.text)}</span></div>`).join("")}</div>
    <div class="acc-bar"><label class="ctl bd-search wide">${I("search")}<input id="accQ" placeholder="Ism yoki login" value="${esc(ACC.q)}" autocomplete="off"></label>
      <button class="btn btn-dark" id="accNew">${I("user-plus")}Foydalanuvchi qo'shish</button></div>
    <div class="acc-list">${list.map((a) => `<button class="acc-row ${a.active ? "" : "off"}" data-acc="${a.id}">
        ${ava(a.name, null, null, "sm")}<span class="acc-n"><b>${esc(a.name)}${a.id === S.meta.me.id ? `<em>siz</em>` : ""}</b><small>${esc(a.login)}, ${esc(accScope(a))}</small></span>
        <span class="acc-r">${esc(a.role === "admin" ? "Admin" : a.role === "rahbar" ? "Rahbar" : "Loyiha menejeri")}</span>
        <span class="acc-t">${a.active ? (a.last_login ? ago(a.last_login) + " kirgan" : "Hali kirmagan") : "Kirish to'xtatilgan"}</span></button>`).join("")
      || emptyBox(q ? "Bu so'z bo'yicha foydalanuvchi yo'q" : "Hali foydalanuvchi yo'q", "people")}</div>`, null, true);
  const qi = $("#accQ");
  qi.oninput = () => { ACC.q = qi.value; const pos = qi.selectionStart; drawAccounts(); const n = $("#accQ"); n.focus(); n.setSelectionRange(pos, pos); };
  $("#accNew").onclick = () => openAccountForm(null);
  $$("[data-acc]").forEach((b) => (b.onclick = () => openAccountForm(d.accounts.find((a) => a.id === +b.dataset.acc))));
}

/* ---- qo'shish va tahrirlash: bitta forma ---- */
function openAccountForm(a) {
  const d = ACC.data, isNew = !a, self = a && a.id === S.meta.me.id;
  let role = a?.role || "menejer", picked = new Set((a?.projects || []).map((p) => p.id)), pq = "";
  openModal(isNew ? "Yangi foydalanuvchi" : esc(a.name), `
    <button class="acc-back" id="accBack">${I("arrow-left")}Foydalanuvchilar</button>
    <div class="bd-2"><div class="field"><label for="afN">Ism-familiya</label><input id="afN" value="${esc(a?.name || "")}" placeholder="Masalan, Feruzbek Karimov" autocomplete="off"></div>
      <div class="field"><label for="afL">Login</label><input id="afL" value="${esc(a?.login || "")}" ${isNew ? "" : "disabled"} placeholder="feruzbek" autocapitalize="none" spellcheck="false" autocomplete="off"></div></div>
    <div class="field"><label for="afP">${isNew ? "Parol" : "Yangi parol"}</label>
      <div class="acc-pw"><input id="afP" type="text" placeholder="${isNew ? "" : "O'zgartirmasangiz bo'sh qoldiring"}" autocomplete="new-password" spellcheck="false">
        <button class="btn btn-line" type="button" id="afGen">${I("refresh")}Yaratish</button><button class="icon-btn" type="button" id="afCopy" title="Nusxa olish" aria-label="Parolni nusxalash">${I("copy")}</button></div>
      <ul class="pw-rules" id="afRules"></ul></div>
    <div class="field"><label>Rol</label><div class="acc-pick" role="radiogroup">${d.roles.map((r) => `<button type="button" role="radio" class="acc-opt" data-role="${r.key}" aria-checked="${r.key === role}" ${self && r.key !== "admin" && a.role === "admin" ? "" : ""}>
        <b>${esc(r.label)}</b><span>${esc(r.text)}</span></button>`).join("")}</div></div>
    <div class="field" id="afProj"><label>Loyihalari</label><p class="acc-hint">Menejer panelda faqat shu loyihalarni ko'radi va ularda vazifa beradi</p>
      <label class="ctl bd-search wide">${I("search")}<input id="afPQ" placeholder="Loyihani qidirish" autocomplete="off"></label>
      <div class="acc-projs" id="afPL"></div></div>
    ${isNew ? "" : `<div class="acc-state"><div><b>Kirish ruxsati</b><span>${a.active ? "Faol: login va parol bilan kira oladi" : "To'xtatilgan: kira olmaydi, ma'lumoti saqlanadi"}</span></div>
      ${self ? `<span class="acc-hint">Bu sizning akkauntingiz</span>` : `<button class="btn btn-line" id="afAct">${a.active ? I("lock") + "Kirishni to'xtatish" : I("check") + "Kirishni qaytarish"}</button>`}</div>
      <p class="acc-meta">${a.created_by ? esc(a.created_by) + " qo'shgan, " : ""}${clock(a.created_at)}${a.last_login ? ". Oxirgi kirish: " + clock(a.last_login) : ". Hali kirmagan"}</p>`}`,
    `${isNew || self ? "" : `<button class="btn btn-ghost danger" id="afDel">${I("trash")}O'chirish</button>`}<span style="flex:1"></span>
     <button class="btn btn-ghost" id="afCancel">Bekor qilish</button><button class="btn btn-dark" id="afGo">${I("check")}${isNew ? "Qo'shish" : "Saqlash"}</button>`, true);
  const drawRules = bindPwField("#afP", "#afRules", () => $("#afL").value.trim());
  $("#afL").addEventListener("input", drawRules);
  const drawRole = () => {
    $$("[data-role]").forEach((b) => b.setAttribute("aria-checked", b.dataset.role === role));
    $("#afProj").hidden = role !== "menejer";
  };
  const drawProjects = () => {
    const list = d.projects.filter((p) => !pq || p.name.toLowerCase().includes(pq));
    $("#afPL").innerHTML = list.map((p) => `<label class="acc-proj"><input type="checkbox" data-pid="${p.id}" ${picked.has(p.id) ? "checked" : ""}><span>${esc(p.name)}</span>${p.demo ? `<small>namuna</small>` : ""}</label>`).join("") || emptyBox("Loyiha topilmadi", "search");
    $$("[data-pid]").forEach((c) => (c.onchange = () => { c.checked ? picked.add(+c.dataset.pid) : picked.delete(+c.dataset.pid); }));
  };
  $$("[data-role]").forEach((b) => (b.onclick = () => { role = b.dataset.role; drawRole(); }));
  $("#afPQ").oninput = (e) => { pq = e.target.value.toLowerCase(); drawProjects(); };
  drawRole(); drawProjects();
  $("#afGen").onclick = () => { $("#afP").value = genPassword(); drawRules(); };
  $("#afCopy").onclick = async () => {
    const v = $("#afP").value;
    if (!v) { toast("Avval parol yozing yoki yarating", "info"); return; }
    try { await navigator.clipboard.writeText(v); toast("Parol nusxalandi: uni xodimga shaxsan bering", "check"); } catch (e) { $("#afP").select(); }
  };
  $("#accBack").onclick = $("#afCancel").onclick = () => drawAccounts();
  (isNew ? $("#afN") : $("#afP")).focus();
  const send = async (body, msg) => {
    try {
      if (isNew) await api("api/accounts", { json: body }); else await api("api/accounts/" + a.id, { json: body });
      toast(msg, "check");
      ACC.data = await api("api/accounts");
      if (self) { S.meta = await api("api/meta"); applyRole(); }
      drawAccounts();
    } catch (e) { toast(esc(e.message), "danger"); }
  };
  $("#afGo").onclick = () => {
    const pw = $("#afP").value, login = $("#afL").value.trim();
    if ((isNew || pw) && !pwOk(pw, login)) { toast("Parol talablarini bajaring", "info"); $("#afP").focus(); return; }
    if (role === "menejer" && !picked.size) { toast("Menejerga kamida bitta loyiha biriktiring", "info"); return; }
    const body = { name: $("#afN").value, role, projects: [...picked] };
    if (isNew) Object.assign(body, { login, password: pw });
    else if (pw) body.password = pw;
    send(body, isNew ? `${esc(first(body.name))} qo'shildi. Login va parolni unga shaxsan bering` : pw ? "Saqlandi, yangi parol bilan kiradi" : "Saqlandi");
  };
  if ($("#afAct")) $("#afAct").onclick = () => send({ active: !a.active }, a.active ? `${esc(first(a.name))} endi kira olmaydi` : `${esc(first(a.name))} yana kira oladi`);
  if ($("#afDel")) $("#afDel").onclick = () => {
    openModal("Foydalanuvchini o'chirish", `<p class="bd-confirm">«${esc(a.name)}» akkaunti butunlay o'chadi. Vaqtincha to'xtatish kerak bo'lsa, «Kirishni to'xtatish» ni tanlang: uni keyin qaytarsa bo'ladi.</p>`,
      `<button class="btn btn-ghost" id="adBack">Ortga</button><button class="btn btn-dark danger" id="adGo">${I("trash")}O'chirish</button>`);
    $("#adBack").onclick = () => openAccountForm(a);
    $("#adGo").onclick = async () => {
      try { await api("api/accounts/" + a.id, { method: "DELETE" }); toast(`${esc(first(a.name))} o'chirildi`, "check"); ACC.data = await api("api/accounts"); drawAccounts(); }
      catch (e) { toast(esc(e.message), "danger"); }
    };
  };
}

/* ================= Telegram ulanishi: bot va akkaunt ================= */
const TG = { data: null, chats: null, q: "", picked: new Set(), days: 365, timer: null };
const TG_ROWS = [
  ["Yangi xabarlar va tahrirlar", true, true],
  ["Guruhning eski tarixi: bot qo'shilishidan oldingi hisobotlar", false, true],
  ["O'chirilgan xabarlar: hisobot o'chirilsa rahbar ko'radi", false, true],
  ["Tugmali vazifa, eslatma va guruhda javob yozish", true, false],
];
async function openTelegram() {
  try { TG.data = await api("api/telegram"); } catch (e) { toast(esc(e.message), "danger"); return; }
  drawTelegram();
}
function tgPoll() {
  clearTimeout(TG.timer);
  const h = Object.values(TG.data?.account?.history || {});
  if (h.some((x) => !x.done)) TG.timer = setTimeout(async () => {
    if (!$("#tgBox")) return;
    try { TG.data = await api("api/telegram"); } catch (e) { return; }
    drawTelegram(true);
  }, 3000);
}
function drawTelegram(quiet) {
  const d = TG.data, a = d.account;
  const mark = (ok) => (ok ? `<span class="tg-yes">${I("check")}</span>` : `<span class="tg-no">—</span>`);
  const steps = { off: tgStepStart, code: tgStepCode, password: tgStepPassword, chats: tgStepChats, on: tgStepOn };
  const body = `<div id="tgBox">
    <p class="tg-lead">Puls guruhlardagi hisobotlarni ikki yo'l bilan o'qiydi. Eng to'liq natija ikkalasi birga ishlaganda bo'ladi: akkaunt o'qiydi, bot yozadi.</p>
    <table class="tg-cmp"><thead><tr><th></th><th>Bot</th><th>Akkaunt</th></tr></thead>
      <tbody>${TG_ROWS.map(([t, b, ac]) => `<tr><td>${t}</td><td>${mark(b)}</td><td>${mark(ac)}</td></tr>`).join("")}</tbody></table>
    <div class="tg-cards">
      <section class="tg-card"><div class="tg-h"><b>Bot</b><span class="pill ${d.bot.on ? "p-ok" : "p-idle"} sm"><span><b>${d.bot.on ? "Ishlayapti" : "O'chiq"}</b></span></span></div>
        <p>${d.bot.username ? "@" + esc(d.bot.username) + ". " : ""}Guruhga qo'shiladi va admin qilinadi. Vazifa tugmalari, eslatmalar va kunlik hisobot fayli shu orqali boradi.</p></section>
      <section class="tg-card main"><div class="tg-h"><b>Akkaunt</b><span class="pill ${a.step === "on" ? "p-ok" : "p-idle"} sm"><span><b>${a.step === "on" ? "Ulangan" : a.step === "off" ? "Ulanmagan" : "Ulanmoqda"}</b></span></span></div>
        ${a.error ? `<div class="tg-err">${esc(a.error)}</div>` : ""}
        <div id="tgStep">${steps[a.step] ? steps[a.step](a) : ""}</div></section>
    </div></div>`;
  if (quiet && $("#tgBox") && a.step === "on") { $("#tgStep").innerHTML = tgStepOn(a); bindTgOn(); tgPoll(); return; }
  openModal("Telegram ulanishi", body, null, true);
  ({ off: bindTgStart, code: bindTgCode, password: bindTgPassword, chats: bindTgChats, on: bindTgOn })[a.step]?.();
  tgPoll();
}
const tgDo = async (path, body, okMsg) => {
  const btn = $("#tgStep .btn-dark"); if (btn) { btn.disabled = true; btn.dataset.t = btn.innerHTML; btn.innerHTML = "Kutilmoqda"; }
  try {
    const st = await api(path, { json: body || {} });
    TG.data.account = st; TG.chats = null;
    if (okMsg) toast(okMsg, "check");
    drawTelegram();
  } catch (e) { toast(esc(e.message), "danger"); if (btn) { btn.disabled = false; btn.innerHTML = btn.dataset.t; } }
};

function tgStepStart() {
  return `<p>Tavsiya: ish uchun alohida Telegram akkaunt oching va uni kuzatiladigan guruhlarga oddiy a'zo qilib qo'shing. Shaxsiy akkaunt kerak emas.</p>
    <ol class="tg-howto"><li><b>my.telegram.org</b> ga shu akkaunt raqami bilan kiring</li><li><b>API development tools</b> bo'limida ilova yarating (nomi: Puls)</li><li>Chiqqan <b>App api_id</b> va <b>App api_hash</b> ni pastga yozing</li></ol>
    <div class="bd-2"><div class="field"><label for="tgId">API ID</label><input id="tgId" inputmode="numeric" autocomplete="off" placeholder="1234567"></div>
      <div class="field"><label for="tgHash">API hash</label><input id="tgHash" autocomplete="off" spellcheck="false" placeholder="32 belgili kalit"></div></div>
    <div class="field"><label for="tgPhone">Akkaunt telefon raqami</label><input id="tgPhone" inputmode="tel" autocomplete="off" placeholder="+998 90 123 45 67"></div>
    <button class="btn btn-dark" id="tgGo">${I("send")}Kod yuborish</button>`;
}
function bindTgStart() {
  $("#tgId").focus();
  $("#tgGo").onclick = () => {
    const id = +$("#tgId").value.trim(), hash = $("#tgHash").value.trim(), phone = $("#tgPhone").value.trim();
    if (!id || hash.length < 20 || phone.replace(/\D/g, "").length < 9) { toast("API ID, API hash va raqamni to'liq yozing", "info"); return; }
    tgDo("api/telegram/login", { api_id: id, api_hash: hash, phone });
  };
}
function tgStepCode(a) {
  return `<p>Telegram ilovasiga kod keldi (${esc(a.phone || "")}). Kodni shu yerga yozing.</p>
    <div class="field"><label for="tgCode">Kod</label><input id="tgCode" inputmode="numeric" autocomplete="one-time-code" maxlength="8" placeholder="12345"></div>
    <div class="tg-acts"><button class="btn btn-ghost" id="tgBack">Ortga</button><button class="btn btn-dark" id="tgGo">${I("check")}Tasdiqlash</button></div>`;
}
function bindTgCode() {
  $("#tgCode").focus();
  $("#tgCode").onkeydown = (e) => { if (e.key === "Enter") $("#tgGo").click(); };
  $("#tgGo").onclick = () => tgDo("api/telegram/code", { code: $("#tgCode").value });
  $("#tgBack").onclick = () => tgDo("api/telegram/logout");
}
function tgStepPassword() {
  return `<p>Akkauntda ikki bosqichli himoya bor. Uning parolini yozing: parol faqat Telegramga yuboriladi, hech qayerda saqlanmaydi.</p>
    <div class="field"><label for="tgPw">Ikki bosqichli parol</label><input id="tgPw" type="password" autocomplete="off"></div>
    <div class="tg-acts"><button class="btn btn-ghost" id="tgBack">Ortga</button><button class="btn btn-dark" id="tgGo">${I("lock")}Kirish</button></div>`;
}
function bindTgPassword() {
  $("#tgPw").focus();
  $("#tgPw").onkeydown = (e) => { if (e.key === "Enter") $("#tgGo").click(); };
  $("#tgGo").onclick = () => tgDo("api/telegram/password", { password: $("#tgPw").value });
  $("#tgBack").onclick = () => tgDo("api/telegram/logout");
}
function tgStepChats(a) {
  return `<p>Ulandi: <b>${esc(a.me?.name || "")}</b>${a.me?.username ? " (@" + esc(a.me.username) + ")" : ""}. Qaysi guruhlar kuzatilsin?</p>
    <label class="ctl bd-search wide">${I("search")}<input id="tgQ" placeholder="Guruhni qidirish" autocomplete="off"></label>
    <div class="tg-chats" id="tgChats"><div class="sk" style="height:160px"></div></div>
    <div class="field" style="margin-top:12px"><label>Tarix qancha oldindan yuklansin</label>
      <div class="seg" id="tgDays">${[[30, "30 kun"], [90, "3 oy"], [365, "1 yil"], [1095, "3 yil"]].map(([v, t]) => `<button data-d="${v}" aria-pressed="${TG.days === v}">${t}</button>`).join("")}</div></div>
    <p class="acc-hint">Eski hisobotlar ham bazaga tushadi: yangi hisobot ular bilan solishtiriladi, eski ishni qayta yozish shunda ko'rinadi.</p>
    <div class="tg-acts"><button class="btn btn-ghost" id="tgOff">Uzish</button><button class="btn btn-dark" id="tgGo">${I("check")}Kuzatishni boshlash</button></div>`;
}
async function bindTgChats() {
  const draw = () => {
    const q = TG.q.toLowerCase();
    const list = (TG.chats || []).filter((c) => !q || c.title.toLowerCase().includes(q));
    $("#tgChats").innerHTML = list.map((c) => `<label class="acc-proj"><input type="checkbox" data-cid="${c.id}" ${TG.picked.has(c.id) ? "checked" : ""}><span>${esc(c.title)}</span>${c.members ? `<small>${c.members} a'zo</small>` : ""}</label>`).join("")
      || emptyBox(TG.chats?.length ? "Topilmadi" : "Akkaunt hali hech qaysi guruhda yo'q: avval guruhlarga qo'shing", "people");
    $$("[data-cid]").forEach((c) => (c.onchange = () => { c.checked ? TG.picked.add(+c.dataset.cid) : TG.picked.delete(+c.dataset.cid); }));
  };
  $("#tgQ").oninput = (e) => { TG.q = e.target.value; draw(); };
  $$("#tgDays [data-d]").forEach((b) => (b.onclick = () => { TG.days = +b.dataset.d; $$("#tgDays [data-d]").forEach((x) => x.setAttribute("aria-pressed", x === b)); }));
  $("#tgOff").onclick = () => tgDo("api/telegram/logout", null, "Akkaunt uzildi");
  $("#tgGo").onclick = () => {
    if (!TG.picked.size) { toast("Kamida bitta guruhni belgilang", "info"); return; }
    tgDo("api/telegram/chats", { ids: [...TG.picked], days: TG.days }, "Kuzatish boshlandi, tarix fonda yuklanmoqda");
  };
  try { TG.chats = (await api("api/telegram/chats")).chats; } catch (e) { toast(esc(e.message), "danger"); TG.chats = []; }
  TG.chats.filter((c) => c.selected).forEach((c) => TG.picked.add(c.id));
  draw();
}
function tgStepOn(a) {
  const h = a.history || {};
  return `<p>Ulangan: <b>${esc(a.me?.name || "")}</b>${a.me?.username ? " (@" + esc(a.me.username) + ")" : ""}. ${a.chats.length} ta guruh kuzatilmoqda${a.last ? `, oxirgi xabar ${ago(a.last)}` : ""}.</p>
    <div class="tg-list">${a.chats.map((c) => { const x = h[String(c.id)];
      return `<div class="tg-row"><span>${esc(c.title)}</span><small>${x ? (x.done ? (x.error ? "Tarix yuklanmadi: " + esc(x.error) : `Tarix yuklandi: ${x.read} xabar, ${x.added} tasi yangi`) : `Tarix yuklanmoqda: ${x.read} xabar o'qildi`) : "Kuzatilmoqda"}</small></div>`; }).join("")}</div>
    <div class="tg-acts"><button class="btn btn-ghost danger" id="tgOff">${I("logout")}Uzish</button><button class="btn btn-line" id="tgEdit">${I("pen")}Guruhlarni o'zgartirish</button></div>`;
}
function bindTgOn() {
  $("#tgEdit").onclick = () => { TG.data.account.step = "chats"; TG.picked = new Set(TG.data.account.chats.map((c) => c.id)); drawTelegram(); };
  $("#tgOff").onclick = () => {
    openModal("Akkauntni uzish", `<p class="bd-confirm">Akkaunt Puls'dan chiqadi va guruhlarni kuzatish to'xtaydi. Yig'ilgan hisobotlar bazada qoladi. Bot ishlashda davom etadi.</p>`,
      `<button class="btn btn-ghost" id="tgNo">Ortga</button><button class="btn btn-dark danger" id="tgYes">${I("logout")}Uzish</button>`);
    $("#tgNo").onclick = () => drawTelegram();
    $("#tgYes").onclick = async () => { try { TG.data.account = await api("api/telegram/logout", { json: {} }); toast("Akkaunt uzildi", "check"); drawTelegram(); } catch (e) { toast(esc(e.message), "danger"); } };
  };
}

/* ================= ishga tushirish ================= */
function skeleton() {
  const el = $(".view.on") || $("#v-holat");
  el.innerHTML = `<div class="ph"><div><div class="sk" style="height:32px;width:220px"></div><div class="sk" style="height:14px;width:300px;margin-top:10px"></div></div></div>
    <div class="sk" style="height:118px"></div>
    <div class="hl-grid" style="margin-top:24px"><div class="sk" style="height:420px"></div><div class="sk" style="height:420px"></div></div>`;
}
(async function init() {
  readHash();
  buildNav();
  initMenu();
  go(S.tab);
  skeleton();
  try { S.meta = await api("api/meta"); } catch (e) { return; }
  // Dam olish kuni "Kunlik holat" bo'sh ko'rinmasin: sana tanlanmagan bo'lsa oxirgi ish kuni ochiladi
  const today = todayIso();
  if (!S.asof && S.period === "day" && isWeekend(today) && ["holat", "jamoa"].includes(S.tab)) {
    S.asof = workdayShift(today, -1); S.asofAuto = true;
  }
  applyRole();
  drawScope();
  $("#scopeSel").addEventListener("change", (e) => setDept(e.target.value));
  await load();
  try { S.ui = (await api("api/version")).ui; } catch (e) {}
  startStream();
  let agWas = null;
  try { agWas = localStorage.getItem("puls-ag-open"); } catch (e) { /* xotira yopiq */ }
  if (agWas && innerWidth >= 1280) { agOpen.quiet = true; agOpen(); agOpen.quiet = false; }
  if (S.open.startsWith("p:")) openPerson(S.open.slice(2));
  else if (S.open.startsWith("j:")) { const id = S.open.slice(2); S.open = ""; openProject(id); }
  else if (S.open.startsWith("a:")) { const x = S.data.decisions[+S.open.slice(2)]; S.open = ""; writeHash(); if (x && x.action) openAction(x.action); }
  else if (S.open === "tm") { S.open = ""; writeHash(); const b = $("[data-tm]", $(".view.on")); if (b) toggleTM(b); }
  addEventListener("hashchange", () => {
    const t = S.tab, d = S.dept, was = [S.period, S.start, S.end, S.chat, S.asof].join("|");
    readHash();
    if (d !== S.dept) setDept(S.dept);
    else if (was !== [S.period, S.start, S.end, S.chat, S.asof].join("|")) load();
    if (t !== S.tab || S.sec) go(S.tab);
  });
})();

/* ================= 2-variant: "Jamoa" — bosh sahifa har bir xodimga qurilgan ================= */
// Rahbar raqamga emas, odamga qaraydi: bir gapli xulosa, uni kutayotgan masalalar, keyin butun jamoa — istisnolar tepada
// (eski ishni qayta yozgan, asosan mayda ish, yozmagan), har qatorda shu kuni nima yozgani, odatiga nisbatan va 14 kunlik izi.
const TM = { day: "", q: "", f: "", dept: "", sort: "diqqat", rep: null, repKey: "", cur: -1 };
const WT_WORD = { 1: "Mayda", 2: "Kichik", 3: "O'rta", 4: "Katta", 5: "Juda katta" };
const isRep = (i) => i.dup_kind === "takror" || i.dup_kind === "nusxa";
const capFirst = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
function dayWord(day, today) {
  if (day === today) return "bugun";
  if (day === isoDay(new Date(parseDay(today) - 864e5))) return "kecha";
  const d = parseDay(day);
  return WEEK[d.getDay()] + ", " + uzDate(d);
}
function whenWord(ts, today) {  // "kecha 18:20", "bugun 09:05", "12-oktyabr"
  if (!ts) return "";
  const day = ts.slice(0, 10), w = dayWord(day, today);
  const t = ts.slice(11, 16);
  return (w === "bugun" || w === "kecha") ? w + " " + t : uzDate(parseDay(day));
}
async function tmReports(day) {
  const key = day + "|" + S.version + "|" + S.dept;
  if (TM.repKey === key && TM.rep) return TM.rep;
  const r = await api("api/reports?day=" + day);
  TM.rep = r; TM.repKey = key;
  return r;
}
async function renderTeam(d) {
  const el = $("#v-jamoa");
  const today = d.now.slice(0, 10), day = TM.day || today;  // o'tgan kun tanlangan bo'lsa d.now o'sha kun oxiri
  if (!el.innerHTML.trim()) el.innerHTML = `<div class="sk" style="height:40px;width:40%"></div><div class="sk" style="height:420px;margin-top:20px"></div>`;
  let rep = null;
  try { rep = await tmReports(day); } catch (e) { toast(esc(e.message), "danger"); }
  if (S.tab !== "jamoa") return;
  drawTeam(d, rep, day, today);
}
function tmRows(d, rep, day, today) {
  const by = Object.fromEntries((rep?.people || []).map((p) => [p.name, p]));
  return d.people.map((p) => {
    const r = by[p.name], items = r ? r.items : [];
    const real = items.filter((i) => !isRep(i) && !i.deleted_at);
    const reps = items.filter(isRep), small = real.filter((i) => i.weight === 1).length;
    const vol = real.reduce((a, i) => a + (i.weight || 2), 0);
    let cmp = "";
    if (items.length && p.usual_day && day === today) cmp = vol < 0.6 * p.usual_day ? "odatdagidan kam" : vol > 1.6 * p.usual_day ? "odatdagidan ko'p" : "";
    const kind = reps.length ? "rep" : !items.length ? "none" : items.length >= 4 && small / items.length >= 0.6 ? "small" : "ok";
    return { p, items, real, reps, small, kind, cmp };
  });
}
const TM_FILTERS = {
  "": ["Hammasi", () => true],
  none: ["Yozmadi", (r) => r.kind === "none"],
  rep: ["Qayta yozdi", (r) => r.reps.length > 0],
  small: ["Mayda ish", (r) => r.kind === "small"],
  up: ["O'sdi", (r) => ["ancha_osdi", "osdi"].includes(r.p.growth?.verdict)],
  down: ["Pasaydi", (r) => r.p.growth?.verdict === "pasaydi"],
  new: ["Yangi", (r) => r.p.new && r.p.evidence],
};
function tmStrip(p, day) {
  const days = p.days14 || [], max = Math.max(1, ...days.map((x) => x[1]));
  return `<span class="jr-strip" aria-hidden="true">${days.map(([k, v, n]) => {
    const we = [0, 6].includes(parseDay(k).getDay());
    return `<i class="${we ? "we" : ""} ${k === day ? "on" : ""} ${n ? "" : "z"}" style="--h:${n ? Math.max(18, Math.round((100 * v) / max)) : 6}%" title="${uzDate(parseDay(k))}: ${n ? n + " ta ish" : "yozmagan"}"></i>`;
  }).join("")}</span>`;
}
function tmRow(r, day, today) {
  const p = r.p, it = r.real[0] || r.items[0];
  const final = day < today || (rep_final(day, today));
  let text;
  if (r.reps.length) {
    const x = r.reps[0];
    text = `<span class="jr-line rep"><b>Eski ish:</b> «${esc(x.title)}»<em>${x.old_done_at ? ", " + uzDate(parseTs(x.old_done_at)) + "da ham yozilgan" : ""}</em></span>`;
  } else if (it) {
    text = `<span class="jr-line"><span class="wtw w${it.weight || 0}">${it.weight ? WT_WORD[it.weight] : "Baholanmoqda"}</span>${esc(it.title)}${r.items.length > 1 ? `<em>, yana ${r.items.length - 1} ta ish</em>` : ""}</span>`;
  } else {
    const we = [0, 6].includes(parseDay(day).getDay());
    text = `<span class="jr-line none">${we ? "Dam olish kuni" : final ? "Yozmadi" : "Hali yozmadi"}${p.last_done ? `<em>, oxirgi hisobot ${esc(whenWord(p.last_done, today))}</em>` : ""}</span>`;
  }
  const tags = [];
  if (r.reps.length) tags.push(`<span class="jt risk">${r.reps.length} ta qayta yozilgan</span>`);
  if (r.kind === "small") tags.push(`<span class="jt warn">ko'pi mayda</span>`);
  if (r.cmp) tags.push(`<span class="jt">${r.cmp}</span>`);
  if (p.growth && ["ancha_osdi", "osdi"].includes(p.growth.verdict)) tags.push(`<span class="jt ok" title="${esc(p.growth.why.join(", "))}">${esc(p.growth.label)}</span>`);
  if (p.growth?.verdict === "pasaydi") tags.push(`<span class="jt warn" title="${esc(p.growth.why.join(", "))}">Pasaydi</span>`);
  if (p.new && p.evidence) tags.push(`<span class="jt">Yangi xodim</span>`);
  return `<div class="jr k-${r.kind}" data-person="${esc(p.name)}" tabindex="-1">
    <span class="jr-who">${ava(p.name, p.department, p.state)}<span><b>${esc(p.name)}</b><small>${esc(p.department)}${p.rank ? `, ${p.rank}-o'rin` : ""}${mv(p)}</small></span></span>
    ${text}
    <span class="jr-tags">${tags.join("")}</span>
    ${tmStrip(p, day)}
  </div>`;
}
const rep_final = (day, today) => day < today || +(S.data?.now || "").slice(11, 13) >= 18;
function drawTeam(d, rep, day, today) {
  const el = $("#v-jamoa"), rows = tmRows(d, rep, day, today), q = fold(TM.q);
  const inDept = rows.filter((r) => !TM.dept || r.p.department === TM.dept);
  const cnt = (k) => inDept.filter(TM_FILTERS[k][1]).length;
  const list = inDept.filter((r) => TM_FILTERS[TM.f][1](r) && (!q || fold(r.p.name).includes(q)));
  const byRank = (a, b) => (a.p.rank ?? 1e9) - (b.p.rank ?? 1e9) || a.p.name.localeCompare(b.p.name);
  const wrote = inDept.filter((r) => r.items.length).length, repN = inDept.filter((r) => r.reps.length).length;
  const final = rep_final(day, today), dw = dayWord(day, todayIso()), we = [0, 6].includes(parseDay(day).getDay());  // yozuv haqiqiy bugunga nisbatan
  const decs = d.decisions.filter((x) => !x.good), good = d.decisions.filter((x) => x.good);
  // bir gapli xulosa: rahbar birinchi qatordayoq holatni biladi
  const sum = !inDept.length ? "Guruhlarda hali hech kim hisobot yozmagan. Botni ish guruhiga qo'shib, admin qiling: xodimlar yozishi bilan shu yerda paydo bo'ladi."
    : `${capFirst(dw)} ${inDept.length} kishidan <b>${wrote}</b> tasi yozdi${we ? "" : `, <a href="#" data-tmf="none">${inDept.length - wrote} kishi ${final ? "yozmadi" : "hali yozmadi"}</a>`}`
    + (repN ? `, <a href="#" data-tmf="rep" class="risk">${repN} kishi eski ishni qayta yozdi</a>` : "") + "."
    + (decs.length && day === today ? ` ${decs.length} ta masala sizni kutyapti.` : "");
  const groups = TM.sort !== "diqqat" ? [["", list.sort(TM.sort === "ism" ? (a, b) => a.p.name.localeCompare(b.p.name) : byRank)]]
    : [["Eski ishni qayta yozdi", list.filter((r) => r.kind === "rep").sort(byRank)],
       ["Asosan mayda ish", list.filter((r) => r.kind === "small").sort(byRank)],
       [we ? "Dam olish kuni yozmaganlar" : final ? "Yozmadi" : "Hali yozmadi", list.filter((r) => r.kind === "none").sort(byRank)],
       ["Yozdi", list.filter((r) => r.kind === "ok").sort(byRank)]];
  const chip = (k) => { const n = cnt(k); return `<button class="chip ${["none", "rep"].includes(k) && n ? "alarm" : ""}" data-tmf="${k}" aria-pressed="${TM.f === k}" ${n || TM.f === k ? "" : "disabled"}>${TM_FILTERS[k][0]}<b>${n}</b></button>`; };
  const depts = [...new Set(d.people.map((p) => p.department))].sort();
  const slip = d.projects.filter((x) => x.level >= 3);
  const focus = document.activeElement?.id === "tmQ";
  el.innerHTML = `<div class="ph jm-ph"><div><h1>Xodimlar</h1>
        <div class="jm-day"><button class="icon-btn" data-tmd="-1" aria-label="Oldingi kun">${I("arrow-left")}</button>
          <label class="jm-date">${I("calendar")}<span>${capFirst(dw)}${day !== today && dw.indexOf(",") < 0 ? ", " + uzDate(parseDay(day)) : ""}</span><input type="date" id="tmDate" value="${day}" max="${today}" aria-label="Kun"></label>
          <button class="icon-btn" data-tmd="1" aria-label="Keyingi kun" ${day >= today ? "disabled" : ""}>${I("arrow")}</button>
          ${day !== today ? `<button class="btn btn-ghost" data-tmd="0">Bugunga qaytish</button>` : ""}</div></div>
      <div class="filters"><a class="icon-btn" href="api/export.xlsx?${query({ view: "people" })}" title="Excelga yuklab olish" aria-label="Excelga yuklab olish">${I("download")}</a></div></div>
    <p class="jm-sum">${sum}</p>
    <form class="jm-ask" id="tmAsk">${I("stars")}<input id="tmAskQ" placeholder="Yordamchidan so'rang: kim avvalgiga qaraganda ancha o'sdi?" autocomplete="off" maxlength="600"><kbd>/</kbd></form>
    ${unlinkedBar(d)}
    <div class="jm-cols"><div class="jm-main">
    <section class="card jm-card"><div class="jm-tools">
        <label class="searchbox">${I("search")}<input id="tmQ" type="search" placeholder="Xodimni qidirish" value="${esc(TM.q)}" autocomplete="off"></label>
        ${!S.dept && depts.length > 1 ? `<select class="ctl" id="tmDept" aria-label="Bo'lim"><option value="">Hamma bo'limlar</option>${depts.map((x) => `<option ${TM.dept === x ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>` : ""}
        <div class="seg jm-sort" role="group" aria-label="Tartib"><button data-tms="diqqat" aria-pressed="${TM.sort === "diqqat"}">Avval muammolar</button><button data-tms="reyting" aria-pressed="${TM.sort === "reyting"}">Reyting</button><button data-tms="ism" aria-pressed="${TM.sort === "ism"}">Ism</button></div>
        <div class="legend jm-chips">${Object.keys(TM_FILTERS).map(chip).join("")}</div>
      </div>
      ${groups.filter((g) => g[1].length).map(([title, rs]) => `<div class="jm-g">${title ? `<div class="jm-gh"><b>${title}</b><span>${rs.length}</span>
          ${title.includes("ozmadi") && !we && day >= isoDay(new Date(parseDay(today) - 864e5)) && can("decide") ? `<button class="btn btn-line sm" data-remind>${I("bell")}Hammasiga eslatish</button>` : ""}</div>` : ""}
        ${rs.map((r) => tmRow(r, day, today)).join("")}</div>`).join("") || `<div class="jm-empty">${emptyBox(q ? "Bu ismli xodim yo'q" : "Bu filtrga mos xodim yo'q", q ? "search" : "check")}</div>`}
    </section></div>
    <aside class="jm-side">${day === today && !S.asof ? tmInbox(decs, good) : ""}
    ${slip.length ? `<section class="card jm-slip"><div class="ch"><h3>Muddatdan orqada qolayotgan loyihalar</h3><span class="count">${slip.length}</span>
        <div class="right"><button class="more-link" data-go="loyihalar">Hamma loyihalar</button></div></div>
      <div class="cb">${slip.map((x) => `<div class="sl-row" data-project="${x.id}"><span class="dot lv${x.level}"></span><b>${esc(x.name)}</b><span>${esc(x.risks[0]?.text || x.status)}</span><em>${x.progress}%</em></div>`).join("")}</div></section>` : ""}
    </aside></div>`;
  bindCommon(el);
  $$("[data-tmf]", el).forEach((b) => (b.onclick = (e) => { e.preventDefault(); TM.f = TM.f === b.dataset.tmf ? "" : b.dataset.tmf; drawTeam(d, rep, day, today); }));
  $$("[data-tms]", el).forEach((b) => (b.onclick = () => { TM.sort = b.dataset.tms; drawTeam(d, rep, day, today); }));
  $$("[data-tmd]", el).forEach((b) => (b.onclick = () => tmShift(+b.dataset.tmd)));
  $("#tmDate").onchange = (e) => { if (e.target.value) { TM.day = e.target.value >= today ? "" : e.target.value; renderTeam(S.data); } };
  $("#tmDept")?.addEventListener("change", (e) => { TM.dept = e.target.value; drawTeam(d, rep, day, today); });
  $("#tmAsk").onsubmit = (e) => { e.preventDefault(); const v = $("#tmAskQ").value.trim(); if (v) { $("#tmAskQ").value = ""; agOpen(v); } };
  $("[data-remind]", el)?.addEventListener("click", () => tmRemind(inDept.filter((r) => r.kind === "none").map((r) => r.p.name)));
  $("#ulOpen")?.addEventListener("click", openLinks);
  $$("[data-snooze]", el).forEach((b) => (b.onclick = (e) => { e.stopPropagation(); tmSnooze(b.dataset.snooze); }));
  const qi = $("#tmQ");
  qi.oninput = () => { TM.q = qi.value; clearTimeout(qi._t); qi._t = setTimeout(() => drawTeam(d, rep, day, today), 140); };
  if (focus) { qi.focus(); qi.setSelectionRange(qi.value.length, qi.value.length); }
  TM.cur = -1;
}
function tmInbox(decs, good) {
  if (!decs.length && !good.length) return `<div class="ib-done">${I("check")}<span>Hammasi hal qilindi: sizni kutayotgan masala yo'q</span></div>`;
  const row = (x) => `<div class="ib-row lv${x.level} ${x.good ? "good" : ""}" ${x.target.type === "project" ? `data-project="${x.target.id}"` : `data-person="${esc(x.target.name)}"`}>
      <span class="ic">${I(x.icon)}</span><div class="ib-t"><b>${esc(x.title)}</b><span>${esc(x.fact)}</span></div>
      <div class="ib-a">${x.action ? `<button class="btn ${x.good ? "btn-line" : "btn-dark"} sm" data-act='${esc(JSON.stringify(x.action))}'>${I(ACT_ICON[x.action.type] || "check")}<span>${esc(x.button)}</span></button>` : ""}
        <button class="btn btn-ghost sm" data-snooze="${esc(x.id)}" title="Bugun boshqa ko'rsatilmaydi">Keyinroq</button></div></div>`;
  const lim = innerWidth < 1280 ? 2 : 5;  // telefonda navbat jamoa ro'yxatini pastga surib yubormasin
  const shown = S.showAllDecs ? decs : decs.slice(0, lim);
  return `<section class="ib"><div class="ib-h"><h2>Sizni kutmoqda</h2><span>${decs.length}</span>
      ${decs.length > lim ? `<button class="more-link" data-alldec>${S.showAllDecs ? "Kamroq" : `Hammasi (${decs.length})`}</button>` : ""}</div>
    ${shown.map(row).join("")}
    ${good.length ? `<div class="ib-sub">Yaxshi xabarlar<span>${good.length}</span>${good.length > 3 ? `<button class="more-link" data-tmf="up">Hammasi</button>` : ""}</div>${good.slice(0, S.showAllDecs ? 3 : Math.min(3, lim)).map(row).join("")}` : ""}</section>`;
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("#v-jamoa [data-alldec]");
  if (b) { S.showAllDecs = !S.showAllDecs; renderTeam(S.data); }
});
function tmShift(n) {
  const today = S.data.now.slice(0, 10);
  if (n === 0) { TM.day = ""; renderTeam(S.data); return; }
  const cur = parseDay(TM.day || today), next = isoDay(new Date(cur.getTime() + n * 864e5));
  if (next > today) return;
  TM.day = next === today ? "" : next;
  renderTeam(S.data);
}
async function tmSnooze(id, undo) {
  try { await api("api/decisions/snooze", { json: { id, undo: !!undo } }); } catch (e) { toast(esc(e.message), "danger"); return; }
  if (!undo) toastUndo("Bugunga yashirildi", () => tmSnooze(id, true));
  load(true);
}
function toastUndo(text, undo) {
  const t = document.createElement("div");
  t.className = "toast undo";
  t.innerHTML = I("check") + `<span>${esc(text)}</span><button type="button">Qaytarish</button>`;
  $("#toasts").appendChild(t);
  const close = () => { t.classList.add("out"); setTimeout(() => t.remove(), 350); };
  $("button", t).onclick = () => { close(); undo(); };
  setTimeout(close, 6000);
}
function tmRemind(names) {
  if (!names.length) return;
  openModal(`${names.length} kishiga eslatma`, `<p class="mb-p">Botga ulanganlarga shaxsan, qolganlarga ish guruhida qisqa eslatma ketadi.</p>
    <div class="checks">${names.map((n) => `<label><input type="checkbox" data-rm="${esc(n)}" checked>${esc(n)}</label>`).join("")}</div>`,
    `<button class="btn btn-ghost" data-close>Bekor qilish</button><button class="btn btn-dark" id="rmGo">${I("send")}Eslatma yuborish</button>`);
  $("#rmGo").onclick = async () => {
    const pick = $$("[data-rm]").filter((x) => x.checked).map((x) => x.dataset.rm);
    if (!pick.length) return;
    const b = $("#rmGo"); b.disabled = true;
    let ok = 0;
    for (const [i, name] of pick.entries()) {
      b.innerHTML = `${I("send")}Yuborilyapti ${i + 1}/${pick.length}`;
      try { await api("api/actions/execute", { json: { action: { type: "ping_person", name } } }); ok++; } catch (e) { /* bitta xato boshqalarni to'xtatmaydi */ }
    }
    closeModal();
    toast(`${ok} kishiga eslatma yuborildi${ok < pick.length ? `, ${pick.length - ok} tasiga ketmadi` : ""}`, ok ? "send" : "danger");
    load(true);
  };
}
function tmKey(e) {
  const rows = $$("#v-jamoa .jr");
  if (!rows.length) return false;
  if (e.key === "j" || e.key === "k" || e.key === "ArrowDown" || e.key === "ArrowUp") {
    const down = e.key === "j" || e.key === "ArrowDown";
    TM.cur = Math.max(0, Math.min(rows.length - 1, TM.cur + (down ? 1 : -1)));
    rows[TM.cur].focus(); rows[TM.cur].scrollIntoView({ block: "nearest" });
    return true;
  }
  if (e.key === "Enter" && document.activeElement?.classList.contains("jr")) { openPerson(document.activeElement.dataset.person); return true; }
  if (e.key === "ArrowLeft") { tmShift(-1); return true; }
  if (e.key === "ArrowRight") { tmShift(1); return true; }
  return false;
}

/* ================= 2-variant: xodim sahifasi — kunma-kun hisobotlari, dalillari bilan ================= */
const PP = { tab: "kunlar", name: "" };
async function openPerson(name) {
  S.open = "p:" + name; writeHash();
  PP.name = name;
  openDrawer(skelHead());
  $("#drawer").classList.add("wide");
  let days, growth;
  try {
    [days, growth] = await Promise.all([api("api/person/days?" + new URLSearchParams({ name, days: 30 })),
      api("api/person/growth?" + new URLSearchParams({ name, days: 90 })).catch(() => null)]);
  } catch (e) { closeDrawer(); toast(esc(e.message), "danger"); return; }
  if (PP.name !== name) return;
  const p = (S.data?.people || []).find((x) => x.name === name) || { name, department: S.data?.head?.department || "", open_tasks: [], q28: {}, traits: [] };
  const today = S.data.now.slice(0, 10);
  const s = [];
  if (p.week_items != null) s.push(`Bu hafta ${p.week_items} ta ish yozdi${p.usual_week != null ? `, odatda ${p.usual_week} ta` : ""}.`);
  if (p.growth && p.growth.verdict !== "barqaror") s.push(`${p.growth.label}: ${p.growth.why.join(", ")}.`);
  if (p.q28 && p.q28.items) s.push(p.q28.repeats ? `4 haftada ${p.q28.repeats} marta eski ishni qayta yozdi.` : "4 haftada eski ishni qayta yozmagan.");
  if (p.rank) s.push(`Jamoada ${p.rank}-o'rin${p.move ? (p.move > 0 ? `, bu hafta ${p.move} pog'ona ko'tarildi` : `, bu hafta ${-p.move} pog'ona tushdi`) : ""}${p.dept_rank_of > 1 ? `, bo'limida ${p.dept_rank}-o'rin` : ""}.`);
  if (p.state && p.state !== "ok" && p.state !== "idle") s.push(`${STATE[p.state].label}: ${p.fact}.`);
  const tabs = [["kunlar", "Hisobotlari"], ["osish", "O'sishi"], ["vazifa", "Vazifalari"], ["reyting", "Reytingi"]];
  $("#drawer .sheet").innerHTML = `
    <div class="sh-head">${ava(p.name, p.department, p.state, "lg")}
      <div style="min-width:0"><div class="name-row"><h2>${esc(p.name)}</h2>${can("people") && !S.asof ? `<button class="icon-btn name-edit" data-ppa="edit" title="Ism, bo'lim va holatini tahrirlash" aria-label="Tahrirlash">${I("pen")}</button>` : ""}</div>
        <div class="meta"><span>${esc(p.department || "")}</span>${p.username ? `<span>@${esc(p.username)}</span>` : ""}${p.dm === false ? `<span class="pill p-idle sm">Botga ulanmagan</span>` : ""}</div></div>
      <button class="icon-btn x" aria-label="Yopish">${I("close")}</button></div>
    <div class="sh-body xp">
      <p class="xp-sum">${s.map(esc).join(" ")}</p>
      ${S.asof || !can("decide") ? "" : `<div class="sh-acts">
        <button class="btn btn-dark" data-ppa="ping">${I("chat-dots")}Eslatma yuborish</button>
        <button class="btn btn-line" data-ppa="thank">${I("cup-star")}Rahmat aytish</button>
        ${p.open ? `<button class="btn btn-line" data-ppa="move">${I("transfer")}Vazifasini boshqaga berish</button>` : ""}
        ${p.dm === false && can("people") ? `<button class="btn btn-line" data-ppa="link">${I("copy")}Ulanish havolasini nusxalash</button>` : ""}
        ${can("people") ? `<button class="btn btn-line" data-ppa="edit">${I("pen")}Ma'lumotlari</button>` : ""}
        <button class="btn btn-ghost" data-ppa="ask">${I("stars")}Yordamchidan so'rash</button></div>`}
      ${ppStrip(days.days)}
      <div class="seg pp-tabs" role="tablist">${tabs.map(([k, t]) => `<button role="tab" data-ppt="${k}" aria-pressed="${PP.tab === k}">${t}</button>`).join("")}</div>
      <div id="ppBody"></div>
    </div>`;
  $("#drawer .x").onclick = closeDrawer;
  const draw = () => {
    $$("[data-ppt]").forEach((b) => b.setAttribute("aria-pressed", PP.tab === b.dataset.ppt));
    $("#ppBody").innerHTML = PP.tab === "kunlar" ? ppDays(days.days, today) : PP.tab === "osish" ? ppGrowth(growth) : PP.tab === "vazifa" ? ppTasks(p) : ppScore(p);
    bindCommon($("#ppBody"));
    $$("[data-notrep]").forEach((b) => (b.onclick = () => ppNotRepeat(+b.dataset.notrep, b.dataset.kind)));
    $$("[data-cplink]").forEach((b) => (b.onclick = () => copyText(b.dataset.cplink, "Havola nusxalandi")));
  };
  $$("[data-ppt]").forEach((b) => (b.onclick = () => { PP.tab = b.dataset.ppt; draw(); }));
  $$("[data-ppa]").forEach((b) => (b.onclick = () => {
    const a = b.dataset.ppa;
    if (a === "ping") openAction({ type: "ping_person", name: p.name });
    else if (a === "thank") openAction({ type: "thank_person", name: p.name, why: p.growth?.why?.[0] || "" });
    else if (a === "move") openMove(p);
    else if (a === "link") api("api/person/link?" + new URLSearchParams({ name: p.name })).then((c) => copyText(linkMsg(p.name, c.link), "Havola nusxalandi: xodimga yuboring"), (e) => toast(esc(e.message), "danger"));
    else if (a === "edit") openPersonEdit(p.name);
    else { agOpen(); const q = $("#agQ"); q.value = `${p.name}: `; q.focus(); }
  }));
  draw();
}
function ppStrip(days) {
  const list = days.slice().reverse(), max = Math.max(1, ...list.map((x) => x.items.reduce((a, i) => a + (isRep(i) ? 0 : i.weight || 2), 0)));
  return `<div class="xp-strip" aria-label="30 kun">${list.map((x) => {
    const v = x.items.reduce((a, i) => a + (isRep(i) ? 0 : i.weight || 2), 0);
    return `<i class="${x.workday ? "" : "we"} ${x.repeats ? "rep" : ""} ${x.count ? "" : "z"}" style="--h:${x.count ? Math.max(14, Math.round((100 * v) / max)) : 5}%" title="${uzDate(parseDay(x.day))}: ${x.count ? x.count + " ta ish" + (x.repeats ? ", " + x.repeats + " tasi qayta yozilgan" : "") : x.workday ? "yozmagan" : "dam olish kuni"}"></i>`;
  }).join("")}</div>`;
}
const tgA = (link, text = "Telegramda ochish") => (link ? `<a class="tga" href="${esc(link)}" target="_blank" rel="noopener">${I("send")}${text}</a><button type="button" class="icon-btn xs" data-cplink="${esc(link)}" title="Havolani nusxalash" aria-label="Havolani nusxalash">${I("copy")}</button>` : "");
function ppDays(days, today) {
  const out = days.filter((x) => x.count || x.workday).map((x) => {
    const dt = parseDay(x.day), head = `${capFirst(WEEK[dt.getDay()])}, ${uzDate(dt)}${x.day === today ? " (bugun)" : ""}`;
    if (!x.count) return `<div class="tl-day empty"><div class="tl-dh"><b>${head}</b><span>${x.day === today ? "Hali yozmadi" : "Yozmagan"}</span></div></div>`;
    return `<div class="tl-day"><div class="tl-dh"><b>${head}</b><span>${x.count} ta ish${x.repeats ? `, <em>${x.repeats} tasi qayta yozilgan</em>` : ""}</span></div>
      <ul>${x.items.map((i) => ppItem(i)).join("")}</ul></div>`;
  });
  return out.join("") || emptyBox("30 kunda hisobot yo'q", "doc");
}
function ppItem(i) {
  const rep = isRep(i);
  return `<li class="tl-it ${rep ? "rep" : ""} ${i.deleted_at ? "del" : ""}">
    <span class="wtw w${i.weight || 0}" title="${esc(i.wnote || "")}">${i.weight ? WT_WORD[i.weight] : "Baholanmoqda"}</span>
    <div class="tl-tx"><b>${esc(i.title)}</b>
      <small>${esc(i.project || "")}, ${i.done_at.slice(11, 16)}${i.deleted_at ? ", hisobot xabari o'chirilgan" : i.edited_at ? ", keyin o'zgartirilgan" : ""}${!rep && i.link ? " " + tgA(i.link, "Telegramda") : ""}</small>
      ${rep ? `<div class="dv">
        <div class="dv-r"><span>Oldin, ${i.old_done_at ? uzDate(parseTs(i.old_done_at)) : "?"}${i.dup_kind === "nusxa" && i.old_assignee ? `, ${esc(i.old_assignee)} yozgan` : ""}</span><q>${esc(i.old_title || "")}</q>${tgA(i.old_link)}</div>
        <div class="dv-r now"><span>Bu safar, ${uzDate(parseTs(i.done_at))}</span><q>${esc(i.title)}</q>${tgA(i.link)}</div>
        <div class="dv-a"><button class="btn btn-line sm" data-rep="${i.id}">${I("doc")}Xabarlarni solishtirish</button>${can("decide") ? `<button class="btn btn-ghost sm" data-notrep="${i.id}" data-kind="${i.dup_kind}">Bu takror emas</button>` : ""}</div>
      </div>` : ""}
      ${i.dup_kind === "rad" ? `<small class="dv-ok">Rahbar: takror emas</small>` : ""}
    </div></li>`;
}
async function ppNotRepeat(id, kind, undo) {
  try { await api("api/task/repeat", { json: { task_id: id, kind: undo ? kind : "rad" } }); } catch (e) { toast(esc(e.message), "danger"); return; }
  if (!undo) toastUndo("Takror belgisi olib tashlandi, ish reytingga qaytdi", () => ppNotRepeat(id, kind, true));
  await load(true);
  if (PP.name) openPerson(PP.name);
}
function ppGrowth(g) {
  if (!g || !g.davrlar?.length) return emptyBox("O'sishni ko'rish uchun ma'lumot hali kam", "chart");
  const rows = g.davrlar, max = Math.max(0.1, ...rows.map((r) => r.kunlik_hajm));
  const cmp = g.solishtirish_birinchi_va_ikkinchi_yarmi || {};
  const line = (k, label, fmt = (v) => nf(v, 1), better = 1) => {
    const x = cmp[k]; if (!x || x.oldin == null || x.keyin == null) return "";
    const d = x.keyin - x.oldin, good = d * better > 0;
    return `<div class="gr-c"><span>${label}</span><b>${fmt(x.oldin)} → ${fmt(x.keyin)}</b><em class="${d === 0 ? "" : good ? "up" : "down"}">${d === 0 ? "o'zgarmadi" : good ? "yaxshilandi" : "yomonlashdi"}</em></div>`;
  };
  return `<div class="gr-cmp">${line("kunlik_hajm", "Kunlik ish hajmi")}${line("ortacha_ogirlik", "O'rtacha og'irlik (5 dan)")}
      ${line("qayta_yozilgan", "Qayta yozilgan ishlar", (v) => nf(v), -1)}${line("mayda_foiz", "Mayda ishlar", (v) => nf(v) + "%", -1)}${line("muntazamlik_foiz", "Yozgan kunlari", (v) => nf(v) + "%")}</div>
    <div class="gr-bars">${rows.map((r) => `<div class="gr-b" title="${r.ishlar} ta ish, ${r.yozgan_kunlari}/${r.ish_kunlari} kun${r.qayta_yozilgan ? ", " + r.qayta_yozilgan + " qayta yozilgan" : ""}">
        <i style="--h:${Math.max(4, Math.round((100 * r.kunlik_hajm) / max))}%" class="${r.qayta_yozilgan ? "rep" : ""}"></i>
        <span>${g.davr_turi === "hafta" ? uzDate(parseDay(r.davr)) : r.davr.slice(5) + "-oy"}</span></div>`).join("")}</div>
    <div class="gr-note">${g.davr_turi === "hafta" ? "Haftalar" : "Oylar"} bo'yicha kunlik ish hajmi; qizil — shu davrda eski ish qayta yozilgan.</div>`;
}
function ppTasks(p) {
  return `<div class="xp-tasks">${(p.open_tasks || []).map((t) => `<div class="task"><span>${esc(t.title)}</span>${dueTag(t)}<small>${esc(t.project || "")}, ${clock(t.created_at)}${t.giver ? `, ${esc(first(t.giver))} berdi` : ""}</small></div>`).join("") || emptyBox("Ochiq vazifa yo'q")}</div>`;
}
function ppScore(p) {
  const sp = p.score_parts;
  if (!sp) return emptyBox("Reyting uchun ma'lumot hali kam", "chart");
  const W = S.data.weights || { completion: 30, output: 30, speed: 15, regular: 15, fresh: 10 };
  const parts = [["Vazifani bajarish", sp.completion, W.completion], ["Ish hajmi", sp.output, W.output], ["Tezlik", sp.speed, W.speed],
    ["Muntazam hisobot", sp.regular, W.regular], ["Eski vazifa yo'qligi", sp.fresh, W.fresh]].filter((r) => r[1] != null && r[2]);
  return `<div class="scorebox">${scoreRing(p.score, "xl", p)}<div><b style="font:640 17px var(--display)">${p.rank ? `${p.rank}-o'rin, ${p.rank_of} xodim ichida` : "Reyting hali yo'q"}${mv(p)}</b>
      <div style="font-size:13px;color:var(--ink-3);margin-top:2px">${esc(p.grade || "")}</div></div></div>
    <div class="sb" style="margin-top:16px">${parts.map((r) => `<div class="sb-row"><span>${r[0]}</span><b>${r[1]} / ${r[2]}</b><div class="bar"><i style="width:${Math.round((100 * r[1]) / r[2])}%"></i></div></div>`).join("")}
      ${sp.penalty ? `<div class="sb-row pen"><span>Qayta yozilgan ish uchun</span><b>${sp.penalty}</b></div>` : ""}</div>`;
}

/* ================= Yordamchi agent: javob aniq bo'lguncha qadamma-qadam ishlaydi (Claude Code kabi) ================= */
// Jarayon ko'rinib turadi: agent fikri, har qadam (qaysi asbob, nima bilan — SQL bo'lsa so'rovning o'zi), natija qisqasi va
// ochiladigan ko'rinishi, javob tekshiruvi, sarflangan vaqt. Amallar (eslatma, rahmat, vazifa o'tkazish, muddat) faqat
// taklif: tugma bosilganda oldindan ko'rish oynasi ochiladi va rahbar tasdiqlaydi.
const AG = { turns: [], busy: false, ctrl: null, t0: 0, tick: null };
const AG_STARTERS = ["Kecha kim hisobot yozmadi?", "Kim avvalgiga qaraganda ancha o'sdi?", "Oxirgi 30 kunda eng og'ir ishlarni qilgan 10 kishi",
  "Kim eski ishni qayta yozyapti, misollar bilan?", "Qaysi loyiha muddatga ulgurmaydi va nega?"];
const AG_TOOL = { jamoa: "Jamoa", kun_hisoboti: "Kunlik hisobot", xodim: "Xodim", xodim_kunlari: "Kunma-kun hisobot", osish: "O'sish tahlili",
  qayta_yozilganlar: "Qayta yozilganlar", vazifalar: "Vazifalar", loyihalar: "Loyihalar", loyiha: "Loyiha", bolimlar: "Bo'limlar",
  qidir: "Qidiruv", sql: "Baza so'rovi", taklif: "Amal" };
const AG_VERBS = ["O'ylayapman", "Ma'lumot yig'yapman", "Solishtiryapman", "Hisoblayapman"];
try { AG.turns = JSON.parse(sessionStorage.getItem("puls-ag") || "[]"); } catch (e) { AG.turns = []; }
function agSave() { try { sessionStorage.setItem("puls-ag", JSON.stringify(AG.turns.slice(-12))); } catch (e) { /* xotira yopiq: suhbat sahifa yangilanguncha turadi */ } }

function agMount() {
  if ($("#ag")) return;
  const el = document.createElement("aside");
  el.id = "ag"; el.className = "yx"; el.setAttribute("aria-label", "Yordamchi"); el.setAttribute("aria-hidden", "true");
  el.innerHTML = `<div class="yx-grip" id="agGrip" role="separator" aria-orientation="vertical" aria-label="Yordamchi kengligi: tortib o'zgartiring" title="Tortib kengaytiring, ikki marta bosilsa odatiy kenglik" tabindex="0"></div>
    <div class="yx-h"><span class="yx-ic">${I("stars")}</span><b>Yordamchi</b>
      <button class="btn btn-ghost yx-new" id="agNew" title="Yangi suhbat">${I("refresh")}<span>Yangi suhbat</span></button>
      <button class="icon-btn sm" id="agMax" aria-label="Kattalashtirish" title="Kattalashtirish">${I("zoom-in")}</button>
      <button class="icon-btn" id="agX" aria-label="Yopish">${I("close")}</button></div>
    <div class="yx-body" id="agBody"></div>
    <div class="yx-status" id="agStatus" hidden></div>
    <form class="yx-f" id="agF"><textarea id="agQ" rows="1" placeholder="Savolingizni yozing" maxlength="600"></textarea>
      <button class="btn btn-dark" id="agGo" aria-label="Yuborish">${I("send")}</button></form>`;
  document.body.appendChild(el);
  $("#agX").onclick = agClose;
  $("#agNew").onclick = () => { if (AG.busy) AG.ctrl?.abort(); AG.turns = []; agSave(); agDraw(); $("#agQ").focus(); };
  agBindResize();
  const q = $("#agQ");
  q.addEventListener("input", () => { q.style.height = "auto"; q.style.height = Math.min(160, q.scrollHeight) + "px"; });
  q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#agF").requestSubmit(); } });
  $("#agF").onsubmit = (e) => { e.preventDefault(); if (AG.busy) { AG.ctrl?.abort(); return; } agAsk(q.value); };
  $("#agBody").addEventListener("click", (e) => {
    const t = e.target.closest("[data-agx]");
    if (t) { const box = t.closest(".yx-step"); box.classList.toggle("open"); t.setAttribute("aria-expanded", box.classList.contains("open")); }
  });
}
// Keng ekranda yordamchi sahifani yopmaydi: o'ng tomonda biriktirilgan panel (Claude Code kabi), sahifa torayadi.
// Ochiq-yopiqligi eslab qolinadi; telefonda va tor ekranda ustidan ochiladigan oyna
function agOpen(question) {
  agMount();
  const el = $("#ag");
  el.classList.add("open"); el.setAttribute("aria-hidden", "false"); document.body.classList.add("yx-on");
  $("#aiBtn")?.setAttribute("aria-pressed", "true");
  try { localStorage.setItem("puls-ag-open", "1"); } catch (e) { /* xotira yopiq: faqat shu sahifada eslab qolinadi */ }
  agDraw();
  if (question) agAsk(question); else if (!agOpen.quiet) setTimeout(() => $("#agQ").focus(), 60);
  agDockChanged();
}
function agClose() {
  const el = $("#ag"); if (!el) return;
  el.classList.remove("open"); el.setAttribute("aria-hidden", "true"); document.body.classList.remove("yx-on");
  $("#aiBtn")?.setAttribute("aria-pressed", "false");
  try { localStorage.removeItem("puls-ag-open"); } catch (e) { /* xotira yopiq */ }
  agDockChanged();
}
// panel kengligi o'zgarganda grafiklar va matritsa yangi o'lchamga moslashadi
function agDockChanged() { setTimeout(() => dispatchEvent(new Event("resize")), 300); }

/* yordamchi kengligi: chap chetidagi dastakni tortib (yoki strelka tugmalari bilan) xohlagancha kengaytiriladi, eslab qolinadi.
   Sahifaga kamida 520px joy qoladi; "katta" tugmasi — mumkin bo'lgan eng katta kenglik, qayta bosilsa avvalgisi */
const AGW = { def: 440, min: 340, w: 440, prev: 0 };
function agMaxW() { return Math.max(AGW.min, innerWidth - (innerWidth > 960 ? 248 : 0) - 520); }
function agSetW(w, save) {
  AGW.w = Math.round(Math.min(agMaxW(), Math.max(AGW.min, w)));
  document.documentElement.style.setProperty("--agw", AGW.w + "px");
  const big = AGW.w >= agMaxW() - 8, b = $("#agMax");
  if (b) { b.innerHTML = I(big ? "zoom-out" : "zoom-in"); b.title = big ? "Odatiy kenglik" : "Kattalashtirish"; b.setAttribute("aria-label", b.title); }
  if (save) { try { localStorage.setItem("puls-ag-w", String(AGW.w)); } catch (e) { /* xotira yopiq: faqat shu sahifada */ } agDockChanged(); }
}
function agBindResize() {
  const grip = $("#agGrip");
  grip.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    grip.setPointerCapture(e.pointerId);
    document.body.classList.add("yx-dragging");
    const move = (ev) => agSetW(innerWidth - ev.clientX);
    const up = () => {
      grip.removeEventListener("pointermove", move); grip.removeEventListener("pointerup", up); grip.removeEventListener("pointercancel", up);
      document.body.classList.remove("yx-dragging"); agSetW(AGW.w, true);
    };
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", up);
    grip.addEventListener("pointercancel", up);
  });
  grip.addEventListener("dblclick", () => agSetW(AGW.def, true));
  grip.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 120 : 40;
    if (e.key === "ArrowLeft") agSetW(AGW.w + step, true);
    else if (e.key === "ArrowRight") agSetW(AGW.w - step, true);
    else if (e.key === "Home") agSetW(agMaxW(), true);
    else if (e.key === "End") agSetW(AGW.min, true);
    else return;
    e.preventDefault();
  });
  $("#agMax").onclick = () => {
    if (AGW.w >= agMaxW() - 8) agSetW(AGW.prev && AGW.prev < agMaxW() - 8 ? AGW.prev : AGW.def, true);
    else { AGW.prev = AGW.w; agSetW(agMaxW(), true); }
  };
  agSetW(AGW.w);
}
try { const w = +localStorage.getItem("puls-ag-w"); if (w) AGW.w = w; } catch (e) { /* xotira yopiq */ }
agSetW(AGW.w);
addEventListener("resize", () => { if (!document.body.classList.contains("yx-dragging")) agSetW(AGW.w); });
// sahifaga qolgan joyga qarab ixcham joylashuv (yordamchi qancha keng bo'lsa ham sahifa buzilmaydi)
if (window.ResizeObserver) {
  new ResizeObserver((ents) => {
    const w = ents[0].contentRect.width;
    document.body.classList.toggle("main-narrow", innerWidth > 960 && w < 1150);
    document.body.classList.toggle("main-tight", innerWidth > 960 && w < 820);
  }).observe($(".mainwrap"));
}

const agCol = (c) => esc(String(c).replace(/_/g, " ").replace(/^./, (x) => x.toUpperCase()));
const agCell = (v) => (v == null ? "—" : typeof v === "number" ? nf(v, 2) : esc(v));
function agTable(t, cls = "") {
  return `<div class="yx-tbl ${cls}"><table><thead><tr>${t.columns.map((c) => `<th>${agCol(c)}</th>`).join("")}</tr></thead>
    <tbody>${t.rows.map((r) => `<tr>${r.map((v) => `<td>${agCell(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function agStep(s) {
  const pv = s.preview, can = pv && (pv.rows?.length || pv.text);
  return `<li class="yx-step ${s.done ? (s.ok === false ? "bad" : "ok") : "run"}"><i class="dot"></i>
    <div class="yx-sb"><div class="yx-sl">${esc(s.label)}</div>
      ${s.tool ? `<div class="yx-sd">${esc(AG_TOOL[s.tool] || s.tool)}${s.detail && s.tool !== "sql" ? `<span>${esc(s.detail)}</span>` : ""}</div>` : ""}
      ${s.tool === "sql" && s.detail ? `<pre class="yx-sql">${esc(s.detail)}</pre>` : ""}
      ${s.done ? `<div class="yx-sr"><span>⎿</span>${esc(s.summary || "")}${can ? `<button type="button" class="yx-x" data-agx aria-expanded="false">Natija</button>` : ""}</div>` : ""}
      ${can ? `<div class="yx-pv">${pv.rows ? agTable(pv, "sm") + (pv.total > pv.rows.length ? `<small>${pv.rows.length} / ${pv.total} qator ko'rsatildi</small>` : "") : `<pre>${esc(pv.text)}</pre>`}</div>` : ""}
    </div></li>`;
}
function agTurn(t) {
  const a = t.answer;
  const log = (t.log || []).map((x) => x.kind === "think" ? `<li class="yx-think">${esc(x.text)}</li>`
    : x.kind === "check" ? `<li class="yx-check ${x.bad ? "bad" : ""}">${I(x.bad ? "danger" : "check")}<span>${esc(x.text)}</span></li>` : agStep(x)).join("");
  return `<div class="yx-turn"><p class="yx-q">${esc(t.q)}</p>
    ${log ? `<ol class="yx-log">${log}</ol>` : ""}
    ${t.error ? `<p class="yx-err">${esc(t.error)}</p>` : ""}
    ${t.ask ? `<div class="yx-a"><p>${esc(t.ask.text)}</p>${t.ask.options.length ? `<div class="yx-next">${t.ask.options.map((o) => `<button class="chip" data-agq="${esc(t.q + " — " + o)}">${esc(o)}</button>`).join("")}</div>` : ""}</div>` : ""}
    ${a ? `<div class="yx-a"><p>${esc(a.text)}</p>
      ${(a.tables || []).map((tb) => `<div class="yx-grp"><h4>${esc(tb.title)}<span>${tb.rows.length}${tb.more ? "+" : ""}</span></h4>${agTable(tb)}</div>`).join("")}
      ${(a.groups || []).map((g) => `<div class="yx-grp"><h4>${esc(g.title)}<span>${g.people.length}</span></h4><div class="traits">${g.people.map((n) => `<button class="chip" data-person="${esc(n)}">${esc(n)}</button>`).join("")}</div></div>`).join("")}
      ${(a.actions || []).length ? `<div class="yx-acts">${a.actions.map((x) => `<button class="btn btn-dark" data-act='${esc(JSON.stringify(x.action))}'>${I(ACT_ICON[x.action.type] || "check")}<span>${esc(x.label)}</span></button>`).join("")}</div>` : ""}
      <div class="yx-foot">${a.steps} qadam, ${nf(a.seconds, 1)} soniya</div>
    </div>` : ""}
    ${a && (a.follow_ups || []).length ? `<div class="yx-next">${a.follow_ups.map((f) => `<button class="chip" data-agq="${esc(f)}">${esc(f)}</button>`).join("")}</div>` : ""}</div>`;
}
function agStatus() {
  const st = $("#agStatus");
  if (!st) return;
  st.hidden = !AG.busy;
  if (!AG.busy) return;
  const sec = Math.floor((Date.now() - AG.t0) / 1000), t = AG.turns[AG.turns.length - 1];
  const last = t?.log?.[t.log.length - 1];
  const verb = last?.kind === "check" ? "Tekshiryapman" : last && !last.done && last.kind === "step" ? "Ma'lumot yig'yapman" : AG_VERBS[Math.floor(sec / 4) % AG_VERBS.length];
  st.innerHTML = `<i class="spin"></i><b>${verb}</b><span>${sec} s</span><em>Esc — to'xtatish</em>`;
}
function agDraw() {
  const body = $("#agBody");
  if (!body) return;
  const keep = new Set($$(".yx-step.open", body).map((x) => x.dataset.k));
  body.innerHTML = AG.turns.length ? AG.turns.map(agTurn).join("")
    : `<div class="yx-empty"><p>Jamoa, hisobotlar, vazifalar va loyihalar bo'yicha istalgan savolni bering: kerak bo'lsa bazadan o'zim hisoblab chiqaman. Eslatma, rahmat yoki vazifa o'tkazishni ham tayyorlab beraman, siz faqat tasdiqlaysiz.</p>
      <div class="yx-next">${AG_STARTERS.map((f) => `<button class="chip" data-agq="${esc(f)}">${esc(f)}</button>`).join("")}</div></div>`;
  $$(".yx-step", body).forEach((x, i) => { x.dataset.k = i; if (keep.has(String(i))) x.classList.add("open"); });
  bindCommon(body);
  $$("[data-agq]", body).forEach((b) => (b.onclick = () => agAsk(b.dataset.agq)));
  const go = $("#agGo");
  go.innerHTML = AG.busy ? I("pause") : I("send");
  go.setAttribute("aria-label", AG.busy ? "To'xtatish" : "Yuborish");
  go.title = AG.busy ? "To'xtatish" : "";
  agStatus();
  body.scrollTop = body.scrollHeight;
}
async function agAsk(text) {
  const q = String(text || "").trim();
  if (q.length < 2 || AG.busy) return;
  const turn = { q, log: [] };
  const history = AG.turns.filter((t) => t.answer).slice(-4).map((t) => ({ q: t.q, a: t.answer.text }));
  AG.turns.push(turn);
  AG.busy = true; AG.ctrl = new AbortController(); AG.t0 = Date.now();
  AG.tick = setInterval(agStatus, 1000);
  $("#agQ").value = ""; $("#agQ").style.height = "auto";
  agDraw();
  try {
    const r = await fetch("api/agent" + (S.dept ? "?dept=" + encodeURIComponent(S.dept) : ""), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q, history }), signal: AG.ctrl.signal });
    if (r.status === 401) { location.href = "login"; return; }
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.detail || "Server javob bermadi"); }
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let k;
      while ((k = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, k).trim(); buf = buf.slice(k + 2);
        if (!line.startsWith("data:")) continue;
        const ev = JSON.parse(line.slice(5));
        if (ev.type === "think") turn.log.push({ kind: "think", text: ev.text });
        else if (ev.type === "step") turn.log.push({ kind: "step", n: ev.n, label: ev.label, tool: ev.tool, detail: ev.detail });
        else if (ev.type === "done") { const s = turn.log.find((x) => x.kind === "step" && x.n === ev.n); if (s) Object.assign(s, { done: true, ok: ev.ok, summary: ev.summary, preview: ev.preview }); }
        else if (ev.type === "check") turn.log.push({ kind: "check", text: ev.text, bad: ev.bad });
        else if (ev.type === "answer") turn.answer = ev;
        else if (ev.type === "ask") turn.ask = { text: ev.text, options: ev.options || [] };
        else if (ev.type === "error") turn.error = ev.text;
        agDraw();
      }
    }
  } catch (e) {
    turn.error = e.name === "AbortError" ? "To'xtatildi" : e.message;
  }
  turn.log.forEach((s) => { if (s.kind === "step" && !s.done) { s.done = true; s.ok = false; } });
  clearInterval(AG.tick);
  AG.busy = false; AG.ctrl = null;
  agSave(); agDraw();
}
document.addEventListener("keydown", (e) => {
  const typing = /INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName);
  if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey) { e.preventDefault(); agOpen(); }
  else if (e.key === "Escape" && $("#ag")?.classList.contains("open") && !$("#modal").classList.contains("open") && !$("#drawer").classList.contains("open")) {
    if (AG.busy) AG.ctrl?.abort(); else agClose();
  }
});
