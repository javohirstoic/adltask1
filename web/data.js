/* Ma'lumotlar: modellarni ko'rish, qo'shish, tahrirlash va o'chirish (/api/data/<resurs>).
   Har resurs bitta tavsif (DATA): jadval ustunlari, forma maydonlari, filtrlar. Qolganini umumiy kod bajaradi. */
"use strict";

const dash = (v) => (v == null || v === "" ? `<span class="dt-nil">—</span>` : esc(v));
const fmtTs = (v) => (v ? esc(String(v).replace("T", " ").slice(0, 16)) : `<span class="dt-nil">—</span>`);
const clip = (v, n = 90) => `<span class="dt-clip" title="${esc(v)}">${esc(String(v ?? "").slice(0, n))}${String(v ?? "").length > n ? "…" : ""}</span>`;
const dtPill = (cls, text) => `<span class="pill ${cls} sm">${esc(text)}</span>`;
const sub = (t) => (t ? `<div class="dt-sub">${esc(t)}</div>` : "");
const ROLE_NAMES = { menejer: "Loyiha menejeri", rahbar: "Rahbar", admin: "Admin" };
const KINDS = { task: "Vazifa", done: "Bajarildi", blocker: "Muammo", deadline: "Muddat", reassign: "O'tkazish", none: "Ish xabari emas" };
const STATUSES = { open: "Ochiq", done: "Bajarilgan", taklif: "Taklif" };
const STATUS_PILL = { open: "p-l1", done: "p-ok", taklif: "p-l2" };

// cols: [sarlavha, katak(row), tartiblash kaliti?] · fields: forma · filters: ro'yxat tepasidagi tanlovlar
// src: boshqa resursdan tanlov (chats, projects, people, managers, departments)
// Ruxsatlar (ko'rish, qo'shish, o'zgartirish, o'chirish) serverdan keladi: /api/meta -> me.access. hideFor: shu rollarga tab ko'rsatilmaydi
const DATA = {
  projects: {
    label: "Loyihalar", noun: "loyiha",
    filters: [{ k: "chat", src: "chats", all: "Barcha guruhlar" }],
    cols: [
      ["Loyiha", (r) => `<b>${esc(r.name)}</b>${sub("#" + r.key)}`, "name"],
      ["Menejer", (r) => dash(r.manager_name)],
      ["Guruh", (r) => dash(r.chat_title)],
      ["Muddat", (r) => dash(r.deadline), "deadline"],
      ["Vazifalar", (r) => `<b class="num">${r.open_tasks}</b> ochiq${sub("jami " + r.total_tasks)}`, "open_tasks"],
    ],
    fields: [
      { k: "name", label: "Nomi", type: "text", req: true },
      { k: "key", label: "Teg", type: "text", createOnly: true, hint: "Guruhda #teg bo'lib yoziladi. Bo'sh qoldirsangiz nomdan olinadi; keyin o'zgarmaydi." },
      { k: "aliases", label: "Boshqa nomlari", type: "text", hint: "AI erkin matnda loyihani shu so'zlar bilan taniydi, vergul bilan yozing." },
      { k: "chat", label: "Guruh", type: "select", src: "chats" },
      { k: "manager", label: "Loyiha menejeri", type: "select", src: "managers", hint: "Menejer faqat shu loyihani ko'radi va boshqaradi. Ro'yxatda «Loyiha menejeri» roli berilgan xodimlar chiqadi." },
      { k: "deadline", label: "Muddat", type: "date" },
    ],
    warn: "Loyiha o'chirilsa, uning barcha vazifalari va muammolari ham o'chadi. Xabarlar tarixi qoladi.",
  },
  tasks: {
    label: "Vazifalar", noun: "vazifa",
    filters: [{ k: "project", src: "projects", all: "Barcha loyihalar" }, { k: "assignee", src: "people", all: "Barcha xodimlar" },
      { k: "status", choices: STATUSES, all: "Barcha holatlar" }],
    cols: [
      ["Vazifa", (r) => `<b>${esc(r.title)}</b>${sub(r.project_name)}`, "title"],
      ["Mas'ul", (r) => dash(r.assignee_name)],
      ["Holat", (r) => dtPill(STATUS_PILL[r.status], STATUSES[r.status]), "status"],
      ["Muddat", (r) => dash(r.deadline), "deadline"],
      ["Berilgan", (r) => fmtTs(r.created_at), "created_at"],
      ["Bajarilgan", (r) => fmtTs(r.done_at), "done_at"],
    ],
    fields: [
      { k: "project", label: "Loyiha", type: "select", src: "projects", req: true },
      { k: "title", label: "Vazifa", type: "text", req: true },
      { k: "assignee", label: "Mas'ul", type: "select", src: "people" },
      { k: "status", label: "Holat", type: "select", choices: STATUSES, def: "open", req: true },
      { k: "deadline", label: "Muddat", type: "date" },
    ],
  },
  blockers: {
    label: "Muammolar", noun: "muammo",
    filters: [{ k: "project", src: "projects", all: "Barcha loyihalar" }, { k: "resolved", choices: { 0: "Ochiq", 1: "Hal bo'lgan" }, all: "Hammasi" }],
    cols: [
      ["Muammo", (r) => `<b>${clip(r.text, 110)}</b>${sub(r.project_name)}`],
      ["Muallif", (r) => dash(r.author_name)],
      ["Holat", (r) => (r.resolved ? dtPill("p-ok", "Hal bo'lgan") : dtPill("p-l3", "Ochiq"))],
      ["Yozilgan", (r) => fmtTs(r.created_at), "created_at"],
      ["Hal bo'lgan", (r) => fmtTs(r.resolved_at), "resolved_at"],
    ],
    fields: [
      { k: "project", label: "Loyiha", type: "select", src: "projects", req: true },
      { k: "text", label: "Muammo", type: "textarea", req: true },
      { k: "author", label: "Muallif", type: "select", src: "people" },
      { k: "resolved", label: "Hal bo'lgan", type: "bool" },
    ],
  },
  people: {
    label: "Xodimlar", noun: "xodim", hideFor: ["menejer"],
    filters: [{ k: "department", src: "departments", all: "Barcha bo'limlar" }, { k: "role", choices: ROLE_NAMES, all: "Barcha rollar" }],
    cols: [
      ["Xodim", (r) => `<b>${esc(r.name)}</b>${sub(r.username ? "@" + r.username : "")}`, "name"],
      ["Bo'lim", (r) => dash(r.department_name), "department__name"],
      ["Rol", (r) => (r.role ? dtPill("p-ok", ROLE_NAMES[r.role] || r.role) : `<span class="dt-nil">—</span>`)],
      ["Panel akkaunti", (r) => dash(r.account)],
      ["Ochiq vazifa", (r) => `<b class="num">${r.open_tasks}</b>`, "open_tasks"],
      ["Bot", (r) => (r.dm_linked ? dtPill("p-ok", "Ulangan") : `<span class="dt-nil">ulanmagan</span>`)],
    ],
    fields: [
      { k: "name", label: "Ism-familiya", type: "text", req: true, hint: "Hamma joyda (panel, Excel, bot) shu ism ko'rinadi." },
      { k: "username", label: "Telegram @username", type: "text" },
      { k: "department", label: "Bo'lim", type: "select", src: "departments" },
      { k: "role", label: "Rol", type: "select", choices: ROLE_NAMES, hint: "Admin: hamma narsa. Rahbar: to'liq dashboard va qarorlar. Menejer: faqat o'z loyihalari. Telegramda ham uchalasi vazifa beradi." },
      { k: "telegram_id", label: "Telegram ID", type: "number", hint: "Bo'sh qoldirsangiz, odam guruhga birinchi yozganda o'zi bog'lanadi." },
      { k: "account", label: "Hozirgi panel akkaunti", type: "info" },
      { k: "login", label: "Panel login", type: "text", hint: "Panelga kirish uchun. Akkaunt rol bilan ishlaydi: avval rol tanlang." },
      { k: "password", label: "Panel paroli", type: "password", raw: true, hint: "Kamida 8 belgi, oddiy parol bo'lmasin. Tahrirda bo'sh qoldirsangiz parol o'zgarmaydi." },
    ],
    warn: "Xodim o'chirilsa, uning vazifalari mas'ulsiz qoladi va panel akkaunti ham o'chadi.",
  },
  departments: {
    label: "Bo'limlar", noun: "bo'lim", hideFor: ["menejer"],
    cols: [["Bo'lim", (r) => `<b>${esc(r.name)}</b>`, "name"], ["Xodimlar", (r) => `<b class="num">${r.people_count}</b>`, "people_count"]],
    fields: [{ k: "name", label: "Nomi", type: "text", req: true }],
    warn: "Bo'lim o'chirilsa, xodimlar o'chmaydi, faqat «Belgilanmagan» bo'lib qoladi.",
  },
  chats: {
    label: "Guruhlar", noun: "guruh", hideFor: ["menejer"],
    filters: [{ k: "demo", choices: { 0: "Haqiqiy", 1: "Namuna" }, all: "Barcha guruhlar" }],
    cols: [
      ["Guruh", (r) => `<b>${esc(r.title || "Nomsiz")}</b>${sub("ID " + r.id)}`, "title"],
      ["Turi", (r) => (r.demo ? dtPill("p-l1", "Namuna") : dtPill("p-ok", "Haqiqiy"))],
      ["Loyihalar", (r) => `<b class="num">${r.projects_count}</b>`, "projects_count"],
      ["Xabarlar", (r) => `<b class="num">${r.messages_count}</b>`, "messages_count"],
      ["Qo'shilgan", (r) => fmtTs(r.added_at), "added_at"],
    ],
    fields: [
      { k: "id", label: "Telegram chat ID", type: "number", req: true, createOnly: true, hint: "Guruhlar uchun manfiy son, masalan -1001234567890." },
      { k: "title", label: "Nomi", type: "text", req: true },
      { k: "demo", label: "Namuna guruh (Telegramga hech narsa yuborilmaydi)", type: "bool" },
    ],
    warn: "Guruh o'chirilsa, uning barcha xabarlari o'chadi; loyihalari esa guruhsiz qoladi.",
  },
  messages: {
    label: "Xabarlar", noun: "xabar",
    filters: [{ k: "chat", src: "chats", all: "Barcha guruhlar" }, { k: "kind", choices: KINDS, all: "Barcha turlar" }],
    cols: [
      ["Sana", (r) => fmtTs(r.date), "date"],
      ["Xodim", (r) => dash(r.user_name)],
      ["Xabar", (r) => `${clip(r.text, 120)}${sub(r.chat_title)}`],
      ["Turi", (r) => dtPill(r.kind === "none" ? "p-l1" : "p-ok", KINDS[r.kind] || r.kind), "kind"],
      ["Loyiha", (r) => dash(r.project_name)],
    ],
    warn: "Xabar o'chirilsa, undan yaratilgan vazifalar qoladi, lekin manbasi bo'lmaydi.",
  },
  decisions: {
    label: "Qarorlar", noun: "qaror",
    filters: [{ k: "origin", choices: { panel: "Panel", guruh: "Guruh" }, all: "Hammasi" }],
    cols: [
      ["Sana", (r) => fmtTs(r.created_at), "created_at"],
      ["Qaror", (r) => `<b>${esc(r.title)}</b>${sub(r.note)}`],
      ["Turi", (r) => dash(r.type), "type"],
      ["Manba", (r) => dash(r.origin === "guruh" ? "Guruh" : "Panel")],
      ["Yuborildi", (r) => (r.sent ? dtPill("p-ok", "Ha") : `<span class="dt-nil">yo'q</span>`)],
    ],
  },
  alerts: {
    label: "Savollar", noun: "savol",
    filters: [{ k: "kind", choices: { yuklama: "Yuklama", taklif: "Taklif" }, all: "Hammasi" }],
    cols: [
      ["Sana", (r) => fmtTs(r.created_at), "created_at"],
      ["Turi", (r) => dash(r.kind === "yuklama" ? "Yuklama" : "Taklif"), "kind"],
      ["Mas'ul", (r) => dash(r.assignee_name)],
      ["Savol", (r) => clip(String(r.text).replace(/<[^>]+>/g, ""), 120)],
      ["Natija", (r) => (r.resolved_at ? `${dtPill("p-ok", r.resolution || "hal qilindi")}${sub(r.resolved_by)}` : dtPill("p-l2", "Kutilmoqda"))],
    ],
  },
  corrections: {
    label: "Tuzatishlar", noun: "tuzatish",
    cols: [
      ["Sana", (r) => fmtTs(r.created_at), "created_at"],
      ["Xabar", (r) => clip(r.text, 120)],
      ["Tur", (r) => `${esc(KINDS[r.old_kind] || r.old_kind || "—")} → <b>${esc(KINDS[r.new_kind] || r.new_kind)}</b>`],
      ["Loyiha", (r) => `${esc(r.old_project || "—")} → <b>${esc(r.new_project || "—")}</b>`],
    ],
    warn: "Tuzatish AI'ni o'qitish to'plamidan chiqariladi.",
  },
};
const LOOKUP = { chats: (r) => r.title || "ID " + r.id, projects: (r) => r.name, people: (r) => r.name, managers: (r) => r.name, departments: (r) => r.name };
const dtVisible = () => Object.entries(DATA).filter(([k, v]) => can(k, "r") && !(v.hideFor || []).includes(ME().role));

const DT = { res: "projects", q: "", page: 1, order: "", filters: {}, rows: [], count: 0, opts: {}, seq: 0 };

/* ----- tanlov ro'yxatlari (boshqa resurslardan, keshlanadi) ----- */
async function dtOpts(src) {
  if (!DT.opts[src]) {
    const url = src === "managers" ? "people?role=menejer&" : src + "?";
    DT.opts[src] = api(`api/data/${url}page_size=1000&ordering=${src === "chats" ? "title" : "name"}`)
      .then((d) => d.results.map((r) => [String(r.id), LOOKUP[src](r)]));
    DT.opts[src].catch(() => delete DT.opts[src]);
  }
  return DT.opts[src];
}
const optionList = (pairs, selected, blank) =>
  (blank == null ? "" : `<option value="">${esc(blank)}</option>`) + pairs.map(([v, t]) => `<option value="${esc(v)}" ${String(selected ?? "") === String(v) ? "selected" : ""}>${esc(t)}</option>`).join("");

/* ----- ekran ----- */
function renderData() {
  const el = $("#v-malumotlar");
  if (!$("#dtBody", el)) buildDataShell(el);
  dtFetch(true);
}

function buildDataShell(el) {
  const R = DATA[DT.res];
  el.innerHTML = `<div class="ph"><div><h1>Ma'lumotlar</h1><div class="sub">Loyiha, vazifa, xodim va boshqa yozuvlarni shu yerda boshqaring</div></div>
      <div class="filters">${can(DT.res, "c") ? `<button class="btn btn-dark" id="dtAdd">${I("add")}Qo'shish</button>` : ""}</div></div>
    <div class="grid"><section class="card s12"><div class="cb">
      <div class="dt-tabs"><div class="seg" role="tablist">${dtVisible().map(([k, v]) => `<button data-res="${k}" role="tab" aria-pressed="${k === DT.res}">${v.label}</button>`).join("")}</div></div>
      <div class="dt-bar"><input class="ctl dt-q" id="dtQ" type="search" placeholder="Qidirish" aria-label="Qidirish" value="${esc(DT.q)}">
        ${(R.filters || []).map((f, i) => `<select class="ctl" data-f="${f.k}" data-fi="${i}" aria-label="${esc(f.all)}"></select>`).join("")}
        <span class="dt-count" id="dtCount"></span></div>
      <div id="dtBody"></div></div></section></div>`;
  $$("[data-res]", el).forEach((b) => (b.onclick = () => { DT.res = b.dataset.res; DT.q = ""; DT.page = 1; DT.order = ""; DT.filters = {}; buildDataShell(el); dtFetch(); }));
  const add = $("#dtAdd", el);
  if (add) add.onclick = () => dtForm(null);
  let timer;
  $("#dtQ", el).oninput = (e) => { clearTimeout(timer); timer = setTimeout(() => { DT.q = e.target.value.trim(); DT.page = 1; dtFetch(); }, 300); };
  (R.filters || []).forEach(async (f) => {
    const sel = $(`[data-f="${f.k}"]`, el);
    const pairs = f.src ? await dtOpts(f.src).catch(() => []) : Object.entries(f.choices);
    sel.innerHTML = optionList(pairs, DT.filters[f.k], f.all);
    sel.onchange = () => { DT.filters[f.k] = sel.value; DT.page = 1; dtFetch(); };
  });
}

async function dtFetch(silent) {
  const R = DATA[DT.res], res = DT.res, my = ++DT.seq;
  const p = new URLSearchParams({ page: DT.page });
  if (DT.q) p.set("search", DT.q);
  if (DT.order) p.set("ordering", DT.order);
  Object.entries(DT.filters).forEach(([k, v]) => v !== "" && p.set(k, v));
  let d;
  try { d = await api(`api/data/${res}?${p}`); }
  catch (e) { if (!silent) toast(esc(e.message), "danger"); return; }
  if (my !== DT.seq || res !== DT.res) return; // eskirgan javob
  if (d.results.length === 0 && DT.page > 1) { DT.page -= 1; return dtFetch(silent); }
  DT.rows = d.results; DT.count = d.count;
  const body = $("#dtBody");
  if (!body) return;
  $("#dtCount").textContent = `${nf(d.count)} ta ${R.noun}`;
  body.innerHTML = d.results.length ? dtTable(R) + dtPager(d) : emptyBox(DT.q || Object.values(DT.filters).some(Boolean) ? "Hech narsa topilmadi" : `Hali ${R.noun} yo'q`, "search");
  $$("th[data-sort]", body).forEach((h) => (h.onclick = () => {
    const k = h.dataset.sort;
    DT.order = DT.order === k ? "-" + k : k;
    DT.page = 1; dtFetch();
  }));
  $$("[data-edit]", body).forEach((b) => (b.onclick = () => dtForm(DT.rows.find((r) => String(r.id) === b.dataset.edit))));
  $$("[data-del]", body).forEach((b) => (b.onclick = () => dtDelete(DT.rows.find((r) => String(r.id) === b.dataset.del))));
  $$("[data-pg]", body).forEach((b) => (b.onclick = () => { DT.page += +b.dataset.pg; dtFetch(); }));
}

function dtTable(R) {
  const key = DT.order.replace(/^-/, ""), desc = DT.order.startsWith("-");
  const head = R.cols.map((c) => (c[2] ? `<th data-sort="${c[2]}" class="${key === c[2] ? "on" + (desc ? "" : " asc") : ""}">${c[0]}</th>` : `<th>${c[0]}</th>`)).join("");
  const ed = can(DT.res, "u"), del = can(DT.res, "d"), acts = ed || del;
  return `<div class="tw"><table class="t dt"><thead><tr>${head}${acts ? "<th></th>" : ""}</tr></thead><tbody>${DT.rows.map((r) => `<tr>
    ${R.cols.map((c) => `<td>${c[1](r)}</td>`).join("")}
    ${acts ? `<td class="dt-act">${ed ? `<button class="icon-btn" data-edit="${r.id}" title="Tahrirlash" aria-label="Tahrirlash">${I("pen")}</button>` : ""}
      ${del ? `<button class="icon-btn dt-danger" data-del="${r.id}" title="O'chirish" aria-label="O'chirish">${I("close")}</button>` : ""}</td>` : ""}</tr>`).join("")}</tbody></table></div>`;
}

function dtPager(d) {
  const pages = Math.max(1, Math.ceil(d.count / 50));
  if (pages === 1) return "";
  return `<div class="dt-pager"><button class="btn btn-line" data-pg="-1" ${d.previous ? "" : "disabled"}>${I("arrow-left")}Oldingi</button>
    <span>${DT.page} / ${pages}</span><button class="btn btn-line" data-pg="1" ${d.next ? "" : "disabled"}>Keyingi${I("arrow")}</button></div>`;
}

/* ----- qo'shish / tahrirlash ----- */
async function dtForm(row) {
  const R = DATA[DT.res], edit = !!row;
  const fields = R.fields.filter((f) => !(edit && f.createOnly));
  const opts = {};
  try { for (const f of fields) if (f.src) opts[f.src] = await dtOpts(f.src); } catch (e) { toast(esc(e.message), "danger"); return; }
  const field = (f) => {
    const v = edit ? row[f.k] : f.def ?? "";
    const id = "df_" + f.k;
    let input;
    if (f.type === "select") input = `<select id="${id}" data-k="${f.k}">${optionList(f.src ? opts[f.src] : Object.entries(f.choices), v, f.req ? null : "—")}</select>`;
    else if (f.type === "textarea") input = `<textarea id="${id}" data-k="${f.k}" ${f.req ? "required" : ""}>${esc(v)}</textarea>`;
    else if (f.type === "info") return `<div class="field"><label>${esc(f.label)}</label><div class="dt-info">${edit && row[f.k] ? esc(row[f.k]) : "yo'q"}</div></div>`;
    else if (f.type === "bool") return `<div class="checks"><label><input type="checkbox" data-k="${f.k}" data-bool ${v ? "checked" : ""}>${esc(f.label)}</label></div>`;
    else input = `<input id="${id}" data-k="${f.k}" type="${f.type}" value="${f.type === "password" ? "" : esc(v)}" ${f.req ? "required" : ""} ${f.type === "number" ? 'step="1"' : ""} ${f.type === "password" ? 'autocomplete="new-password"' : f.k === "login" ? 'autocomplete="off"' : ""}>`;
    return `<div class="field"><label for="${id}">${esc(f.label)}</label>${input}${f.hint ? `<div class="dt-hint">${esc(f.hint)}</div>` : ""}</div>`;
  };
  openModal(`${edit ? "Tahrirlash" : "Yangi"}: ${R.noun}`, `<form id="dtForm" novalidate>${fields.map(field).join("")}<div class="dt-err" id="dtErr" role="alert"></div></form>`,
    `<button class="btn btn-ghost" data-close>Bekor qilish</button><button class="btn btn-dark" id="dtSave">${I("check")}Saqlash</button>`);
  const first = $("#dtForm input, #dtForm select, #dtForm textarea");
  if (first && !edit) first.focus();
  const save = async () => {
    const body = {};
    $$("#dtForm [data-k]").forEach((i) => {
      const k = i.dataset.k, f = fields.find((x) => x.k === k);
      if (i.dataset.bool !== undefined) body[k] = i.checked;
      else if (f.type === "select" && f.src) body[k] = i.value === "" ? null : Number(i.value);
      else if (f.type === "select" || f.type === "date") body[k] = i.value === "" ? null : i.value;
      else if (f.type === "number") body[k] = i.value === "" ? null : Number(i.value);
      else body[k] = f.raw ? i.value : i.value.trim();
    });
    if (edit) fields.forEach((f) => { if (f.k === "key") delete body[f.k]; });
    $("#dtSave").disabled = true;
    try {
      await api(`api/data/${DT.res}${edit ? "/" + row.id : ""}`, { method: edit ? "PATCH" : "POST", json: body });
      await dtDone(edit ? "Saqlandi" : "Qo'shildi");
    } catch (e) {
      // DRF xatosi "name: ..." ko'rinishida: maydon kalitini formadagi nomga almashtiramiz
      $("#dtErr").textContent = fields.reduce((m, f) => m.replace(new RegExp(`(^|; )${f.k}: `), `$1${f.label}: `), e.message);
      $("#dtSave").disabled = false;
    }
  };
  $("#dtForm").addEventListener("input", () => { $("#dtErr").textContent = ""; });
  $("#dtSave").onclick = save;
  $("#dtForm").onsubmit = (e) => { e.preventDefault(); save(); };
}

/* ----- o'chirish ----- */
function dtDelete(row) {
  const R = DATA[DT.res];
  const name = row.name || row.title || row.text || "#" + row.id;
  openModal("O'chirish", `<p style="margin:0 0 10px;color:var(--ink)">«${esc(String(name).slice(0, 120))}» o'chirilsinmi?</p>${R.warn ? `<div class="note">${I("danger")}${esc(R.warn)}</div>` : ""}<div class="dt-err" id="dtErr" role="alert"></div>`,
    `<button class="btn btn-ghost" data-close>Bekor qilish</button><button class="btn btn-dark dt-confirm" id="dtOk">${I("close")}O'chirish</button>`);
  $("#dtOk").onclick = async () => {
    $("#dtOk").disabled = true;
    try { await api(`api/data/${DT.res}/${row.id}`, { method: "DELETE" }); await dtDone("O'chirildi"); }
    catch (e) { $("#dtErr").textContent = e.message; $("#dtOk").disabled = false; }
  };
}

// o'zgarishdan keyin: jadval, tanlov ro'yxatlari, filtrlar va asosiy ekranlar yangilanadi
async function dtDone(text) {
  closeModal();
  toast(text, "check");
  DT.opts = {};
  S.officeKey = "";
  await dtFetch();
  try { S.meta = await api("api/meta"); } catch (e) { /* keyingi yangilanishda */ }
  load(true);
}
