"""Sozlamalar: barcha chegaralar va og'irliklar bazada turadi, paneldan o'zgartiriladi (kodga qotirilmaydi)."""
import json
import sqlite3

# kalit: (standart qiymat, nomi, eng kam, eng ko'p, guruh[, tanlov variantlari])
SPEC = {
    "silent_days": (4, "Xodim necha ish kuni xabarsiz qolsa «Jim»", 1, 15, "Xodim holati"),
    "stuck_days": (10, "Eng eski ochiq vazifasi necha kunlik bo'lsa «Cho'zilgan»", 3, 60, "Xodim holati"),
    "overload_ratio": (1.8, "2 haftada berilgan vazifa jamoa o'rtachasidan necha marta ko'p bo'lsa «Ishi ko'p»", 1.2, 5, "Xodim holati"),
    "overload_min_open": (6, "«Ishi ko'p» uchun kamida nechta ochiq vazifa", 2, 50, "Xodim holati"),
    "deadline_warn_days": (3, "Muddatga necha kun qolganda tekshiriladi", 1, 30, "Loyiha holati"),
    "deadline_warn_progress": (70, "Shu paytda bajarilgan qismi necha foizdan kam bo'lsa «Xavf»", 10, 100, "Loyiha holati"),
    "project_silence_days": (2, "Loyihada necha ish kuni xabar bo'lmasa «Diqqat»", 1, 15, "Loyiha holati"),
    "project_silence_high_days": (5, "Necha ish kuni xabar bo'lmasa «Xavf»", 2, 30, "Loyiha holati"),
    "blocker_high_days": (3, "Muammo necha kun hal bo'lmasa «Xavf»", 1, 30, "Loyiha holati"),
    "low_activity_pct": (40, "Vazifalar soni o'rtachaning necha foizidan kam bo'lsa «kam faol»", 5, 90, "Loyiha holati"),
    "bus_share": (75, "Ishning necha foizi bitta odamda bo'lsa ogohlantirish", 50, 100, "Loyiha holati"),
    "age_slow_days": (3, "Vazifa necha kundan «cho'zilyapti»", 1, 30, "Vazifa yoshi"),
    "age_stuck_days": (7, "Vazifa necha kundan «qotib qolgan» (qizil)", 2, 60, "Vazifa yoshi"),
    "w_completion": (30, "Bajarish", 0, 100, "Baho og'irliklari"),
    "w_output": (30, "Ish hajmi (AI bahosi)", 0, 100, "Baho og'irliklari"),
    "w_speed": (15, "Tezlik", 0, 100, "Baho og'irliklari"),
    "w_regular": (15, "Muntazam hisobot", 0, 100, "Baho og'irliklari"),
    "w_fresh": (10, "Eskirgan vazifa yo'qligi", 0, 100, "Baho og'irliklari"),
    "repeat_penalty": (5, "Qayta yozilgan har ish uchun reytingdan ayiriladi (4 haftada)", 0, 25, "Baho og'irliklari"),
    "bot_react": ("off", "Bot guruhdagi xabarga reaksiya qo'yadi", None, None, "Hisobot qabul qilish",
                  [("off", "Yo'q, jim qabul qiladi"), ("on", "Ha (👍, 🤔)")]),
    "report_from": ("hamma", "Hisobot kimdan qabul qilinadi", None, None, "Hisobot qabul qilish",
                    [("hamma", "Guruhdagi har kimdan (keyin panelda tasdiqlanadi)"),
                     ("ulangan", "Faqat tasdiqlangan yoki botga ulangan xodimdan")]),
    "report_deadline": ("18:00", "Kunlik hisobot muddati (shundan keyin yozilgani kechikkan)", None, None, "Hisobot qabul qilish"),
    "project_mode": ("guruh", "Loyiha", None, None, "Hisobot qabul qilish",
                     [("guruh", "Har guruh — bitta loyiha"), ("teg", "Hisobotdagi loyiha tegi bo'yicha")]),
    "ai_read": ("aqlli", "Tegsiz xabarlar", None, None, "Hisobot qabul qilish",
                [("aqlli", "Ishga o'xshaganini AI o'qiydi"), ("teg", "Faqat tegli hisobot (AI ishlatilmaydi)")]),
    "assign_check": ("guruh", "Ishi ko'p xodimga vazifa berilsa ogohlantirish", None, None, "Vazifa berish",
                     [("guruh", "Guruhda"), ("shaxsan", "Bergan kishiga shaxsan"), ("off", "O'chiq")]),
    "assign_policy": ("hamma", "Boshqa xodimga vazifa beradi", None, None, "Vazifa berish",
                      [("hamma", "Har kim"), ("rahbar", "Faqat rahbarlar")]),
    "digest_morning": ("09:00", "Ertalabki brifing", None, None, "Telegram brifing"),
    "digest_evening": ("19:00", "Kun yakuni", None, None, "Telegram brifing"),
    "group_report": ("excel", "Har guruhga bugun bajarilgan vazifalar", None, None, "Telegram brifing",
                     [("excel", "Excel fayl"), ("off", "O'chiq")]),
    "group_report_time": ("18:30", "Guruhga yuboriladigan vaqt", None, None, "Telegram brifing"),
}


def load(conn: sqlite3.Connection) -> dict:
    values = {k: v[0] for k, v in SPEC.items()}
    for r in conn.execute("SELECT key, value FROM settings"):
        if r["key"] in SPEC:
            values[r["key"]] = json.loads(r["value"])
    return values


def save(conn: sqlite3.Connection, changes: dict) -> dict:
    """Faqat ma'lum kalitlar, ruxsat etilgan oraliqda saqlanadi. Xato bo'lsa ValueError."""
    for key, value in changes.items():
        if key not in SPEC:
            raise ValueError("Noma'lum sozlama: %s" % key)
        default, label, lo, hi = SPEC[key][:4]
        options = SPEC[key][5] if len(SPEC[key]) > 5 else None
        if options:
            if value not in [o[0] for o in options]:
                raise ValueError("%s: noto'g'ri qiymat" % label)
        elif isinstance(default, str):
            value = str(value).strip()
            h, _, m = value.partition(":")
            if not (h.isdigit() and m.isdigit() and 0 <= int(h) < 24 and 0 <= int(m) < 60):
                raise ValueError("%s: vaqt HH:MM ko'rinishida bo'lsin" % label)
            value = "%02d:%02d" % (int(h), int(m))
        else:
            try:
                value = float(value) if isinstance(default, float) else int(round(float(value)))
            except (TypeError, ValueError):
                raise ValueError("%s: son kiriting" % label)
            if not lo <= value <= hi:
                raise ValueError("%s: %s dan %s gacha bo'lsin" % (label, lo, hi))
        conn.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (key, json.dumps(value)))
    return load(conn)


HIDDEN = {"project_mode"}  # bitta guruh — bitta loyiha: shart, panelda o'zgartirilmaydi (teg rejimi faqat sinov va eski bazalar uchun)


def schema() -> list[dict]:
    groups: dict[str, list] = {}
    for key, spec in SPEC.items():
        if key in HIDDEN:
            continue
        default, label, lo, hi, group = spec[:5]
        options = spec[5] if len(spec) > 5 else None
        kind = "choice" if options else "time" if isinstance(default, str) else "number"
        groups.setdefault(group, []).append({"key": key, "label": label, "default": default, "min": lo, "max": hi, "type": kind,
                                             "options": [{"value": v, "label": t} for v, t in options or []],
                                             "step": 0.1 if isinstance(default, float) else 1})
    return [{"group": g, "items": items} for g, items in groups.items()]
