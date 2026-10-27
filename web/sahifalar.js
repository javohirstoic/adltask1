/* Puls — "Kunlik holat": rahbar ishini bitta sahifada bitiradi.
 * Bo'limlar: umumiy holat, hisobot matritsasi va xulosa, xodimlar, loyihalar, murojaatlar (yordam guruhlari va chatbotlar),
 * jamoa ichidagi muammolar, guruhlar.
 * Loyiha va xodim tafsiloti shu sahifaning ustida yon oynada ochiladi. Har guruh — bitta loyiha.
 * puls2.js dan keyin yuklanadi va uning yordamchilaridan foydalanadi ($, esc, I, S, api, pageHead, bindCommon ...). */
"use strict";

/* ================= umumiy ================= */
const PST = { kritik: ["Kritik", "bad"], kechikyapti: ["Kechikyapti", "warn"], jim: ["Jim", "idle"], yaxshi: ["Me'yorida", "good"], yangi: ["Yangi", "info"] };
const PST_ORDER = { kritik: 0, kechikyapti: 1, jim: 2, yaxshi: 3, yangi: 4 };
const HOLAT = { yashil: ["Yashil", "good"], sariq: ["Sariq", "warn"], qizil: ["Qizil", "bad"] };
const SEC = { done: "Bajarildi", doing: "Jarayonda", plan: "Ertangi reja", task: "Vazifa", blocker: "Bloker" };
const SRC_WORD = { format: "Hisobot shabloni bo'yicha", ai: "AI ma'nosi bo'yicha", taxmin: "Kalit so'zlar bo'yicha", tuzatildi: "Rahbar tuzatgan" };

const tag = (text, cls = "", dot = false) => `<span class="tag ${cls}">${dot ? "<i></i>" : ""}${text}</span>`;
const pstTag = (p) => { const x = PST[p.pstate] || PST.yaxshi; return tag(x[0], x[1], true); };
const holatTag = (h, sm) => (h && HOLAT[h] ? tag(HOLAT[h][0], HOLAT[h][1] + (sm ? " sm" : ""), true) : "");
const deadline = () => S.meta?.report_deadline || "18:00";
const highDays = () => S.meta?.blocker_high_days || 3;  // muammo shuncha kun hal bo'lmasa qizil (sozlamada)
const longDay = (day) => { const d = parseDay(day); return capFirst(WEEK[d.getDay()]) + ", " + uzDate(d); };
const pct = (a, b) => (b ? Math.round((100 * a) / b) : null);
// loyiha qancha e'tibor talab qiladi: kritik murojaat → eski muammo → ochiq muammo → yozmaganlar → kechikkan/qayta yozilgan → jim → me'yorida → bo'sh
function missingOf(p, d) {
  d = d || S.data;
  const last = p.days10[p.days10.length - 1];
  return d && d.period.key === "day" && last && last[0] === d.period.to && dayFinal(d.period.to, d) ? Math.max(0, last[2] - last[1]) : 0;
}
function pAttn(p) {
  const open = p.blocker_list.length, oldest = Math.max(0, ...p.blocker_list.map((x) => x.age)), miss = missingOf(p);
  const empty = !p.team_count && !p.people.length && !p.done;
  const tier = empty ? 9 : p.pstate === "kritik" ? 0 : open && oldest >= highDays() ? 1 : open ? 2 : miss ? 3
    : p.late_reports.length || p.repeats ? 4 : p.pstate === "jim" || p.pstate === "kechikyapti" ? 5 : 6;
  return [tier, -(open * 10 + miss * 3 + p.late_reports.length + p.repeats * 2), -p.done];
}
const byState = (a, b) => { const x = pAttn(a), y = pAttn(b); return x[0] - y[0] || x[1] - y[1] || x[2] - y[2] || a.name.localeCompare(b.name); };
const isEmptyProject = (p) => !p.team_count && !p.people.length && !p.done;
// kun yakunlandimi: o'tgan kun yoki bugun hisobot muddati o'tgan bo'lsa "yozmadi" deyiladi, aks holda "kutilmoqda"
function dayFinal(day, d) {
  const now = (d || S.data)?.now || "";
  return day < now.slice(0, 10) || now.slice(11, 16) >= deadline();
}
function dayOf(d) { return d.period.to; }
function meterCls(v) { return v == null ? "" : v >= 80 ? "" : v >= 50 ? "warn" : "bad"; }
const periodWord = (d) => (d.period.key === "day" ? dotDate(dayOf(d)) : d.period.range_label);
// qayta yozilgan ish dalili tugmasi: bosilsa eski va yangi xabar yonma-yon ochiladi
const repBtn = (id, text, cls = "tag bad sm") => (id ? `<button type="button" class="${cls} rep-btn" data-rep="${id}" title="Dalilni ko'rish">${text}</button>` : `<span class="${cls}">${text}</span>`);

/* chap menyu pastida: ma'lumot manbasi */
function sideFoot() {
  const box = $("#sideInfo");
  if (!box || !S.meta) return;
  const chats = (S.meta.chats || []).filter((c) => !c.demo);
  const demo = (S.meta.chats || []).length - chats.length;
  const last = S.meta.last_message;
  box.innerHTML = `<div class="sf-row"><i class="${chats.length ? "" : "off"}"></i><span>${chats.length ? chats.length + " ta guruh ulangan" : demo ? "Namuna: " + demo + " ta guruh" : "Guruh ulanmagan"}</span></div>
    <div class="sf-row"><i class="${last ? "" : "off"}"></i><span>Oxirgi xabar</span><em>${last ? esc(clock(last)) : "yo'q"}</em></div>
    <div class="sf-row"><i></i><span>Hisobot muddati</span><em>${esc(deadline())}</em></div>
    <div class="sf-row"><i class="${S.meta.ai ? "" : "off"}"></i><span>Rahbarga xulosa</span><em>${esc(S.meta.digest_morning || "09:00")}</em></div>`;
}

/* bir kun uchun jamoa holati: kim yozdi, kim kechikdi, kim yozmadi (hamma loyiha bo'yicha) */
function dayWho(d) {
  const team = new Set(), wrote = new Set();
  d.projects.forEach((p) => { p.team.forEach((n) => team.add(n)); p.people.forEach((n) => wrote.add(n)); });
  const people = d.people.filter((p) => team.has(p.name) || wrote.has(p.name));
  return { team, wrote, people };
}
function personRow(p, d) {
  const day = d.period.key === "day";
  const wrote = !!(p.report_at || p.done || (day && p.today?.items));
  const st = wrote ? (p.report_late ? "late" : "ok") : "none";
  return { p, wrote, st, rep: p.repeats || 0, repId: p.repeat_list?.[0]?.id || p.q28?.example?.id, repTitle: p.repeat_list?.[0]?.title || p.q28?.example?.title };
}
const rowsOf = (d) => dayWho(d).people.map((p) => personRow(p, d));

/* ================= Kunlik holat: bitta sahifa ================= */
const HL = { pf: "", q: "", copied: false, best: [], bestKey: "" };
function renderHolat(d) {
  const el = $("#v-holat");
  const rows = rowsOf(d);
  el.innerHTML = pageHead("Kunlik holat", "") + `
    <div class="hl">
      <section data-secid="umumiy">${bandHtml(d, rows)}</section>
      <div class="hl-grid" data-secid="matritsa">
        <div class="hl-col">${matrixPanel(d)}${timePanel(d)}</div>
        <section class="panel aisum" id="hlAi">${aiSummary(d, rows)}</section>
      </div>
      <section class="panel" id="hlPeople" data-secid="xodimlar">${peopleInner(d)}</section>
      <section id="hlProjects" data-secid="loyihalar">${projectsInner(d)}</section>
      <section id="hlAppeals" class="ap" data-secid="murojaatlar">${appealsInner()}</section>
      <section class="panel" id="hlIssues" data-secid="muammolar">${issuesInner(d)}</section>
      ${planPanel(d)}
      <section class="panel" id="hlGroups" data-secid="guruhlar">${groupsInner(d)}</section>
    </div>`;
  bindHead(el);
  bindCommon(el);
  bindHolat(el, d);
  $$(".mx", el).forEach((m) => { if (m.scrollWidth > m.clientWidth + 4) m.scrollLeft = m.scrollWidth; });  // tor ekranda eng yangi kunlar ko'rinsin
  spySections(el);
  if (S.sec) { const id = S.sec; S.sec = ""; setTimeout(() => scrollSection(id), 30); }
  if (!S.asof && S.meta?.ai && !YD.data && !YD.loading) loadYd().then(() => { if (S.tab === "holat") redrawAi(); });
  loadIssues(d);
  loadAppeals();
}
function bindHolat(el, d) {
  $$("[data-hf]", el).forEach((b) => b.addEventListener("click", () => { HL.pf = HL.pf === b.dataset.hf ? "" : b.dataset.hf; drawPeople(d); scrollSection("xodimlar"); }));
  $$("[data-goto]", el).forEach((b) => b.addEventListener("click", () => scrollSection(b.dataset.goto)));
  $$("[data-anchor]", el).forEach((b) => b.addEventListener("click", () => $("#" + b.dataset.anchor)?.scrollIntoView({ behavior: "smooth", block: "start" })));
  $$("[data-enter]", el).forEach((b) => b.addEventListener("click", () => setDept(b.dataset.enter)));
  $$("[data-mxday]", el).forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); openProjectDrawer(b.dataset.mxp, b.dataset.mxday); }));
  bindAi($("#hlAi"), d);
  bindPeople(d);
  bindProjects(d);
  bindIssues(d);
  bindAppeals($("#hlAppeals"));
  bindGroups(d);
}
// chap menyuda hozir ko'rinib turgan bo'lim belgilanadi
let spyObs = null;
function spySections(el) {
  spyObs?.disconnect();
  if (!window.IntersectionObserver) return;
  const seen = new Map();
  spyObs = new IntersectionObserver((ents) => {
    ents.forEach((e) => seen.set(e.target.dataset.secid, e.isIntersecting ? e.boundingClientRect.top : null));
    const vis = [...seen.entries()].filter((x) => x[1] != null).sort((a, b) => Math.abs(a[1] - 80) - Math.abs(b[1] - 80));
    if (vis.length && S.tab === "holat") markNav(window.scrollY < 40 ? "umumiy" : vis[0][0]);
  }, { rootMargin: "-70px 0px -55% 0px" });
  $$("[data-secid]", el).forEach((s) => spyObs.observe(s));
}

/* 6 ta asosiy ko'rsatkich: har biri bosiladi va tegishli ro'yxatni ochadi */
function bandHtml(d, rows) {
  const day = dayOf(d), isDay = d.period.key === "day", final = dayFinal(day, d), who = dayWho(d);
  const wroteN = rows.filter((r) => r.wrote && who.team.has(r.p.name)).length, teamN = who.team.size;
  const sum = (k) => d.projects.reduce((a, p) => a + (p[k] || 0), 0);
  const planT = sum("plan_total"), planD = sum("plan_done"), reqN = sum("requests_open"), probN = sum("problems_open");
  const oldest = Math.max(0, ...d.projects.flatMap((p) => p.blocker_list.map((b) => b.age)));
  const repN = sum("repeats"), repPeople = rows.filter((r) => r.rep).length;
  const lateN = isDay ? rows.filter((r) => r.st === "late").length : d.projects.reduce((a, p) => a + p.late_reports.length, 0);
  const doneN = d.kpi.done, prevN = sum("done_prev"), diff = doneN - prevN;
  const cov = pct(wroteN, teamN), planP = pct(planD, planT);
  const per = isDay ? "kunga" : d.period.key === "week" ? "haftaga" : "davrga";  // "+5, oldingi kunga"
  const missN = teamN - wroteN;
  return `<div class="band">
      <button class="metric" data-hf="none"><span class="l">Hisobot yozdi</span>
        <span class="v">${wroteN}<small> / ${teamN}</small></span><span class="d ${missN && final ? "down" : ""}">${missN ? `${missN} kishi ${final || !isDay ? "yozmadi" : "hali yozmadi"}` : teamN ? "hammasi yozdi" : "jamoa yo'q"}</span>
        <span class="meter"><i class="${meterCls(cov)}" style="width:${cov || 0}%"></i></span></button>
      <button class="metric" data-hf="ok"><span class="l">Bajarilgan ishlar</span><span class="v">${nf(doneN)}</span>
        <span class="d ${diff > 0 ? "up" : diff < 0 ? "down" : ""}">${prevN || doneN ? `${diff > 0 ? "+" : ""}${diff}, oldingi ${per}` : "hali yozilmagan"}</span></button>
      <button class="metric" data-anchor="hlReja"><span class="l">Reja bajarilishi</span><span class="v">${planP == null ? "—" : planP + "%"}</span>
        <span class="d">${planT ? `${planD} / ${planT} band` : "rejada band yo'q"}</span>
        <span class="meter"><i class="${meterCls(planP)}" style="width:${planP || 0}%"></i></span></button>
      <button class="metric" data-goto="muammolar"><span class="l">Ochiq masalalar</span><span class="v ${reqN + probN && oldest >= highDays() ? "bad" : ""}">${reqN + probN}</span>
        <span class="d">${reqN + probN ? `${reqN} so'rov, ${probN} muammo` : "ochiq masala yo'q"}</span></button>
      <button class="metric" data-hf="rep"><span class="l">Qayta yozilgan ishlar</span><span class="v ${repN ? "bad" : ""}">${repN}</span>
        <span class="d">${repN ? `${repPeople} kishi eski ishni yozdi` : "takror yo'q"}</span></button>
      <button class="metric" data-hf="late"><span class="l">Kechikkan hisobot</span><span class="v ${lateN ? "warn" : ""}">${lateN}</span>
        <span class="d">${esc(deadline())} dan keyin</span></button>
    </div>`;
}

/* hisobot matritsasi: loyihalar x oxirgi 10 ish kuni */
function mxCell(p, cell, sel, final, d) {
  const [day, w, e] = cell, today = d.now.slice(0, 10);
  let cls, txt;
  if (!e && !w) { cls = "na"; txt = ""; }
  else if (w >= e && e) { cls = "full"; txt = I("check"); }
  else if (day === today && !final) { cls = "wait"; txt = `${w}/${e}`; }
  else if (!w) { cls = "none"; txt = `0/${e}`; }
  else { cls = "part"; txt = `${w}/${e || w}`; }
  const title = `${p.name}, ${longDay(day)}: ${e ? `${w} / ${e} kishi yozdi` : w ? `${w} kishi yozdi` : "kuzatilmagan"}`;
  return `<td><button class="mc ${cls} ${day === sel ? "sel" : ""}" data-mxday="${day}" data-mxp="${p.id}" title="${esc(title)}" aria-label="${esc(title)}">${txt}</button></td>`;
}
function matrixPanel(d) {
  const sel = dayOf(d), final = dayFinal(sel, d);
  const list = d.projects.slice().sort(byState);
  const days = list[0]?.days10 || [];
  if (!list.length) return `<section class="panel"><div class="pnl-h"><h2>Hisobot matritsasi</h2></div><div class="pnl-b">${emptyBox("Botni ish guruhiga qo'shib admin qiling: guruh shu yerda loyiha bo'lib chiqadi", "projects")}</div></section>`;
  return `<section class="panel"><div class="pnl-h"><h2>Hisobot matritsasi</h2>
      <div class="legend2"><span><i class="lg-full"></i>to'liq</span><span><i class="lg-part"></i>qisman</span><span><i class="lg-none"></i>yozilmagan</span><span><i class="lg-wait"></i>kutilmoqda</span></div></div>
    <div class="mx"><table><thead><tr><th class="pn"></th>${days.map(([k]) => { const x = parseDay(k);
      return `<th class="${k === sel ? "sel" : ""}">${WD_SHORT[x.getDay()]}<br>${k.slice(8, 10)}.${k.slice(5, 7)}</th>`; }).join("")}</tr></thead>
      <tbody>${list.map((p) => `<tr><td class="pn"><button data-project="${p.id}" title="${esc(p.name)}">${esc(p.name)}</button><small>${p.team_count} kishi</small></td>
        ${p.days10.map((c) => mxCell(p, c, sel, final, d)).join("")}</tr>`).join("")}</tbody></table></div></section>`;
}

/* hisobot yuborilgan vaqt: har loyiha qatorida xodimlarning birinchi hisoboti, qizil chiziq — muddat */
function timePanel(d) {
  const day = dayOf(d);
  if (d.period.key !== "day") return "";
  const list = d.projects.filter((p) => p.team_count || p.report_times.length).sort(byState);
  if (!list.length) return "";
  const W = 600, L = 150, R = 12, top = 28, rowH = 34, H = top + list.length * rowH + 6;
  const h0 = 8, h1 = 27.5;  // 08:00 dan ertasi kun 03:30 gacha
  const x = (hh, mm) => L + ((Math.min(h1, Math.max(h0, hh + mm / 60)) - h0) / (h1 - h0)) * (W - L - R);
  const [dh, dm] = deadline().split(":").map(Number);
  const ticks = [10, 14, 18, 22];
  const svg = `<svg class="tchart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Hisobot yuborilgan vaqt">
    <rect class="next" x="${x(24, 0)}" y="${top - 8}" width="${x(h1, 0) - x(24, 0)}" height="${H - top + 4}"/>
    ${ticks.map((t) => `<line class="grid" x1="${x(t, 0)}" x2="${x(t, 0)}" y1="${top - 8}" y2="${H - 2}"/><text x="${x(t, 0)}" y="15" text-anchor="middle">${String(t).padStart(2, "0")}:00</text>`).join("")}
    <text x="${(x(24, 0) + x(h1, 0)) / 2}" y="15" text-anchor="middle">ertasi kun</text>
    <line class="dl" x1="${x(dh, dm)}" x2="${x(dh, dm)}" y1="${top - 8}" y2="${H - 2}"/>
    ${list.map((p, i) => { const y = top + i * rowH + rowH / 2;
      const dots = p.report_times.map((r) => { const [hh, mm] = r.at.split(":").map(Number); const next = r.on > day;
        return `<circle class="${r.late ? "late" : "ok"}" cx="${next ? x(24 + hh, mm) : x(hh, mm)}" cy="${y}" r="7"><title>${esc(r.name)}: ${next ? "ertasi kuni " : ""}${r.at}${r.late ? ", kechikkan" : ""}</title></circle>`; }).join("");
      return `<text class="pn" x="0" y="${y + 5}">${esc(p.name.length > 18 ? p.name.slice(0, 17) + "…" : p.name)}</text>
        ${dots || (p.team_count ? `<text class="none" x="${L + 6}" y="${y + 5}">${dayFinal(day, d) ? "hisobot yo'q" : "kutilmoqda"}</text>` : "")}`; }).join("")}
  </svg>`;
  return `<section class="panel"><div class="pnl-h"><h2>Hisobot yuborilgan vaqt</h2>
      <div class="legend2"><span><i class="lg-dot ok"></i>o'z vaqtida</span><span><i class="lg-dot late"></i>kechikkan</span><span><i class="lg-line"></i>muddat ${esc(deadline())}</span></div></div>
    <div class="pnl-b"><div class="tscroll">${svg}</div></div></section>`;
}

/* kun xulosasi: sizni kutayotgan qarorlar (bir bosishda amal), keyin e'tibor kerak bo'lgan narsalar */
function ruleItems(d, rows) {
  const out = [], day = dayOf(d), final = dayFinal(day, d);
  d.projects.slice().sort(byState).forEach((p) => {
    const t = `data-project="${p.id}"`;
    if (p.requests_open) out.push(["bad", t, `<b>${esc(p.name)}:</b> ${p.requests_open} ta ochiq so'rov${p.requests_oldest ? `, eng eskisi ${p.requests_oldest} kun` : ""}`, p.request_list[0]?.text]);
    p.blocker_list.filter((b) => b.kind !== "murojaat").forEach((b) => out.push([b.age >= highDays() ? "bad" : "warn", t, `<b>${esc(p.name)}:</b> ${esc(b.text)}`, b.age ? b.age + " kundan beri" : S.asof ? "shu kuni" : "bugun"]));
    const last = p.days10[p.days10.length - 1];
    if (d.period.key === "day" && last && last[0] === day && last[2] && !last[1] && final) out.push(["warn", t, `<b>${esc(p.name)}:</b> hisobot yo'q`]);
    if (p.stalled) out.push(["warn", t, `<b>${esc(p.name)}:</b> ${p.stalled} ta ish 3 kundan ortiq jarayonda`]);
    if (p.plan_total && p.plan_done < p.plan_total && final) out.push(["warn", t, `<b>${esc(p.name)}:</b> rejadagi ${p.plan_total} ta banddan ${p.plan_done} tasi bajarildi`]);
  });
  rows.filter((r) => r.rep).forEach((r) => out.push(["bad", r.repId ? `data-rep="${r.repId}"` : `data-person="${esc(r.p.name)}"`, `<b>${esc(r.p.name)}</b> eski ishni qayta yozdi${r.rep > 1 ? ": " + r.rep + " ta" : ""}`, r.repTitle ? "«" + r.repTitle + "»" : ""]));
  return out;
}
function decisionsHtml(d) {
  if (S.asof) return "";
  const decs = d.decisions.filter((x) => !x.good).slice(0, 4);
  if (!decs.length) return "";
  return `<h3>Sizni kutmoqda <span class="n">${d.decisions.filter((x) => !x.good).length}</span></h3><ul class="alist dec">${decs.map((x) => `<li><div class="it" ${x.target.type === "project" ? `data-project="${x.target.id}"` : `data-person="${esc(x.target.name)}"`}>
      <span class="sev ${x.level >= 3 ? "bad" : "warn"}">${I(x.icon || "info")}</span><span style="flex:1;min-width:0"><b>${esc(x.title)}</b><small>${esc(x.fact)}</small>
      <span class="it-acts">${x.action ? `<button class="btn btn-dark sm" data-act='${esc(JSON.stringify(x.action))}'>${I(ACT_ICON[x.action.type] || "check")}<span>${esc(x.button)}</span></button>` : ""}
        <button class="btn btn-ghost sm" data-snooze="${esc(x.id)}">Keyinroq</button></span></span></div></li>`).join("")}</ul>`;
}
function aiSummary(d, rows) {
  const day = dayOf(d), useAi = !S.asof && S.meta?.ai && YD.data?.items?.length;
  const items = useAi ? YD.data.items.map((x) => [x.level >= 3 ? "bad" : x.level === 2 ? "warn" : "", ydTarget(x), `<b>${esc(x.title)}:</b> ${esc(x.text)}`])
    : ruleItems(d, rows);
  const late = rows.filter((r) => r.st === "late").sort((a, b) => (a.p.report_at || "").localeCompare(b.p.report_at || ""));
  const icon = { bad: "danger", warn: "clock", good: "check", "": "info" };
  const li = (x) => `<li><div class="it" ${x[1]}><span class="sev ${x[0]}">${I(icon[x[0]] || "info")}</span><span>${x[2]}${x[3] ? `<small>${esc(x[3])}</small>` : ""}</span></div></li>`;
  const best = (HL.best || []).slice(0, 3);
  return `<div class="pnl-h"><h2>${I("stars")}Kun xulosasi</h2>
      <div class="right">${useAi ? `<button class="icon-btn sm" id="hlAiRe" title="Qayta yozish" aria-label="Xulosani qayta yozish" ${YD.loading ? "disabled" : ""}>${I("refresh")}</button>` : ""}</div></div>
    <div class="pnl-b">
      ${decisionsHtml(d)}
      ${decisionsHtml(d) ? `<h3>E'tibor kerak</h3>` : ""}
      ${YD.loading && !items.length ? `<div class="sk" style="height:160px"></div>` : items.length ? `<ul class="alist">${items.slice(0, 8).map(li).join("")}</ul>` : `<div class="empty">${I("check")}<span>E'tibor talab qiladigan masala yo'q</span></div>`}
      ${late.length ? `<details><summary>${I("clock")}Kechikkan hisobotlar: ${late.length} ta</summary>
        <ul class="alist">${late.map((r) => `<li><div class="it" data-person="${esc(r.p.name)}"><span class="sev warn">${I("clock")}</span><span><b>${esc(r.p.name)}</b>, ${esc(r.p.report_at)}${r.p.projects?.[0] ? `<small>${esc(r.p.projects.slice(0, 2).join(", "))}</small>` : ""}</span></div></li>`).join("")}</ul></details>` : ""}
      ${best.length ? `<h3>Eng og'ir ishlar</h3><ul class="alist">${best.map((x) => `<li><div class="it" data-person="${esc(x.who)}"><span class="sev good">${I("check")}</span><span><b>${esc(first(x.who))}:</b> ${esc(x.title)}<small>${esc(x.project || "")}${x.weight ? `, ${WT_WORD[x.weight].toLowerCase()} ish` : ""}</small></span></div></li>`).join("")}</ul>` : ""}
      <div class="foot"><button class="btn btn-line sm" id="hlCopy">${I("copy")}${HL.copied ? "Nusxa olindi" : "Telegram uchun nusxa"}</button>
        <button class="btn btn-ghost sm" id="hlAsk">${I("stars")}Yordamchidan so'rash</button></div>
    </div>`;
}
function redrawAi() { const box = $("#hlAi"); if (box && S.data) { box.innerHTML = aiSummary(S.data, rowsOf(S.data)); bindAi(box, S.data); } }
function bindAi(box, d) {
  if (!box) return;
  bindCommon(box);
  $$("[data-snooze]", box).forEach((b) => (b.onclick = (e) => { e.stopPropagation(); tmSnooze(b.dataset.snooze); }));
  $("#hlAiRe", box)?.addEventListener("click", () => loadYd(true).then(() => { if (S.tab === "holat") redrawAi(); }));
  $("#hlAsk", box)?.addEventListener("click", () => agOpen(`${dotDate(dayOf(d))} kuni jamoada nima bo'ldi: kim yozmadi, qaysi loyiha orqada va nima qilishim kerak?`));
  $("#hlCopy", box)?.addEventListener("click", () => {
    copyText(dayText(d), () => { HL.copied = true; $("#hlCopy").innerHTML = I("check") + "Nusxa olindi"; setTimeout(() => { HL.copied = false; }, 4000); toast("Xulosa nusxalandi", "copy"); });
  });
  const day = dayOf(d);
  if (d.period.key === "day" && HL.bestKey !== day + "|" + S.version) {
    HL.bestKey = day + "|" + S.version;
    tmReports(day).then((rep) => {
      HL.best = (rep?.people || []).flatMap((p) => p.items.filter((i) => !isRep(i) && !i.deleted_at).map((i) => ({ ...i, who: p.name })))
        .sort((a, b) => (b.weight || 0) - (a.weight || 0) || (b.hours || 0) - (a.hours || 0)).slice(0, 3);
      if (S.tab === "holat" && HL.best.length) redrawAi();
    }).catch(() => {});
  }
}
function dayText(d) {
  const day = dayOf(d), who = dayWho(d), rows = rowsOf(d);
  const sum = (k) => d.projects.reduce((a, p) => a + (p[k] || 0), 0);
  const wrote = rows.filter((r) => r.wrote && who.team.has(r.p.name)), miss = rows.filter((r) => !r.wrote && who.team.has(r.p.name));
  const late = rows.filter((r) => r.st === "late"), rep = rows.filter((r) => r.rep);
  const lines = [`Kunlik holat, ${dotDate(day)} (${WEEK[parseDay(day).getDay()]})`, "",
    `Hisobot yozdi: ${wrote.length} / ${who.team.size}`, `Bajarilgan ishlar: ${d.kpi.done}`,
    `Reja bajarilishi: ${sum("plan_total") ? pct(sum("plan_done"), sum("plan_total")) + "% (" + sum("plan_done") + " / " + sum("plan_total") + ")" : "rejada band yo'q"}`,
    `Ochiq so'rovlar: ${sum("requests_open")}, muammolar: ${sum("problems_open")}`];
  if (late.length) lines.push(`Kechikkan hisobot (${deadline()} dan keyin): ${late.map((r) => r.p.name + " " + r.p.report_at).join(", ")}`);
  if (miss.length) lines.push(`Yozmaganlar: ${miss.map((r) => r.p.name).join(", ")}`);
  if (rep.length) lines.push(`Eski ishni qayta yozgan: ${rep.map((r) => r.p.name + " (" + r.rep + ")").join(", ")}`);
  const bad = d.projects.filter((p) => ["kritik", "kechikyapti", "jim"].includes(p.pstate)).sort(byState);
  if (bad.length) { lines.push("", "E'tibor talab qiladigan loyihalar:"); bad.forEach((p) => lines.push(`- ${p.name}: ${PST[p.pstate][0].toLowerCase()}${p.requests_open ? ", " + p.requests_open + " ta so'rov" : ""}${p.risks[0] ? ", " + p.risks[0].text : ""}`)); }
  return lines.join("\n");
}

/* xodimlar: kim yozdi, kim kechikdi, kim yozmadi, kim eski ishni qayta yozdi */
const HL_F = {
  "": ["Hammasi", () => true], ok: ["Yozdi", (r) => r.wrote], none: ["Yozmadi", (r) => !r.wrote], late: ["Kechikdi", (r) => r.st === "late"],
  rep: ["Qayta yozdi", (r) => r.rep > 0], red: ["Sariq va qizil", (r) => ["sariq", "qizil"].includes(r.p.holat)],
};
function peopleInner(d) {
  const day = dayOf(d), isDay = d.period.key === "day", final = dayFinal(day, d);
  const all = rowsOf(d), q = fold(HL.q);
  const cnt = (k) => all.filter(HL_F[k][1]).length;
  const order = (r) => (!r.wrote ? 0 : r.rep ? 1 : r.st === "late" ? 2 : 3);
  const list = all.filter((r) => HL_F[HL.pf][1](r) && (!q || fold(r.p.name + " " + (r.p.projects || []).join(" ")).includes(q)))
    .sort((a, b) => order(a) - order(b) || a.p.name.localeCompare(b.p.name));
  const missN = cnt("none");
  const status = (r) => !r.wrote ? (isDay && !final ? tag("Kutilmoqda", "idle") : tag("Yozmadi", "bad", true))
    : r.st === "late" ? tag("Kechikdi, " + esc(r.p.report_at), "warn", true) : tag(r.p.report_at ? esc(r.p.report_at) : "Yozdi", "good", true);
  return `<div class="pnl-h"><h2>Xodimlar <span class="n">${all.length}</span></h2>
      <div class="right">${missN && isDay && day >= workdayShift(todayIso(), -1) && !S.asof && can("decide") ? `<button class="btn btn-line sm" id="hlRemind">${I("bell")}Yozmaganlarga eslatish</button>` : ""}
        ${can("people") ? `<button class="btn btn-line sm" id="hlPeopleAll">${I("people")}Guruhdagi odamlar</button><button class="btn btn-dark sm" id="hlAdd">${I("user-plus")}Xodim qo'shish</button>` : ""}</div></div>
    <div class="tools-row"><label class="searchbox">${I("search")}<input id="hlQ" type="search" placeholder="Xodim yoki loyiha" value="${esc(HL.q)}" autocomplete="off"></label>
      <div class="legend">${Object.keys(HL_F).map((k) => { const n = cnt(k); return `<button class="chip ${(k === "none" || k === "rep") && n ? "alarm" : ""}" data-hlf="${k}" aria-pressed="${HL.pf === k}" ${n || HL.pf === k ? "" : "disabled"}>${HL_F[k][0]} <b>${n}</b></button>`; }).join("")}</div></div>
    <div class="tscroll"><table class="dtab"><thead><tr><th>Xodim</th><th class="hm">Loyiha</th><th>Hisobot</th><th class="hm">O'z holati</th><th class="num hm">Bajarildi</th><th class="num hm">Reja</th><th>Takror</th></tr></thead>
      <tbody>${list.map((r) => `<tr class="clk ${r.wrote ? "" : "miss"}" data-person="${esc(r.p.name)}">
        <td><span class="who">${ava(r.p.name, r.p.department, r.p.state)}<span><b>${esc(r.p.name)}</b><small>${esc(r.p.department)}</small></span></span></td>
        <td class="hm"><span class="ttl">${esc((r.p.projects || []).slice(0, 2).join(", ") || "—")}</span></td>
        <td>${status(r)}</td><td class="hm">${holatTag(r.p.holat) || `<span class="sm">—</span>`}</td>
        <td class="num hm"><b>${r.p.done || 0}</b></td>
        <td class="num hm">${r.p.plan_total ? `${r.p.plan_done} / ${r.p.plan_total}` : `<span class="sm">—</span>`}</td>
        <td>${r.rep ? repBtn(r.repId, `${r.rep} ta, dalil`) : `<span class="sm">—</span>`}</td></tr>`).join("") || `<tr><td colspan="7">${emptyBox(q ? "Bu nomli xodim yo'q" : "Bu filtrga mos xodim yo'q", q ? "search" : "check")}</td></tr>`}</tbody></table></div>`;
}
function drawPeople(d) {
  const box = $("#hlPeople");
  if (!box) return;
  const focus = document.activeElement?.id === "hlQ";
  box.innerHTML = peopleInner(d);
  bindCommon(box);
  bindPeople(d);
  if (focus) { const q = $("#hlQ"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
}
function bindPeople(d) {
  const box = $("#hlPeople");
  if (!box) return;
  $$("[data-hlf]", box).forEach((b) => (b.onclick = () => { HL.pf = HL.pf === b.dataset.hlf ? "" : b.dataset.hlf; drawPeople(d); }));
  const q = $("#hlQ", box);
  if (q) q.oninput = () => { HL.q = q.value; clearTimeout(q._t); q._t = setTimeout(() => drawPeople(d), 140); };
  $("#hlRemind", box)?.addEventListener("click", () => tmRemind(rowsOf(d).filter((r) => !r.wrote).map((r) => r.p.name)));
  $("#hlAdd", box)?.addEventListener("click", openAddPerson);
  $("#hlPeopleAll", box)?.addEventListener("click", openLinks);
}

/* loyihalar: har guruh — bitta loyiha; kartalar yoki jadval */
const LP_F = {
  "": ["Hammasi", () => true],
  yozmagan: ["Yozmaganlar bor", (p) => missingOf(p) > 0],
  muammo: ["Muammo yoki so'rov", (p) => p.blocker_list.length > 0],
  kechikkan: ["Kechikkan hisobot", (p) => p.late_reports.length > 0],
  takror: ["Qayta yozilgan", (p) => p.repeats > 0],
  jim: ["Jim", (p) => p.pstate === "jim"],
  bosh: ["Hisobotsiz guruh", isEmptyProject],
};
const LP = { sort: "diqqat", f: "", q: "", view: "kartalar" };
try { LP.view = localStorage.getItem("puls-lp-view") || "kartalar"; } catch (e) { /* xotira yopiq */ }
const LP_SORT = {
  diqqat: ["E'tibor talab qiladigani tepada", byState],
  nomi: ["Nomi bo'yicha", (a, b) => a.name.localeCompare(b.name)],
  faol: ["Eng faoli tepada", (a, b) => b.done - a.done || b.people_count - a.people_count],
  murojaat: ["Murojaati ko'pi tepada", (a, b) => (b.appeals?.n || 0) - (a.appeals?.n || 0) || (b.appeals?.open || 0) - (a.appeals?.open || 0)],
  masala: ["Ochiq masalasi ko'pi tepada", (a, b) => b.requests_open - a.requests_open || b.problems_open - a.problems_open],
  jamoa: ["Jamoasi kattasi tepada", (a, b) => b.team_count - a.team_count],
};
function teamChips(p, d, limit = 8) {
  const day = dayOf(d), isDay = d.period.key === "day", final = dayFinal(day, d), wrote = new Set(p.people);
  const names = [...new Set([...p.team, ...p.people])].sort((a, b) => (wrote.has(b) - wrote.has(a)) || a.localeCompare(b));
  const chip = (n) => wrote.has(n) ? `<span class="tdot ok" title="${esc(n)}: yozdi">${I("check")}${esc(first(n))}</span>`
    : isDay && !final ? `<span class="tdot wait" title="${esc(n)}: hali yozmadi">${esc(first(n))}</span>` : `<span class="tdot no" title="${esc(n)}: yozmadi">${esc(first(n))}</span>`;
  return names.length ? `<div class="teamchips">${names.slice(0, limit).map(chip).join("")}${names.length > limit ? `<span class="tdot wait">+${names.length - limit}</span>` : ""}</div>` : `<div class="teamchips"><span class="tdot wait">hali hech kim yozmagan</span></div>`;
}
function pAlert(p) {
  const b = p.blocker_list.slice().sort((x, y) => y.age - x.age)[0];
  if (!b) return "";
  const more = p.blocker_list.length - 1;
  return `<div class="pj-alert ${b.age >= highDays() ? "bad" : ""}">${I(b.kind === "murojaat" ? "chat-dots" : "danger")}<span><b>${b.kind === "murojaat" ? "So'rov" : "Muammo"}${b.age ? ", " + b.age + " kun" : S.asof ? ", shu kuni" : ", bugun"}:</b> ${esc(b.text)}${more > 0 ? `<em> va yana ${more} ta</em>` : ""}</span></div>`;
}
function projectCard(p, d) {
  const isDay = d.period.key === "day", flags = [];
  if (p.late_reports.length) flags.push(tag(p.late_reports.length + " kechikkan hisobot", "warn sm"));
  if (p.repeats) flags.push(tag(p.repeats + " qayta yozilgan", "bad sm"));
  if (p.stalled) flags.push(tag(p.stalled + " ta ish 3+ kun jarayonda", "warn sm"));
  const st = p.pstate !== "yaxshi" ? pstTag(p) : "";
  const more = p.done - p.done_top.length;
  return `<article class="pjc" data-project="${p.id}" tabindex="0">
    <div class="top"><div style="min-width:0"><div class="nm">${esc(p.name)}</div>${p.chat_title && p.chat_title !== p.name ? `<span class="grp2">${esc(p.chat_title)}</span>` : ""}</div>${st}</div>
    <div class="pj-sec"><span class="k">${isDay ? "Hisobot" : "Yozganlar"}</span>${teamChips(p, d)}</div>
    <div class="pj-sec"><span class="k">Bajarildi <b>${p.done}</b></span>
      ${p.done_top.length ? `<ul class="pj-list">${p.done_top.map((x) => `<li>${esc(x.title)}<small>${esc(first(x.who || ""))}</small></li>`).join("")}</ul>${more > 0 ? `<span class="pj-more">yana ${more} ta ish</span>` : ""}`
        : `<span class="pj-none">${isDay ? "Bu kuni bajarilgan ish yozilmagan" : "Davrda bajarilgan ish yozilmagan"}</span>`}</div>
    ${p.doing_n || p.plan_next ? `<div class="pj-sec"><span class="k">${p.doing_n ? `Jarayonda <b>${p.doing_n}</b>` : ""}${p.doing_n && p.plan_next ? ", " : ""}${p.plan_next ? `ertangi reja <b>${p.plan_next}</b>` : ""}</span>
      ${p.doing_top ? `<ul class="pj-list"><li>${esc(p.doing_top)}</li></ul>` : ""}</div>` : ""}
    ${pAlert(p)}
    ${p.appeals ? `<button class="pj-ap" data-goap="${p.id}">${I("chat-dots")}<span><b>Murojaatlar, 30 kun: ${p.appeals.n}</b>${p.appeals.open ? `, ${p.appeals.open} tasi hal qilinmagan` : ", hammasi hal qilingan"}${p.appeals.rep ? `, ${p.appeals.rep} takroriy` : ""}</span>${I("arrow")}</button>` : ""}
    ${flags.length ? `<div class="flags">${flags.join("")}</div>` : ""}
    <div class="foot">Oxirgi xabar: ${p.last_activity ? esc(clock(p.last_activity)) : "yo'q"}</div></article>`;
}
function projectRowsTable(list) {
  return `<div class="tscroll"><table class="dtab"><thead><tr><th>Loyiha</th><th>Holat</th><th class="num">Yozdi</th><th class="num">Bajarildi</th><th class="num hm">Reja</th><th class="num">Murojaat</th><th class="num hm">So'rov</th><th class="num hm">Muammo</th><th class="hm">Oxirgi xabar</th></tr></thead>
    <tbody>${list.map((p) => { const w = p.people.filter((n) => p.team.includes(n)).length;
      return `<tr class="clk" data-project="${p.id}"><td><b>${esc(p.name)}</b></td><td>${pstTag(p)}</td>
        <td class="num">${w} / ${p.team_count}</td><td class="num"><b>${p.done}</b></td><td class="num hm">${p.plan_total ? `${p.plan_done} / ${p.plan_total}` : "—"}</td>
        <td class="num">${p.appeals ? `<b class="${p.appeals.open ? "bad-t" : ""}">${p.appeals.n}</b>` : "—"}</td>
        <td class="num hm">${p.requests_open ? `<b class="bad-t">${p.requests_open}</b>` : "0"}</td><td class="num hm">${p.problems_open || 0}</td>
        <td class="sm hm">${p.last_activity ? esc(ago(p.last_activity)) : "—"}</td></tr>`; }).join("")}</tbody></table></div>`;
}
function projectsInner(d) {
  if (!LP_F[LP.f]) LP.f = "";
  const q = fold(LP.q), cnt = (k) => d.projects.filter(LP_F[k][1]).length;
  const all = d.projects.filter((p) => LP_F[LP.f][1](p) && (!q || fold(p.name + " " + (p.chat_title || "")).includes(q))).sort(LP_SORT[LP.sort][1]);
  // hisobotsiz guruhlar (hali hech kim yozmagan) karta egallamaydi: pastda bitta qatorda
  const list = LP.f === "bosh" || LP.view === "jadval" ? all : all.filter((p) => !isEmptyProject(p));
  const idle = LP.f === "bosh" || LP.view === "jadval" ? [] : all.filter(isEmptyProject);
  return `<div class="sec-h"><h2>Loyihalar <span class="n">${d.projects.length}</span></h2>
      <div class="right"><select class="ctl" id="lpSort" aria-label="Saralash">${Object.entries(LP_SORT).map(([k, v]) => `<option value="${k}" ${LP.sort === k ? "selected" : ""}>${v[0]}</option>`).join("")}</select>
        <div class="seg" role="group" aria-label="Ko'rinish"><button data-lpv="kartalar" aria-pressed="${LP.view === "kartalar"}" title="Kartalar" aria-label="Kartalar">${I("board")}</button><button data-lpv="jadval" aria-pressed="${LP.view === "jadval"}" title="Jadval" aria-label="Jadval">${I("list")}</button></div></div></div>
    <div class="sec-tools"><label class="searchbox">${I("search")}<input id="lpQ" type="search" placeholder="Loyiha yoki guruh" value="${esc(LP.q)}" autocomplete="off"></label>
      <div class="legend">${Object.keys(LP_F).map((k) => { const n = cnt(k);
        return n || !k || LP.f === k ? `<button class="chip ${["yozmagan", "muammo", "takror"].includes(k) && n ? "alarm" : ""}" data-lpf="${k}" aria-pressed="${LP.f === k}">${LP_F[k][0]} <b>${n}</b></button>` : ""; }).join("")}</div></div>
    ${!list.length ? `<div class="panel"><div class="pnl-b">${emptyBox(d.projects.length ? "Bu filtrga mos loyiha yo'q" : "Botni ish guruhiga qo'shib admin qiling: har guruh shu yerda loyiha bo'lib chiqadi", "projects")}</div></div>`
      : LP.view === "jadval" ? `<div class="panel">${projectRowsTable(list)}</div>` : `<div class="pjgrid">${list.map((p) => projectCard(p, d)).join("")}</div>`}
    ${idle.length ? `<div class="pj-idle">${I("info")}<span>Hali hisobot tushmagan guruhlar:</span>${idle.map((p) => `<button class="chip" data-project="${p.id}">${esc(p.name)}</button>`).join("")}</div>` : ""}`;
}
function drawProjects(d) {
  const box = $("#hlProjects");
  if (!box) return;
  const focus = document.activeElement?.id === "lpQ";
  box.innerHTML = projectsInner(d);
  bindCommon(box);
  bindProjects(d);
  if (focus) { const q = $("#lpQ"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
}
function bindProjects(d) {
  const box = $("#hlProjects");
  if (!box) return;
  $("#lpSort", box).onchange = (e) => { LP.sort = e.target.value; drawProjects(d); };
  $$("[data-lpf]", box).forEach((b) => (b.onclick = () => { LP.f = LP.f === b.dataset.lpf ? "" : b.dataset.lpf; drawProjects(d); }));
  $$("[data-lpv]", box).forEach((b) => (b.onclick = () => { LP.view = b.dataset.lpv; try { localStorage.setItem("puls-lp-view", LP.view); } catch (e) { /* xotira yopiq */ } drawProjects(d); }));
  $$(".pjc", box).forEach((c) => c.addEventListener("keydown", (e) => { if (e.key === "Enter") openProjectDrawer(c.dataset.project); }));
  $$("[data-goap]", box).forEach((b) => (b.onclick = (e) => { e.stopPropagation(); goAppeals(b.dataset.goap); }));
  const qi = $("#lpQ", box);
  qi.oninput = () => { LP.q = qi.value; clearTimeout(qi._t); qi._t = setTimeout(() => drawProjects(d), 160); };
}

/* murojaat va muammolar: ochiqlari va hal bo'lganlari, loyiha va tur bo'yicha */
const BL = { data: null, key: "", kind: "", proj: "", q: "", st: "open" };
function blockersTable(rows, withProject = true) {
  return `<div class="tscroll"><table class="dtab"><thead><tr>${withProject ? "<th>Loyiha</th>" : ""}<th>Turi</th><th>Matn</th><th class="hm">Kim yozgan</th><th class="hm">Ochilgan</th><th>Holat</th></tr></thead>
    <tbody>${rows.map((x) => `<tr class="clk" data-project="${x.project_id}">${withProject ? `<td><b>${esc(x.project || "—")}</b></td>` : ""}
      <td>${x.kind === "murojaat" ? tag("So'rov", "info sm") : tag("Muammo", "idle sm")}</td><td class="wrap">${esc(x.text)}</td><td class="sm hm">${esc(x.author || "—")}</td>
      <td class="sm hm">${x.created_at ? dotDate(x.created_at.slice(0, 10)) : "—"}</td>
      <td>${x.resolved_at ? tag(`Hal bo'ldi, ${x.age} kunda`, "good sm") : tag(x.age ? x.age + " kundan beri" : "bugun", x.age >= highDays() ? "bad sm" : "warn sm")}</td></tr>`).join("")}</tbody></table></div>`;
}
function issueRows(d) {
  if (BL.data) return BL.data;
  // to'liq ro'yxat kelguncha: shu kungi ochiqlari umumiy ma'lumotdan
  return { open: d.projects.flatMap((p) => p.blocker_list.map((b) => ({ ...b, project: p.name, project_id: p.id, created_at: null }))).sort((a, b) => b.age - a.age), resolved: [], days: 30 };
}
function issuesInner(d) {
  const b = issueRows(d), q = fold(BL.q);
  const ok = (x) => (!BL.kind || x.kind === BL.kind) && (!BL.proj || String(x.project_id) === BL.proj) && (!q || fold(x.text + " " + (x.author || "") + " " + (x.project || "")).includes(q));
  const rows = (BL.st === "open" ? b.open : b.resolved).filter(ok);
  const sel = BL.proj ? d.projects.find((p) => String(p.id) === BL.proj) : null;
  // loyihalar kesimida: har guruh — bitta loyiha; qaysi loyihaga murojaat ko'p tushayotgani darhol ko'rinadi
  const per = d.projects.map((p) => ({ p, open: p.requests_open + p.problems_open, oldest: Math.max(0, ...p.blocker_list.map((x) => x.age)) }))
    .sort((a, c) => c.p.requests_open - a.p.requests_open || c.open - a.open || c.p.requests_new - a.p.requests_new || a.p.name.localeCompare(c.p.name));
  const word = d.period.key === "day" ? (S.asof ? "Shu kuni" : "Bugun") : "Davrda";
  return `<div class="pnl-h"><h2>Muammolar <span class="n">${b.open.length}</span></h2><p>Jamoa ish guruhida yozgan muammo va so'rovlar: ishni to'xtatgan narsa yoki guruhga tushgan xato</p></div>
    <div class="tscroll" style="margin-top:14px"><table class="dtab bl-proj"><thead><tr><th>Loyiha (guruh)</th><th class="num">Ochiq so'rov</th><th class="num">Ochiq muammo</th><th class="num">Eng eskisi</th><th class="num hm">${word} keldi</th><th class="num hm">${word} yopildi</th></tr></thead>
      <tbody>${per.map((x) => `<tr class="clk ${String(x.p.id) === BL.proj ? "on" : ""}" data-blp="${x.p.id}">
        <td><b>${esc(x.p.name)}</b></td>
        <td class="num">${x.p.requests_open ? `<b class="bad-t">${x.p.requests_open}</b>` : `<span class="sm">0</span>`}</td>
        <td class="num">${x.p.problems_open ? `<b>${x.p.problems_open}</b>` : `<span class="sm">0</span>`}</td>
        <td class="num">${x.open ? tag(x.oldest ? x.oldest + " kun" : S.asof ? "shu kuni" : "bugun", x.oldest >= highDays() ? "bad sm" : "warn sm") : `<span class="sm">—</span>`}</td>
        <td class="num hm">${x.p.requests_new || `<span class="sm">0</span>`}</td><td class="num hm">${x.p.requests_closed || `<span class="sm">0</span>`}</td></tr>`).join("")}</tbody></table></div>
    <div class="tools-row">
      ${sel ? `<button class="chip" aria-pressed="true" data-blp="${sel.id}">${esc(sel.name)} ${I("close")}</button>` : ""}
      <div class="seg" role="group" aria-label="Holati"><button data-blst="open" aria-pressed="${BL.st === "open"}">Ochiq</button><button data-blst="done" aria-pressed="${BL.st === "done"}">Hal bo'lgan</button></div>
      <div class="seg" role="group" aria-label="Turi"><button data-blk="" aria-pressed="${!BL.kind}">Hammasi</button><button data-blk="murojaat" aria-pressed="${BL.kind === "murojaat"}">So'rov</button><button data-blk="muammo" aria-pressed="${BL.kind === "muammo"}">Muammo</button></div>
      <label class="searchbox">${I("search")}<input id="blQ" type="search" placeholder="Matn yoki muallif" value="${esc(BL.q)}" autocomplete="off"></label>
    </div>
    ${rows.length ? blockersTable(rows, !sel) : `<div class="pnl-b">${emptyBox(BL.st === "open" ? (sel ? "Bu loyihada ochiq so'rov ham, muammo ham yo'q" : "Ochiq so'rov va muammo yo'q") : "Oxirgi 30 kunda hal bo'lgani yo'q", BL.st === "open" ? "check" : "info")}</div>`}`;
}
function drawIssues(d) {
  const box = $("#hlIssues");
  if (!box) return;
  const focus = document.activeElement?.id === "blQ";
  box.innerHTML = issuesInner(d);
  bindCommon(box);
  bindIssues(d);
  if (focus) { const q = $("#blQ"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
}
function bindIssues(d) {
  const box = $("#hlIssues");
  if (!box) return;
  $$("[data-blk]", box).forEach((x) => (x.onclick = () => { BL.kind = x.dataset.blk; drawIssues(d); }));
  $$("[data-blst]", box).forEach((x) => (x.onclick = () => { BL.st = x.dataset.blst; drawIssues(d); }));
  $$("[data-blp]", box).forEach((x) => (x.onclick = (e) => { e.stopPropagation(); BL.proj = BL.proj === x.dataset.blp ? "" : x.dataset.blp; drawIssues(d); }));
  const qi = $("#blQ", box);
  qi.oninput = () => { BL.q = qi.value; clearTimeout(qi._t); qi._t = setTimeout(() => drawIssues(d), 160); };
}
async function loadIssues(d) {
  const key = [S.version, S.asof, S.dept].join("|");
  if (BL.key === key) return;
  try { BL.data = await api("api/blockers?" + new URLSearchParams({ days: 30, ...(S.asof ? { asof: S.asof } : {}) })); BL.key = key; }
  catch (e) { return; }
  if (S.tab === "holat") drawIssues(S.data);
}

/* rejadan qolgan bandlar: hisobotdagi "Ertangi reja" o'z kunida bajarilmagan */
function planPanel(d) {
  const miss = d.projects.flatMap((p) => p.plan_missed.map((x) => ({ ...x, project: p.name, pid: p.id })));
  return `<section class="panel" id="hlReja"><div class="pnl-h"><h2>Rejadan qolgan <span class="n">${miss.length}</span></h2></div>
    ${miss.length ? `<div class="tscroll"><table class="dtab"><thead><tr><th>Band</th><th>Kim</th><th class="hm">Loyiha</th><th>Kuni</th></tr></thead>
      <tbody>${miss.slice(0, 20).map((x) => `<tr class="clk" data-project="${x.pid}"><td class="wrap">${esc(x.title)}</td><td>${esc(x.who || "—")}</td><td class="hm">${esc(x.project)}</td><td class="sm">${dotDate(x.day)}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="pnl-b">${emptyBox(d.projects.some((p) => p.plan_total) ? "Rejadagi hamma band o'z kunida bajarildi" : "«Ertangi reja» bandlari hali yozilmagan", "check")}</div>`}</section>`;
}

/* guruhlar: har Telegram guruh — bitta loyiha; tarix yuklash va botni sinash shu yerdan */
function groupsInner(d) {
  const list = d.projects.slice().sort((a, b) => (b.last_activity || "").localeCompare(a.last_activity || ""));
  const unl = d.unlinked || [];
  // yordam guruhlari: tizim foydalanuvchilari murojaat yozadi (jamoa emas), tizimiga bog'langan
  const sys = Object.fromEntries((S.meta?.systems || []).map((p) => [p.id, p.name]));
  const support = (S.meta?.chats || []).filter((c) => c.kind === "yordam" && !c.demo);
  const kindBtn = (chatId) => (can("settings") && chatId ? `<button class="icon-btn sm ck-btn" data-ck="${chatId}" title="Guruh turini o'zgartirish" aria-label="Guruh turini o'zgartirish">${I("tuning")}</button>` : "");
  return `<div class="pnl-h"><h2>Guruhlar <span class="n">${list.length}</span></h2>
      <div class="right">${can("import") ? `<button class="btn btn-line sm" data-gx="import">${I("upload")}Tarixni yuklash</button>` : ""}
        <button class="btn btn-line sm" data-gx="bottest">${I("check")}Botni sinash</button>
        ${can("settings") ? `<button class="btn btn-line sm" data-gx="settings">${I("tuning")}Muddat ${esc(deadline())}</button><button class="btn btn-line sm" data-gx="telegram">${I("send")}Telegram</button>` : ""}</div></div>
    <div class="tscroll" style="margin-top:14px"><table class="dtab"><thead><tr><th>Guruh va loyiha</th><th class="hm">Turi</th><th class="num hm">A'zolar</th><th class="num">Yozib turadi</th><th class="hm">Oxirgi xabar</th><th class="num hm">7 kunda</th><th>Holat</th></tr></thead>
      <tbody>${list.map((p) => `<tr class="clk" data-project="${p.id}"><td><b>${esc(p.name)}</b>${p.chat_title && p.chat_title !== p.name ? `<div class="sm">${esc(p.chat_title)}</div>` : ""}</td>
        <td class="hm"><span class="ck-cell">${tag("Ish guruhi", "idle sm")}${kindBtn(p.chat_id)}</span></td>
        <td class="num hm">${p.members_count || "—"}</td><td class="num">${p.team_count}</td><td class="sm hm">${p.last_activity ? esc(clock(p.last_activity)) : "xabar yo'q"}</td>
        <td class="num hm">${p.msgs7}</td><td>${pstTag(p)}</td></tr>`).join("")}
      ${support.map((c) => `<tr class="clk" data-goap="${c.projects[0] || 0}"><td><b>${esc(c.title)}</b><div class="sm">Tizim: ${esc(c.projects.map((x) => sys[x]).filter(Boolean).join(", ") || "belgilanmagan")}</div></td>
        <td class="hm"><span class="ck-cell">${tag("Yordam guruhi", "info sm")}${kindBtn(c.id)}</span></td>
        <td class="num hm">—</td><td class="num">—</td><td class="sm hm">murojaatlar</td><td class="num hm">—</td><td>${tag("Murojaatlar", "info sm")}</td></tr>`).join("")}
      ${!list.length && !support.length ? `<tr><td colspan="7">${emptyBox("Botni ish guruhiga qo'shib admin qiling", "send")}</td></tr>` : ""}</tbody></table></div>
    ${unl.length && can("people") ? `<div class="conn"><b>Tasdiqlanmagan a'zolar: ${unl.length}</b><span class="teamchips" style="margin:0">${unl.slice(0, 8).map((u) => `<span class="tdot wait">${esc(u.name)}</span>`).join("")}</span>
      <button class="btn btn-dark sm" data-gx="links">${I("user-check")}Tasdiqlash</button></div>` : ""}
    <div class="conn"><span>Bot <b>@${esc(S.meta?.bot || "puls_loyiha_bot")}</b>: ish guruhiga qo'shilsa guruh loyiha bo'ladi, yordam guruhiga qo'shilsa murojaatlarni yig'adi (u yerda jim turadi)</span>
      <span class="ap-conn-b"><button class="lnk" data-gx="guide">Yozish formati${I("arrow")}</button><button class="lnk" data-gx="support">Yordam guruhi${I("arrow")}</button>${can("settings") ? `<button class="lnk" data-gx="bots">Chatbotlar${I("arrow")}</button>` : ""}</span></div>`;
}
function bindGroups() {
  const box = $("#hlGroups");
  if (!box) return;
  $$("[data-ck]", box).forEach((b) => (b.onclick = (e) => { e.stopPropagation(); openChatKind(b.dataset.ck); }));
  $$("[data-goap]", box).forEach((r) => (r.onclick = () => goAppeals(+r.dataset.goap || 0)));
  $$("[data-gx]", box).forEach((b) => (b.onclick = (e) => { e.stopPropagation(); ({ import: openImport, bottest: openBotTest, settings: openSettings, telegram: openTelegram, guide: openGuide, links: openLinks,
    support: openSupportGuide, bots: () => openBots() })[b.dataset.gx](); }));
}

/* ================= loyiha: yon oyna (sahifadan chiqmasdan) ================= */
const PJ = { tab: "kunlar", day: "", id: "", det: null, feed: null, bl: null, ap: null };
async function openProjectDrawer(id, day) {
  PJ.id = String(id); PJ.day = day || ""; PJ.bl = null; PJ.ap = null;
  if (day) PJ.tab = "kunlar";
  S.open = "j:" + id; writeHash();
  openDrawer(skelHead());
  $("#drawer").classList.add("xwide");
  try {
    const qs = query().replace(/&?chat=[^&]*/, "");
    const [det, feed] = await Promise.all([api(`api/project/${id}?` + qs), api(`api/project/${id}/feed?` + new URLSearchParams({ until: dayOf(S.data), days: 16 }))]);
    PJ.det = det; PJ.feed = feed;
  } catch (e) { closeDrawer(); toast(esc(e.message), "danger"); return; }
  if (S.open !== "j:" + id) return;
  drawProjectDrawer();
}
function drawProjectDrawer() {
  const sheet = $("#drawer .sheet"), d = S.data, p = PJ.det.project, msgs = PJ.feed.messages, day = dayOf(d);
  const last = p.days10[p.days10.length - 1] || [day, 0, 0];
  const plan = pct(p.plan_done, p.plan_total), open = p.blocker_list.length;
  const tabs = [["kunlar", "Kunlar", null], ["xabarlar", "Xabarlar", msgs.length], ["murojaat", "Muammolar", open, open && p.blocker_list.some((b) => b.age >= highDays())],
    ...(p.appeals ? [["yordam", "Murojaatlar", p.appeals.n, p.appeals.open > 0]] : []),
    ["reja", "Rejadan qolgan", p.plan_missed.length], ["vazifalar", "Ochiq vazifalar", PJ.det.open_tasks.length], ["jamoa", "Jamoa", p.team_count]];
  if (!tabs.some((t) => t[0] === PJ.tab)) PJ.tab = "kunlar";
  const acts = S.asof || !can("decide") ? "" : `<div class="sh-acts"><button class="btn btn-line sm" id="pjPing">${I("chat-dots")}Holatni so'rash</button>
    ${open ? `<button class="btn btn-line sm" id="pjBl">${I("bell")}Muammo bo'yicha eslatish</button>` : ""}<button class="btn btn-line sm" id="pjDl">${I("deadline")}Muddat belgilash</button></div>`;
  sheet.innerHTML = `<div class="sh-head"><div style="min-width:0;flex:1"><h2>${esc(p.name)}</h2>
      <div class="meta">${pstTag(p)}${p.chat_title && p.chat_title !== p.name ? `<span>${esc(p.chat_title)}</span>` : ""}<span>${esc(periodWord(d))}</span></div></div>
      <button class="icon-btn x" aria-label="Yopish">${I("close")}</button></div>
    <div class="sh-body pj-sheet">${acts}
      <div class="band b5">
        <div class="metric"><span class="l">Yozdi</span><span class="v">${last[1]}<small> / ${last[2]}</small></span><span class="d">${dotDate(last[0])}</span></div>
        <div class="metric"><span class="l">Bajarildi</span><span class="v">${p.done}</span><span class="d">${esc(periodWord(d))}</span></div>
        <div class="metric"><span class="l">Reja</span><span class="v">${plan == null ? "—" : plan + "%"}</span><span class="d">${p.plan_total ? `${p.plan_done} / ${p.plan_total} band` : "band yo'q"}</span></div>
        <div class="metric"><span class="l">So'rov, muammo</span><span class="v ${p.requests_open >= 3 || p.requests_oldest >= 2 ? "bad" : ""}">${open}</span><span class="d">${open ? `${p.requests_open} so'rov, ${p.problems_open} muammo` : "yo'q"}</span></div>
        <div class="metric"><span class="l">Kechikkan</span><span class="v ${p.late_reports.length ? "warn" : ""}">${p.late_reports.length}</span><span class="d">${p.late_reports.length ? esc(p.late_reports.slice(0, 2).map(first).join(", ")) : esc(deadline()) + " dan keyin"}</span></div>
      </div>
      <dl class="pj-meta"><div><dt>Jamoa</dt><dd>${p.team_count} kishi${p.members_count ? `, guruhda ${p.members_count}` : ""}</dd></div>
        <div><dt>Oxirgi xabar</dt><dd>${p.last_activity ? esc(clock(p.last_activity)) : "—"}</dd></div>
        <div><dt>Kuzatuv boshlangan</dt><dd>${p.start_date ? dotDate(p.start_date) : "—"}</dd></div>
        <div><dt>Muddat</dt><dd>${p.deadline ? `${esc(p.deadline_label)}, ${p.days_left < 0 ? -p.days_left + " kun o'tdi" : p.days_left + " kun qoldi"}` : "belgilanmagan"}</dd></div></dl>
      <div class="ptabs" role="tablist">${tabs.map((t) => `<button role="tab" data-pjt="${t[0]}" aria-selected="${PJ.tab === t[0]}">${t[1]}${t[2] != null ? `<span class="n ${t[3] ? "bad" : ""}">${t[2]}</span>` : ""}</button>`).join("")}</div>
      <div id="pjBody">${pjTab(d)}</div></div>`;
  $(".x", sheet).onclick = closeDrawer;
  bindCommon(sheet);
  $$("[data-pjt]", sheet).forEach((b) => (b.onclick = () => { PJ.tab = b.dataset.pjt; PJ.day = ""; drawPjBody(); }));
  bindPjBody(sheet);
  $("#pjPing")?.addEventListener("click", () => openAction({ type: "ping_project", project_id: p.id }));
  $("#pjBl")?.addEventListener("click", () => openAction({ type: "ping_blocker", project_id: p.id }));
  $("#pjDl")?.addEventListener("click", () => openAction({ type: "deadline", project_id: p.id, date: p.eta_date || isoDay(new Date(Date.now() + 7 * 864e5)) }));
  if (PJ.day) { const t = $(`[data-pday="${PJ.day}"]`, sheet); if (t) setTimeout(() => t.scrollIntoView({ behavior: "smooth", block: "start" }), 80); PJ.day = ""; }
}
function drawPjBody() {
  const sheet = $("#drawer .sheet"), body = $("#pjBody", sheet);
  if (!body) return;
  body.innerHTML = pjTab(S.data);
  $$("[data-pjt]", sheet).forEach((b) => b.setAttribute("aria-selected", String(b.dataset.pjt === PJ.tab)));
  bindCommon(body);
  bindPjBody(body);
}
function bindPjBody(root) {
  $$("[data-fixm]", root).forEach((b) => (b.onclick = (e) => {
    e.stopPropagation();
    const m = PJ.feed.messages.find((x) => String(x.id) === b.dataset.fixm);
    if (!m) return;
    if (!S.data.feed.some((f) => f.id === m.id)) S.data.feed.push({ id: m.id, author: m.author, text: m.text, kind: m.kind, project_id: PJ.det.project.id });
    openFix(m.id);
  }));
  $$("[data-goap]", root).forEach((b) => (b.onclick = () => goAppeals(b.dataset.goap)));
  $$("[data-apid]", root).forEach((r) => (r.onclick = () => openAppeal(+r.dataset.apid)));
  if (PJ.tab === "yordam" && !PJ.ap) {
    api("api/appeals?" + new URLSearchParams({ days: 30, project: PJ.det.project.id, limit: 30, ...(S.asof ? { asof: S.asof } : {}) }))
      .then((a) => { PJ.ap = a; if (PJ.tab === "yordam") drawPjBody(); }).catch(() => {});
  }
  if (PJ.tab === "murojaat" && !PJ.bl) {
    api("api/blockers?" + new URLSearchParams({ days: 60, ...(S.asof ? { asof: S.asof } : {}) })).then((b) => { PJ.bl = b; if (PJ.tab === "murojaat") drawPjBody(); }).catch(() => {});
  }
}
const itemLi = (x) => `<li>${esc(x.title)}${x.progress != null ? `<div class="pctbar"><span><i style="width:${x.progress}%"></i></span>${x.progress}%</div>` : ""}</li>`;
function mergeSections(ms) {
  const out = {};
  ms.forEach((m) => Object.entries(m.sections).forEach(([k, v]) => { out[k] = (out[k] || []).concat(v); }));
  return out;
}
function reportCard(name, ms) {
  const sec = mergeSections(ms), firstM = ms[ms.length - 1], late = ms.some((m) => m.late), h = ms.find((m) => m.holat)?.holat;
  const reps = ms.flatMap((m) => m.repeats), ai = ms.some((m) => m.source === "ai");
  const col = (list, title) => `<div class="col"><h4>${title}</h4>${list.length ? `<ul class="items">${list.map(itemLi).join("")}</ul>` : `<span class="items empty2">—</span>`}</div>`;
  return `<article class="rcard"><div class="hd">${ava(name || "?")}<b data-person="${esc(name || "")}">${esc(name || "Noma'lum")}</b><span class="t">${firstM.date.slice(11, 16)}${firstM.date.slice(0, 10) > firstM.day ? ", ertasi kuni" : ""}</span>
      ${late ? tag("kechikkan", "warn sm") : ""}${holatTag(h, true)}${ai ? `<span class="chiplet" title="Shablonsiz yozilgan: bot ma'nosini AI orqali tushundi">AI</span>` : ""}${ms.some((m) => m.edited) ? `<span class="chiplet">tahrirlangan</span>` : ""}</div>
    <div class="cols">${col(sec.done || [], "Bajarildi")}${col(sec.doing || [], "Jarayonda")}${col((sec.plan || []).concat(sec.task || []), "Ertangi reja")}</div>
    ${(sec.blocker || []).map((b) => `<div class="blk">${I("danger")}<span>${esc(b.title)}</span></div>`).join("")}
    ${reps.length ? `<div class="rep">${I("danger")}<span>Qayta yozilgan: ${reps.map((r) => repBtn(r.id, "«" + esc(r.title) + "»", "rep-link")).join(", ")}</span></div>` : ""}</article>`;
}
function pjTab(d) {
  const p = PJ.det.project, msgs = PJ.feed.messages, final = (day) => dayFinal(day, d);
  if (PJ.tab === "kunlar") {
    const byDay = {};
    msgs.forEach((m) => (byDay[m.day] = byDay[m.day] || []).push(m));
    const days = [...new Set([...p.days10.map((x) => x[0]), ...Object.keys(byDay)])].filter((k) => k <= dayOf(d) && (byDay[k] || p.days10.some((x) => x[0] === k && x[2]))).sort().reverse().slice(0, 12);
    if (!days.length) return emptyBox("Bu loyihada hali hisobot yo'q", "doc");
    return days.map((k) => {
      const ms = byDay[k] || [], cell = p.days10.find((x) => x[0] === k);
      const people = {};
      ms.forEach((m) => (people[m.author || ""] = people[m.author || ""] || []).push(m));
      const wrote = new Set(Object.keys(people)), miss = p.team.filter((n) => !wrote.has(n));
      const we = isWeekend(k);
      return `<section class="pday" data-pday="${k}"><div class="pday-h"><h3>${longDay(k)}</h3>
          ${cell && cell[2] ? tag(`${cell[1]} / ${cell[2]} yozdi`, cell[1] >= cell[2] ? "good sm" : cell[1] ? "warn sm" : "bad sm") : ""}
          ${miss.length && !we && ms.length ? `<span class="miss">${final(k) ? "Yozmadi" : "Hali yozmadi"}: ${esc(miss.join(", "))}</span>` : ""}</div>
        ${ms.length ? `<div class="rcards">${Object.entries(people).map(([n, list]) => reportCard(n, list)).join("")}</div>`
          : `<div class="absent-card">${I("info")}${we ? "Dam olish kuni" : final(k) ? `Hech kim yozmadi${p.team.length ? ": " + esc(p.team.join(", ")) : ""}` : "Hisobotlar kutilmoqda"}</div>`}</section>`;
    }).join("");
  }
  if (PJ.tab === "xabarlar") {
    if (!msgs.length) return emptyBox("Oxirgi 16 kunda ish xabari yo'q", "chat-dots");
    return `<div class="msgs">${msgs.map((m) => {
      const s = m.sections, n = (k) => (s[k] || []).length;
      const blk = (s.blocker || []).map((b) => b.title).join("; ");
      const warns = [];
      if (m.late) warns.push(["", "clock", `Muddatdan keyin yozilgan (${deadline()})`]);
      m.repeats.forEach((r) => warns.push(["bad", "danger", `Qayta yozilgan: «${esc(r.title)}»`, r.id]));
      if (m.requests) warns.push(["bad", "chat-dots", "So'rov sifatida qayd etildi"]);
      if (m.edited) warns.push(["", "pen", "Xabar tahrirlangan"]);
      if (m.deleted) warns.push(["bad", "trash", "Xabar guruhdan o'chirilgan"]);
      return `<article class="msgc ${m.deleted ? "del" : ""}"><div class="body"><div class="who">${ava(m.author || "?")}<b data-person="${esc(m.author || "")}">${esc(m.author || "Noma'lum")}</b><span>${esc(clock(m.date))}</span>${m.source === "ai" ? `<span class="chiplet">AI</span>` : ""}</div><pre>${esc(m.text)}</pre></div>
        <div class="parsed"><h4>Bot ajratib oldi</h4><dl class="kv">
          <dt>Hisobot kuni</dt><dd>${dotDate(m.day)}</dd>
          ${n("done") ? `<dt>Bajarildi</dt><dd>${n("done")} ta</dd>` : ""}${n("doing") ? `<dt>Jarayonda</dt><dd>${n("doing")} ta</dd>` : ""}
          ${n("plan") ? `<dt>Ertangi reja</dt><dd>${n("plan")} ta</dd>` : ""}${n("task") ? `<dt>Vazifa</dt><dd>${n("task")} ta</dd>` : ""}
          <dt>Bloker</dt><dd>${blk ? esc(blk) : "yo'q"}</dd>
          ${m.holat ? `<dt>Holat</dt><dd>${holatTag(m.holat, true)}</dd>` : ""}
          <dt>O'qildi</dt><dd class="lt">${esc(SRC_WORD[m.source] || m.source || "—")}</dd></dl>
          ${warns.length ? `<ul class="warns">${warns.map((w) => `<li class="${w[0]}">${I(w[1])}<span>${w[2]}${w[3] ? " " + repBtn(w[3], "dalil", "rep-link") : ""}</span></li>`).join("")}</ul>` : ""}
          ${can("correct") && !S.asof ? `<button class="btn btn-ghost sm fixb" data-fixm="${m.id}">${I("pen")}Tuzatish</button>` : ""}</div></article>`;
    }).join("")}</div>`;
  }
  if (PJ.tab === "murojaat") {
    const rows = PJ.bl ? PJ.bl.open.concat(PJ.bl.resolved).filter((x) => String(x.project_id) === String(p.id))
      : p.blocker_list.map((b) => ({ ...b, project_id: p.id, created_at: null, resolved_at: null }));
    if (!rows.length) return emptyBox("Bu loyihada so'rov ham, muammo ham yo'q");
    return `<div class="panel">${blockersTable(rows, false)}</div>`;
  }
  if (PJ.tab === "yordam") {
    const a = PJ.ap;
    if (!a) return `<div class="sk" style="height:200px"></div>`;
    const k = a.kpi;
    return `<div class="band ap-band b4">
        <div class="metric"><span class="l">Murojaatlar, 30 kun</span><span class="v">${nf(k.n)}</span>${apDeltaMetric(k.delta)}</div>
        <div class="metric"><span class="l">Hal qilingan</span><span class="v">${apPct(k.res_rate)}</span><span class="d">${k.open ? k.open + " tasi hal qilinmagan" : "hammasi"}</span></div>
        <div class="metric"><span class="l">O'rtacha hal qilish</span><span class="v">${apH(k.avg_h)}</span><span class="d">${k.prev_avg_h != null ? "oldin " + apH(k.prev_avg_h) : ""}</span></div>
        <div class="metric"><span class="l">Takroriy</span><span class="v ${k.rep_rate > .12 ? "bad" : ""}">${apPct(k.rep_rate)}</span><span class="d">${k.rep} ta</span></div></div>
      <div class="panel">${apFeedTable(a.feed.items, false)}</div>
      <div class="foot-r"><button class="btn btn-line sm" data-goap="${p.id}">${I("chart")}To'liq tahlil: Murojaatlar bo'limida</button></div>`;
  }
  if (PJ.tab === "reja") {
    if (!p.plan_missed.length) return emptyBox(p.plan_total ? "Rejadagi hamma band o'z kunida bajarildi" : "«Ertangi reja» bandlari yozilmagan", "check");
    return `<div class="panel"><div class="tscroll"><table class="dtab"><thead><tr><th>Band</th><th>Kim</th><th>Kuni</th></tr></thead>
      <tbody>${p.plan_missed.map((x) => `<tr class="clk" data-person="${esc(x.who || "")}"><td class="wrap">${esc(x.title)}</td><td>${esc(x.who || "—")}</td><td class="sm">${dotDate(x.day)}</td></tr>`).join("")}</tbody></table></div></div>`;
  }
  if (PJ.tab === "vazifalar") {
    const t = PJ.det.open_tasks;
    if (!t.length) return emptyBox("Ochiq vazifa yo'q", "check");
    return `<div class="panel"><div class="tscroll"><table class="dtab"><thead><tr><th>Vazifa</th><th>Kimda</th><th class="hm">Bergan</th><th>Muddat</th></tr></thead>
      <tbody>${t.slice(0, 80).map((x) => `<tr class="clk" data-person="${esc(x.assignee || "")}"><td class="wrap">${esc(x.title)}</td><td>${esc(x.assignee || "—")}</td><td class="sm hm">${esc(x.giver || "—")}</td><td>${dueTag(x)}</td></tr>`).join("")}</tbody></table></div></div>`;
  }
  const load = Object.fromEntries(PJ.det.team.map((x) => [x.name, x]));
  const names = [...new Set([...p.team, ...PJ.det.team.map((x) => x.name)])];
  const wrote = new Set(p.people), fin = dayFinal(dayOf(d), d);
  return `<div class="panel"><div class="tscroll"><table class="dtab"><thead><tr><th>Xodim</th><th>${d.period.key === "day" ? "Shu kun" : "Davrda"}</th><th class="hm">O'z holati</th><th class="num">Ochiq</th><th class="num">Bajardi</th></tr></thead>
    <tbody>${names.map((n) => { const pp = (S.data?.people || []).find((x) => x.name === n), l = load[n] || { open: 0, done: 0 };
      return `<tr class="clk" data-person="${esc(n)}"><td><span class="who">${ava(n, pp?.department, pp?.state)}<span><b>${esc(n)}</b><small>${esc(pp?.department || "")}</small></span></span></td>
        <td>${wrote.has(n) ? tag(p.late_reports.includes(n) ? "Kechikdi" : "Yozdi", p.late_reports.includes(n) ? "warn" : "good", true) : tag(fin ? "Yozmadi" : "Kutilmoqda", fin ? "bad" : "idle", true)}</td>
        <td class="hm">${holatTag(p.holat[n]) || `<span class="sm">—</span>`}</td><td class="num">${l.open}</td><td class="num"><b>${l.done}</b></td></tr>`; }).join("")}</tbody></table></div></div>`;
}

/* ================= qayta yozilgan ish: dalil ================= */
// Ikkala xabar yonma-yon: qaysi kuni, kim, qaysi guruhda yozgan va xabarning o'zi (ish nomi ichida belgilanadi)
function markItem(text, title) {
  const t = esc(text || ""), low = t.toLowerCase();
  for (const probe of [title, String(title || "").split(/\s+/).slice(0, 5).join(" "), String(title || "").split(/\s+/).slice(0, 3).join(" ")]) {
    const k = esc(probe || "").toLowerCase();
    if (k.length < 6) continue;
    const i = low.indexOf(k);
    if (i >= 0) { const end = t.indexOf("\n", i); const j = end < 0 ? t.length : end; return t.slice(0, i) + "<mark>" + t.slice(i, j) + "</mark>" + t.slice(j); }
  }
  return t;
}
async function openRepeatProof(tid) {
  openModal("Qayta yozilgan ish", `<div class="sk" style="height:260px"></div>`, "", true);
  let r;
  try { r = await api("api/repeat/" + tid); } catch (e) { closeModal(); toast(esc(e.message), "danger"); return; }
  const side = (x, label, now) => !x ? `<div class="rp-col"><div class="rp-h"><b>${label}</b></div>${emptyBox("Asl ish topilmadi", "info")}</div>` : `
    <div class="rp-col ${now ? "now" : ""}"><div class="rp-h"><b>${label}</b><span>${esc(longDay((x.done_at || x.created_at).slice(0, 10)))}, ${(x.msg_date || x.done_at || "").slice(11, 16)}</span></div>
      <div class="rp-who">${ava(x.assignee || "?")}<span><b>${esc(x.assignee || "—")}</b><small>${esc(x.chat_title || x.project || "")}</small></span></div>
      <div class="rp-item">«${esc(x.title)}»</div>
      ${x.text ? `<pre class="rp-msg ${x.deleted_at ? "del" : ""}">${markItem(x.text, x.title)}</pre>` : `<div class="empty">${I("info")}<span>Xabar matni saqlanmagan</span></div>`}
      ${x.link ? `<a class="lnk" href="${esc(x.link)}" target="_blank" rel="noopener">${I("send")}Telegramda ochish</a>` : ""}</div>`;
  const o = r.old, n = r.now;
  const lead = r.kind === "nusxa" && o && o.assignee !== n.assignee
    ? `<span><b>${esc(n.assignee)}</b> ${esc(o.assignee)}ning ${esc(uzDate(parseTs(o.done_at || o.created_at)))}dagi ishini o'z hisobotiga yozgan</span>`
    : `<span><b>${esc(n.assignee)}</b> ${o ? esc(uzDate(parseTs(o.done_at || o.created_at))) + "da" : "oldin"} yozgan ishini ${esc(uzDate(parseTs(n.done_at)))}da yana yozgan</span>`;
  $("#modal .mb").innerHTML = `<p class="rp-lead">${lead}${r.score ? `<span class="tag ${r.score >= 0.9 ? "bad" : "warn"} sm">o'xshashlik ${Math.round(r.score * 100)}%</span>` : ""}</p>
    <div class="rp">${side(o, "Oldin", false)}${side(n, "Bu safar", true)}</div>${r.note ? `<p class="rp-note">${esc(r.note)}</p>` : ""}`;
  $("#modal .mbox").insertAdjacentHTML("beforeend", `<div class="mf">${can("decide") ? `<button class="btn btn-line" id="rpNo">${I("check")}Bu takror emas</button>` : ""}<button class="btn btn-dark" data-close>Yopish</button></div>`);
  $$("#modal [data-close]").forEach((b) => (b.onclick = closeModal));
  $("#rpNo")?.addEventListener("click", async () => {
    try { await api("api/task/repeat", { json: { task_id: +tid, kind: "rad" } }); } catch (e) { toast(esc(e.message), "danger"); return; }
    closeModal(); toast("Belgi olib tashlandi: ish reytingga qaytdi", "check"); load(true);
  });
}

/* ================= botni sinash (oyna) ================= */
const GX = { text: "", res: null, busy: false };
const GX_TEMPLATE = "#loyiha_tegi\nSana: " + (() => { const t = new Date(); return String(t.getDate()).padStart(2, "0") + "." + String(t.getMonth() + 1).padStart(2, "0") + "." + t.getFullYear(); })()
  + "\nHolat: Yashil\nBajarildi:\n1. Login sahifasi tayyorlandi\nJarayonda:\n1. Hisobotlar bo'limi — 60%\nErtangi reja:\n1. Hisobotlar bo'limini tugatish\nBloker: yo'q";
function openBotTest() {
  openModal("Botni sinash", `<form class="bt-f" id="gxForm"><textarea id="gxText" placeholder="Guruhga yoziladigan xabar" spellcheck="false">${esc(GX.text)}</textarea>
      <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn btn-dark">${I("check")}Tekshirish</button><button type="button" class="btn btn-line" id="gxTpl">${I("doc")}Shablon</button></div></form>
    <div id="gxRes" style="margin-top:14px">${gxResult()}</div>`, "", true);
  const ta = $("#gxText");
  ta.oninput = () => (GX.text = ta.value);
  $("#gxTpl").onclick = () => { GX.text = ta.value = GX_TEMPLATE; ta.focus(); };
  $("#gxForm").onsubmit = async (e) => {
    e.preventDefault();
    if (!ta.value.trim() || GX.busy) return;
    GX.busy = true;
    try { GX.res = await api("api/parse-test", { json: { text: ta.value } }); } catch (err) { GX.res = { error: err.message }; }
    GX.busy = false;
    $("#gxRes").innerHTML = gxResult();
  };
  setTimeout(() => ta.focus(), 40);
}
function gxResult() {
  const r = GX.res;
  if (!r) return "";
  if (r.error) return `<div class="bt-res bad">${esc(r.error)}</div>`;
  const secs = Object.entries(r.sections || {});
  if (r.kind === "none" || !secs.length) {
    return `<div class="bt-res mid"><b>${r.work ? "Bot buni ish xabari deb biladi" : "Bu ish xabariga o'xshamaydi"}</b>
      <span>${r.work ? (r.ai ? "Shablonsiz: guruhda bot ma'nosini AI orqali tushunadi." : "Shablonsiz va AI ulanmagan: «Bajarildi:» bo'limi bilan yozilsa aniq o'qiladi.") : "Salom, rahmat kabi gaplar hisobotga kirmaydi."}</span></div>`;
  }
  return `<div class="bt-res"><b>Bot shunday tushundi</b><dl class="kv">
      <dt>Turi</dt><dd>${secs.length > 1 ? "Kunlik hisobot" : esc(KIND[r.kind] || r.kind)}</dd>
      ${r.day ? `<dt>Hisobot kuni</dt><dd>${dotDate(r.day)}</dd>` : ""}${r.project ? `<dt>Teg</dt><dd>#${esc(r.project)}</dd>` : ""}
      ${r.department ? `<dt>Bo'lim</dt><dd>${esc(r.department)}</dd>` : ""}${r.holat ? `<dt>Holat</dt><dd>${holatTag(r.holat, true)}</dd>` : ""}
      ${secs.map(([k, v]) => `<dt>${esc(SEC[k] || k)}</dt><dd>${v.length} ta<ul class="items" style="margin-top:4px;font-weight:500">${v.slice(0, 6).map(itemLi).join("")}</ul></dd>`).join("")}</dl></div>`;
}

/* ================= xodimni qo'shish va tahrirlash ================= */
// Qo'lda qo'shilgan xodimga shaxsiy havola beriladi: u bossa Telegram akkaunti bog'lanadi (guruhga yozgan bo'lsa, yozuvlari ham)
const linkMsg = (name, link) => `Assalomu alaykum, ${first(name)}! Puls'ga ulanish uchun shu havolani bosing va «Start» ni bosing:\n${link}`;
function openAddPerson() {
  const depts = S.meta?.departments || [];
  openModal("Xodim qo'shish", `<div class="field"><label for="apName">Ism-familiya</label><input id="apName" maxlength="60" autocomplete="off" placeholder="Masalan: Dilshod Karimov"></div>
    <div class="field"><label for="apDept">Bo'lim</label><select id="apDept"><option value="">Tanlanmagan</option>${depts.map((x) => `<option>${esc(x)}</option>`).join("")}</select></div>
    <div id="apRes"></div>`,
    `<button class="btn btn-ghost" data-close>Bekor qilish</button><button class="btn btn-dark" id="apGo">${I("user-plus")}Qo'shish va havola olish</button>`);
  const inp = $("#apName");
  setTimeout(() => inp.focus(), 40);
  const go = async () => {
    const name = inp.value.trim();
    if (name.length < 2) { inp.focus(); return; }
    const b = $("#apGo"); b.disabled = true;
    let r;
    try { r = await api("api/person/add", { json: { name, department: $("#apDept").value || null } }); }
    catch (e) { b.disabled = false; toast(esc(e.message), "danger"); return; }
    load(true);
    $("#modal .mb").innerHTML = `<div class="ap-done"><p><b>${esc(r.name)}</b> qo'shildi. Shu havolani unga yuboring: bossa, Telegram akkaunti panelga bog'lanadi va guruhdagi hisobotlari hisobga kiradi.</p>
      <div class="contact"><span class="lnk-box">${esc(r.link)}</span><button class="btn btn-dark sm" id="apCopy">${I("copy")}Xabar bilan nusxalash</button></div></div>`;
    $("#modal .mf").innerHTML = `<button class="btn btn-line" id="apMore">${I("user-plus")}Yana qo'shish</button><button class="btn btn-dark" data-close>Tayyor</button>`;
    $$("#modal [data-close]").forEach((x) => (x.onclick = closeModal));
    $("#apCopy").onclick = () => copyText(linkMsg(r.name, r.link), "Havola nusxalandi: xodimga yuboring");
    $("#apMore").onclick = openAddPerson;
  };
  $("#apGo").onclick = go;
  inp.onkeydown = (e) => { if (e.key === "Enter") go(); };
}
async function openPersonEdit(name) {
  openModal("Xodim ma'lumotlari", `<div class="sk" style="height:220px"></div>`);
  let x;
  try { x = (await api("api/links")).people.find((p) => p.name === name); } catch (e) { closeModal(); toast(esc(e.message), "danger"); return; }
  if (!x) { closeModal(); toast("Xodim topilmadi", "danger"); return; }
  const pp = (S.data?.people || []).find((p) => p.name === name), depts = S.meta?.departments || [];
  const st = x.status === "begona" ? "begona" : x.lead ? "rahbar" : "xodim";
  $("#modal .mb").innerHTML = `<div class="field"><label for="peName">Ism-familiya</label><input id="peName" value="${esc(x.name)}" maxlength="60" autocomplete="off"></div>
    <div class="field"><label for="peDept">Bo'lim</label><select id="peDept"><option value="">Tanlanmagan</option>${depts.map((d) => `<option ${pp?.department === d ? "selected" : ""}>${esc(d)}</option>`).join("")}</select></div>
    <div class="field"><label>Kim</label><div class="seg" id="peSt">${[["xodim", "Xodim"], ["rahbar", "Rahbar"], ["begona", "Hisobga olinmasin"]].map(([k, t]) => `<button type="button" data-v="${k}" aria-pressed="${st === k}" ${x.owner && k !== "rahbar" ? "disabled" : ""}>${t}</button>`).join("")}</div></div>
    <div class="field"><label>Murojaatlarga javob berganda</label><div class="seg" id="peLine">${[["", "Avtomatik"], ["1", "Operator"], ["2", "Mutaxassis"], ["3", "Dasturchi"]].map(([k, t]) => `<button type="button" data-v="${k}" aria-pressed="${String(x.line ?? "") === k}">${t}</button>`).join("")}</div>
      <small class="tgid">Yordam guruhida javob bersa, "Qay tartibda hal qilingan" shu liniyada sanaladi. Avtomatik: tizim jamoasidagi dasturchi 3-liniya, boshqa xodim 2-liniya.</small></div>
    <div class="field"><label>Botga ulanish</label><div class="contact"><span class="lnk-box">${x.linked ? I("check") + " Ulangan" : esc(x.link)}</span>
      ${x.linked ? "" : `<button class="btn btn-line sm" id="peCopy">${I("copy")}Nusxalash</button>`}<button class="btn btn-ghost sm" id="peReset">Yangi havola</button></div>
      <small class="tgid">${x.username ? "@" + esc(x.username) + ", " : ""}${x.id > 0 ? "Telegram ID " + x.id : "Hali Telegram akkaunti bog'lanmagan"}</small></div>`;
  $("#modal .mbox").insertAdjacentHTML("beforeend", `<div class="mf"><button class="btn btn-ghost" data-close>Bekor qilish</button><button class="btn btn-dark" id="peSave">${I("check")}Saqlash</button></div>`);
  $$("#modal [data-close]").forEach((b) => (b.onclick = closeModal));
  let want = st, line = String(x.line ?? "");
  $$("#peLine [data-v]").forEach((b) => (b.onclick = () => { line = b.dataset.v; $$("#peLine [data-v]").forEach((q) => q.setAttribute("aria-pressed", q === b)); }));
  $$("#peSt [data-v]").forEach((b) => (b.onclick = () => { want = b.dataset.v; $$("#peSt [data-v]").forEach((q) => q.setAttribute("aria-pressed", q === b)); }));
  $("#peCopy")?.addEventListener("click", () => copyText(linkMsg(x.name, x.link), "Havola nusxalandi: xodimga yuboring"));
  $("#peReset").onclick = async () => {
    try { const c = await api("api/person/link/reset", { json: { name: x.name } }); copyText(linkMsg(x.name, c.link), "Yangi havola nusxalandi, eskisi ishlamaydi"); openPersonEdit(x.name); }
    catch (e) { toast(esc(e.message), "danger"); }
  };
  $("#peSave").onclick = async () => {
    const b = $("#peSave"); b.disabled = true;
    let cur = x.name;
    try {
      const nn = $("#peName").value.trim();
      if (nn.length >= 2 && nn !== cur) { await api("api/person/name", { json: { name: cur, new_name: nn } }); cur = nn; }
      const dp = $("#peDept").value;
      if (dp !== (pp?.department && pp.department !== "Belgilanmagan" ? pp.department : "")) await api("api/person/department", { json: { name: cur, department: dp } });
      if (line !== String(x.line ?? "")) await api("api/person/line", { json: { name: cur, line: line ? +line : null } });
      if (want !== st) {
        if (want === "rahbar" || st === "rahbar") await api("api/person/role", { json: { name: cur, role: want === "rahbar" ? "rahbar" : "" } });
        if (want === "begona" || st === "begona") await api("api/person/status", { json: { name: cur, status: want === "begona" ? "begona" : "xodim" } });
      }
    } catch (e) { b.disabled = false; toast(esc(e.message), "danger"); return; }
    closeModal(); toast(`Saqlandi: <b>${esc(cur)}</b>`, "check");
    await load(true);
    if ($("#drawer").classList.contains("open") && S.open.startsWith("p:")) openPerson(cur);
  };
}
