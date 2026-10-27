"""Panelga kirish: parol, sessiya, rollar va loyiha menejeri doirasi."""
from datetime import datetime

import pytest

from puls import analytics, auth, board, config, db, settings
from puls.ingest import Incoming, ingest

CHAT = -100777


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(auth, "ITERATIONS", 1000)  # testlar tez bo'lsin
    db.init()
    c = db.connect()
    settings.save(c, {"project_mode": "teg"})  # bitta guruhda bir nechta loyiha (teg bo'yicha)
    c.execute("INSERT INTO people(id, name, username, department) VALUES(2, 'Sardor Tursunov', 'demo_sardor', 'Backend')")
    for i, text in enumerate(("#task #Shajara Login sahifasi", "#task #Portal Bosh sahifa dizayni"), 1):
        ingest(c, Incoming(CHAT, "G", i, 2, "Sardor Tursunov", "demo_sardor", datetime(2026, 10, 20, 9, i), text), use_ai=False)
    yield c
    c.close()


def pid(conn, name):
    return conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()["id"]


def test_password_is_django_format_and_checked():
    h = auth.hash_password("Kuchli-parol-7")
    assert h.startswith("pbkdf2_sha256$") and auth.check_password("Kuchli-parol-7", h)
    assert not auth.check_password("kuchli-parol-7", h) and not auth.check_password("x", "buzilgan")


@pytest.mark.parametrize("pw", ["qisqa1", "12345678901", "password", "javohir2026"])
def test_weak_passwords_rejected(conn, pw):
    with pytest.raises(ValueError):
        auth.create(conn, "javohir", "Javohir Jumaboyev", pw, auth.ADMIN)


def test_login_session_and_password_change_closes_old_sessions(conn):
    aid = auth.create(conn, "Javohir", "Javohir Jumaboyev", "Kuchli-parol-7", auth.ADMIN)
    assert auth.login(conn, "javohir", "xato-parol-1") is None
    acc = auth.login(conn, " JAVOHIR ", "Kuchli-parol-7")
    token = auth.make_token(acc)
    assert auth.account_by_token(conn, token)["role_label"] == "Admin"
    auth.change_own(conn, aid, "Kuchli-parol-7", "Yangi-parol-77")
    assert auth.account_by_token(conn, token) is None  # parol almashdi: eski sessiya yopildi
    assert auth.account_by_token(conn, "1.1.soxta") is None


def test_last_admin_cannot_be_removed_or_demoted(conn):
    a = auth.create(conn, "javohir", "Javohir Jumaboyev", "Kuchli-parol-7", auth.ADMIN)
    b = auth.create(conn, "feruzbek", "Feruzbek", "Boshqa-parol-8", auth.BOSS)
    with pytest.raises(ValueError):
        auth.update(conn, a, b, role=auth.BOSS)
    with pytest.raises(ValueError):
        auth.remove(conn, a, b)
    with pytest.raises(ValueError):
        auth.remove(conn, b, b)  # o'zini o'chira olmaydi
    auth.update(conn, b, a, active=False)
    with pytest.raises(PermissionError):
        auth.login(conn, "feruzbek", "Boshqa-parol-8")


def test_manager_sees_only_own_projects(conn):
    own, other = pid(conn, "Shajara"), pid(conn, "Portal")
    aid = auth.create(conn, "valijon", "Valijon", "Menejer-parol-9", auth.MANAGER, projects=[own])
    acc = auth.public(conn, conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone())
    sc = auth.scope(acc)
    assert sc == {own} and not auth.can(acc, "decide") and auth.can(acc, "board")
    data = analytics.compute(conn, "week", scope=sc, now=datetime(2026, 10, 22, 10))
    assert [p["name"] for p in data["projects"]] == ["Shajara"]
    assert {c["project"] for c in board.board(conn, scope=sc)["cards"]} == {"Shajara"}
    task = conn.execute("SELECT id FROM tasks WHERE project_id = ?", (other,)).fetchone()["id"]
    with pytest.raises(PermissionError):
        board.allowed(conn, task, sc)
    assert auth.scope(auth.public(conn, conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone())) == {own}


def test_role_change_from_manager_clears_projects(conn):
    a = auth.create(conn, "javohir", "Javohir Jumaboyev", "Kuchli-parol-7", auth.ADMIN)
    m = auth.create(conn, "valijon", "Valijon", "Menejer-parol-9", auth.MANAGER, projects=[pid(conn, "Shajara")])
    auth.update(conn, m, a, role=auth.BOSS)
    acc = auth.public(conn, conn.execute("SELECT * FROM accounts WHERE id = ?", (m,)).fetchone())
    assert acc["projects"] == [] and auth.scope(acc) is None
