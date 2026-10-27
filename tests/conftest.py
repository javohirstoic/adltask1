"""Hamma testlar uchun: til modeli va embedding chaqirilmaydi (testlar internetsiz, tez va bir xil natija beradi).
Model kerak bo'lgan testlar soxta javobni o'zi o'rnatadi.

DATABASE_URL berilgan bo'lsa testlar PostgreSQL'da yuradi: har test oldidan sxema tozalanadi (har test o'z toza bazasida).
"""
import pytest

from puls import config, db


@pytest.fixture(autouse=True)
def _no_network_ai(monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", "off")




@pytest.fixture(autouse=True)
def _fresh_postgres():
    if not db.PG:
        yield
        return
    import psycopg
    db.reset_pool()
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as c:
        c.execute("DROP SCHEMA IF EXISTS public CASCADE")
        c.execute("CREATE SCHEMA public")
    yield
    db.reset_pool()
