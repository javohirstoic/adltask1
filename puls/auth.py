"""Panelga kirish: login, parol va rollar.

Rollar Django versiyasi (core/permissions.py) bilan bir xil: admin, rahbar, menejer. Parol Django formatida saqlanadi
(pbkdf2_sha256$takror$tuz$xesh), shuning uchun akkauntlar Django'ga o'zgarishsiz ko'chadi.
Panelga faqat login va parol bilan kiriladi. Birinchi admin serverda yaratiladi (python -m puls.auth <login>), qolgan
foydalanuvchilarni admin paneldagi "Foydalanuvchilar va rollar" oynasidan qo'shadi.
"""
import base64
import hashlib
import hmac
import secrets
import sqlite3
import time

from . import config, db

ADMIN, BOSS, MANAGER = "admin", "rahbar", "menejer"
ROLES = {ADMIN: "Admin", BOSS: "Rahbar", MANAGER: "Loyiha menejeri"}
ROLE_TEXT = {
    ADMIN: "Hamma narsa: foydalanuvchilar va rollar, sozlamalar, guruh tarixini yuklash",
    BOSS: "Hamma loyiha va xodimni ko'radi, qaror qabul qiladi, vazifa beradi. Foydalanuvchi va sozlamalarga kirmaydi",
    MANAGER: "Faqat o'ziga biriktirilgan loyihalarni ko'radi va ularda vazifa beradi",
}
# Ruxsatlar bitta joyda: server ham, panel ham shu jadvalga qaraydi (/api/me -> can)
PERMS = {
    ADMIN: {"board", "decide", "correct", "people", "settings", "import", "accounts"},
    BOSS: {"board", "decide", "correct"},
    MANAGER: {"board"},
}
ITERATIONS = 600_000
SESSION_DAYS = 30
COMMON = {"12345678", "123456789", "1234567890", "password", "qwerty123", "11111111", "parol123", "admin123", "00000000"}


def hash_password(password: str, salt: str | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or secrets.token_urlsafe(16)[:22]
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (iterations, salt, base64.b64encode(dk).decode())


def check_password(password: str, encoded: str | None) -> bool:
    try:
        algo, iterations, salt, _ = (encoded or "").split("$", 3)
    except ValueError:
        return False
    return algo == "pbkdf2_sha256" and hmac.compare_digest(hash_password(password, salt, int(iterations)), encoded)


def password_problem(password: str, login: str = "") -> str | None:
    """Parol talablari (Django'dagi asosiy tekshiruvlar): qisqa, faqat raqam, oddiy yoki loginga o'xshash bo'lmasin."""
    if len(password) < 8:
        return "Parol kamida 8 belgi bo'lsin"
    if password.isdigit():
        return "Parol faqat raqamdan iborat bo'lmasin"
    if password.lower() in COMMON:
        return "Bu parol juda oddiy"
    if login and login.lower() in password.lower():
        return "Parolda login bo'lmasin"
    return None


def _clean_login(login: str) -> str:
    login = (login or "").strip().lower()
    if not 3 <= len(login) <= 32 or not all(c.isalnum() or c in "._-" for c in login):
        raise ValueError("Login 3-32 belgi: lotin harfi, raqam, nuqta, chiziqcha")
    return login


# ---------- sessiya ----------

def _sign(text: str) -> str:
    return hmac.new(config.PANEL_SECRET.encode(), text.encode(), hashlib.sha256).hexdigest()[:40]


def make_token(acc) -> str:
    """id.muddat.imzo — imzoga parol xeshining bir bo'lagi kiradi: parol almashsa eski sessiyalar o'z-o'zidan yopiladi."""
    exp = int(time.time()) + SESSION_DAYS * 86400
    return "%d.%d.%s" % (acc["id"], exp, _sign("%d.%d.%s" % (acc["id"], exp, acc["pass_hash"][-16:])))


def account_by_token(conn: sqlite3.Connection, token: str | None) -> dict | None:
    try:
        aid, exp, sig = (token or "").split(".")
        aid, exp = int(aid), int(exp)
    except ValueError:
        return None
    if exp < time.time():
        return None
    acc = conn.execute("SELECT * FROM accounts WHERE id = ? AND active = 1", (aid,)).fetchone()
    if acc is None or not hmac.compare_digest(sig, _sign("%d.%d.%s" % (aid, exp, acc["pass_hash"][-16:]))):
        return None
    return public(conn, acc)


def public(conn: sqlite3.Connection, acc) -> dict:
    acc = dict(acc)
    projects = [dict(r) for r in conn.execute(
        "SELECT p.id, p.name FROM account_projects ap JOIN projects p ON p.id = ap.project_id WHERE ap.account_id = ? ORDER BY p.name",
        (acc["id"],))]
    return {"id": acc["id"], "login": acc["login"], "name": acc["name"], "role": acc["role"], "role_label": ROLES[acc["role"]],
            "person": acc["person"], "active": bool(acc["active"]), "created_at": acc["created_at"], "created_by": acc["created_by"],
            "last_login": acc["last_login"], "projects": projects, "can": sorted(PERMS[acc["role"]])}


def scope(acc: dict | None) -> set[int] | None:
    """Menejer uchun o'z loyihalari; admin va rahbar uchun None (cheklov yo'q)."""
    if acc and acc["role"] == MANAGER:
        return {p["id"] for p in acc["projects"]}
    return None


def can(acc: dict | None, perm: str) -> bool:
    return bool(acc) and perm in PERMS.get(acc["role"], set())


def has_accounts(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone() is not None


def login(conn: sqlite3.Connection, login_: str, password: str) -> dict | None:
    acc = conn.execute("SELECT * FROM accounts WHERE login = ?", ((login_ or "").strip().lower(),)).fetchone()
    if acc is None:
        hash_password(password)  # vaqt bo'yicha farq bilinmasin: login bor-yo'qligi javob tezligidan sezilmaydi
        return None
    if not check_password(password, acc["pass_hash"]):
        return None
    if not acc["active"]:
        raise PermissionError("Akkaunt o'chirilgan. Admin bilan bog'laning")
    conn.execute("UPDATE accounts SET last_login = ? WHERE id = ?", (config.now().strftime("%Y-%m-%d %H:%M:%S"), acc["id"]))
    return dict(acc)


# ---------- boshqarish (faqat admin) ----------

def _validate(conn: sqlite3.Connection, role: str, person: str | None, projects: list[int] | None) -> None:
    if role not in ROLES:
        raise ValueError("Rol: Admin, Rahbar yoki Loyiha menejeri")
    if person and not conn.execute("SELECT 1 FROM people WHERE name = ?", (person,)).fetchone():
        raise ValueError("Bunday xodim topilmadi")
    for pid in projects or []:
        if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (pid,)).fetchone():
            raise ValueError("Loyiha topilmadi")


def _set_projects(conn: sqlite3.Connection, aid: int, role: str, projects: list[int] | None) -> None:
    conn.execute("DELETE FROM account_projects WHERE account_id = ?", (aid,))
    if role == MANAGER:
        conn.executemany("INSERT INTO account_projects(account_id, project_id) VALUES(?, ?) ON CONFLICT DO NOTHING",
                         [(aid, p) for p in projects or []])


def create(conn: sqlite3.Connection, login_: str, name: str, password: str, role: str, person: str | None = None,
           projects: list[int] | None = None, created_by: str | None = None) -> int:
    login_ = _clean_login(login_)
    name = " ".join((name or "").split())[:60]
    if len(name) < 2:
        raise ValueError("Ism-familiyani yozing")
    problem = password_problem(password, login_)
    if problem:
        raise ValueError(problem)
    _validate(conn, role, person, projects)
    if conn.execute("SELECT 1 FROM accounts WHERE login = ?", (login_,)).fetchone():
        raise ValueError("Bu login band")
    cur = conn.execute("INSERT INTO accounts(login, name, pass_hash, role, person, active, created_at, created_by) "
                       "VALUES(?, ?, ?, ?, ?, 1, ?, ?)",
                       (login_, name, hash_password(password), role, person or None, config.now().strftime("%Y-%m-%d %H:%M:%S"), created_by))
    _set_projects(conn, cur.lastrowid, role, projects)
    db.bump_version(conn)
    return cur.lastrowid


def _admins_left(conn: sqlite3.Connection, without: int) -> int:
    return conn.execute("SELECT count(*) FROM accounts WHERE role = 'admin' AND active = 1 AND id != ?", (without,)).fetchone()[0]


def update(conn: sqlite3.Connection, aid: int, me: int, **f) -> None:
    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    if acc is None:
        raise ValueError("Akkaunt topilmadi")
    role = f.get("role") or acc["role"]
    active = acc["active"] if f.get("active") is None else int(bool(f["active"]))
    if acc["role"] == ADMIN and acc["active"] and (role != ADMIN or not active) and not _admins_left(conn, aid):
        raise ValueError("Kamida bitta faol admin qolishi kerak")
    if aid == me and not active:
        raise ValueError("O'zingizni o'chira olmaysiz")
    person = acc["person"] if f.get("person") is None else (f["person"] or None)
    _validate(conn, role, person, f.get("projects"))
    name = acc["name"] if f.get("name") is None else " ".join(f["name"].split())[:60]
    if len(name) < 2:
        raise ValueError("Ism-familiyani yozing")
    sets, args = ["name = ?", "role = ?", "person = ?", "active = ?"], [name, role, person, active]
    if f.get("password"):
        problem = password_problem(f["password"], acc["login"])
        if problem:
            raise ValueError(problem)
        sets.append("pass_hash = ?"); args.append(hash_password(f["password"]))
    conn.execute("UPDATE accounts SET %s WHERE id = ?" % ", ".join(sets), args + [aid])
    if f.get("projects") is not None or role != MANAGER:
        _set_projects(conn, aid, role, f.get("projects") if f.get("projects") is not None else
                      [r[0] for r in conn.execute("SELECT project_id FROM account_projects WHERE account_id = ?", (aid,))])
    db.bump_version(conn)


def remove(conn: sqlite3.Connection, aid: int, me: int) -> None:
    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    if acc is None:
        raise ValueError("Akkaunt topilmadi")
    if aid == me:
        raise ValueError("O'zingizni o'chira olmaysiz")
    if acc["role"] == ADMIN and acc["active"] and not _admins_left(conn, aid):
        raise ValueError("Kamida bitta faol admin qolishi kerak")
    conn.execute("DELETE FROM account_projects WHERE account_id = ?", (aid,))
    conn.execute("DELETE FROM accounts WHERE id = ?", (aid,))
    db.bump_version(conn)


def change_own(conn: sqlite3.Connection, aid: int, old: str, new: str) -> dict:
    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    if acc is None or not check_password(old, acc["pass_hash"]):
        raise ValueError("Hozirgi parol noto'g'ri")
    problem = password_problem(new, acc["login"])
    if problem:
        raise ValueError(problem)
    conn.execute("UPDATE accounts SET pass_hash = ? WHERE id = ?", (hash_password(new), aid))
    return dict(conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone())


def listing(conn: sqlite3.Connection) -> list[dict]:
    order = {ADMIN: 0, BOSS: 1, MANAGER: 2}
    rows = [public(conn, r) for r in conn.execute("SELECT * FROM accounts")]
    return sorted(rows, key=lambda a: (not a["active"], order[a["role"]], a["name"].lower()))


if __name__ == "__main__":  # serverda parolni tiklash: python -m puls.auth <login>
    import getpass
    import sys
    db.init()
    with db.session() as c:
        who = sys.argv[1] if len(sys.argv) > 1 else input("Login: ")
        row = c.execute("SELECT id FROM accounts WHERE login = ?", (who.strip().lower(),)).fetchone()
        pw = getpass.getpass("Yangi parol: ")
        if row is None:
            print("Bunday login yo'q. Yangi admin yaratiladi.")
            create(c, who, who, pw, ADMIN, created_by="server")
        else:
            update(c, row["id"], 0, password=pw, active=True)
        print("Tayyor")
