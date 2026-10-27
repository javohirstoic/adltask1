# Puls: "Boshqaruv" sahifasi (TZ, 25.10.2026)

## Nega
Rahbar bitta sahifada ishini bitirishi kerak: loyihalar, xodimlar va hisobotlar orasida sakrab yurmasdan. Asosiy birlik — loyiha
(har Telegram guruh = bitta loyiha). Yonida doim ochiq AI yordamchi (Claude Code kabi jarayonni ko'rsatadi).

Manbalar: egasining 25.10 ovozli xabarlari, Feruzbek'ning "adliya-loyihalar-dashboard" maketi (undan faqat kerakli g'oyalar
olindi: qamrov, reja bajarilishi, hisobot matritsasi, hisobot muddati va kechikkanlar, faol blokerlar), Puls'dagi
real hisobotlar tahlili (9 kamchilik).

## Ekran (bitta sahifa, standart ochiladigan)
```
┌ Filtr qatori (yopishqoq) ──────────────────────────────────────────────┐ ┌ AI yordamchi ─┐
│ ‹ Bugun ›  Kun|Hafta|Oy   Loyiha ▾   Qidiruv   [Yozmadi][Qayta][Kritik]│ │ suhbat, qadam │
├ Ko'rsatkichlar (har biri bosilsa filtr bo'ladi) ───────────────────────┤ │ lar, jadval,  │
│ Qamrov 7/11 · Bajarilgan 22 (+10) · Reja 64% · Murojaat 5 · Muammo 2 · │ │ tasdiqli      │
│ Qayta yozilgan 1 · Kechikkan 3                                          │ │ amallar       │
├ [Loyihalar | Xodimlar] ────────────────────────────────────────────────┤ │               │
│ Loyiha  Holat  Yozdi  Ishlar  Murojaat  Muammo  Reja  10 kun  Oxirgi    │ │               │
│ ▸ SI-Internship  Kritik  4/7  12  3 ochiq  1  50%  ■■□■■■■□■■  15:05    │ │               │
│   └ (ochiladi shu yerda) Odamlar: yozdi/yozmadi/qayta yozdi/kechikdi    │ │               │
│     Ochiq murojaatlar · Muammolar · Bugungi ishlar · Rejadan qolgan     │ │               │
└────────────────────────────────────────────────────────────────────────┘ └───────────────┘
```
- Loyiha qatori bosilsa, sahifadan chiqmasdan pastida ochiladi. Xodim ismi bosilsa — yon oynada xodim sahifasi.
- "Xodimlar" ko'rinishi: har odam bir qator (loyihasi, bugun, ishlar, qayta yozgan, reja, oxirgi hisobot, holati).
- Hamma filtr ikkala ko'rinishga va AI savoliga ham taalluqli.
- Telefon: AI tugma orqali ochiladi; jadval kartochkaga aylanadi.

## Yangi ma'lumotlar (backend)
1. Murojaat: guruhga tushgan xato yoki "to'g'rilab bering" so'rovi (AI ajratadi). Muammo (bloker) — jamoaning o'z
   ishini to'xtatgan narsa. Ikkalasi ochiq/yopiq bo'ladi (tuzatdim degan xabar yopadi).
2. Reja bajarilishi: "Ertangi reja" bandi keyingi ish kuniga muddat oladi; o'sha kuni bajarildimi — hisoblanadi.
3. Hisobot muddati (sozlama, standart 18:00): kech yoki ertasi kuni yozilgan hisobot "kechikkan".
4. "Holat: Sariq/Qizil" xodim o'zi bergan holat sifatida saqlanadi.
5. Loyiha holati: Kritik (ochiq murojaat ko'p yoki eski), Kechikyapti (muddat o'tgan/qotgan ish), Jim (2 ish kuni hisobot yo'q), Yaxshi.
6. Hisobot sifati tuzatishlari: ikki qatorli band nomi, jarayondagi foiz, Jarayonda+Reja takrori, kunlik soat chegarasi.

## Dizayn qoidalari
Sokin, neytral, rang faqat istisnoda (kritik, kechikkan, qayta yozilgan), minimal radius, izoh matnsiz, bitta shrift.
Telefon 390 va kompyuter 1440 da tekshiriladi.
