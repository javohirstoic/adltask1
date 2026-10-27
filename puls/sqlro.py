"""Yordamchi agent uchun faqat o'qiladigan SQL: tayyor asbob yetmagan har qanday savolga agent o'zi so'rov yozadi.

Himoya bir necha qatlamda:
1. PostgreSQL'da alohida rol (puls_ro_<baza>): u faqat `agent` sxemasidagi ko'rinishlarni (view) ko'radi — panel akkauntlari,
   parollar, sozlamalar unga ko'rinmaydi. Rol darajasida default_transaction_read_only va statement_timeout: so'rov hech
   narsani o'zgartira olmaydi va 5 soniyadan uzoq ishlamaydi. Rol paroli asosiy baza parolidan HMAC bilan hosil qilinadi:
   hech qayerga yozilmaydi va har jarayonda (panel, buyruq qatori) bir xil chiqadi.
2. Kod tekshiruvi: faqat bitta SELECT/WITH, yozish va tizim buyruqlari (INSERT, COPY, SET, pg_* funksiyalar ...) taqiqlangan.
3. Natija ko'pi 200 qator, uzun matnlar qisqartiriladi.
SQLite (faqat lokal sinov): o'sha nomli ko'rinishlar va faqat o'qish rejimidagi ulanish.
"""
import hashlib
import hmac
import re
import sqlite3
import time
from decimal import Decimal

from . import config

# Ustun nomlari o'zbekcha: model savoldagi so'zlarni ustunga oson bog'laydi, rahbar ham jadvalni tushunadi
VIEWS = {
    "xodimlar": "SELECT p.id, p.name AS ism, COALESCE(p.department, 'Belgilanmagan') AS bolim, p.username AS telegram, "
                "CASE WHEN p.dm_chat_id IS NULL THEN 0 ELSE 1 END AS botga_ulangan, p.dm_linked_at AS ulangan_vaqt, "
                "p.role AS guruh_roli FROM people p",
    "ishlar": "SELECT t.id, t.title AS nomi, t.assignee AS kim, "
              "CASE t.status WHEN 'done' THEN 'bajarilgan' WHEN 'open' THEN 'ochiq' ELSE t.status END AS holat, "
              "t.stage AS bosqich, t.progress AS foiz, t.priority AS muhimlik, pr.name AS loyiha, t.project_id AS loyiha_id, "
              "t.created_at AS berilgan_vaqt, substr(t.created_at, 1, 10) AS berilgan_sana, t.done_at AS bajarilgan_vaqt, "
              "substr(t.done_at, 1, 10) AS bajarilgan_sana, t.deadline AS muddat, t.weight AS ogirlik, t.hours AS soat, "
              "t.wcat AS ish_turi, t.wnote AS ogirlik_izohi, t.dup_kind AS takror_turi, t.dup_of AS asl_ish_id, "
              "t.dup_note AS takror_izohi, t.created_by AS bergan, t.note AS tavsif, t.done_msg AS hisobot_xabar_id, "
              "t.plan_day AS reja_kuni "
              "FROM tasks t LEFT JOIN projects pr ON pr.id = t.project_id",
    "loyihalar": "SELECT id, name AS nomi, key AS teg, chat_id AS guruh_id, deadline AS muddat, created_at AS yaratilgan FROM projects",
    "xabarlar": "SELECT m.id, m.chat_id AS guruh_id, c.title AS guruh, pe.name AS kim, m.date AS vaqt, substr(m.date, 1, 10) AS sana, "
                "m.kind AS turi, m.source AS manba, m.text AS matn, m.items AS ishlar_soni, m.project_id AS loyiha_id, "
                "m.edited_at AS tahrirlangan, m.deleted_at AS ochirilgan, m.report_day AS hisobot_kuni, m.holat AS holat "
                "FROM messages m LEFT JOIN people pe ON pe.id = m.user_id LEFT JOIN chats c ON c.id = m.chat_id",
    "xabar_tahrirlari": "SELECT message_id AS xabar_id, at AS vaqt, kind AS turi, old_text AS eski_matn, new_text AS yangi_matn "
                        "FROM message_edits",
    "muammolar": "SELECT b.id, pr.name AS loyiha, coalesce(b.kind, 'muammo') AS turi, b.text AS matn, b.author AS kim, "
                 "b.created_at AS ochilgan, b.resolved_at AS hal_qilingan FROM blockers b LEFT JOIN projects pr ON pr.id = b.project_id",
    "azolar": "SELECT mb.chat_id AS guruh_id, c.title AS guruh, pe.name AS kim, mb.joined_at AS qoshilgan, mb.left_at AS chiqqan "
              "FROM members mb LEFT JOIN people pe ON pe.id = mb.user_id LEFT JOIN chats c ON c.id = mb.chat_id",
    "guruhlar": "SELECT id, title AS nomi, demo AS namuna, coalesce(kind, 'ish') AS turi FROM chats",
    "murojaatlar": "SELECT a.id, pr.name AS loyiha, a.project_id AS loyiha_id, a.source AS manba, "
                   "coalesce(s.name, ch.title) AS kanal, a.type AS turi, coalesce(a.summary, a.text) AS muammo, a.text AS matn, "
                   "cl.name AS foydalanuvchi, a.created_at AS kelgan, substr(a.created_at, 1, 10) AS sana, "
                   "a.first_answer_at AS birinchi_javob, a.answered_by AS javob_bergan, a.line AS liniya, a.grade AS javob_bahosi, "
                   "a.status AS holat, a.resolved_at AS hal_qilingan, a.resolution AS qanday_yopildi, a.rep AS takroriy, "
                   "a.chain AS zanjir FROM appeals a LEFT JOIN projects pr ON pr.id = a.project_id "
                   "LEFT JOIN clients cl ON cl.id = a.client_id LEFT JOIN chats ch ON ch.id = a.chat_id "
                   "LEFT JOIN appeal_sources s ON s.id = a.source_id",
    "murojaat_yozishmasi": "SELECT appeal_id AS murojaat_id, at AS vaqt, kind AS turi, who AS kim, staff AS xodim, line AS liniya, "
                           "grade AS baho, note AS izoh, text AS matn FROM appeal_events",
    "qarorlar": "SELECT created_at AS vaqt, type AS turi, title AS nomi, sent AS yuborilgan, origin AS qayerdan FROM decisions",
    "vazifa_tarixi": "SELECT task_id AS ish_id, at AS vaqt, who AS kim, kind AS turi, text AS matn FROM task_events",
}

DOC = """Read-only views (one SELECT/WITH query, at most 200 rows come back):
- xodimlar(id, ism, bolim, telegram, botga_ulangan 0/1, ulangan_vaqt, guruh_roli)
- ishlar(id, nomi, kim = xodimlar.ism, holat 'ochiq'|'bajarilgan'|'taklif', bosqich 'yangi'|'qabul'|'jarayon'|'tekshiruv'|'bajarildi',
  foiz, muhimlik, loyiha, loyiha_id, berilgan_vaqt, berilgan_sana, bajarilgan_vaqt, bajarilgan_sana, muddat 'YYYY-MM-DD',
  ogirlik 1..5 (AI estimate: 1 trivial .. 5 very big), soat (AI estimate), ish_turi, ogirlik_izohi,
  takror_turi NULL|'takror' (re-posted his own old work)|'nusxa' (wrote someone else's work)|'rad' (boss said: not a repeat)|
  'muntazam' (routine, normal)|'davomi' (continuation)|'boshqa', asl_ish_id (the original row in ishlar), takror_izohi, bergan,
  tavsif, hisobot_xabar_id = xabarlar.id, reja_kuni (the day an "Ertangi reja" item was planned for; done on time if
  bajarilgan_sana <= reja_kuni))
  A reported finished item is a row with holat = 'bajarilgan'; its day is bajarilgan_sana. Repeats: takror_turi IN ('takror','nusxa').
- xabarlar(id, guruh_id, guruh, kim, vaqt, sana, turi 'done'|'task'|'blocker'|'request'|'deadline'|'none', manba, matn,
  ishlar_soni, loyiha_id, tahrirlangan, ochirilgan, hisobot_kuni (the day a report is about), holat 'yashil'|'sariq'|'qizil'
  (status the employee wrote)) — every Telegram group message (turi 'none' = ordinary chat). A report is late when vaqt is
  after hisobot_kuni + 18:00.
- xabar_tahrirlari(xabar_id, vaqt, turi 'edit'|'delete', eski_matn, yangi_matn) — earlier versions of edited/deleted messages
- muammolar(id, loyiha, turi 'muammo'|'murojaat', matn, kim, ochilgan, hal_qilingan)  team-internal: muammo = blocker of the
  author's work, 'murojaat' here = a bug or request posted in the team's work group (shown as "so'rov" in the panel)
- azolar(guruh_id, guruh, kim, qoshilgan, chiqqan)  guruh a'zolari (chiqqan NULL = hozir guruhda); har guruh = bitta loyiha
- loyihalar(id, nomi, teg, guruh_id, muddat, yaratilgan)
- guruhlar(id, nomi, namuna 0/1, turi 'ish' (team work group) | 'yordam' (support group where system users write))
- qarorlar(vaqt, turi, nomi, yuborilgan, qayerdan)   - vazifa_tarixi(ish_id, vaqt, kim, turi, matn)
- murojaatlar(id, loyiha, loyiha_id, manba 'tg'|'bot', kanal, turi 'login'|'status'|'docs'|'slow'|'howto'|'cert'|'data'|'payment'|
  'sms'|'mobile'|'boshqa', muammo, matn, foydalanuvchi, kelgan, sana, birinchi_javob, javob_bergan, liniya 0 chatbot|1 operator|
  2 mutaxassis|3 dasturchi, javob_bahosi 'good'|'part'|'tpl' (template)|NULL (no answer), holat 'ochiq'|'javob'|'hal'|'qayta',
  hal_qilingan, qanday_yopildi, takroriy 0/1 (same user, same system, same type within 21 days), zanjir) — appeals of system
  users (citizens, notaries) from support groups and chatbots, NOT employees' work. Murojaat = this view.
- murojaat_yozishmasi(murojaat_id, vaqt, turi 'murojaat'|'qoshimcha'|'javob'|'tasdiq'|'qayta'|'tuzatish', kim, xodim 0/1, liniya,
  baho, izoh, matn)
All times are TEXT 'YYYY-MM-DD HH:MM:SS' (Tashkent); *_sana is 'YYYY-MM-DD'. Compare dates as strings; month = substr(x, 1, 7).
Dialect: {dialect}. Use only standard SQL that works in it; no date functions are needed."""

LIMIT = 200
FORBID = re.compile(
    r"\b(insert|update|delete|merge|upsert|create|alter|drop|grant|revoke|truncate|copy|call|do|execute|prepare|"
    r"deallocate|listen|notify|unlisten|vacuum|analyze|cluster|reindex|lock|set|reset|refresh|comment|security|discard|"
    r"checkpoint|load|import|attach|detach|pragma|into)\b|\bpg_\w+|\blo_\w+|\bdblink\w*|\bcurrent_setting\b|\bset_config\b|"
    r"\binformation_schema\b|\bsqlite_\w+", re.I)


def dialect() -> str:
    from . import db
    return "PostgreSQL 17" if db.PG else "SQLite"


def _role() -> str:
    from psycopg.conninfo import conninfo_to_dict
    name = conninfo_to_dict(config.DATABASE_URL).get("dbname") or "puls"
    return "puls_ro_" + re.sub(r"[^a-z0-9_]", "_", name.lower())


def _password() -> str:
    from psycopg.conninfo import conninfo_to_dict
    main = conninfo_to_dict(config.DATABASE_URL).get("password") or ""
    return hmac.new(main.encode(), _role().encode(), hashlib.sha256).hexdigest()[:40]


def ensure(conn) -> None:
    """Ko'rinishlar va (PostgreSQL'da) faqat o'qiydigan rol. db.init() chaqiradi."""
    from . import db
    if not db.PG:
        for name, sql in VIEWS.items():
            conn.execute("DROP VIEW IF EXISTS %s" % name)
            conn.execute("CREATE VIEW %s AS %s" % (name, sql))
        return
    role, pw = _role(), _password()
    conn.execute("CREATE SCHEMA IF NOT EXISTS agent")
    for name, sql in VIEWS.items():
        conn.execute("DROP VIEW IF EXISTS agent.%s" % name)
        conn.execute("CREATE VIEW agent.%s AS %s" % (name, sql))
    if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = ?", (role,)).fetchone():
        conn.execute("CREATE ROLE %s LOGIN" % role)
    conn.execute("ALTER ROLE %s WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS "
                 "PASSWORD '%s'" % (role, pw))
    for setting in ("search_path = agent", "default_transaction_read_only = on", "statement_timeout = '5s'",
                    "idle_in_transaction_session_timeout = '10s'"):
        conn.execute("ALTER ROLE %s SET %s" % (role, setting))
    dbname = conn.execute("SELECT current_database()").fetchone()[0]
    conn.execute('GRANT CONNECT ON DATABASE "%s" TO %s' % (dbname, role))
    conn.execute("GRANT USAGE ON SCHEMA agent TO %s" % role)
    conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA agent TO %s" % role)


def check(sql: str) -> str:
    """Faqat bitta o'qish so'rovi qoladi; bo'lmasa ValueError (sababi agentga qaytadi va u tuzatadi)."""
    s = (sql or "").strip().rstrip(";").strip()
    if not re.match(r"(?is)^(select|with)\b", s):
        raise ValueError("faqat SELECT yoki WITH bilan boshlanadigan bitta so'rov yozing")
    scan = re.sub(r"'(?:[^']|'')*'", "''", s)          # matn ichidagi so'zlar ("update qildim") taqiqqa tushmasin
    scan = re.sub(r'"(?:[^"]|"")*"', '""', scan)
    if ";" in scan:
        raise ValueError("bitta so'rov yozing (nuqtali vergulsiz)")
    m = FORBID.search(scan)
    if m:
        raise ValueError("bu so'rovda ruxsat etilmagan so'z bor: %s" % m.group(0))
    return s


def _plain(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, str) and len(v) > 300:
        return v[:300] + "..."
    if v is not None and not isinstance(v, (int, float, str, bool)):
        return str(v)
    return v


def query(sql: str) -> dict:
    s = check(sql)
    wrapped = "SELECT * FROM (%s) AS q LIMIT %d" % (s, LIMIT + 1)
    from . import db
    t0 = time.monotonic()
    if db.PG:
        import psycopg
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        info = conninfo_to_dict(config.DATABASE_URL)
        info.update(user=_role(), password=_password())
        with psycopg.connect(make_conninfo(**info), autocommit=False, connect_timeout=5) as c:
            c.execute("SET TRANSACTION READ ONLY")
            try:
                cur = c.execute(wrapped)
                cols = [d.name for d in cur.description or []]
                rows = cur.fetchall()
            except psycopg.Error as e:
                raise ValueError("so'rov xatosi: %s" % str(e).split("\n")[0][:300])
            finally:
                c.rollback()
    else:
        c = sqlite3.connect("file:%s?mode=ro" % config.DB_PATH.as_posix(), uri=True, timeout=5)
        c.execute("PRAGMA query_only = ON")
        c.set_progress_handler(lambda: int(time.monotonic() - t0 > 5), 10000)  # 5 soniyadan oshsa to'xtatiladi
        try:
            cur = c.execute(wrapped)
            cols = [d[0] for d in cur.description or []]
            rows = cur.fetchall()
        except sqlite3.Error as e:
            raise ValueError("so'rov xatosi: %s" % str(e)[:300])
        finally:
            c.close()
    out = [[_plain(v) for v in r] for r in rows[:LIMIT]]
    return {"ustunlar": cols, "qatorlar": out, "soni": len(out), "kesildi": len(rows) > LIMIT,
            "vaqt_ms": round(1000 * (time.monotonic() - t0))}
