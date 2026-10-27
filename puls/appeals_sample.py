"""Murojaatlar bo'limining namunasi: haqiqiy manba (yordam guruhi yoki chatbot) hali ulanmaganda ko'rsatiladi.

Bazaga hech narsa yozilmaydi: ma'lumot har kuni xotirada bir xil urug' (seed) bilan yasaladi va panelda "Namuna" deb
belgilanadi. Tizimlar, murojaat turlari, javoblar va sabablar Feruzbek maketidagi (26.10.2026) namunadan olingan.
"""
import random
from collections import defaultdict
from datetime import datetime, timedelta

FMT = "%Y-%m-%d %H:%M:%S"

CL = {
    "login": {"q": ["OneID orqali kira olmayapman, \"xatolik yuz berdi\" chiqyapti", "Parolni tiklash havolasi ishlamayapti",
                    "Kirgandan keyin darhol tizimdan chiqarib yuboryapti"],
              "a": {"good": "Sessiyangiz tozalandi, OneID integratsiyasidagi xato tuzatildi. Qayta kirib ko'ring.",
                    "tpl": "Iltimos, birozdan so'ng qayta urinib ko'ring.", "part": "Brauzer keshini tozalab, boshqa brauzerda urinib ko'ring."},
              "cause": "OneID integratsiyasida vaqti-vaqti bilan uzilish bo'lyapti. Javoblarda asosan \"keyinroq urinib ko'ring\" deyilmoqda, "
                       "asl texnik sabab tuzatilmagan, shuning uchun foydalanuvchilar qayta yozyapti.",
              "act": "OneID integratsiyasi xatolarini monitoringga qo'shish, backend jamoasiga bitta umumiy vazifa ochish va operatorlarga "
                     "aniq javob shablonini berish.", "line": [.15, .35, .2, .3], "h": 1},
    "payment": {"q": ["To'lov qildim, lekin ariza \"to'lanmagan\" deb turibdi", "Davlat boji ikki marta yechib olindi",
                      "Click orqali to'ladim, chek bor, tizimda ko'rinmayapti"],
                "a": {"good": "To'lov billing tizimi bilan qo'lda solishtirildi, arizangiz holati yangilandi.",
                      "tpl": "To'lov 24 soat ichida aks etadi, kuting.", "part": "Chek nusxasini yuboring, tekshirib chiqamiz."},
                "cause": "To'lov tizimi bilan sinxronlash kechikyapti, ayrim tranzaksiyalar umuman kelmayapti. Operatorlar \"24 soat kuting\" "
                         "deb javob beryapti, to'lov qo'lda tekshirilmaguncha muammo hal bo'lmayapti.",
                "act": "Billing bilan avtomatik solishtirishni har soatda ishga tushirish va kechikkan to'lovlar ro'yxatini operatorlarga ko'rsatish.",
                "line": [.1, .3, .45, .15], "h": 1.3},
    "status": {"q": ["Arizam 5 kundan beri \"ko'rib chiqilmoqda\" holatida", "Qachon tayyor bo'ladi? Muddat o'tib ketdi",
                     "Ariza rad etildi, sababi yozilmagan"],
               "a": {"good": "Arizangiz mas'ul xodimga qayta yo'naltirildi, 2 ish kunida natija bo'ladi. Rad etish sababi: hujjat nusxasi o'qilmaydi.",
                     "tpl": "Arizangiz ko'rib chiqilmoqda, kuting.", "part": "Ariza raqamini yuboring, tekshiramiz."},
               "cause": "Arizalar ko'rib chiqish bosqichida uzoq turib qolyapti va foydalanuvchiga aniq holat aytilmayapti. \"Ko'rib chiqilmoqda\" "
                        "degan javob qayta-qayta savol berishga sabab bo'lyapti.",
               "act": "Ariza bosqichi va qolgan muddatni foydalanuvchiga avtomatik ko'rsatish, muddati o'tgan arizalar uchun mas'ul xodimga "
                      "ogohlantirish yuborish.", "line": [.35, .4, .2, .05], "h": 1.5},
    "docs": {"q": ["PDF yuklanmayapti, \"fayl formati noto'g'ri\" chiqyapti", "5 MB dan katta fayl qabul qilinmayapti",
                   "Skaner qilingan hujjat yuklangandan keyin bo'sh ko'rinyapti"],
             "a": {"good": "Fayl hajmi chegarasi 20 MB ga oshirildi, qayta yuklab ko'ring.", "tpl": "Fayl talablarga mosligini tekshiring.",
                   "part": "Faylni kichraytirib, JPG formatda yuklang."},
             "cause": "Fayl hajmi va format cheklovlari foydalanuvchiga oldindan ko'rsatilmayapti, xato matni tushunarsiz.",
             "act": "Yuklash oynasida talablarni ko'rsatish, xato matnini aniq qilish va hajm chegarasini qayta ko'rib chiqish.",
             "line": [.3, .35, .15, .2], "h": .9},
    "sms": {"q": ["Tasdiqlash SMS kodi kelmayapti", "Kod keldi, lekin \"muddati o'tgan\" deyapti", "Boshqa raqamga SMS ketyapti"],
            "a": {"good": "SMS provayderidagi navbat tozalandi, kod qayta yuborildi.", "tpl": "Biroz kutib, kodni qayta so'rang.",
                  "part": "Telefon raqamingiz to'g'ri kiritilganini tekshiring."},
            "cause": "SMS provayderida yuklama oshganda kodlar kechikib keladi va amal qilish muddati tugab qoladi.",
            "act": "Kod amal qilish muddatini uzaytirish, zaxira SMS provayderini ulash va yetkazib berish statistikasini kuzatish.",
            "line": [.3, .35, .1, .25], "h": .7},
    "data": {"q": ["FISh noto'g'ri ko'rsatilgan", "PINFL bo'yicha boshqa odamning ma'lumoti chiqyapti", "Tug'ilgan sana xato yozilgan"],
             "a": {"good": "Ma'lumotlar davlat reestri bilan qayta sinxronlandi va tuzatildi.",
                   "tpl": "Ma'lumotlar reestrdan olinadi, biz o'zgartira olmaymiz.", "part": "Pasport nusxasini yuboring."},
             "cause": "Ma'lumotlar tashqi reestrdan olinadi, reestr bilan sinxronlash qo'lda va kechikib bajarilyapti. Foydalanuvchiga qayerga "
                      "murojaat qilishi aniq aytilmayapti.",
             "act": "Reestr bilan sinxronlashni avtomatlashtirish va ma'lumotni tuzatish so'rovi uchun alohida forma qilish.",
             "line": [.05, .3, .5, .15], "h": 1.6},
    "slow": {"q": ["Sayt ochilmayapti, 502 xatolik", "Sahifa juda sekin yuklanyapti", "Ariza yuborish tugmasi bosilganda osilib qolyapti"],
             "a": {"good": "Serverdagi yuklama muammosi bartaraf etildi, tizim normal ishlayapti.", "tpl": "Texnik ishlar olib borilmoqda.",
                   "part": "Internet aloqangizni tekshiring."},
             "cause": "Ish kunining eng band soatlarida server yuklamani ko'tara olmayapti, foydalanuvchilar bu haqida oldindan ogohlantirilmayapti.",
             "act": "Yuklama monitoringi va avtomatik masshtablashni sozlash, texnik ishlar haqida oldindan e'lon qilish.",
             "line": [.1, .3, .15, .45], "h": 1.2},
    "howto": {"q": ["Arizani qanday topshirsam bo'ladi?", "Qaysi hujjatlar kerak?", "Yuridik shaxs nomidan qanday kiriladi?"],
              "a": {"good": "Bosqichma-bosqich yo'riqnoma va video havolasi yuborildi.", "tpl": "Saytdagi yo'riqnomani o'qing.",
                    "part": "Operator bilan bog'laning."},
              "cause": "Tizimda tushunarli yo'riqnoma yo'q yoki uni topish qiyin. Bir xil savollarga har safar qo'lda javob berilyapti.",
              "act": "Ko'p so'raladigan savollar bo'limi va qisqa video yo'riqnomalar tayyorlash, ularni chatbotning avtomatik javoblariga qo'shish.",
              "line": [.6, .35, .05, 0], "h": .5},
    "cert": {"q": ["Guvohnoma tayyor, lekin yuklab olinmayapti", "QR kod tekshirilganda \"hujjat topilmadi\" chiqyapti",
                   "Elektron hujjatda imzo ko'rinmayapti"],
             "a": {"good": "Hujjat qayta generatsiya qilindi, endi yuklab olish mumkin.", "tpl": "Keyinroq urinib ko'ring.",
                   "part": "Boshqa brauzerda ochib ko'ring."},
             "cause": "Hujjat generatsiyasi xizmati ba'zan bo'sh fayl yaratyapti, QR tekshiruv bazasi kechikib yangilanyapti.",
             "act": "Hujjat yaratilgandan keyin avtomatik tekshiruv qo'shish va xato bo'lsa qayta yaratish.",
             "line": [.1, .3, .2, .4], "h": 1.3},
    "mobile": {"q": ["Ilova ochilishi bilan yopilib qolyapti", "Android 14 da ilova ishlamayapti", "Yangilanishdan keyin kirish tugmasi yo'qoldi"],
               "a": {"good": "Xato tuzatilgan versiya chiqarildi, ilovani yangilang.", "tpl": "Ilovani o'chirib, qayta o'rnating.",
                     "part": "Telefon modeli va Android versiyasini yuboring."},
               "cause": "So'nggi versiyada ayrim qurilmalarda ishdan chiqish xatosi bor. Javoblarda \"qayta o'rnating\" deyilmoqda, lekin bu "
                        "yordam bermayapti.",
               "act": "Ishdan chiqish hisobotlarini yig'ish (masalan, Crashlytics), tuzatilgan versiyani tezkor chiqarish va foydalanuvchilarga "
                      "xabar berish.", "line": [.05, .3, .15, .5], "h": 1.1},
}
# [tizim, hajm og'irligi, turlar og'irligi, sekinlik]
PROJ = [
    ("Yagona platforma", 9, {"login": 5, "status": 2, "docs": 1.5, "slow": 2, "howto": 1}, 1.2),
    ("Zags", 7, {"status": 4, "cert": 3, "data": 2, "payment": 1, "slow": 1}, 1.8),
    ("Adliya mobile", 6, {"mobile": 5, "sms": 3, "login": 2, "howto": 1}, 1),
    ("Notarius, Taqiq", 4.5, {"payment": 4, "status": 2, "docs": 1.5, "howto": 1}, 1.1),
    ("Shajara", 3.5, {"data": 4, "howto": 2, "status": 1.5, "cert": 1}, 1.3),
    ("LicenseGov", 3, {"docs": 4, "status": 2, "payment": 1.5, "howto": 1}, .9),
    ("Apostil", 2.5, {"howto": 3, "status": 3, "payment": 1}, 1.5),
    ("Birdarcha", 2, {"howto": 2, "login": 1.5, "status": 1.5}, .8),
    ("ReestrGov", 1.6, {"data": 2, "docs": 1.5, "status": 1}, 1),
    ("Advokatura", 1.2, {"howto": 1.5, "docs": 1, "login": 1}, .8),
    ("Intelektual mulk", 1.1, {"payment": 1.5, "status": 1.5, "docs": 1}, 1),
    ("Mahalla Adliya", 1, {"howto": 2, "login": 1}, 1.4),
    ("E-saqlov", .6, {"docs": 1, "howto": 1}, 1),
]
REP = {"Yagona platforma": {"login": .45, "slow": .3}, "Zags": {"status": .4, "cert": .35}, "Adliya mobile": {"mobile": .42, "sms": .3},
       "Notarius, Taqiq": {"payment": .38}, "Shajara": {"data": .38}, "Apostil": {"status": .3}}
TG = {"Yagona platforma": "Yagona platforma | Yordam", "Zags": "FHDY bo'limlari chati", "Adliya mobile": "Adliya mobile foydalanuvchilari",
      "Notarius, Taqiq": "Notariuslar guruhi", "Shajara": "FHDY bo'limlari chati", "LicenseGov": "Litsenziya olish guruhi",
      "Apostil": "Apostil masalalari"}
BOTS = ["@AdliyaHelpBot", "my.gov.uz chatbot"]
NAMES = ["Dilshod", "Malika", "Sardor", "Nodira", "Jasur", "Gulnora", "Bekzod", "Madina", "Otabek", "Shahnoza", "Rustam", "Zarina",
         "Aziz", "Feruza", "Javlon", "Kamola", "Sherzod", "Dildora", "Akmal", "Laylo"]
OPS = {1: ["Operator Nilufar", "Operator Bahrom"], 2: ["Mutaxassis Ulug'bek", "Mutaxassis Saida"], 3: ["Dasturchi Elyor", "Dasturchi Timur"]}
HOURS = [.12, 3, 18, 60]
RESOLVE = [.93, .94, .86, .72]
DAYS = 180

_cache: dict = {"key": None, "rows": [], "by_id": {}, "end": datetime.now()}


def _trend(nm: str, d: int) -> float:
    if nm == "Yagona platforma":
        return 1 + (30 - d) / 30 * .7 if d < 30 else 1
    if nm == "Zags":
        return 1.9 if 10 <= d < 20 else 1
    if nm == "Adliya mobile":
        return 1.6 if d < 14 else 1
    if nm == "LicenseGov":
        return .75 if d < 30 else 1
    return 1


def _build(end: datetime) -> list[dict]:
    R = random.Random(20261025)
    now = end
    out: list[dict] = []
    pools: dict = defaultdict(list)
    uid = 1001

    def pois(lam: float) -> int:
        if lam > 30:
            return max(0, round(lam + lam ** .5 * (R.random() + R.random() + R.random() - 1.5) * 2))
        L, k, p = 2.718281828 ** -lam, 0, 1.0
        while True:
            k += 1
            p *= R.random()
            if p <= L:
                return k - 1

    def wpick(obj: dict) -> str:
        s = sum(obj.values())
        r = R.random() * s
        for k, w in obj.items():
            r -= w
            if r <= 0:
                return k
        return next(iter(obj))

    def ipick(arr: list) -> int:
        s = sum(arr)
        r = R.random() * s
        for i, w in enumerate(arr):
            r -= w
            if r <= 0:
                return i
        return len(arr) - 1

    for d in range(DAYS - 1, -1, -1):
        day = (now - timedelta(days=d)).replace(hour=0, minute=0, second=0)
        wf = .45 if day.weekday() >= 5 else 1
        for pid, (nm, w, cw, slow) in enumerate(PROJ, 1):
            n = pois(w * 1.6 * wf * _trend(nm, d))
            for _ in range(n):
                cl = wpick(cw)
                t = day + timedelta(hours=8 + int(R.random() * 12), minutes=int(R.random() * 60))
                if t > now:
                    t = now - timedelta(minutes=int(R.random() * 180))
                bot = R.random() < .55
                src = (BOTS[0] if R.random() < .7 else BOTS[1]) if bot else TG.get(nm, "Adliya yordam guruhi")
                key = (pid, cl)
                pool = pools[key]
                rp = REP.get(nm, {}).get(cl, .07)
                recent = [x for x in pool if x["last"] >= t - timedelta(days=21)]
                if recent and R.random() < rp:
                    u = recent[int(R.random() * len(recent))]
                    user = u["id"]
                    u["last"] = t
                else:
                    user = uid
                    uid += 1
                    pool.append({"id": user, "last": t})
                    if len(pool) > 80:
                        pool.pop(0)
                lw = list(CL[cl]["line"])
                if not bot:
                    lw[0] = 0
                line = ipick(lw)
                hours = HOURS[line] * CL[cl]["h"] * slow * (.3 + R.random() * R.random() * 3.4)
                age = (now - t).total_seconds() / 3600
                resolved = hours < age and R.random() < RESOLVE[line]
                r = R.random()
                if not resolved:
                    q = "none" if r < .55 else "part"
                elif line == 0:
                    q = "good" if r < .5 else "tpl" if r < .82 else "part"
                elif line == 1:
                    q = "good" if r < .62 else "tpl" if r < .82 else "part"
                else:
                    q = "good" if r < .74 else "tpl" if r < .86 else "part"
                out.append({"id": -(len(out) + 1), "pid": -pid, "project": nm, "cl": cl, "t": t, "src": src, "bot": bot, "user": user,
                            "line": line, "hours": hours, "resolved": resolved, "q": q, "qi": int(R.random() * 3),
                            "rep": False, "chain": None})
    by = defaultdict(list)
    for a in out:
        by[(a["pid"], a["cl"], a["user"])].append(a)
    for ch in by.values():
        if len(ch) < 2:
            continue
        ch.sort(key=lambda a: a["t"])
        for i, a in enumerate(ch):
            a["chain"] = ch[0]["id"]
            a["rep"] = i > 0
            if i < len(ch) - 1 and R.random() < .72:
                a["q"] = "tpl" if R.random() < .6 else "part"
    return out


def _all(end: datetime) -> list[dict]:
    key = end.strftime("%Y-%m-%d %H")
    _cache["end"] = end
    if _cache["key"] != key:
        _cache["rows"] = _build(end)
        _cache["by_id"] = {a["id"]: a for a in _cache["rows"]}
        _cache["key"] = key
    return _cache["rows"]


def _row(a: dict) -> dict:
    created = a["t"].strftime(FMT)
    end = _cache["end"]
    # javob hali kelmagan bo'lishi kerak bo'lgan (hozirdan keyin tushadigan) murojaat — hali javobsiz
    answered = a["q"] != "none" and (a["resolved"] or a["t"] + timedelta(hours=a["hours"] * .4 + .05) <= end)
    res_at = (a["t"] + timedelta(hours=a["hours"])).strftime(FMT) if a["resolved"] else None
    first_at = (a["t"] + timedelta(hours=min(a["hours"], a["hours"] * .4 + .05))).strftime(FMT) if answered else None
    return {"id": a["id"], "source": "bot" if a["bot"] else "tg", "source_id": None, "chat_id": None, "project_id": a["pid"],
            "project": a["project"], "client_id": a["user"], "client": "Foydalanuvchi #%d" % a["user"], "username": None,
            "text": CL[a["cl"]]["q"][a["qi"]], "summary": CL[a["cl"]]["q"][a["qi"]], "type": a["cl"], "created_at": created,
            "first_answer_at": first_at, "first_grade": a["q"] if answered else None,
            "answered_by": OPS.get(a["line"], ["Chatbot"])[a["user"] % 2] if a["line"] else "Chatbot", "line": a["line"] if answered else None,
            "grade": a["q"] if answered else None, "status": "hal" if a["resolved"] else ("javob" if answered else "ochiq"),
            "resolved_at": res_at, "resolution": "javob" if a["resolved"] else None, "chain": a["chain"], "rep": 1 if a["rep"] else 0,
            "last_at": res_at or created, "ai": "ai", "chat": None if a["bot"] else a["src"], "bot": a["src"] if a["bot"] else None}


def rows(end: datetime, since: str, until: str) -> list[dict]:
    return [_row(a) for a in _all(end) if since < a["t"].strftime(FMT) <= until]


def insight(typ: str) -> dict | None:
    c = CL.get(typ)
    return {"cause": c["cause"], "act": c["act"], "at": None} if c else None


def detail(aid: int) -> dict | None:
    from . import appeals
    a = _cache["by_id"].get(aid)
    end = _cache["end"]
    if a is None:
        return None
    r = _row(a)
    c = CL[a["cl"]]
    events = [{"id": 1, "at": r["created_at"], "kind": "murojaat", "who": r["client"], "staff": 0, "line": None, "grade": None,
               "note": None, "text": r["text"], "link": None}]
    if r["grade"] and not (r["first_answer_at"] and r["first_answer_at"] > end.strftime(FMT)):
        events.append({"id": 2, "at": r["first_answer_at"], "kind": "javob", "who": r["answered_by"], "staff": 1, "line": r["line"],
                       "grade": r["grade"], "note": {"good": "Javob sababni ko'rsatgan va aniq yechim bergan.",
                                                     "part": "Yo'nalish berilgan, lekin muammo to'liq hal qilinmagan.",
                                                     "tpl": "Umumiy shablon javob, aniq yechim yo'q."}[r["grade"]],
                       "text": c["a"][r["grade"]], "link": None})
    chain = []
    if a["chain"]:
        chain = [{"id": x["id"], "created_at": x["t"].strftime(FMT), "summary": CL[x["cl"]]["q"][x["qi"]],
                  "status": "hal" if x["resolved"] else "ochiq", "grade": x["q"] if x["q"] != "none" else None, "first_grade": None}
                 for x in _cache["rows"] if x["chain"] == a["chain"]]
        chain.sort(key=lambda x: x["created_at"])
    return {"appeal": {**r, "type_name": appeals.TYPES[r["type"]], "status_name": appeals.STATUS[r["status"]],
                       "hours": a["hours"] if a["resolved"] else None,
                       "first_hours": appeals._hours(r["created_at"], r["first_answer_at"]),
                       "client_staff": 0, "client_appeals": None, "grade_note": events[-1]["note"] if r["grade"] else None},
            "events": events, "chain": chain, "client_appeals": len([x for x in _cache["rows"] if x["user"] == a["user"]]),
            "insight": insight(a["cl"]) if a["chain"] else None, "sample": True, "projects": [],
            "labels": {"types": appeals.TYPES, "lines": appeals.LINES, "grades": appeals.GRADES, "status": appeals.STATUS}}
