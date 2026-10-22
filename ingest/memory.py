"""Uzoq xotira: xabar qaysi vazifa haqida ekanini ma'no bo'yicha topish (RAG).

Har vazifa nomi embedding'ga (ma'nosini ifodalovchi 256 ta son) aylantiriladi va bazada saqlanadi.
Yangi xabar kelganda u ham songa aylanadi va eng yaqin vazifalar topiladi: so'zlari boshqa bo'lsa ham
("taqdimot slaydlari" va "prezentatsiya fayllari"), vazifa bir yil oldin yozilgan bo'lsa ham.
Embedding ishlamasa (internet, kvota) bo'sh ro'yxat qaytadi va dastur so'z bo'yicha qidiruv bilan davom etadi.
"""
import json
import logging
import math
import time
import urllib.error
import urllib.request
from array import array

from . import ai
from core import conf
from .models import Embedding

log = logging.getLogger("puls.memory")
MODEL = "gemini-embedding-001"
DIM = 256
BATCH = 50


def _embed(texts: list[str], task_type: str) -> list[list[float]] | None:
    if not conf.ai_enabled() or not texts:
        return None
    try:
        token = ai._token()
        url = ("https://aiplatform.googleapis.com/v1/projects/%s/locations/global/publishers/google/models/%s:predict"
               % (ai._gcp_project, MODEL))
        out = []
        for i in range(0, len(texts), BATCH):
            body = {"instances": [{"content": t[:2000], "task_type": task_type} for t in texts[i:i + BATCH]],
                    "parameters": {"outputDimensionality": DIM}}
            req = urllib.request.Request(url, json.dumps(body).encode(),
                                         {"Content-Type": "application/json", "Authorization": "Bearer " + token})
            for attempt in range(3):  # 429 (so'rov ko'p) bo'lsa biroz kutib qayta urinamiz
                try:
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        out += [p["embeddings"]["values"] for p in json.loads(resp.read())["predictions"]]
                    break
                except urllib.error.HTTPError as e:
                    if e.code != 429 or attempt == 2:
                        raise
                    time.sleep(1.5 * (attempt + 1))
        return out
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError) as e:
        log.warning("embedding ishlamadi, so'z bo'yicha qidiruvga o'tiladi: %s", e)
        return None


def _unit(v: list[float]) -> array:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return array("f", (x / n for x in v))


def vectors(titles: list[str]) -> dict[str, array]:
    """Nom -> birlik vektor. Yangi nomlar bir marta hisoblanib, bazada keshlanadi (namuna qayta yaratilsa ham)."""
    titles = sorted(set(titles))
    have = {}
    for i in range(0, len(titles), 500):
        part = titles[i:i + 500]
        for text, vec in Embedding.objects.filter(text__in=part).values_list("text", "vec"):
            have[text] = array("f", bytes(vec))
    missing = [t for t in titles if t not in have]
    if missing:
        got = _embed(missing, "RETRIEVAL_DOCUMENT")
        if got:
            for t, v in zip(missing, got):
                have[t] = _unit(v)
                Embedding.objects.update_or_create(text=t, defaults={"vec": have[t].tobytes()})
    return have


def nearest(query: str, tasks: list[dict], k: int) -> list[tuple[float, dict]]:
    """tasks ichidan query ga ma'nosi eng yaqin k tasi: [(o'xshashlik 0..1, vazifa)]."""
    if not query.strip() or not tasks:
        return []
    q = _embed([query], "RETRIEVAL_QUERY")
    if not q:
        return []
    qv = _unit(q[0])
    vecs = vectors([t["title"] for t in tasks])
    scored = [(sum(a * b for a, b in zip(qv, vecs[t["title"]])), t) for t in tasks if t["title"] in vecs]
    scored.sort(key=lambda x: -x[0])
    return scored[:k]
