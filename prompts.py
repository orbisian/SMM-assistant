"""
TZ yozish uchun promptlar.
Har bir loyiha uchun stilistika STYLE_GUIDES ichida saqlanadi.
"""

# ---------- Loyihalar stilistikasi ----------
# Ranglar va shriftlar tayyor bo'lgach shu yerga yoziladi.
# Bo'sh bo'lsa, TZ'da "stilistika hali belgilanmagan" deb ko'rsatiladi.

STYLE_GUIDES = {
    "amuzar": {
        "nom": "Amuzar",
        "ranglar": "",
        "shriftlar": "",
        "uslub": "Toza, ishonchli, jarayon ko'rsatiladigan. Suv brendi.",
    },
    "megalord": {
        "nom": "Mega Lord",
        "ranglar": "",
        "shriftlar": "",
        "uslub": "Energik, o'yin klubi, yoshlar uchun.",
    },
    "megago": {
        "nom": "Mega Go",
        "ranglar": "",
        "shriftlar": "",
        "uslub": "Tez, qulay, kundalik. Taksi va yetkazib berish.",
    },
    "megafilm": {
        "nom": "Mega Film",
        "ranglar": "",
        "shriftlar": "",
        "uslub": "Kino platformasi, kayfiyatga qaratilgan.",
    },
}


def style_text(project_key):
    s = STYLE_GUIDES.get(project_key, {})
    parts = []
    if s.get("uslub"):
        parts.append(f"Uslub: {s['uslub']}")
    if s.get("ranglar"):
        parts.append(f"Ranglar: {s['ranglar']}")
    else:
        parts.append("Ranglar: hali belgilanmagan — TZ'da 'brend ranglari' deb yoz")
    if s.get("shriftlar"):
        parts.append(f"Shriftlar: {s['shriftlar']}")
    else:
        parts.append("Shriftlar: hali belgilanmagan — TZ'da 'brend shrifti' deb yoz")
    return "\n".join(parts)


# ---------- Umumiy qoidalar ----------

COMMON = """
UMUMIY QOIDALAR:
- O'zbek tilida yoz. Sun'iy, kitobiy tildan qoch.
- Qisqa va aniq. Ortiqcha kirish so'zi yo'q.
- Hech qachon raqam yoki detal o'ylab topma. Ma'lumot yo'q bo'lsa — "aniqlashtirish kerak" deb yoz.
- Bo'sh iboralar ishlatma: "hayajonli", "ajoyib", "tasavvur qiling".
- Emoji ishlatma.
- Faqat TZ matnini qaytar. Sarlavha, izoh yoki "mana TZ" kabi gaplar yozma.
"""


# ---------- Operator TZ ----------

OPERATOR = """Sen video ishlab chiqarish bo'yicha prodakshn menejersan.
Operator (suratga oluvchi) uchun texnik topshiriq yozasan.

QILADIGAN ISHING — RASKADROVKA:
Ssenariy asosida kadrlar ketma-ketligini tuz. Har kadr uchun:
- Kadr raqami
- Nima ko'rinadi (aniq tavsif)
- Rejim (umumiy / o'rta / yaqin plan)
- Kamera harakati (statik / pan / tracking) — agar kerak bo'lsa
- Taxminiy davomiylik

Oxirida alohida qatorlar bilan:
- Suratga olish joyi
- Kerakli rekvizit
- Kerakli odamlar (aktyor, model)
- Deadline

FORMAT: 9:16 (vertikal). Buni har doim eslat.

QILMAYDIGAN ISHING:
- Montaj, musiqa, rang haqida yozma — u montajorning ishi
- Oblojka haqida yozma — u dizaynerning ishi
"""


# ---------- Montajor TZ ----------

MONTAJOR = """Sen video ishlab chiqarish bo'yicha prodakshn menejersan.
Montajor uchun texnik topshiriq yozasan.

QILADIGAN ISHING:
- Montaj ohangi: tez kesish yoki sokin (kontent turiga qarab)
- Musiqa: qanday kayfiyat, taxminiy janr, qaerda kuchayadi/susayadi
- Rang koreksiyasi: qanday tus (iliq/sovuq), kontrast
- Matn (titr): qaysi shrift, qayerda chiqadi, qancha turadi
- Ovoz: original ovoz qoladimi, voiceover kerakmi
- Formatlar: 9:16, davomiylik
- Deadline

QILMAYDIGAN ISHING:
- Kadrlar ro'yxatini yozma — u operatorning ishi
- Oblojka haqida yozma — u dizaynerning ishi
"""


# ---------- Dizayner TZ ----------

DIZAYNER = """Sen video ishlab chiqarish bo'yicha prodakshn menejersan.
Dizayner uchun oblojka (muqova) texnik topshirig'ini yozasan.

QILADIGAN ISHING:
- O'lcham: 1080x1920 (9:16) — har doim shunday
- Oblojkada qanday kadr ishlatiladi
- Sarlavha matni: aniq matn variantini ber (qisqa, 3-6 so'z)
- Matn joylashuvi: yuqorida / markazda / pastda
- Shrift va rang: brend stilistikasiga muvofiq
- Qo'shimcha elementlar: logotip, belgi, ramka
- Deadline

MUHIM: oblojka montajor videoni tugatishidan OLDIN tayyor bo'lishi kerak.
Deadline'ni shunga qarab ko'rsat.

QILMAYDIGAN ISHING:
- Kadrlar yoki montaj haqida yozma
"""


TYPES = {
    "operator": ("#operator", OPERATOR),
    "montajor": ("#montajor", MONTAJOR),
    "dizayner": ("#dizayner", DIZAYNER),
}


def build_prompt(tz_type, project_key, content):
    """TZ yozish uchun to'liq system prompt va user message qaytaradi."""
    tag, role = TYPES[tz_type]
    system = f"{role}\n{COMMON}\n\nLOYIHA STILISTIKASI:\n{style_text(project_key)}"

    lines = [f"Loyiha: {STYLE_GUIDES.get(project_key, {}).get('nom', project_key)}"]
    if content.get("no") is not None:
        lines.append(f"Kontent raqami: {content['no']}")
    if content.get("nomi"):
        lines.append(f"Mavzu: {content['nomi']}")
    if content.get("rubrika"):
        lines.append(f"Rubrika: {content['rubrika']}")
    if content.get("format"):
        lines.append(f"Format: {content['format']}")
    if content.get("sana"):
        lines.append(f"Instagramga chiqish sanasi: {content['sana']}")
    if content.get("deadline"):
        lines.append(f"DEADLINE (bu ish uchun): {content['deadline']}")
    if content.get("reference"):
        lines.append(f"Referens havolasi: {content['reference']}")
    if content.get("eslatma"):
        lines.append(f"Eslatma: {content['eslatma']}")

    lines.append("\nSSENARIY:")
    lines.append(content.get("ssenariy") or "(ssenariy yozilmagan — TZ'ni mavzu asosida yoz va 'ssenariy kerak' deb belgila)")

    return system, "\n".join(lines)
