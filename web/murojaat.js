/* Puls — "Murojaatlar": tizim foydalanuvchilari yordam guruhlari va chatbotlarga yozgan savol va shikoyatlar, loyihalar kesimida.
 * Kunlik holat sahifasining bo'limi. Bloklar tartibi Feruzbek maketi bo'yicha: ko'rsatkichlar, xulosa va loyihalar, loyiha tahlili
 * (kunlik grafik, turlar, hal qilish tartibi, javob sifati), takroriy murojaatlar, lenta. Murojaat ustiga bosilsa yozishma ochiladi.
 * Haqiqiy manba ulanmaguncha server namunani beradi ("sample"), u bazaga yozilmaydi va shu yerda "Namuna" deb ko'rsatiladi.
 * puls2.js va sahifalar.js dan keyin yuklanadi. */
"use strict";

const AP = { days: 30, src: "", project: null, type: "", status: "", q: "", limit: 25, data: null, key: "", loading: false };
const AP_STATUS = { ochiq: ["Ochiq", "bad"], javob: ["Javob berildi", "warn"], hal: ["Hal qilindi", "good"], qayta: ["Qayta ochildi", "bad"] };
const AP_GRADE = { good: ["To'liq hal qilgan", "good"], part: ["Qisman", "warn"], tpl: ["Shablon javob", "bad"], none: ["Javobsiz", "bad"] };
const AP_LINE = ["Chatbot", "Operator", "Mutaxassis", "Dasturchi"];
const AP_LINE_FULL = ["Chatbot (avtomatik)", "Operator (1-liniya)", "Mutaxassis (2-liniya)", "Dasturchi (3-liniya)"];
const AP_FEED_F = [["", "Hammasi"], ["ochiq", "Hal qilinmagan"], ["hal", "Hal qilingan"], ["takror", "Takroriy"], ["yomon", "Shablon yoki javobsiz"]];
const AP_BUCKETS = ["1 soatgacha", "1–4 soat", "4–24 soat", "1–3 kun", "3 kundan ko'p"];

const apPct = (x) => (x == null ? "—" : Math.round(x * 100) + "%");
function apH(h) {
  if (h == null) return "—";
  if (h < 1) return Math.max(1, Math.round(h * 60)) + " daqiqa";
  if (h < 24) return nf(h, 1) + " soat";
  return nf(h / 24, 1) + " kun";
}
const apTypeName = (k) => AP.data?.labels?.types?.[k] || k || "—";
const apSrc = (x) => `<span class="ap-src"><i class="${x.source === "bot" ? "bot" : "tg"}">${x.source === "bot" ? "Bot" : "TG"}</i>${esc(x.src_name || (x.source === "bot" ? "Chatbot" : "Telegram"))}</span>`;
const apGradeTag = (g) => { const x = AP_GRADE[g] || AP_GRADE.none; return tag(x[0], x[1] + " sm"); };
const apDelta = (d) => (d && d.v != null ? `<span class="ap-dl ${d.c}">${esc(d.t)}</span>` : `<span class="ap-dl flat">${esc(d?.t || "—")}</span>`);
// murojaat oshishi yomon, kamayishi yaxshi: rangi shunga qarab
const apDeltaMetric = (d) => (d && d.v != null ? `<span class="d ${d.c === "up" ? "down" : d.c === "down" ? "up" : ""}">${esc(d.t)}, oldingi davrga</span>` : `<span class="d">oldingi davrda yo'q</span>`);

function appealsInner() {
  const d = AP.data;
  if (!d) return `<div class="sec-h"><h2>Murojaatlar</h2></div><div class="band">${Array(6).fill(`<div class="metric"><div class="sk" style="height:62px"></div></div>`).join("")}</div>`;
  const k = d.kpi, sel = d.projects.find((p) => p.id === d.selected);
  return `<div class="sec-h"><h2>Murojaatlar <span class="n">${nf(k.n)}</span>${d.sample ? `<span class="tag info sm" title="Haqiqiy manba ulanganda o'z-o'zidan almashadi">Namuna</span>` : ""}</h2>
      <div class="right"><div class="seg" role="group" aria-label="Davr">${[7, 30, 90].map((n) => `<button data-apd="${n}" aria-pressed="${AP.days === n}">${n} kun</button>`).join("")}</div>
        <select class="ctl" id="apSrcSel" aria-label="Manba"><option value="">Barcha manbalar</option><option value="tg" ${AP.src === "tg" ? "selected" : ""}>Telegram guruhlar</option><option value="bot" ${AP.src === "bot" ? "selected" : ""}>Chatbotlar</option></select></div></div>
    ${d.sample ? apSampleNote() : apConnected(d)}
    ${k.unknown ? `<div class="ap-note warn">${I("danger")}<div><b>${k.unknown} ta murojaatning tizimi aniqlanmagan.</b> Xabarda qaysi tizim haqida
      ekani aytilmagan, shuning uchun u taxmin bilan biror loyihaga yozilmadi. Ochib, tizimini tanlang: shu tanlovlardan model ham o'rganadi.</div>
      <div class="ap-note-b"><button class="btn btn-dark sm" data-app="${d.unknown_id}">${I("list")}Ko'rish</button></div></div>` : ""}
    <div class="band ap-band">
      <div class="metric"><span class="l">Jami murojaatlar</span><span class="v">${nf(k.n)}</span>${apDeltaMetric(k.delta)}</div>
      <button class="metric" data-apst="ochiq"><span class="l">Hal qilingan</span><span class="v ${k.res_rate != null && k.res_rate < .8 ? "warn" : ""}">${apPct(k.res_rate)}</span>
        <span class="d ${k.waiting ? "down" : ""}">${k.open ? `${nf(k.open)} tasi hal qilinmagan${k.waiting ? `, ${nf(k.waiting)} tasi javob kutyapti` : ""}` : "hammasi hal qilingan"}</span>
        <span class="meter"><i class="${meterCls(k.res_rate == null ? null : Math.round(k.res_rate * 100))}" style="width:${Math.round((k.res_rate || 0) * 100)}%"></i></span></button>
      <div class="metric"><span class="l">O'rtacha hal qilish</span><span class="v">${apH(k.avg_h)}</span><span class="d">${k.prev_avg_h != null ? "oldin " + apH(k.prev_avg_h) : "oldingi davr yo'q"}</span></div>
      <button class="metric" data-apst="takror"><span class="l">Takroriy murojaatlar</span><span class="v ${k.rep_rate > .12 ? "bad" : ""}">${apPct(k.rep_rate)}</span><span class="d">${nf(k.rep)} ta: muammo birinchi marta hal qilinmagan</span></button>
      <button class="metric" data-apst="yomon"><span class="l">Shablon yoki javobsiz</span><span class="v ${k.bad_rate > .25 ? "bad" : ""}">${apPct(k.bad_rate)}</span><span class="d">javob bahosi bo'yicha</span></button>
      <div class="metric"><span class="l">Manbalar</span><span class="v ap-v2">${k.n ? `${apPct(k.tg / k.n)} <small>/</small> ${apPct(k.bot / k.n)}` : "—"}</span><span class="d">Telegram guruhlar / chatbotlar</span></div>
    </div>
    ${!k.n ? `<div class="panel"><div class="pnl-b">${emptyBox(`Oxirgi ${d.days} kunda murojaat kelmagan${AP.src ? " (tanlangan manbadan)" : ""}`, "check")}</div></div>` : `
    <div class="ap-g2">
      <section class="panel"><div class="pnl-h"><h2>${I("stars")}Rahbar uchun xulosa</h2><p>${d.sample ? "Namuna ma'lumot bo'yicha" : "Oxirgi " + d.days + " kun, " + dotDate(d.end) + " gacha"}</p></div>
        <div class="pnl-b">${d.insights.length ? `<ul class="ap-ins">${d.insights.map((s) => `<li>${s.map(([t, b]) => (b ? `<b>${esc(t)}</b>` : esc(t))).join("")}</li>`).join("")}</ul>` : emptyBox("Xulosa uchun murojaat hali kam", "info")}</div></section>
      <section class="panel"><div class="pnl-h"><h2>Loyihalar bo'yicha <span class="n">${d.projects.length}</span></h2><p>E'tibor indeksi: hajm, hal qilinmagani, takroriylik va javob sifati (0–100)</p></div>
        ${apProjectsTable(d)}</section>
    </div>
    <section class="panel" id="apAnalysis"><div class="pnl-h"><h2>Loyiha tahlili: ${esc(sel ? sel.name : "barcha loyihalar")}</h2>
        <div class="right"><select class="ctl" id="apProjSel" aria-label="Loyiha"><option value="0">Barcha loyihalar</option>${d.projects.map((p) => `<option value="${p.id}" ${p.id === d.selected ? "selected" : ""}>${esc(p.name)} (${p.n})</option>`).join("")}</select></div></div>
      <div class="pnl-b">${apChart(d.chart)}</div>
      <div class="ap-g3">
        <div><h3 class="ap-h3">Murojaat turlari${d.type ? ` <button class="chip" aria-pressed="true" data-apt="">${esc(apTypeName(d.type))} ${I("close")}</button>` : `<span class="ap-hint">turni bossangiz pastdagi lenta va o'ngdagi tahlil shu turga o'tadi</span>`}</h3>${apTypesTable(d)}</div>
        <div class="ap-side">${apFlow(d)}${apQuality(d)}</div>
      </div></section>
    ${apRepeats(d)}
    <section class="panel" id="apFeed">${apFeedInner(d)}</section>`}`;
}

function apSampleNote() {
  return `<div class="ap-note">${I("info")}<div><b>Namuna ma'lumot.</b> Yordam guruhi yoki chatbot hali ulanmagan, shuning uchun bo'lim qanday ishlashi namunada ko'rsatilgan (bazaga yozilmaydi).
      Puls botini tizimning yordam guruhiga qo'shing yoki chatbotni ulang: shu yerda haqiqiy murojaatlar chiqadi.</div>
    <div class="ap-note-b"><button class="btn btn-line sm" data-apx="howto">${I("help")}Qanday ulanadi</button>${can("settings") ? `<button class="btn btn-dark sm" data-apx="bots">${I("send")}Chatbot ulash</button>` : ""}</div></div>`;
}
function apConnected(d) {
  const c = d.connected || { chats: [], bots: [] };
  const list = c.chats.map((x) => esc(x.title)).concat(c.bots.map((x) => esc(x.name)));
  return `<div class="ap-conn">${I("send")}<span>Manbalar: ${list.length ? list.join(", ") : "ulanmagan"}</span>
    <span class="ap-conn-b"><button class="lnk" data-apx="howto">Yangi guruh ulash</button>${can("settings") ? `<button class="lnk" data-apx="bots">Chatbotlar</button>` : ""}</span></div>`;
}

function apProjectsTable(d) {
  const mx = Math.max(1, ...d.projects.map((p) => p.n));
  const lv = (a) => (a >= 60 ? "bad" : a >= 35 ? "warn" : "idle");
  return `<div class="tscroll ap-ptab"><table class="dtab"><thead><tr><th>Loyiha</th><th>Murojaat</th><th class="num hm">O'zgarish</th><th class="num hm">Hal qilingan</th><th class="num hm">Takroriy</th><th class="num">E'tibor</th></tr></thead>
    <tbody>${d.projects.map((p) => `<tr class="clk ${p.id === d.selected ? "on" : ""}" data-app="${p.id}" title="${esc(p.reasons.join(", "))}">
      <td><b>${esc(p.name)}</b><small class="ap-why">${esc(p.reasons.filter((r) => !/^\d/.test(r)).join(", ") || " ")}</small></td>
      <td><span class="ap-bar"><span class="t"><i style="width:${(p.n / mx) * 100}%"></i></span><b>${nf(p.n)}</b></span></td>
      <td class="num hm">${apDelta(p.delta)}</td><td class="num hm">${apPct(p.res_rate)}</td>
      <td class="num hm ${p.rep_rate > .15 ? "bad-t" : ""}">${apPct(p.rep_rate)}</td>
      <td class="num"><span class="ap-score ${lv(p.att)}">${p.att}</span></td></tr>`).join("")}</tbody></table></div>`;
}

function apChart(c) {
  const N = c.days.length, W = 1000, H = 140, bw = W / Math.max(1, N), mx = Math.max(1, c.max);
  const bars = c.days.map(([day, v], i) => { const h = (v / mx) * (H - 8), x = i * bw;
    return `<g><rect class="hit" x="${x}" y="0" width="${bw}" height="${H}"><title>${dotDate(day)}: ${v} ta murojaat</title></rect><rect class="b ${v === c.max && v ? "mx" : ""}" x="${(x + 1).toFixed(1)}" y="${(H - h).toFixed(1)}" width="${Math.max(1, bw - 2).toFixed(1)}" height="${h.toFixed(1)}" rx="1.5"/></g>`; }).join("");
  const mid = c.days[Math.floor(N / 2)]?.[0];
  return `<div class="ap-chart"><div class="cap"><b>Kunlik murojaatlar</b><span>kuniga o'rtacha ${nf(c.avg, 1)} ta</span>${c.max ? `<span>eng ko'p: ${c.max} ta (${dotDate(c.max_day)})</span>` : ""}</div>
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Kunlik murojaatlar: o'rtacha ${c.avg}, eng ko'p ${c.max}">${bars}<line class="ax" x1="0" y1="${H - .5}" x2="${W}" y2="${H - .5}" vector-effect="non-scaling-stroke"/></svg>
    <div class="xl"><span>${N ? dotDate(c.days[0][0]) : ""}</span><span>${mid ? dotDate(mid) : ""}</span><span>${N ? dotDate(c.days[N - 1][0]) : ""}</span></div></div>`;
}

function apTypesTable(d) {
  if (!d.types.length) return emptyBox("Murojaat yo'q", "info");
  const mx = Math.max(1, ...d.types.map((t) => t.n));
  return `<div class="tscroll"><table class="dtab"><thead><tr><th>Turi</th><th>Soni</th><th class="num hm">O'rtacha hal qilish</th><th class="num">Takroriy</th><th class="num">Yomon javob</th></tr></thead>
    <tbody>${d.types.map((t) => `<tr class="clk ${d.type === t.key ? "on" : ""}" data-apt="${d.type === t.key ? "" : t.key}">
      <td><b>${esc(t.name)}</b></td>
      <td><span class="ap-bar"><span class="t"><i style="width:${(t.n / mx) * 100}%"></i></span><b>${t.n}</b><small>${apPct(t.share)}</small></span></td>
      <td class="num hm">${apH(t.avg_h)}</td><td class="num ${t.rep_rate > .15 ? "bad-t" : ""}">${apPct(t.rep_rate)}</td>
      <td class="num ${t.bad_rate > .3 ? "bad-t" : ""}">${apPct(t.bad_rate)}</td></tr>`).join("")}</tbody></table></div>`;
}

function apFlow(d) {
  const f = d.flow, mx = Math.max(1, ...f.lines.map((l) => l.n)), bm = Math.max(1, ...f.buckets);
  const rows = f.lines.filter((l) => l.n).map((l) => `<div class="ap-line"><span class="no">${l.line === 0 ? I("bolt") : l.line}</span>
      <div><div class="t1"><b>${AP_LINE_FULL[l.line]}</b><span>${l.n} ta, ${apPct(l.share)}</span></div>
        <div class="t2">${apPct(l.res_rate)} hal qilingan${l.avg_h != null ? `, o'rtacha ${apH(l.avg_h)}` : ""}</div>
        <span class="ap-t"><i style="width:${(l.n / mx) * 100}%"></i></span></div></div>`).join("");
  return `<div class="ap-box"><h3 class="ap-h3">Qay tartibda hal qilingan</h3>
    ${rows || `<p class="ap-hint">Hali javob berilmagan</p>`}
    ${f.unanswered ? `<p class="ap-hint">${f.unanswered} tasiga hali javob berilmagan</p>` : ""}
    <h3 class="ap-h3" style="margin-top:16px">Hal qilish vaqti</h3>
    <div class="ap-bk">${f.buckets.map((v, i) => `<div title="${AP_BUCKETS[i]}: ${v} ta"><em>${v}</em><i class="${i === 4 ? "late" : ""}" style="height:${Math.round((v / bm) * 64)}px"></i><span>${AP_BUCKETS[i]}</span></div>`).join("")}</div></div>`;
}

function apQuality(d) {
  const q = d.quality, mx = Math.max(1, q.good, q.part, q.tpl, q.none);
  const row = (k, cls) => `<div class="ap-q"><span>${AP_GRADE[k][0]}</span><span class="ap-t"><i class="${cls}" style="width:${(q[k] / mx) * 100}%"></i></span><b>${q[k]}</b><small>${apPct(q.n ? q[k] / q.n : null)}</small></div>`;
  return `<div class="ap-box"><h3 class="ap-h3">Javoblar sifati</h3>${row("good", "ok")}${row("part", "md")}${row("tpl", "hi")}${row("none", "hi")}
    ${q.first_bad != null ? `<p class="ap-hint">Takroriy murojaatlarda birinchi javobning <b>${apPct(q.first_bad)}</b> i shablon yoki qisman bo'lgan.</p>` : ""}</div>`;
}

function apRepeats(d) {
  if (!d.repeats.length) return "";
  return `<section class="panel"><div class="pnl-h"><h2>Takroriy murojaatlar: nega qaytib kelyapti</h2><p>${esc(d.projects.find((p) => p.id === d.selected)?.name || "Barcha loyihalar")}: bir odam bir xil muammo bilan 21 kun ichida qayta yozgan</p></div>
    <div class="ap-reps">${d.repeats.map((r) => `<article class="ap-rep">
      <div class="hd"><b>${esc(r.name)}</b>${tag(apPct(r.rate) + " takroriy", "bad sm")}</div>
      <div class="st"><span><b>${r.rep}</b> takroriy murojaat</span><span><b>${r.users}</b> kishi qayta yozgan</span><span>o'rtacha <b>${nf(r.avg_len, 1)}</b> martadan</span></div>
      <div><h4>Sabab</h4><p>${r.cause ? esc(r.cause) : `<span class="ap-hint">AI hali tahlil qilmagan: takroriy murojaatlar to'plangach kuniga bir marta yoziladi</span>`}</p></div>
      <div><h4>Dalil</h4><p>${r.first_bad != null ? `Birinchi javobning ${apPct(r.first_bad)} i shablon yoki qisman. ` : ""}${r.open} tasi hali hal qilinmagan.${r.main_src ? ` Ko'pi «${esc(r.main_src)}» orqali kelgan.` : ""}</p></div>
      ${r.act ? `<div><h4>Tavsiya</h4><p>${esc(r.act)}</p></div>` : ""}
      <div><button class="btn btn-line sm" data-apt="${r.type}" data-apst2="takror">${I("list")}Shu murojaatlarni ko'rish</button></div></article>`).join("")}</div></section>`;
}

function apFeedInner(d) {
  const f = d.feed;
  return `<div class="pnl-h"><h2>Murojaatlar lentasi <span class="n">${nf(f.total)}</span></h2>${d.type ? `<p>Turi: ${esc(apTypeName(d.type))}</p>` : ""}</div>
    <div class="tools-row"><div class="legend">${AP_FEED_F.map(([k, t]) => `<button class="chip" data-apst="${k}" aria-pressed="${AP.status === k}">${t}</button>`).join("")}</div>
      <label class="searchbox">${I("search")}<input id="apQ" type="search" placeholder="Matn, foydalanuvchi yoki guruh" value="${esc(AP.q)}" autocomplete="off"></label></div>
    ${f.items.length ? apFeedTable(f.items, !d.selected) : `<div class="pnl-b">${emptyBox(AP.q ? "Bu so'z bo'yicha murojaat yo'q" : "Bu filtrga mos murojaat yo'q", AP.q ? "search" : "check")}</div>`}
    ${f.total > f.items.length ? `<div class="ap-more"><button class="btn btn-line" id="apMore">${I("chevron-down")}Yana 25 ta ko'rsatish</button><span class="sm">${f.items.length} / ${f.total}</span></div>` : ""}`;
}

function apFeedTable(items, withProject) {
  return `<div class="tscroll"><table class="dtab ap-feed"><thead><tr><th>Vaqt</th><th class="hm">Manba</th><th>Murojaat</th><th class="hm">Turi</th><th>Hal qilinishi</th><th class="hm">Javob bahosi</th></tr></thead>
    <tbody>${items.map((x) => `<tr class="clk" data-apid="${x.id}">
      <td class="sm nw">${esc(clock(x.at))}</td>
      <td class="hm">${apSrc(x)}${withProject ? `<small class="ap-why">${esc(x.project || "")}</small>` : ""}</td>
      <td class="wrap"><span class="ap-sum">${esc(x.summary)}</span>${x.rep ? ` ${tag("takroriy", "bad sm")}` : ""}<small class="ap-why sm-only">${esc(x.type_name)}</small></td>
      <td class="sm hm">${esc(x.type_name)}</td>
      <td class="sm nw">${x.resolved ? `${AP_LINE[x.line] || "Hal qilindi"}${x.hours != null ? ", " + apH(x.hours) : ""}` : `<span class="${x.status === "javob" ? "warn-t" : "bad-t"}">${x.status === "javob" ? "Javob berildi" : x.status === "qayta" ? "Qayta ochildi" : "Ochiq"}</span>${x.line != null ? ", " + AP_LINE[x.line].toLowerCase() : ""}`}</td>
      <td class="hm">${apGradeTag(x.grade)}</td></tr>`).join("")}</tbody></table></div>`;
}

function drawAppeals(scroll) {
  const box = $("#hlAppeals");
  if (!box) return;
  const focus = document.activeElement?.id === "apQ";
  box.innerHTML = appealsInner();
  bindAppeals(box);
  if (focus) { const q = $("#apQ"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
  if (scroll) $("#" + scroll)?.scrollIntoView({ behavior: "smooth", block: "start" });
}
function bindAppeals(box) {
  bindCommon(box);
  $$("[data-apd]", box).forEach((b) => (b.onclick = () => { AP.days = +b.dataset.apd; loadAppeals(true); }));
  const ss = $("#apSrcSel", box);
  if (ss) ss.onchange = () => { AP.src = ss.value; loadAppeals(true); };
  const ps = $("#apProjSel", box);
  if (ps) ps.onchange = () => { AP.project = +ps.value; AP.type = ""; AP.limit = 25; loadAppeals(true, "apAnalysis"); };
  $$("[data-app]", box).forEach((r) => (r.onclick = () => { AP.project = +r.dataset.app === AP.data?.selected ? 0 : +r.dataset.app; AP.type = ""; AP.limit = 25; loadAppeals(true, "apAnalysis"); }));
  $$("[data-apt]", box).forEach((r) => (r.onclick = (e) => { e.stopPropagation(); AP.type = r.dataset.apt; if (r.dataset.apst2) AP.status = r.dataset.apst2; AP.limit = 25; loadAppeals(true, r.dataset.apst2 ? "apFeed" : null); }));
  $$("[data-apst]", box).forEach((b) => (b.onclick = () => { AP.status = AP.status === b.dataset.apst ? "" : b.dataset.apst; AP.limit = 25; loadAppeals(true, b.classList.contains("metric") ? "apFeed" : null); }));
  $$("[data-apid]", box).forEach((r) => (r.onclick = () => openAppeal(+r.dataset.apid)));
  $$("[data-apx]", box).forEach((b) => (b.onclick = () => (b.dataset.apx === "bots" ? openBots() : openSupportGuide())));
  const q = $("#apQ", box);
  if (q) q.oninput = () => { AP.q = q.value; clearTimeout(q._t); q._t = setTimeout(() => loadAppeals(true), 250); };
  $("#apMore", box)?.addEventListener("click", () => { AP.limit += 25; loadAppeals(true); });
}
function apQuery() {
  return new URLSearchParams({ days: AP.days, src: AP.src, type: AP.type, status: AP.status, q: AP.q, limit: AP.limit,
    ...(AP.project != null ? { project: AP.project } : {}), ...(S.asof ? { asof: S.asof } : {}), ...(S.dept ? { dept: S.dept } : {}) });
}
async function loadAppeals(force, scroll) {
  const qs = apQuery().toString(), key = qs + "|" + S.version;
  if (!force && AP.key === key && AP.data) return;  // sahifa shu ma'lumot bilan chizilgan
  AP.key = key;
  try { AP.data = await api("api/appeals?" + qs); }
  catch (e) { if (S.tab === "holat") toast(esc(e.message), "danger"); return; }
  if (AP.key !== key) return;  // orada boshqa so'rov ketdi
  if (S.tab === "holat") drawAppeals(scroll);
}
// boshqa joydan (loyiha kartasi, loyiha oynasi): shu loyihaning murojaatlariga o'tish
function goAppeals(pid) {
  AP.project = pid ? +pid : 0; AP.type = ""; AP.status = ""; AP.limit = 25;
  closeDrawer();
  if (S.tab !== "holat") { S.sec = "murojaatlar"; go("holat"); return; }
  loadAppeals(true, "apAnalysis");
}

/* ---------- murojaat: yozishma va AI xulosasi (yon oyna) ---------- */
async function openAppeal(id) {
  openDrawer(skelHead());
  $("#drawer").classList.add("wide");
  let r;
  try { r = await api("api/appeals/" + id); } catch (e) { closeDrawer(); toast(esc(e.message), "danger"); return; }
  const a = r.appeal, st = AP_STATUS[a.status] || AP_STATUS.ochiq, sheet = $("#drawer .sheet");
  const ev = (e) => e.kind === "tuzatish"
    ? `<li class="ap-ev fix">${I("pen")}<span><b>${esc(e.who || "Rahbar")}</b> tuzatdi: ${esc(e.text)}<small>${esc(clock(e.at))}</small></span></li>`
    : `<li class="ap-ev ${e.staff ? "st" : "us"}"><div class="who"><b>${esc(e.who || (e.staff ? "Xodim" : a.client || "Foydalanuvchi"))}</b>
        <span>${e.staff ? esc(AP_LINE_FULL[e.line] || "Xodim") : { murojaat: "murojaat", qoshimcha: "qo'shimcha", tasdiq: "tasdiqladi", qayta: "qayta yozdi" }[e.kind] || ""}</span>
        <span>${esc(clock(e.at))}</span>${e.grade ? apGradeTag(e.grade) : ""}${e.link ? `<a class="lnk" href="${esc(e.link)}" target="_blank" rel="noopener">${I("send")}Telegram</a>` : ""}</div>
      <p>${esc(e.text || "")}</p>${e.staff && e.note ? `<small class="note">${I("stars")}${esc(e.note)}</small>` : ""}</li>`;
  const fixable = !r.sample && can("correct") && !S.asof;
  sheet.innerHTML = `<div class="sh-head"><div style="min-width:0;flex:1"><h2>${esc(a.project || "Tizim belgilanmagan")}: murojaat</h2>
      <div class="meta">${tag(st[0], st[1], true)}${a.rep ? tag("takroriy", "bad sm") : ""}${apSrc({ source: a.source, src_name: a.bot || a.chat })}${r.sample ? tag("namuna", "info sm") : ""}</div></div>
      <button class="icon-btn x" aria-label="Yopish">${I("close")}</button></div>
    <div class="sh-body">
      <section class="ap-d"><h3>Yozishma</h3><ul class="ap-evs">${r.events.map(ev).join("")}</ul>
        ${a.first_answer_at ? "" : `<p class="ap-hint">${I("clock")} Javob hali berilmagan${a.created_at ? ", " + esc(ago(a.created_at)) + " kutyapti" : ""}</p>`}</section>
      <section class="ap-d"><h3>${I("stars")}Tahlil</h3><dl class="kv">
        <dt>Turi</dt><dd>${esc(a.type_name)}</dd>
        <dt>Muammo</dt><dd>${esc(a.summary || "—")}</dd>
        <dt>Birinchi javob</dt><dd>${a.first_hours != null ? apH(a.first_hours) + " ichida" : "berilmagan"}</dd>
        <dt>Hal qilinishi</dt><dd>${a.status === "hal" ? `${esc(AP_LINE_FULL[a.line] || "")}${a.hours != null ? ", " + apH(a.hours) : ""}${a.resolution === "jim" ? " (javobdan keyin foydalanuvchi qayta yozmadi)" : a.resolution === "tasdiq" ? " (foydalanuvchi tasdiqladi)" : a.resolution === "qolda" ? " (rahbar belgiladi)" : ""}` : `<span class="${a.status === "javob" ? "warn-t" : "bad-t"}">${esc(a.status_name)}</span>`}</dd>
        <dt>Javob bahosi</dt><dd>${apGradeTag(a.grade || "none")}${a.grade_note ? `<small class="ap-why">${esc(a.grade_note)}</small>` : ""}</dd>
        <dt>Foydalanuvchi</dt><dd>${esc(a.client || "—")}${a.username ? " @" + esc(a.username) : ""}${r.client_appeals > 1 ? `, jami ${r.client_appeals} ta murojaat` : ""}</dd></dl></section>
      ${r.chain.length > 1 ? `<section class="ap-d"><h3>Takroriy zanjir</h3><ul class="ap-chain">${r.chain.map((c) => `<li class="${c.id === a.id ? "me" : ""}" ${c.id === a.id ? "" : `data-apid="${c.id}"`}><time>${esc(clock(c.created_at))}</time><span>${esc(c.summary || "")}${c.id === a.id ? " (shu)" : ""}</span>${apGradeTag(c.grade || "none")}</li>`).join("")}</ul>
        ${r.insight ? `<div class="ap-why-box"><h4>Nega takrorlanyapti</h4><p>${esc(r.insight.cause)}</p>${r.insight.act ? `<h4>Tavsiya</h4><p>${esc(r.insight.act)}</p>` : ""}</div>` : ""}</section>` : ""}
      ${fixable ? `<section class="ap-d"><h3>Tuzatish</h3><div class="ap-fix">
        <label>Turi<select id="apfT">${Object.entries(r.labels.types).map(([k, v]) => `<option value="${k}" ${k === a.type ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
        <label>Loyiha<select id="apfP">${a.project_id ? "" : `<option value="" selected>Tanlang: tizim aniqlanmagan</option>`}${r.projects.map((p) => `<option value="${p.id}" ${p.id === a.project_id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></label>
        <div class="ap-fix-b"><button class="btn btn-dark sm" id="apfSave">${I("check")}Saqlash</button>
          ${a.status === "hal" ? `<button class="btn btn-line sm" id="apfOpen">${I("refresh")}Qayta ochish</button>` : `<button class="btn btn-line sm" id="apfDone">${I("check")}Hal qilindi deb belgilash</button>`}</div></div></section>` : ""}
    </div>`;
  $(".x", sheet).onclick = closeDrawer;
  $$("[data-apid]", sheet).forEach((x) => (x.onclick = () => openAppeal(+x.dataset.apid)));
  const fix = async (body, msg) => {
    try { await api(`api/appeals/${a.id}/fix`, { json: body }); } catch (e) { toast(esc(e.message), "danger"); return; }
    toast(msg, "check"); openAppeal(a.id); loadAppeals(true);
  };
  $("#apfSave")?.addEventListener("click", () => fix({ type: $("#apfT").value, project_id: +$("#apfP").value || null }, "Saqlandi"));
  $("#apfDone")?.addEventListener("click", () => fix({ status: "hal" }, "Hal qilindi deb belgilandi"));
  $("#apfOpen")?.addEventListener("click", () => fix({ status: "ochiq" }, "Murojaat qayta ochildi"));
}

/* ---------- ulash: yordam guruhi va chatbotlar ---------- */
function openSupportGuide() {
  const bot = S.meta?.bot || "puls_loyiha_bot";
  openModal("Yordam guruhini ulash", `<ol class="ap-steps">
      <li><b>Botni guruhga qo'shing:</b> @${esc(bot)}. Guruh nomida «yordam» yoki «support» so'zi bo'lsa, u o'zi yordam guruhi deb taniladi.
        Aks holda Guruhlar bo'limida turini «Yordam guruhi» qiling.</li>
      <li><b>Bot guruhda hech narsa yozmaydi.</b> Foydalanuvchilarning savoli, xodimlarning javobi va «ishladi, rahmat» kabi tasdiqlarni o'zi o'qiydi.</li>
      <li><b>Tizimini tekshiring.</b> Guruh nomidan tizim topiladi («Shajara yordam» — Shajara loyihasi). Kerak bo'lsa Guruhlar bo'limida boshqa loyihaga bog'lang.</li>
      <li><b>Kim xodim?</b> Puls xodimlari va guruh adminlari javob beruvchi hisoblanadi. Operator, mutaxassis yoki dasturchi ekanini xodim oynasida belgilash mumkin.</li>
      <li><b>Bot admin qilinmaydigan guruh</b> Telegram akkaunt orqali ham o'qiladi (Guruhlar → Telegram).</li></ol>`,
    `<button class="btn btn-dark" data-close>Tushunarli</button>`);
}
async function openBots(fresh) {
  openModal("Chatbotlar", `<div class="sk" style="height:180px"></div>`, "", true);
  let r;
  try { r = await api("api/appeal-sources"); } catch (e) { closeModal(); toast(esc(e.message), "danger"); return; }
  const systems = S.meta?.systems || [];
  const example = JSON.stringify({ items: [{ id: "12345", user: "user-77", text: "SMS kod kelmayapti", at: "2026-10-26T10:15:00+05:00", system: "Adliya mobile",
    answers: [{ text: "Kod qayta yuborildi", at: "2026-10-26T10:20:00+05:00", by: "Operator", line: 1 }] }] }, null, 1);
  $("#modal .mb").innerHTML = `${fresh ? `<div class="ap-token">${I("lock")}<div><b>${esc(fresh.name)}: kalit (faqat hozir ko'rinadi)</b><span class="lnk-box">${esc(fresh.token)}</span>
        <button class="btn btn-dark sm" id="apTokCopy">${I("copy")}Nusxalash</button></div></div>` : ""}
    ${r.sources.length ? `<div class="tscroll"><table class="dtab"><thead><tr><th>Chatbot</th><th class="hm">Tizim</th><th class="num">Murojaat</th><th class="hm">Oxirgi yuborish</th><th></th></tr></thead>
      <tbody>${r.sources.map((s) => `<tr><td><b>${esc(s.name)}</b>${s.active ? "" : ` ${tag("o'chirilgan", "idle sm")}`}</td><td class="hm">${esc(s.project || "o'zi aniqlaydi")}</td>
        <td class="num">${nf(s.n)}</td><td class="sm hm">${s.last_at ? esc(clock(s.last_at)) : "hali yo'q"}</td>
        <td class="nw"><button class="btn btn-ghost sm" data-srst="${s.id}">Yangi kalit</button><button class="btn btn-ghost sm" data-soff="${s.id}" data-on="${s.active ? 0 : 1}">${s.active ? "O'chirish" : "Yoqish"}</button>
          ${can("import") ? `<label class="btn btn-ghost sm">${I("upload")}Fayl<input type="file" accept=".json,.csv" data-simp="${s.id}" hidden></label>` : ""}</td></tr>`).join("")}</tbody></table></div>` : `<p class="ap-hint">Hali chatbot ulanmagan.</p>`}
    <h4 class="ap-h3" style="margin-top:18px">Yangi chatbot</h4>
    <div class="ap-fix"><label>Nomi<input id="sbName" placeholder="@AdliyaHelpBot" maxlength="80"></label>
      <label>Tizim (ixtiyoriy)<select id="sbProj"><option value="">Har murojaatda o'zi aytadi</option>${systems.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select></label>
      <div class="ap-fix-b"><button class="btn btn-dark sm" id="sbAdd">${I("add")}Ulash va kalit olish</button></div></div>
    ${can("correct") ? `<p class="ap-hint" style="margin-top:14px">${I("download")}<a class="lnk" href="api/appeals/dataset.jsonl">O'quv to'plamini yuklab olish</a>: har murojaat matni, tizimi, turi va javoblar bahosi (lokal modelni o'rgatish uchun).</p>` : ""}
    <details class="ap-api"><summary>Chatbot dasturchisi uchun: murojaatlarni qanday yuborish</summary>
      <p><code>POST ${esc(r.push_url)}</code>, sarlavha <code>Authorization: Bearer &lt;kalit&gt;</code>. Bir xil <code>id</code> qayta yuborilsa, o'sha murojaat yangilanadi (javoblar va holat).
        <code>line</code>: 0 chatbot, 1 operator, 2 mutaxassis, 3 dasturchi. Javob berilmagan bo'lsa <code>answers</code> bo'sh.</p>
      <pre>${esc(example)}</pre></details>`;
  $("#apTokCopy")?.addEventListener("click", () => copyText(fresh.token, "Kalit nusxalandi: chatbot dasturchisiga bering"));
  $("#sbAdd").onclick = async () => {
    const name = $("#sbName").value.trim();
    if (name.length < 2) { $("#sbName").focus(); return; }
    try { const s = await api("api/appeal-sources", { json: { name, project_id: +$("#sbProj").value || null } }); openBots(s); loadAppeals(true); }
    catch (e) { toast(esc(e.message), "danger"); }
  };
  $$("[data-srst]").forEach((b) => (b.onclick = async () => {
    try { const s = await api(`api/appeal-sources/${b.dataset.srst}/reset`, { json: {} }); openBots({ ...s, name: r.sources.find((x) => x.id === +b.dataset.srst)?.name }); }
    catch (e) { toast(esc(e.message), "danger"); }
  }));
  $$("[data-soff]").forEach((b) => (b.onclick = async () => {
    try { await api(`api/appeal-sources/${b.dataset.soff}`, { json: { active: b.dataset.on === "1" } }); openBots(); } catch (e) { toast(esc(e.message), "danger"); }
  }));
  $$("[data-simp]").forEach((inp) => (inp.onchange = async () => {
    const f = inp.files[0];
    if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    try {
      const res = await fetch("api/appeals/import?source=" + inp.dataset.simp, { method: "POST", body: fd, credentials: "same-origin" });
      const j = await res.json();
      if (!res.ok) throw new Error(j.detail || "Yuklanmadi");
      toast(`Yuklandi: ${j.added} ta yangi, ${j.updated} ta yangilandi${j.errors.length ? `, ${j.errors.length} ta xato` : ""}`, "check");
      openBots(); loadAppeals(true);
    } catch (e) { toast(esc(e.message), "danger"); }
  }));
}

/* ---------- guruh turi: ish yoki yordam ---------- */
function openChatKind(chatId) {
  const c = (S.meta?.chats || []).find((x) => x.id === +chatId);
  if (!c) return;
  const systems = (S.meta?.systems || []);
  let kind = c.kind || "ish";
  const linked = new Set(c.projects || []);
  const body = () => `<p class="ap-hint" style="margin-top:0"><b>${esc(c.title)}</b></p>
    <div class="field"><label>Guruh turi</label><div class="seg" id="ckKind"><button type="button" data-v="ish" aria-pressed="${kind === "ish"}">Ish guruhi</button><button type="button" data-v="yordam" aria-pressed="${kind === "yordam"}">Yordam guruhi</button></div>
      <small class="tgid">${kind === "ish" ? "Jamoa hisobot va vazifalarini yozadi: guruh — bitta loyiha." : "Tizim foydalanuvchilari savol va shikoyat yozadi: Murojaatlar bo'limida ko'rinadi, bot jim turadi."}</small></div>
    ${kind === "yordam" ? `<div class="field"><label>Qaysi tizimga xizmat qiladi</label><div class="ap-sys">${systems.map((p) => `<label class="ap-ck"><input type="checkbox" value="${p.id}" ${linked.has(p.id) ? "checked" : ""}>${esc(p.name)}</label>`).join("")}</div>
      <input id="ckNew" placeholder="Yoki yangi tizim nomi" maxlength="80" style="margin-top:8px"></div>
      <p class="ap-hint">Oxirgi 30 kundagi xabarlari murojaat sifatida qayta o'qiladi.</p>` : ""}`;
  const draw = () => {
    $("#modal .mb").innerHTML = body();
    $$("#ckKind [data-v]").forEach((b) => (b.onclick = () => { kind = b.dataset.v; draw(); }));
    $$(".ap-ck input").forEach((x) => (x.onchange = () => (x.checked ? linked.add(+x.value) : linked.delete(+x.value))));
  };
  openModal("Guruh turi", "", `<button class="btn btn-ghost" data-close>Bekor qilish</button><button class="btn btn-dark" id="ckSave">${I("check")}Saqlash</button>`);
  draw();
  $("#ckSave").onclick = async () => {
    try { await api(`api/chats/${c.id}/kind`, { json: { kind, project_ids: kind === "yordam" ? [...linked] : null, new_name: kind === "yordam" ? ($("#ckNew")?.value || null) : null } }); }
    catch (e) { toast(esc(e.message), "danger"); return; }
    closeModal(); toast(kind === "yordam" ? "Yordam guruhi: murojaatlar shu yerdan yig'iladi" : "Ish guruhi qilindi", "check");
    await load(true); loadAppeals(true);
  };
}
