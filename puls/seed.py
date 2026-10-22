"""Namuna (demo) ma'lumot: 4 guruh, 14 loyiha, 50 xodim (7 bo'lim), ~6 hafta xabarlar.

Har bir xabar botdagi kabi aynan ingest() orqali o'tadi, ya'ni namuna tizimni ham sinaydi.
Sanalar bugungi kunga nisbatan yasaladi. Bugungi kunning hali vaqti kelmagan xabarlari navbatga
qo'yiladi va vaqti kelganda birma-bir tushadi (release): panel kun bo'yi jonli ko'rinadi, rahbarning
paneldagi qarorlari esa o'chib ketmaydi.

    python -m puls.seed          # tez: AI javoblari keshdan olinadi, keshda yo'g'i kalit so'zlar bilan
    python -m puls.seed --warm   # sekin: keshda yo'q matnlarni AI'ga yuborib keshni to'ldiradi
"""
import argparse
import json
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from . import ai, config, db
from .ingest import Incoming, ingest
from .parser import Item, Parsed, parse_format

CHATS = {
    "A": (-1009000000001, "Raqamli xizmatlar — kunlik hisobot (namuna)"),
    "B": (-1009000000002, "Ichki tizimlar — ish guruhi (namuna)"),
    "C": (-1009000000003, "AI markazi — ish guruhi (namuna)"),
    "D": (-1009000000004, "Infratuzilma va xavfsizlik (namuna)"),
}
# (ism, bo'lim). Birinchi 14 tasi avvalgi tartibda — havolalar va qarorlar buzilmasin
STAFF = [
    ("Aziz Karimov", "Fullstack"), ("Dilnoza Rahimova", "Frontend"), ("Sardor Tursunov", "Backend"), ("Madina Yusupova", "DevOps"),
    ("Bekzod Aliyev", "Backend"), ("Nodira Hasanova", "Frontend"), ("Jasur Nematov", "DevOps"), ("Shahzoda Ismoilova", "Fullstack"),
    ("Otabek Qodirov", "Backend"), ("Malika Abdullayeva", "Fullstack"), ("Rustam Ergashev", "Backend"), ("Zarina Sobirova", "Backend"),
    ("Laylo Karimova", "AI"), ("Timur Rasulov", "AI"),
    ("Akmal Xolmatov", "AI"), ("Nilufar Saidova", "AI"), ("Sherzod Usmonov", "AI"), ("Gulnora Hamidova", "AI"),
    ("Ulug'bek Nazarov", "AI"), ("Kamola Sharipova", "AI"),
    ("Farrux Mahmudov", "Backend"), ("Javlon Qosimov", "Backend"), ("Doniyor Raxmatov", "Backend"), ("Asilbek Jo'rayev", "Backend"),
    ("Behruz Yusupov", "Backend"),
    ("Sevara Mirzayeva", "Frontend"), ("Muxlisa Toshpo'latova", "Frontend"), ("Feruza Xolmatova", "Frontend"), ("Mohira Rasulova", "Frontend"),
    ("Dilshoda Ergasheva", "Frontend"),
    ("Sanjar Nematov", "Fullstack"), ("Islom Karimov", "Fullstack"), ("Nigora Aliyeva", "Fullstack"), ("Bobur Saidov", "Fullstack"),
    ("Elyor Hasanov", "DevOps"), ("Mirjalol Usmonov", "DevOps"), ("Oybek Sobirov", "DevOps"), ("Sarvar Hamidov", "DevOps"),
    ("Shoira Nazarova", "Dizayn"), ("Komila Sharipova", "Dizayn"), ("Barno Mahmudova", "Dizayn"), ("Yulduz Qosimova", "Dizayn"),
    ("Maftuna Raxmatova", "Dizayn"),
    ("Jahongir Jo'rayev", "Test (QA)"), ("Ozoda Yusupova", "Test (QA)"), ("Nodir Mirzayev", "Test (QA)"), ("Lola Toshpo'latova", "Test (QA)"),
    ("Abbos Ismoilov", "Test (QA)"), ("Charos Saidova", "Test (QA)"),
    ("Ilhom Qodirov", "Backend"),
]


def _username(i: int, name: str) -> str:
    base = "".join(ch for ch in name.split()[0].lower() if ch.isalpha())
    return "demo_%s%d" % (base, i) if i >= 14 else "demo_%s" % base


PEOPLE = [(900000001 + i, n, _username(i, n)) for i, (n, _) in enumerate(STAFF)]
# Xodim xarakteri: (bo'lim, ishonchlilik, sekinlik kunlari, yuklama og'irligi). Ko'rsatilmaganlar — me'yoriy.
_SPECIAL = {1: (1.1, -1, 1), 2: (0.95, 1, 2.4), 4: (1.06, -1, 1), 6: (0.9, 2, 2.0), 8: (0.45, 4, 1), 10: (0.9, 1, 1),
            12: (1.08, -1, 1), 13: (1.3, -1, 1), 26: (0.7, 2, 1), 45: (0.95, 2, 2.6), 47: (1.1, -1, 1)}
TRAITS = {i: (dept,) + _SPECIAL.get(i, (1.0, 0, 1)) for i, (_, dept) in enumerate(STAFF)}
IDLE = {13: 5, 33: 4}       # oxirgi N ish kunida yangi vazifa olmagan — "bo'sh"
SILENT = {18: 5}            # oxirgi N ish kunida hech narsa yozmagan — "jim"
LAGS = [0, 0, 1, 1, 2, 2, 2, 3, 4, 5]   # vazifa necha ish kunida bajariladi (xodimning sekinligi qo'shiladi)

PROJECTS = [
    dict(key="portal", tag="Portal", name="Yangi portal", aliases="portal", short="Portal", chat="A",
         lead=0, team=[1, 2, 3, 38, 43], start=38, rate=3.3, target=0.93, deadline=2, ramp=(9, 2.6),
         objects=["Login sahifasi", "Ro'yxatdan o'tish formasi", "OneID integratsiyasi", "SMS tasdiqlash", "Ariza formasi",
                  "To'lov moduli", "Shaxsiy kabinet", "Bildirishnomalar", "Qidiruv filtri", "Admin panel jadvali",
                  "PDF ko'chirma", "Mobil versiya", "Parolni tiklash", "Ariza holati sahifasi", "Foydalanuvchi profili",
                  "Audit jurnali", "API hujjatlari", "Bosh sahifa", "Fikr-mulohaza formasi", "Rollar va ruxsatlar"],
         aspects=["dizayn", "backend", "frontend", "testlar", "xatolarni tuzatish", "optimizatsiya", "kod sharhi"]),
    dict(key="arxiv", tag="Arxiv", name="Arxivni raqamlashtirish", aliases="arxiv", short="Arxiv", chat="A",
         lead=4, team=[5, 6, 40, 44], start=44, rate=3.2, target=0.985, deadline=19,
         objects=["Skaner moduli", "OCR tanib olish", "Metama'lumotlar formasi", "Qidiruv indeksi", "Fayl ombori",
                  "Hujjatlar katalogi", "Kirish huquqlari", "PDF/A eksport", "Import skripti", "Dublikatlarni aniqlash",
                  "Sifat nazorati", "Statistika hisoboti", "Zaxira nusxa", "Hujjat ko'rish oynasi", "Teglar tizimi",
                  "Muqova tasvirlari", "Saqlash muddatlari", "Ommaviy yuklash", "Sahifalarni tekislash", "Arxiv xaritasi"],
         aspects=["sozlash", "backend", "testlar", "optimizatsiya", "integratsiya", "xatolarni tuzatish", "kod sharhi"]),
    dict(key="litsenziya", tag="Litsenziya", name="Litsenziya moduli", aliases="litsenziya", short="Litsenziya", chat="A",
         lead=7, team=[8, 29, 41, 46], start=30, rate=2.4, target=0.93, deadline=-1,
         objects=["Ariza qabul qilish", "Hujjatlar ro'yxati", "To'lov tekshiruvi", "Litsenziya reyestri", "Muddat eslatmasi",
                  "QR kod tekshiruvi", "Arizani rad etish oqimi", "Imzo (ERI) ulash", "Hisobot shakli", "Inspektor kabineti",
                  "Ochiq API", "Arxivga o'tkazish", "Shikoyatlar oqimi"],
         aspects=["backend", "frontend", "testlar", "xatolarni tuzatish", "kod sharhi", "optimizatsiya"]),
    dict(key="mobil", tag="Mobil", name="Adliya mobil ilovasi", aliases="mobil ilova", short="Mobil ilova", chat="A",
         lead=30, team=[1, 22, 25, 39, 45], start=33, rate=3.5, target=0.92, deadline=9, ramp=(6, 1.4),
         objects=["Kirish ekrani", "Push bildirishnomalar", "Arizalar ro'yxati", "Hujjat skaneri", "To'lov oqimi",
                  "Profil sozlamalari", "Offline rejim", "Til almashtirish", "Biometrik kirish", "Xaritada xizmatlar",
                  "Yordam chati", "Ilova tezligi", "Ariza holati", "QR skaner", "Bosh ekran",
                  "Sozlamalar ekrani", "Xatolar hisoboti", "Yangilanish oqimi", "Onboarding ekranlari", "Qorong'i rejim",
                  "Hujjatlar hamyoni", "Fikr bildirish"],
         aspects=["dizayn", "iOS", "Android", "API", "testlar", "xatolarni tuzatish"]),
    dict(key="notarial", tag="Notarial", name="Notarial reyestr integratsiyasi", aliases="notarial reyestr", short="Notarial reyestr",
         chat="A", lead=20, team=[21, 24, 27, 41, 44], start=40, rate=3.0, target=0.985, deadline=24,
         objects=["Reyestr API", "Ma'lumot sinxronlash", "Notarius kabineti", "Hujjat tekshiruvi", "Arxiv eksporti",
                  "Xatolar jurnali", "Avtorizatsiya", "Hisobot shakllari", "Qidiruv indeksi", "Audit izi",
                  "Notarial harakatlar ro'yxati", "Vasiyatnomalar bo'limi", "Ishonchnomalar reyestri", "To'lovlar hisobi",
                  "Ma'lumot almashinuvi", "Notarius bildirishnomalari", "Navbatga yozilish", "Tariflar jadvali",
                  "Hujjat namunalari", "Statistik hisobot"],
         aspects=["backend", "integratsiya", "testlar", "dizayn", "yo'riqnoma", "optimizatsiya"]),
    dict(key="maslahatbot", tag="MaslahatBot", name="Maslahat boti", aliases="maslahat bot", short="Maslahat boti", chat="B",
         lead=9, team=[10], start=35, rate=2.7, target=0.95, deadline=26, silence=5,
         objects=["Savol-javob bazasi", "Menyu tugmalari", "Operatorga ulash", "Ko'p tillilik", "Murojaatlar tarixi",
                  "FAQ yangilash", "Statistika", "Navbat tizimi", "Baholash so'rovnomasi", "Ovozli xabar qabul qilish",
                  "Admin buyruqlari", "Xabarnoma yuborish", "Fayl qabul qilish", "Ish vaqti sozlamasi"],
         aspects=["sozlash", "backend", "testlar", "matnlar", "xatolarni tuzatish", "integratsiya"]),
    dict(key="hujjataylanishi", tag="HujjatAylanishi", name="Hujjat aylanishi", aliases="hujjat aylanishi",
         short="Hujjat aylanishi", chat="B", lead=11, team=[2, 33], start=40, rate=0.45, target=0.92, deadline=45, solo=0.85,
         objects=["Kiruvchi hujjatlar jurnali", "Rezolyutsiya oqimi", "Ijro nazorati", "Shablonlar", "Elektron imzo",
                  "Bo'limlar ro'yxati"],
         aspects=["tahlil", "backend", "testlar"]),
    dict(key="ichkiportal", tag="IchkiPortal", name="Ichki portal", aliases="ichki portal", short="Ichki portal", chat="B",
         lead=31, team=[21, 23, 26, 33, 40, 47], start=36, rate=2.7, target=0.97, deadline=30,
         objects=["Xodimlar katalogi", "Ta'til so'rovi", "Ichki yangiliklar", "Hujjat almashinuvi", "Bo'limlar tuzilmasi",
                  "Tabriklar sahifasi", "Ichki qidiruv", "Taklif va shikoyatlar", "Navbatchilik jadvali", "Ichki chat", "Ichki e'lonlar", "Xodim profili",
                  "Uchrashuv xonalari", "So'rovnomalar", "Bilimlar bazasi", "Mobil ko'rinish"],
         aspects=["dizayn", "backend", "frontend", "testlar", "xatolarni tuzatish", "kod sharhi"]),
    dict(key="monitoring", tag="Monitoring", name="Server monitoringi", aliases="monitoring", short="Monitoring", chat="B",
         lead=3, team=[6, 37], start=25, rate=2.0, target=0.97, deadline=None,
         objects=["CPU va xotira grafiklari", "Disk to'lishi ogohlantirishi", "Log yig'ish", "Uptime tekshiruvi",
                  "Telegram ogohlantirish", "Zaxira nusxa nazorati", "SSL muddati tekshiruvi", "Grafana panel",
                  "Prometheus eksporterlari", "Javob vaqti o'lchovi"],
         aspects=["sozlash", "testlar", "yo'riqnoma", "integratsiya", "xatolarni tuzatish"]),
    dict(key="aitasnif", tag="AITasnif", name="Murojaatlarni AI tasniflash", aliases="ai tasnif", short="AI tasniflash",
         chat="C", lead=12, team=[13, 15, 19, 48], start=28, rate=2.4, target=0.98, deadline=12,
         objects=["Dataset yig'ish", "Ma'lumotni tozalash", "Prompt sozlash", "Aniqlikni o'lchash", "Model API",
                  "Natijalar paneli", "Xato tahlili", "Kategoriyalar ro'yxati", "Embedding qidiruv", "Sinov to'plami", "Model versiyalari",
                  "Qayta o'qitish rejasi", "Sifat metrikalari"],
         aspects=["tayyorlash", "sinov", "integratsiya", "tahlil", "baholash"]),
    dict(key="sudqidiruv", tag="SudQidiruv", name="Sud qarorlari bo'yicha AI qidiruv", aliases="sud qidiruv", short="Sud qidiruvi",
         chat="C", lead=14, team=[15, 17, 18, 28, 42, 48], start=32, rate=3.0, target=0.96, deadline=16,
         objects=["Qarorlar korpusi", "Matnni bo'laklash", "Vektor indeks", "Qidiruv API", "Natija reytingi",
                  "Manba havolalari", "Baholash to'plami", "Qidiruv interfeysi", "Filtrlar", "Javob xulosasi", "Xavfsizlik filtri",
                  "Sinonimlar lug'ati", "Kesh qatlami", "Foydalanuvchi fikri", "Qonun moddalari bog'lanishi", "Javob tezligi"],
         aspects=["tayyorlash", "sinov", "integratsiya", "tahlil", "baholash", "optimizatsiya"]),
    dict(key="ovozliyordamchi", tag="OvozliYordamchi", name="Ovozli yordamchi", aliases="ovozli yordamchi", short="Ovozli yordamchi",
         chat="C", lead=16, team=[17, 32, 42], start=14, rate=1.9, target=0.95, deadline=40,
         objects=["Nutqni tanish", "Ovoz sintezi", "Dialog ssenariysi", "Shovqinni kamaytirish", "Telefon ulanishi",
                  "Lahjalar to'plami", "Javob shablonlari"],
         aspects=["tayyorlash", "sinov", "integratsiya", "tahlil"]),
    dict(key="kiber", tag="Kiber", name="Kiberxavfsizlik auditi", aliases="kiberxavfsizlik", short="Kiberxavfsizlik", chat="D",
         lead=34, team=[24, 36, 49], start=26, rate=2.2, target=0.95, deadline=14,
         objects=["Port skaneri", "Parol siyosati", "Zaiflik hisoboti", "Kirish jurnali", "Firewall qoidalari",
                  "Zaxira tekshiruvi", "Fishing sinovi", "SSL sertifikatlar", "Antivirus siyosati", "Xodimlar treningi",
                  "Hodisalarga javob rejasi"],
         aspects=["tahlil", "sozlash", "testlar", "yo'riqnoma", "hisobot"]),
    dict(key="bulut", tag="Bulut", name="Ma'lumotlar markazini bulutga ko'chirish", aliases="bulut", short="Bulut", chat="D",
         lead=35, team=[23, 36, 37, 47], start=40, rate=2.4, target=0.97, deadline=21,
         objects=["Virtual mashinalar", "Bazani ko'chirish", "Tarmoq sozlamalari", "Zaxira strategiyasi", "Monitoring agentlari",
                  "Kirish huquqlari", "Xarajat hisobi", "Ko'chirish rejasi", "Yuklama sinovi", "Konteynerlar", "DNS ko'chirish",
                  "Ma'lumot shifrlash", "Avtomatik masshtablash", "Tiklash sinovi", "Log markazi"],
         aspects=["sozlash", "testlar", "integratsiya", "yo'riqnoma", "optimizatsiya", "xavfsizlik tekshiruvi"]),
]
NOISE = ["Assalomu alaykum, bugun 15:00 da yig'ilish bo'ladi", "Rahmat!", "Kim bugun ofisda?", "Ok, tushunarli",
         "Ertaga 10:00 da demo bor", "Yaxshi, kelishdik", "Zoom havolasini tashlab yuboring", "Tushlikka chiqdik",
         "Hisobotni kim tashlaydi?", "Bugun tushlikdan keyin bayram tadbiri bor"]


@dataclass(eq=False)
class Msg:
    chat: str
    at: datetime
    who: int
    text: str
    reply_to: "Msg | None" = None
    expect: tuple = ("none", None)       # (kind, project key) — AI aniqligini o'lchash uchun
    msg_id: int = 0
    tasks: list = field(default_factory=list)


def workdays_back(today: date, n: int) -> date:
    d = today
    while n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def at(d: date, h: int, m: int) -> datetime:
    return datetime.combine(d, time(h, m))


def generate(now: datetime, rnd: random.Random) -> list[Msg]:
    today = now.date()
    msgs: list[Msg] = []
    for P in PROJECTS:
        names = [rnd.sample(P["aspects"], len(P["aspects"])) for _ in P["objects"]]
        pool = ["%s — %s" % (o, a) for o, asp in zip(P["objects"], names) for a in asp]
        rnd.shuffle(pool)
        start = today - timedelta(days=P["start"])
        quiet_from = workdays_back(today, P["silence"]) + timedelta(days=1) if P.get("silence") else None
        lead = P["lead"]
        tasks = []

        if P["deadline"] is not None:
            dl = today + timedelta(days=P["deadline"])
            first = start if start.weekday() < 5 else start + timedelta(days=7 - start.weekday())
            msgs.append(Msg(P["chat"], at(first, 9, 2), lead, "#deadline #%s %s" % (P["tag"], dl.strftime("%d.%m.%Y")),
                            expect=("deadline", P["key"])))

        d = start
        while d <= today:
            if d.weekday() >= 5 or (quiet_from and d >= quiet_from):
                d += timedelta(days=1)
                continue
            rate = P["rate"] + (P["ramp"][1] if P.get("ramp") and d > workdays_back(today, P["ramp"][0]) else 0)
            n = int(rate) + (1 if rnd.random() < rate - int(rate) else 0)
            n = max(0, n + rnd.choice([-1, 0, 0, 0, 1])) if P["rate"] >= 1 else n
            when = at(d, 9, 0) + timedelta(minutes=rnd.randint(5, 80))
            if n and pool and when <= now:
                items = []
                for _ in range(min(n, len(pool))):
                    crew = [p for p in P["team"] + [lead] if not (p in IDLE and d > workdays_back(today, IDLE[p]))]
                    if P.get("solo") and rnd.random() < P["solo"]:
                        who = lead
                    else:
                        who = rnd.choices(crew, weights=[TRAITS[p][3] for p in crew])[0]
                    items.append({"title": pool.pop(), "who": who, "created": when, "done": None})
                ment = lambda it: " @" + PEOPLE[it["who"]][2] if it["who"] != lead else ""
                style = rnd.random()
                if style < 0.7:
                    body = "\n".join("- %s%s" % (it["title"], ment(it)) for it in items) if len(items) > 1 \
                        else items[0]["title"] + ment(items[0])
                    text = "#task #%s\n%s" % (P["tag"], body) if len(items) > 1 else "#task #%s %s" % (P["tag"], body)
                elif len(items) > 1:
                    text = "%s bo'yicha bugungi vazifalar:\n%s" % (
                        P["short"], "\n".join("- %s%s" % (it["title"], ment(it)) for it in items))
                else:
                    it = items[0]
                    text = "%s: %s qilish kerak%s" % (P["short"], it["title"], (", @%s olsin" % PEOPLE[it["who"]][2]) if it["who"] != lead else "")
                m = Msg(P["chat"], when, lead, text, expect=("task", P["key"]), tasks=items)
                for it in items:
                    it["msg"] = m
                msgs.append(m)
                tasks.extend(items)
            d += timedelta(days=1)

        # Har vazifa target ehtimol bilan bir necha ish kunida bajariladi: ish har kuni oqadi,
        # orqada qolgan loyihada esa ochiq vazifalar to'planib boradi
        for t in tasks:
            _, reliability, slowness, _ = TRAITS[t["who"]]
            if rnd.random() < min(1.0, P["target"] * reliability):
                lag = max(0, rnd.choice(LAGS) + slowness)
            elif rnd.random() < 0.95 * min(1.0, reliability):
                lag = rnd.randint(4, 8) + slowness  # kechikib bo'lsa ham oxiri yopiladi
            else:
                continue
            dd = t["created"].date()
            while lag:
                dd += timedelta(days=1)
                if dd.weekday() < 5:
                    lag -= 1
            done = at(dd, rnd.randint(11, 18), rnd.randint(0, 59))
            if done <= t["created"]:
                done = t["created"] + timedelta(hours=2)
            if done > now or (quiet_from and done.date() >= quiet_from):
                continue
            if t["who"] in SILENT and done.date() > workdays_back(today, SILENT[t["who"]]):
                continue
            t["done"] = done

        groups: dict = {}
        for t in tasks:
            if t["done"]:
                groups.setdefault((t["who"], t["done"].date()), []).append(t)
        for (who, _), ts in groups.items():
            when = max(t["done"] for t in ts)
            parent = ts[0]["msg"]
            same_parent = len(ts) == 1 and sum(1 for x in parent.tasks if x["who"] == who) == 1
            style = rnd.random()
            if same_parent and style < 0.25:
                text = rnd.choice(["#done", "Tayyor ✅", "Bajarildi"])
                msgs.append(Msg(P["chat"], when, who, text, reply_to=parent, expect=("done", P["key"])))
            elif len(ts) > 1 or style < 0.6:
                body = "\n".join("- " + t["title"] for t in ts) if len(ts) > 1 else ts[0]["title"]
                text = "#done #%s%s%s" % (P["tag"], "\n" if len(ts) > 1 else " ", body)
                msgs.append(Msg(P["chat"], when, who, text, expect=("done", P["key"])))
            else:
                title = ts[0]["title"]
                low = title[0].lower() + title[1:]
                text = rnd.choice([
                    "%s: %s tayyor bo'ldi" % (P["short"], title),
                    "%s bo'yicha %s tugatdim" % (P["short"], low),
                    "%s: %s bajarildi, testga berdim" % (P["short"], title),
                    "%sda %s yakunlandi" % (P["short"], low),
                ])
                msgs.append(Msg(P["chat"], when, who, text, expect=("done", P["key"])))

    # Muammolar: ikkitasi hal bo'lgan, ikkitasi hali ochiq
    def blocker(chat, d, who, text, key, fix_after=None, fix_who=None, fix_text="Hal bo'ldi, endi ishlayapti"):
        b = Msg(chat, at(d, 10, 40), who, text, expect=("blocker", key))
        msgs.append(b)
        if fix_after is not None:
            msgs.append(Msg(chat, at(d + timedelta(days=fix_after), 16, 5), fix_who, fix_text, reply_to=b, expect=("done", key)))

    blocker("A", workdays_back(today, 12), 2, "#muammo #Portal OneID test muhiti ishlamayapti", "portal", 1, 0)
    blocker("A", workdays_back(today, 20), 6, "Arxiv: skaner drayveri Windows 11 da ishlamayapti", "arxiv", 2, 4, "#done")
    blocker("A", workdays_back(today, 5), 8, "Litsenziya: ERI kalitlari hali berilmagan, imzo ulashni kutib turibmiz", "litsenziya")
    blocker("B", workdays_back(today, 1), 6, "Monitoring: test serverga SSH ruxsat yo'q, ishlay olmayapmiz", "monitoring")
    blocker("A", workdays_back(today, 16), 25, "#muammo #Mobil App Store hisobi vaqtincha bloklandi", "mobil", 2, 30)
    blocker("D", workdays_back(today, 4), 36, "Kiberxavfsizlik: tashqi auditor ruxsatnomasi hali yo'q, ishni boshlay olmayapmiz", "kiber")
    blocker("C", workdays_back(today, 9), 17, "#muammo #SudQidiruv GPU server band, indeks qurilmayapti", "sudqidiruv", 1, 14, "#done")

    members = {c: sorted({P["lead"] for P in PROJECTS if P["chat"] == c} | {x for P in PROJECTS if P["chat"] == c for x in P["team"]})
               for c in CHATS}
    d = today - timedelta(days=44)
    while d <= today:
        if d.weekday() < 5:
            for chat in CHATS:
                if rnd.random() < 0.6:
                    when = at(d, rnd.randint(9, 17), rnd.randint(0, 59))
                    who = rnd.choice(members[chat])
                    if when <= now and not (who in SILENT and d > workdays_back(today, SILENT[who])):
                        msgs.append(Msg(chat, when, who, rnd.choice(NOISE)))
        d += timedelta(days=1)

    msgs.sort(key=lambda m: m.at)
    counters = {c: 1000 for c in CHATS}
    for m in msgs:
        counters[m.chat] += 1
        m.msg_id = counters[m.chat]
    return msgs


def reset(conn) -> None:
    ids = [c[0] for c in CHATS.values()]
    marks = ",".join("?" * len(ids))
    pids = [r[0] for r in conn.execute(f"SELECT id FROM projects WHERE chat_id IN ({marks})", ids)]
    pm = ",".join("?" * len(pids)) or "NULL"
    conn.execute(f"DELETE FROM tasks WHERE project_id IN ({pm})", pids)
    conn.execute(f"DELETE FROM blockers WHERE project_id IN ({pm})", pids)
    conn.execute(f"DELETE FROM projects WHERE id IN ({pm})", pids)
    conn.execute(f"DELETE FROM messages WHERE chat_id IN ({marks})", ids)
    conn.execute(f"DELETE FROM chats WHERE id IN ({marks})", ids)
    conn.execute("DELETE FROM people WHERE id BETWEEN 900000000 AND 900999999")
    conn.execute("DELETE FROM demo_queue")


def _cache() -> dict:
    path = config.DB_PATH.parent / "ai_cache.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _pre(c: dict | None) -> Parsed | None:
    return Parsed(c["kind"], c["project"], [Item(t, a) for t, a in c["items"]], None, "ai") if c else None


def release(now: datetime | None = None) -> int:
    """Navbatdagi namuna xabarlardan vaqti kelganlarini qabul qiladi."""
    now = now or config.now()
    with db.session() as conn:
        rows = conn.execute("SELECT * FROM demo_queue WHERE at <= ? ORDER BY at, id", (now.strftime("%Y-%m-%d %H:%M:%S"),)).fetchall()
        if not rows:
            return 0
        cache = _cache()
        for r in rows:
            at = datetime.strptime(r["at"], "%Y-%m-%d %H:%M:%S")
            pre = None if r["reply_to"] or parse_format(r["text"], at.date()) else _pre(cache.get(r["text"]))
            ingest(conn, Incoming(r["chat_id"], r["title"], r["msg_id"], r["user_id"], r["user_name"], r["username"], at, r["text"],
                                  reply_to=r["reply_to"], demo=True), use_ai=False, pre=pre)
            conn.execute("DELETE FROM demo_queue WHERE id = ?", (r["id"],))
    return len(rows)


def seeded_day() -> str | None:
    with db.session() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = 'demo_day'").fetchone()
    return row["value"] if row else None


def run(warm: bool = False, now: datetime | None = None, quiet: bool = False) -> dict:
    now = now or config.now()
    rnd = random.Random(20261022)
    db.init()
    # Butun bugungi kun yasaladi: hali vaqti kelmagan xabarlar navbatga tushadi
    msgs = generate(max(now, datetime.combine(now.date(), time(20, 0))), rnd)
    cache_path = config.DB_PATH.parent / "ai_cache.json"
    cache = _cache()
    with db.session() as conn:
        reset(conn)
        for cid, title in CHATS.values():
            conn.execute("INSERT INTO chats(id, title, demo, added_at) VALUES(?, ?, 1, ?)", (cid, title, now.isoformat(" ")))
        leads = {P["lead"] for P in PROJECTS}  # loyiha rahbarlari vazifa beradi va botning savollarini hal qiladi
        for i, (pid, name, username) in enumerate(PEOPLE):
            conn.execute("INSERT OR REPLACE INTO people(id, name, username, department, role) VALUES(?, ?, ?, ?, ?)",
                         (pid, name, username, TRAITS[i][0], "rahbar" if i in leads else None))
        start = (now - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S")
        for P in PROJECTS:
            conn.execute("INSERT INTO projects(key, name, aliases, chat_id, created_at) VALUES(?, ?, ?, ?, ?)",
                         (P["key"], P["name"], P["aliases"], CHATS[P["chat"]][0], start))
        projects = [dict(r) for r in conn.execute("SELECT key, name, aliases FROM projects")]

    free = [m for m in msgs if parse_format(m.text, m.at.date()) is None]
    if warm and config.ai_enabled():
        # AI'ga faqat keshda yo'q matnlar yuboriladi; har javob darhol faylga yoziladi (uzilsa ham yo'qolmaydi)
        todo = list({m.text: m for m in free if m.text not in cache}.values())
        lock = threading.Lock()

        def ask(m: Msg) -> None:
            p = ai.extract(m.text, PEOPLE[m.who][1], projects, m.at.date(), retries=5)
            if p is None:
                return
            with lock:
                cache[m.text] = {"kind": p.kind, "project": p.project, "items": [[i.title, i.assignee] for i in p.items]}
                cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

        with ThreadPoolExecutor(2) as ex:
            list(ex.map(ask, todo))
    pre: dict[str, Parsed] = {m.text: _pre(cache[m.text]) for m in free if m.text in cache}

    ok = total = queued = 0
    wrong = []
    free_ids = {id(m) for m in free}
    with db.session() as conn:
        for m in msgs:
            cid, title = CHATS[m.chat]
            pid, name, username = PEOPLE[m.who]
            if m.at > now:
                conn.execute("INSERT INTO demo_queue(at, chat_id, title, msg_id, user_id, user_name, username, text, reply_to) "
                             "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)", (m.at.strftime("%Y-%m-%d %H:%M:%S"), cid, title, m.msg_id, pid, name,
                                                                username, m.text, m.reply_to.msg_id if m.reply_to else None))
                queued += 1
                continue
            inc = Incoming(cid, title, m.msg_id, pid, name, username, m.at, m.text,
                           reply_to=m.reply_to.msg_id if m.reply_to else None, demo=True)
            res = ingest(conn, inc, use_ai=False, pre=None if m.reply_to else pre.get(m.text))
            if id(m) in free_ids:
                total += 1
                got = conn.execute("SELECT kind, project_id FROM messages WHERE chat_id = ? AND msg_id = ?", (cid, m.msg_id)).fetchone()
                key = conn.execute("SELECT key FROM projects WHERE id = ?", (got["project_id"],)).fetchone() if got["project_id"] else None
                got_t = (got["kind"], key["key"] if key else None)
                exp = m.expect if m.expect[0] != "none" else ("none", None)
                if got_t[0] == exp[0] and (exp[0] == "none" or got_t[1] == exp[1]):
                    ok += 1
                else:
                    wrong.append((m.text[:70], exp, got_t))
        conn.execute("INSERT INTO meta(key, value) VALUES('demo_day', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (now.date().isoformat(),))
        ids = [c[0] for c in CHATS.values()]
        stats = {
            "messages": len(msgs) - queued, "queued": queued, "free_text": total, "understood": ok,
            "tasks": conn.execute("SELECT count(*) FROM tasks t JOIN projects p ON p.id = t.project_id WHERE p.chat_id IN (%s)"
                                  % ",".join("?" * len(ids)), ids).fetchone()[0],
            "ai": bool(pre),
        }
    if not quiet:
        print("Xabarlar: %(messages)d (bugun yana %(queued)d tasi vaqti kelganda tushadi), erkin matn: %(free_text)d, "
              "to'g'ri tushunildi: %(understood)d, vazifalar: %(tasks)d, AI: %(ai)s" % stats)
        for w in wrong[:15]:
            print("  XATO:", w)
    stats["wrong"] = wrong
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--warm", action="store_true", help="keshda yo'q erkin matnlarni AI'ga yuborib keshni to'ldirish (sekin)")
    args = ap.parse_args()
    run(warm=args.warm)
