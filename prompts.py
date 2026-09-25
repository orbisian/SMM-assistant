"""
TZ shablonlari.

Tuzilma kod orqali quriladi (havolalar, shrift, qoidalar aniq qo'yiladi).
LLM faqat ijodiy qismlarni yozadi: matn highlightlari, b-roll jadvali, cover matni.
"""

import json

# 8-band uchun doimiy havola
TRANSITION_REF = "https://www.instagram.com/p/DSSTlpLjIZO/"

PLACEHOLDER_LINK = "[havola kerak]"


# ==================== LLM uchun ijodiy qism ====================

CREATIVE_SYSTEM = """Sen video prodakshn menejerisan. Ssenariy asosida montajor va dizayner
uchun ijodiy qismlarni tayyorlaysan.

FAQAT JSON qaytar, boshqa hech narsa yozma (izoh, ``` belgilari ham yo'q).

Format:
{
  "text_highlights": ["...", "..."],
  "broll": [{"vaqt": "0:00-0:03", "tavsif": "..."}],
  "cover_text": "..."
}

QOIDALAR:

text_highlights — videoda ekranga chiqadigan va ta'kidlanadigan eng muhim jumlalar.
  - 2-5 ta, har biri qisqa (2-7 so'z)
  - Ssenariydan olingan, o'ylab topilmagan

broll — b-roll jadvali, ssenariy bo'laklari asosida.
  - Ssenariy bo'laklarga bo'lingan bo'lsa — har bo'lak uchun bitta qator
  - vaqt: taxminiy oraliq, "0:00-0:03" formatida
  - tavsif: shu vaqtda ekranda nima ko'rinishi (aniq, qisqa)
  - Ssenariy bo'lmasa — bo'sh ro'yxat qaytar: []

cover_text — Reels muqovasidagi matn.
  - Insoniy, samimiy ohangda. Robot yozgandek bo'lmasin
  - Qisqa: 2-6 so'z
  - Mavzuga mos: savol, kutilmagan da'vo yoki qiziqish uyg'otuvchi jumla
  - Reklama shiori emas — odam do'stiga aytadigan gap kabi
  - Katta harflarda yozma, oddiy yoz (dizayner o'zi belgilaydi)
  - Taqiqlangan: "tasavvur qiling", "aytsam ishonmaysiz", "ajoyib", "hayratlanarli", emoji

Hech qachon faktlar yoki raqamlar o'ylab topma."""


def build_creative_prompt(content):
    """LLM'ga yuboriladigan user message."""
    lines = []
    if content.get("nomi"):
        lines.append(f"Mavzu: {content['nomi']}")
    if content.get("rubrika"):
        lines.append(f"Rubrika: {content['rubrika']}")
    if content.get("format"):
        lines.append(f"Format: {content['format']}")
    if content.get("hook"):
        lines.append(f"Hook (Notion'dan): {content['hook']}")
    lines.append("")
    lines.append("SSENARIY:")
    lines.append(content.get("ssenariy") or "(ssenariy yozilmagan)")
    return "\n".join(lines)


def parse_creative(text):
    """LLM javobini JSON sifatida o'qiydi. Buzuq bo'lsa — bo'sh qiymatlar."""
    empty = {"text_highlights": [], "broll": [], "cover_text": ""}
    if not text:
        return empty
    t = text.strip()
    s, e = t.find("{"), t.rfind("}")
    if s == -1 or e == -1:
        return empty
    try:
        data = json.loads(t[s:e + 1])
    except json.JSONDecodeError:
        return empty
    return {
        "text_highlights": [str(x) for x in data.get("text_highlights", []) if x],
        "broll": [b for b in data.get("broll", []) if isinstance(b, dict)],
        "cover_text": str(data.get("cover_text", "") or "").strip(),
    }


# ==================== Yordamchilar ====================

def _is_not_needed(value):
    """'shart emas' kabi qiymatlarni aniqlaydi."""
    if not value:
        return False
    v = str(value).strip().lower()
    return v in ("shart emas", "kerak emas", "yo'q", "yoq", "-", "—", "no", "none")


def _link_or_placeholder(value):
    return str(value).strip() if value else PLACEHOLDER_LINK


def _checked(value):
    return value is True or str(value).strip().lower() in ("true", "1", "ha", "yes", "✓")


# ==================== Montajor TZ ====================

def build_montajor_tz(content, style, creative, deadline_text):
    """Foydalanuvchining 9 bandli shabloni bo'yicha montajor TZ."""
    lines = []

    lines.append(f"1. Referens: {_link_or_placeholder(content.get('reference'))}")

    hv = content.get("hook_video")
    if _is_not_needed(hv):
        lines.append("2. Hook videosi: shart emas")
    else:
        lines.append(f"2. Hook videosi: {_link_or_placeholder(hv)}")
        lines.append("   B-roll hookda FullHD dan sifati tushmasin")

    hl = creative.get("text_highlights") or []
    if hl:
        lines.append("3. Text — ekranga chiqadigan va highlight bo'ladigan joylar:")
        for h in hl:
            lines.append(f"   • {h}")
    else:
        lines.append("3. Text: [ssenariydan aniqlash kerak]")

    lines.append(f"4. Shrift: {style.get('shrift') or '[brend shrifti]'}")
    lines.append(f"5. Text ranglari: {style.get('ranglar') or '[brend ranglari]'}")
    lines.append(f"6. Musiqa referensi: {_link_or_placeholder(content.get('musiqa'))}")

    broll = creative.get("broll") or []
    if broll:
        lines.append("7. B-roll time table (FullHD):")
        for b in broll:
            vaqt = str(b.get("vaqt", "")).strip()
            tavsif = str(b.get("tavsif", "")).strip()
            if vaqt or tavsif:
                lines.append(f"   {vaqt} — {tavsif}")
    else:
        lines.append("7. B-roll time table: [ssenariy bo'laklari kerak]")

    n = 8
    if _checked(content.get("otish_3s")):
        lines.append(f"{n}. Kadr yoki b-roll almashish har 3 soniyada bo'lishi shart")
        lines.append(f"   Namuna: {TRANSITION_REF}")
        n += 1

    if _checked(content.get("cta")):
        lines.append(f"{n}. CTA: obuna bo'lish knopkasi animatsiyasi — akkuratniy formatda, "
                     f"tayyor shablondan")

    lines.append("")
    lines.append(f"Deadline: {deadline_text}")
    return "\n".join(lines)


# ==================== Dizayner TZ ====================

def build_dizayner_tz(project_name, content, style, creative, deadline_text):
    """Reels cover uchun oddiy TZ."""
    lines = []
    lines.append(f"1. Brend: {project_name}")
    lines.append(f"2. Video mavzusi: {content.get('nomi') or '[mavzu]'}")

    cover = creative.get("cover_text")
    lines.append(f"3. Coverdagi matn: «{cover}»" if cover else "3. Coverdagi matn: [aniqlash kerak]")

    colors = style.get("ranglar")
    if colors:
        lines.append(f"4. Ranglar: {colors} — umumiy dizayn bo'yicha")
    else:
        lines.append("4. Brend ranglaridan foydalanilsin, umumiy dizayn bo'yicha ishlansin")

    lines.append(f"5. Deadline: {deadline_text}")
    lines.append("6. Qayerga: Telegram guruhiga, cover papkasiga")
    lines.append("")
    lines.append("Format: 1080x1920 (9:16)")
    return "\n".join(lines)
