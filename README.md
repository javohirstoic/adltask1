# Puls

Telegram ish guruhlaridagi xabarlardan rahbar uchun loyihalar va jamoa nazorati.
Xodimlar guruhda odatdagidek yozadi; bot har xabarni o'qiydi, panel esa holatni, xavflarni va tayyor qarorlarni ko'rsatadi.

To'liq texnik topshiriq: [docs/Puls_TZ_v1.pdf](docs/Puls_TZ_v1.pdf).

## Tuzilma (Django)

```
config/        loyiha sozlamalari (settings.py, urls.py)
core/          Setting, DataVersion · kirish/login, sahifalar, /api/meta, /api/settings · namuna ma'lumot (demo.py)
people/        Department, Person · xodim API: bo'lim, rol, ism, shaxsiy havola
projects/      Chat, Project, Message, Task, Blocker
ingest/        parser.py, ai.py (Gemini), memory.py (embedding) · ingest servisi · Telegram tarixini import
analytics/     xavf qoidalari, Puls indeksi, qarorlar · /api/summary, /api/project, /api/person
actions/       Decision, Alert · qaror markazi, vazifa berishdagi nazorat · /api/actions/*
reports/       Excel (guruh kun yakuni, panel eksporti) · /api/export.xlsx
telegram/      aiogram bot · `manage.py run_bot`
web/           panel (freymvorksiz JS: puls.js, data.js, office.js, puls.css) — /static/ orqali beriladi
tests/         pytest-django (92 ta test)
```

Hamma API — DRF class view'lar (`APIView`), har app o'z `views.py` va `urls.py` ida. Kirish Django sessiyasi bilan,
yozuvchi so'rovlar CSRF tokenini talab qiladi (panel uni o'zi yuboradi).

## Rollar

`Person.role` + panel akkaunti (`Person.user`). `is_superuser` har doim **admin**. Roli yo'q foydalanuvchi panelga kira olmaydi.
Telegramda uchala rol ham boshqalarga vazifa bera oladi va botning savollarini hal qiladi.

| | Admin | Rahbar | Loyiha menejeri |
|---|---|---|---|
| Dashboard (brifing, ofis, xodim, loyiha, bo'lim) | hammasi | **to'liq** | faqat o'z loyihalari |
| Qarorlar (muddat surish, vazifa o'tkazish, eslatma), AI tuzatish | ha | ha | yo'q |
| Vazifa, muammo CRUD | hammasi | hammasi | faqat o'z loyihalarida |
| Loyiha CRUD, menejer biriktirish | ha | ha | faqat ko'rish (o'zinikini) |
| Xodim, bo'lim, guruh CRUD, rol va panel akkaunti berish | ha | faqat ko'rish | yo'q |
| Xabar, tuzatish o'chirish; Sozlamalar; Telegram tarixini yuklash | ha | yo'q | yo'q |
| Qarorlar jurnali, bot savollari | ko'rish | ko'rish | yo'q |

Menejer: `Project.manager` orqali biriktirilgan loyihalar. Dashboard, eksport, xabarlar lentasi va hamma API faqat shular bilan cheklanadi;
loyiha oynasida **«Kim qancha qildi»** — har xodimning vazifalari, bajarilgan ulushi, muddati o'tganlari, o'rtacha muddati va o'z vaqtida bajarilgani.
Ruxsatlar jadvali bitta joyda: `core/permissions.py` (`ACCESS`); panel ham undan foydalanadi (`/api/meta` → `me.access`).

Akkaunt berish: **Ma'lumotlar → Xodimlar → Qo'shish/Tahrirlash** (rol, login, parol). Parol Django qoidalari bo'yicha tekshiriladi.

## Ma'lumotlarni boshqarish (CRUD)

Panelda **Ma'lumotlar** tabi (`web/data.js`): har modelni ko'rish, qidirish, filtrlash, tartiblash, qo'shish, tahrirlash va o'chirish.
API — `/api/data/<resurs>` (DRF `ModelViewSet`, sahifalash `?page=`, `?page_size=`, `?search=`, `?ordering=`, resursga xos filtrlar):

| Resurs | Imkoniyat |
|---|---|
| `projects`, `tasks`, `blockers`, `people`, `departments`, `chats` | CRUD (rolga qarab, yuqoridagi jadval) |
| `messages`, `corrections` | ko'rish va o'chirish (tahrir tarixni buzadi; AI tuzatishi uchun `/api/messages/<id>/correct`) |
| `decisions`, `alerts` | faqat ko'rish (tizim jurnali) |

Har o'zgarish panel versiyasini oshiradi, shuning uchun asosiy ekranlar o'zi yangilanadi. `Setting` — panelning «Sozlamalar» oynasi,
`DataVersion`, `Embedding`, `DemoQueueItem` ichki jadvallar bo'lgani uchun API'da yo'q.

## Qanday ishlaydi

1. **Bot** guruhdagi xabarni oladi va reaksiya bilan tasdiqlaydi: ✍ vazifa, 👍 bajarildi, 👀 muammo, 🫡 muddat, 🤔 loyiha aniqlanmadi.
2. **Tushunish** (`ingest/parser.py`, `ingest/ai.py`): `#task #done #muammo #deadline` teglari bo'lsa qoida bilan; teg bo'lmasa Gemini (faqat JSON, loyihani faqat ro'yxatdan tanlaydi); AI ishlamasa kalit so'zlar.
3. **Baza** — Django ORM (standart SQLite `data/db.sqlite3`, WAL rejimida; istasangiz `DATABASES` ni PostgreSQL'ga o'zgartiring).
4. **Hisob-kitob** (`analytics/services.py`): loyiha va xodim holatlari, prognoz, qarorlar. Chegaralar `core/appsettings.py` da va paneldan o'zgartiriladi.
5. **Qaror markazi** (`actions/services.py`): vazifa o'tkazish, muddat surish, holat so'rash, shaxsiy eslatma. Har harakat jurnalga yoziladi.
6. **Vazifa berishdagi nazorat** (`actions/load.py`): ishi ko'p xodimga vazifa yozilsa, bot bo'shroq hamkasbni tavsiya qiladi; "Faqat rahbarlar" sozlamasida boshqaga yozilgan vazifa u qabul qilgandan keyin hisobga kiradi.
7. **Panel** (`web/`): freymvorksiz JavaScript.

## Ishga tushirish (kompyuterda)

```
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env                 # qiymatlarni to'ldiring
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser     # panelga kirish uchun login/parol
.venv/bin/python manage.py runserver           # panel: http://127.0.0.1:8000/
.venv/bin/python manage.py run_bot             # alohida terminalda: Telegram bot (BOT_TOKEN kerak)
```

`.env` (namuna `.env.example` da): `SECRET_KEY`, `BOT_TOKEN`, `BOT_USERNAME`, `OWNER_ID`, `PANEL_URL`, `GEMINI_SA`, `DEMO_DATA`.
Bot faqat BITTA joyda ishlashi kerak (`BOT_ENABLED`). Rahbarlar va qo'shimcha foydalanuvchilar `/admin/` orqali qo'shiladi.

Namuna ma'lumot (50 xodim, 7 bo'lim, 14 loyiha, 4 guruh): `python manage.py seed_demo`.
`DEMO_DATA=1` bo'lsa `run_bot` namunani har kuni yangilaydi va bugungi xabarlarni vaqti kelganda birma-bir tushiradi.

Sinovlar: `.venv/bin/python -m pytest`.

## Serverda

`docker compose up -d --build` — ikki konteyner: `web` (gunicorn, faqat `127.0.0.1:8121`, tashqariga nginx orqali) va `bot`.
Ikkalasi `./data` ni ulashadi. Birinchi marta: `docker compose exec web python manage.py createsuperuser`.

## Guruhda yozish

```
#task #Portal Login sahifasi @ali
#done #Portal Login sahifasi
#muammo #Portal Serverga ruxsat yo'q
#deadline #Portal 15.11.2026
```

Vazifa xabariga javob (reply) qilib `#done` yozilsa — o'sha vazifa yopiladi. Teg bo'lmasa ham AI tushunadi.

Xodim shaxsiy havolani (panel, xodim kartasi, Shaxsiy aloqa) ochib Start bossa, rahbar eslatmalari unga shaxsan boradi. Yangi akkauntdan qayta bossa, ulanish yangilanadi.

Rahbar: xodim kartasidagi "Rahbar" tugmasi, guruh adminlari va `OWNER_ID` ham rahbar hisoblanadi. Rahbar boshqalarga vazifa bera oladi va botning savollarini hal qiladi.

## Mualliflar

Javohir Jumaboyev, Valijon, Asror — Adliya AKT markazi, 2026.
Belgilar: Solar Icons (480 Design, CC BY 4.0). Shrift: Onest (SIL OFL).
