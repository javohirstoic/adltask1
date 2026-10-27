"""Uzoq xotira: xabar qaysi vazifa haqida ekanini ma'no bo'yicha topish (RAG).

Har vazifa nomi embedding'ga (ma'nosini ifodalovchi 256 ta son) aylantiriladi va bazada saqlanadi.
Yangi xabar kelganda u ham songa aylanadi va eng yaqin vazifalar topiladi: so'zlari boshqa bo'lsa ham
("taqdimot slaydlari" va "prezentatsiya fayllari"), vazifa bir yil oldin yozilgan bo'lsa ham.
Embedding ishlamasa (internet, kvota) bo'sh ro'yxat qaytadi va dastur so'z bo'yicha qidiruv bilan davom etadi.
"""
import json
import logging
import math
import sqlite3
import time
import urllib.error
import urllib.request
from array import array

import numpy as np

from . import ai, config, db

log = logging.getLogger("puls.memory")
MODEL = "gemini-embedding-001"
DIM = 256
BATCH = 50


def _embed(texts: list[str], task_type: str, patient: bool = False) -> list[list[float]] | None:
    """patient=True (fon ishchisi): 429 bo'lsa uzoqroq kutadi va so'rovlar orasida pauza qiladi. Yarmida to'xtasa ham
    olingan qismi qaytadi (keshga yoziladi, keyingi safar qolgani olinadi)."""
    if not config.ai_enabled() or not texts:
        return None
    out = []
    try:
        token = ai._token()
        url = ("https://aiplatform.googleapis.com/v1/projects/%s/locations/global/publishers/google/models/%s:predict"
               % (ai._gcp_project, MODEL))
        for i in range(0, len(texts), BATCH):
            if patient and i:
                time.sleep(0.4)
            body = {"instances": [{"content": t[:2000], "task_type": task_type} for t in texts[i:i + BATCH]],
                    "parameters": {"outputDimensionality": DIM}}
            req = urllib.request.Request(url, json.dumps(body).encode(),
                                         {"Content-Type": "application/json", "Authorization": "Bearer " + token})
            tries = 6 if patient else 3
            for attempt in range(tries):  # 429 (so'rov ko'p) bo'lsa kutib qayta urinamiz
                try:
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        out += [p["embeddings"]["values"] for p in json.loads(resp.read())["predictions"]]
                    break
                except urllib.error.HTTPError as e:
                    if e.code != 429 or attempt == tries - 1:
                        raise
                    time.sleep(min(30, 2 ** (attempt + 1)) if patient else 1.5 * (attempt + 1))
        return out
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError) as e:
        log.warning("embedding ishlamadi%s: %s", ", olingani saqlanadi" if out else ", so'z bo'yicha qidiruvga o'tiladi", e)
        return out or None


def _unit(v: list[float]) -> array:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return array("f", (x / n for x in v))


def vectors(conn: sqlite3.Connection, titles: list[str], patient: bool = False) -> dict[str, array]:
    """Nom -> birlik vektor. Yangi nomlar bir marta hisoblanib, bazada keshlanadi (namuna qayta yaratilsa ham)."""
    titles = sorted(set(titles))
    have = {}
    for i in range(0, len(titles), 500):
        part = titles[i:i + 500]
        for r in conn.execute("SELECT text, vec FROM vec_cache WHERE text IN (%s)" % ",".join("?" * len(part)), part):
            have[r["text"]] = np.asarray(r["vec"], dtype=np.float32) if db.PG else array("f", r["vec"])
    missing = [t for t in titles if t not in have]
    if missing:
        got = _embed(missing, "RETRIEVAL_DOCUMENT", patient)
        if got:
            for t, v in zip(missing, got):
                have[t] = np.frombuffer(_unit(v), dtype=np.float32).copy() if db.PG else _unit(v)
                conn.execute("INSERT INTO vec_cache(text, vec) VALUES(?, ?) ON CONFLICT(text) DO UPDATE SET vec = excluded.vec",
                             (t, have[t] if db.PG else have[t].tobytes()))
    return have


def nearest(conn: sqlite3.Connection, query: str, tasks: list[dict], k: int) -> list[tuple[float, dict]]:
    """tasks ichidan query ga ma'nosi eng yaqin k tasi: [(o'xshashlik 0..1, vazifa)]."""
    if not query.strip() or not tasks:
        return []
    q = _embed([query], "RETRIEVAL_QUERY")
    if not q:
        return []
    qv = _unit(q[0])
    vecs = vectors(conn, [t["title"] for t in tasks])
    have = [t for t in tasks if t["title"] in vecs]
    if not have:
        return []
    sims = matrix([vecs[t["title"]] for t in have]) @ np.frombuffer(qv, dtype=np.float32)
    order = np.argsort(-sims)[:k]
    return [(float(sims[i]), have[i]) for i in order]


def matrix(vs: list[array]) -> np.ndarray:
    """Birlik vektorlar ro'yxati -> (n, DIM) matritsa: ming vazifa bilan solishtirish bitta ko'paytma."""
    return np.frombuffer(b"".join(v.tobytes() for v in vs), dtype=np.float32).reshape(len(vs), -1)
