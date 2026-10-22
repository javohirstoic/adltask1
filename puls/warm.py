"""Namuna matnlari uchun AI keshini oldindan to'ldirish: bugun va keyingi bir necha kun.

Namuna har kuni bugungi sanaga nisbatan qayta yasaladi, shuning uchun ertangi matnlar bugungidan
biroz farq qiladi. Kesh oldindan to'ldirilsa, taqdimot kuni barcha erkin matnlarni AI o'qigan bo'ladi.

    python -m puls.warm --days 4
"""
import argparse
import json
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta

from . import ai, config, seed
from .parser import parse_format


def texts_for(days: int) -> dict:
    out = {}
    today = config.now().date()
    for k in range(days):
        until = datetime.combine(today + timedelta(days=k), time(20, 0))
        for m in seed.generate(until, random.Random(20261022)):
            if parse_format(m.text, m.at.date()) is None:
                out.setdefault(m.text, m)
    return out


def main(days: int) -> None:
    path = config.DB_PATH.parent / "ai_cache.json"
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    todo = [m for t, m in texts_for(days).items() if t not in cache]
    print("Keshda yo'q: %d ta matn" % len(todo), flush=True)
    projects = [{"key": P["key"], "name": P["name"], "aliases": P["aliases"]} for P in seed.PROJECTS]
    lock, done = threading.Lock(), [0]
    # 20 tadan bitta so'rovda: kvota (daqiqasiga so'rovlar soni) yetadi
    chunks = [todo[i:i + 20] for i in range(0, len(todo), 20)]

    def ask(chunk) -> None:
        res = ai.extract_many([(m.text, seed.PEOPLE[m.who][1]) for m in chunk], projects, config.now().date())
        with lock:
            for m, p in zip(chunk, res):
                if p is not None:
                    cache[m.text] = {"kind": p.kind, "project": p.project, "items": [[i.title, i.assignee] for i in p.items]}
            done[0] += len(chunk)
            path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            print("  %d/%d" % (done[0], len(todo)), flush=True)

    with ThreadPoolExecutor(2) as ex:
        list(ex.map(ask, chunks))
    print("Tayyor: keshda %d ta matn" % len(cache), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=4)
    main(ap.parse_args().days)
