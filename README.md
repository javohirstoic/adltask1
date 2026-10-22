# Puls

Telegram ish guruhlaridagi xabarlardan rahbar uchun loyihalar va jamoa nazorati.
Xodimlar guruhda odatdagidek yozadi; bot har xabarni o'qiydi, panel esa holatni, xavflarni va tayyor qarorlarni ko'rsatadi.

To'liq texnik topshiriq: [docs/Puls_TZ_v1.pdf](docs/Puls_TZ_v1.pdf).

## Qanday ishlaydi

1. **Bot** (`puls/bot.py`) guruhdagi xabarni oladi va reaksiya bilan tasdiqlaydi: ✍ vazifa, 👍 bajarildi, 👀 muammo, 🫡 muddat, 🤔 loyiha aniqlanmadi.
2. **Tushunish** (`puls/parser.py`, `puls/ai.py`): `#task #done #muammo #deadline` teglari bo'lsa qoida bilan; teg bo'lmasa Gemini (faqat JSON, loyihani faqat ro'yxatdan tanlaydi); AI ishlamasa kalit so'zlar.
3. **Baza** (`puls/db.py`): SQLite — `data/puls.db`.
4. **Hisob-kitob** (`puls/analytics.py`): loyiha va xodim holatlari, prognoz, qarorlar. Barcha chegaralar `puls/settings.py` da va paneldan o'zgartiriladi.
5. **Qaror markazi** (`puls/actions.py`): vazifa o'tkazish, muddat surish, holat so'rash, shaxsiy eslatma. Har harakat jurnalga yoziladi.
6. **Vazifa berishdagi nazorat** (`puls/load.py`): ishi ko'p xodimga vazifa yozilsa, bot o'sha xabarga javob beradi va shu bo'limdan bo'shroq hamkasbni tavsiya qiladi. Tugmani vazifa bergan kishi yoki rahbar bosadi, tanlov qarorlar jurnaliga tushadi. "Faqat rahbarlar" sozlamasida oddiy xodim boshqaga yozgan vazifa o'sha xodim qabul qilgandan keyin hisobga kiradi.
7. **Panel** (`web/`): freymvorksiz JavaScript, `puls.css` dizayn tizimi, `office.js` izometrik ofis sahnasi.

## Ishga tushirish (kompyuterda)

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py --open
```

`.env` (namuna):

```
BOT_TOKEN=...            # BotFather dan
BOT_USERNAME=puls_loyiha_bot
OWNER_ID=...             # kunlik brifing shu odamga keladi
AI_PROVIDER=gemini
GEMINI_SA=path/to/service-account.json
PANEL_PIN=123456         # bo'sh bo'lsa panel kodsiz ochiladi
DEMO_DATA=1              # namuna guruhlarni har kuni yangilash
BOT_ENABLED=1            # bot faqat BITTA joyda ishlashi kerak
```

Namuna ma'lumot (50 xodim, 7 bo'lim, 14 loyiha, 4 guruh): `python -m puls.seed` (tez, AI javoblari keshdan).
Bugungi kunning hali vaqti kelmagan xabarlari navbatga tushadi va vaqti kelganda birma-bir qabul qilinadi, panel kun bo'yi jonli ko'rinadi.
AI keshini oldindan to'ldirish (bugun va keyingi kunlar uchun): `python -m puls.warm --days 4`.

Sinovlar: `python -m pytest tests`.

## Serverda

`docker compose up -d --build` — konteyner faqat `127.0.0.1:8121` da, tashqariga nginx orqali (`/adliya/puls/`).

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
