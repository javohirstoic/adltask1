"""SQLite -> PostgreSQL: bir martalik ko'chirish.

    DATABASE_URL=postgresql://... python -m puls.migrate data/puls.db

Har jadval to'liq ko'chiriladi (PostgreSQL'dagi eski qatorlar avval o'chiriladi), id hisoblagichlari oxirgi id dan davom etadi,
embedding'lar pgvector ustuniga o'tadi. Oxirida har jadvalda qatorlar soni ikkala bazada solishtiriladi.
"""
import sqlite3
import sys

import numpy as np

from . import db

ORDER = ["meta", "settings", "chats", "people", "projects", "messages", "tasks", "blockers", "decisions", "alerts", "corrections",
         "demo_queue", "vec_cache", "work_eval", "judge_cache", "message_edits", "task_events", "task_checks", "accounts",
         "account_projects"]


def main(path: str) -> int:
    if not db.PG:
        print("DATABASE_URL berilmagan")
        return 2
    db.init()
    src = sqlite3.connect(path)
    src.row_factory = sqlite3.Row
    have = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    tables = [t for t in ORDER if t in have] + [t for t in have if t not in ORDER]
    report = []
    with db.session() as dst:
        for t in reversed(tables):
            if dst.execute("SELECT 1 FROM information_schema.tables WHERE table_name = ?", (t,)).fetchone():
                dst.execute('DELETE FROM "%s"' % t)
        for t in tables:
            pg_cols = {r[0] for r in dst.execute("SELECT column_name FROM information_schema.columns WHERE table_name = ?", (t,))}
            if not pg_cols:
                report.append((t, "PostgreSQL'da yo'q, o'tkazib yuborildi"))
                continue
            cols = [r[1] for r in src.execute('PRAGMA table_info("%s")' % t) if r[1] in pg_cols]
            rows = src.execute('SELECT %s FROM "%s"' % (", ".join('"%s"' % c for c in cols), t)).fetchall()
            data = []
            for r in rows:
                vals = list(r)
                if t == "vec_cache":
                    vals[cols.index("vec")] = np.frombuffer(vals[cols.index("vec")], dtype=np.float32)
                data.append(vals)
            if data:
                dst.executemany('INSERT INTO "%s" (%s) VALUES (%s)' % (t, ", ".join('"%s"' % c for c in cols), ", ".join("?" * len(cols))),
                                data)
            if "id" in cols and t in db._SERIAL:
                dst.execute("SELECT setval(pg_get_serial_sequence(?, 'id'), (SELECT coalesce(max(id), 0) + 1 FROM \"%s\"), false)" % t, (t,))
            report.append((t, len(data)))
    ok = True
    with db.session() as dst:
        for t, n in report:
            if isinstance(n, int):
                got = dst.execute('SELECT count(*) FROM "%s"' % t).fetchone()[0]
                ok &= got == n
                print("%-18s %8d -> %8d %s" % (t, n, got, "" if got == n else "XATO"))
            else:
                print("%-18s %s" % (t, n))
    print("Tayyor" if ok else "Farq bor: tekshiring")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "data/puls.db"))
