"""
TotMega TZ Bot
Notion'dan kontentni oladi, Claude orqali TZ yozadi, Telegram forum mavzulariga joylaydi.

Environment variables:
  BOT_TOKEN          — BotFather tokeni
  ANTHROPIC_API_KEY  — console.anthropic.com kaliti
  NOTION_TOKEN       — Notion integration tokeni (ntn_...)
  OWNER_ID           — sizning Telegram ID raqamingiz
  GROUP_ID           — guruh ID (manfiy raqam, -100... bilan boshlanadi)
"""

import os
import re
import json
import sqlite3
import logging
import urllib.request
import urllib.error
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)

import notion_api
import prompts as P

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tz-bot")

# Baza yo'li. Railway'da doimiy disk (Volume) ulansa, DB_PATH ni
# shu diskka yo'naltiring — masalan /data/tzbot.db
# Aks holda har qayta deploy'da sozlamalar o'chib ketadi.
DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "tzbot.db"))
MODEL = "claude-sonnet-4-6"
TG_LIMIT = 3900

# Deadline: Sana'dan necha kun oldin (o'zgartirish mumkin)
# Deadline sozlamalari
# Montajor deadline: chiqish sanasidan necha kun oldin (vaqt Notion'dan olinadi)
MONTAJOR_DAYS_BEFORE = 1
# Dizayner montajordan necha soat oldin tugatadi
DIZAYNER_HOURS_BEFORE = 3
# Notion'da vaqt yozilmagan bo'lsa ishlatiladigan standart vaqt
DEFAULT_MONTAJOR_TIME = "18:00"

# Mavzu turlari
TOPICS = {
    "ssenariy": "Ssenariylar",
    "tz_video": "TZ: Operator/Montajor",
    "tz_dizayn": "TZ: Dizayner",
}

STATUS_JARAYONDA = "Jarayonda"
STATUS_TAYYOR = "Tayyor"


# ==================== Baza ====================

def init_db():
    # Baza papkasi mavjud bo'lmasa — yaratamiz (Volume uchun)
    folder = os.path.dirname(os.path.abspath(DB_PATH))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)

    if not os.environ.get("DB_PATH"):
        log.warning(
            "DB_PATH sozlanmagan — sozlamalar har qayta deploy'da o'chadi. "
            "Railway'da Volume ulab, DB_PATH=/data/tzbot.db qiling.")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS topics (
        kind TEXT PRIMARY KEY,
        thread_id INTEGER NOT NULL,
        title TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS projects (
        key TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        notion_db TEXT,
        video_thread_id INTEGER
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS refs (
        project TEXT NOT NULL,
        no INTEGER NOT NULL,
        file_id TEXT NOT NULL,
        added_at TEXT NOT NULL,
        PRIMARY KEY (project, no, file_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS styles (
        project TEXT PRIMARY KEY,
        shrift TEXT,
        ranglar TEXT,
        raw TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS sent_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project TEXT, no INTEGER, tz_type TEXT,
        page_id TEXT, sent_at TEXT
    )""")
    conn.commit()
    conn.close()


def db():
    return sqlite3.connect(DB_PATH)


def set_topic(kind, thread_id, title):
    conn = db()
    conn.execute(
        "INSERT INTO topics (kind, thread_id, title) VALUES (?,?,?) "
        "ON CONFLICT(kind) DO UPDATE SET thread_id=excluded.thread_id, title=excluded.title",
        (kind, thread_id, title))
    conn.commit()
    conn.close()


def get_topic(kind):
    conn = db()
    row = conn.execute("SELECT thread_id FROM topics WHERE kind=?", (kind,)).fetchone()
    conn.close()
    return row[0] if row else None


def all_topics():
    conn = db()
    rows = conn.execute("SELECT kind, thread_id, title FROM topics").fetchall()
    conn.close()
    return rows


def set_project(key, name, notion_db=None, video_thread=None):
    conn = db()
    cur = conn.execute("SELECT notion_db, video_thread_id FROM projects WHERE key=?", (key,)).fetchone()
    if cur:
        notion_db = notion_db if notion_db is not None else cur[0]
        video_thread = video_thread if video_thread is not None else cur[1]
    conn.execute(
        "INSERT INTO projects (key, name, notion_db, video_thread_id) VALUES (?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET name=excluded.name, notion_db=excluded.notion_db, "
        "video_thread_id=excluded.video_thread_id",
        (key, name, notion_db, video_thread))
    conn.commit()
    conn.close()


def get_project(key):
    conn = db()
    row = conn.execute(
        "SELECT key, name, notion_db, video_thread_id FROM projects WHERE key=?", (key,)).fetchone()
    conn.close()
    return row


def all_projects():
    conn = db()
    rows = conn.execute("SELECT key, name, notion_db, video_thread_id FROM projects").fetchall()
    conn.close()
    return rows


def project_by_thread(thread_id):
    conn = db()
    row = conn.execute("SELECT key, name FROM projects WHERE video_thread_id=?", (thread_id,)).fetchone()
    conn.close()
    return row


def add_ref(project, no, file_id):
    conn = db()
    conn.execute("INSERT OR REPLACE INTO refs (project,no,file_id,added_at) VALUES (?,?,?,?)",
                 (project, no, file_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_refs(project, no):
    conn = db()
    rows = conn.execute("SELECT file_id FROM refs WHERE project=? AND no=?", (project, no)).fetchall()
    conn.close()
    return [r[0] for r in rows]


def set_style(project, shrift, ranglar, raw):
    conn = db()
    conn.execute(
        "INSERT INTO styles (project, shrift, ranglar, raw) VALUES (?,?,?,?) "
        "ON CONFLICT(project) DO UPDATE SET shrift=excluded.shrift, "
        "ranglar=excluded.ranglar, raw=excluded.raw",
        (project, shrift, ranglar, raw))
    conn.commit()
    conn.close()


def get_style(project):
    conn = db()
    row = conn.execute(
        "SELECT shrift, ranglar, raw FROM styles WHERE project=?", (project,)).fetchone()
    conn.close()
    if not row:
        return {}
    return {"shrift": row[0], "ranglar": row[1], "raw": row[2]}


def log_sent(project, no, tz_type, page_id):
    conn = db()
    conn.execute("INSERT INTO sent_log (project,no,tz_type,page_id,sent_at) VALUES (?,?,?,?,?)",
                 (project, no, tz_type, page_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()


# ==================== Claude API ====================

def ask_llm(system_prompt, user_message, max_tokens=1500):
    """Claude API'dan javob oladi."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "⚠️ ANTHROPIC_API_KEY sozlanmagan."

    payload = json.dumps({
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        blocks = data.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return text.strip() if text else "(bo'sh javob)"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")[:300]
        return f"⚠️ API xatoligi ({e.code}): {body}"
    except Exception as e:
        return f"⚠️ Xatolik: {e}"


# ==================== Yordamchi ====================

def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        owner = os.environ.get("OWNER_ID")
        if owner and str(update.effective_user.id) != str(owner):
            return
        return await func(update, context)
    return wrapper


def _parse_time(text):
    """'15:00', '15.00', '15' -> (15, 0). Topilmasa None."""
    if not text:
        return None
    m = re.search(r"(\d{1,2})\s*[:.]\s*(\d{2})", str(text))
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"\b(\d{1,2})\b", str(text))
        if not m:
            return None
        h, mi = int(m.group(1)), 0
    if 0 <= h <= 23 and 0 <= mi <= 59:
        return h, mi
    return None


def calc_deadlines(sana_str, montajor_time_text):
    """
    Montajor va dizayner deadline'larini hisoblaydi.

    Montajor: chiqish sanasidan MONTAJOR_DAYS_BEFORE kun oldin,
              vaqt Notion'dagi «Montajor deadline» dan
    Dizayner: montajordan DIZAYNER_HOURS_BEFORE soat oldin

    Qaytaradi: (montajor_matn, dizayner_matn)
    """
    if not sana_str:
        msg = "chiqish sanasi belgilanmagan"
        return msg, msg

    try:
        d = datetime.fromisoformat(str(sana_str)[:10])
    except ValueError:
        return str(sana_str), str(sana_str)

    t = _parse_time(montajor_time_text) or _parse_time(DEFAULT_MONTAJOR_TIME)
    montajor = (d - timedelta(days=MONTAJOR_DAYS_BEFORE)).replace(hour=t[0], minute=t[1])
    dizayner = montajor - timedelta(hours=DIZAYNER_HOURS_BEFORE)

    fmt = "%d.%m.%Y, %H:%M"
    return montajor.strftime(fmt), dizayner.strftime(fmt)


def norm_key(text):
    """'Mega Go' -> 'megago'"""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


async def send_to_topic(context, thread_id, text, photos=None):
    """Mavzuga xabar yuboradi, uzun bo'lsa bo'laklaydi."""
    group_id = os.environ.get("GROUP_ID")
    if not group_id:
        raise RuntimeError("GROUP_ID sozlanmagan")

    chunks = [text[i:i + TG_LIMIT] for i in range(0, len(text), TG_LIMIT)] or [text]
    first_msg = None
    for ch in chunks:
        m = await context.bot.send_message(
            chat_id=int(group_id), message_thread_id=thread_id, text=ch)
        if first_msg is None:
            first_msg = m

    if photos:
        for fid in photos:
            await context.bot.send_photo(
                chat_id=int(group_id), message_thread_id=thread_id,
                photo=fid, caption="Referens")
    return first_msg


# ==================== Buyruqlar ====================

@owner_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*TotMega TZ Bot*\n\n"
        "*Ishlatish:*\n"
        "/yubor <loyiha> <son> — TZ yuborish\n"
        "   masalan: `/yubor megago 3` yoki `/yubor amuzar 2,5`\n"
        "/royxat <loyiha> — kontent ro'yxati\n\n"
        "*Stilistika:*\n"
        "/stil <loyiha> — ko'rish yoki saqlash\n"
        "   `/stil amuzar`\n"
        "   `Shrift: Montserrat Bold`\n"
        "   `Ranglar: #0A6EBD, oq`\n\n"
        "*Referens:* rasmni yuboring, izohiga `megago 3`\n\n"
        "*Sozlash:*\n"
        "/loyiha <kalit> <nom> <notion\\_id> — loyiha qo'shish/almashtirish\n"
        "/mavzu <turi> — mavzu ichida (ssenariy, tz\\_video, tz\\_dizayn)\n"
        "/video <kalit> — tayyor videolar mavzusi ichida\n"
        "/holat · /tekshir · /id"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mavzu ichida ishlatiladi — thread ID ni ko'rsatadi."""
    msg = update.message
    tid = msg.message_thread_id
    chat_id = msg.chat_id
    if tid:
        await msg.reply_text(
            f"Mavzu ID: `{tid}`\nGuruh ID: `{chat_id}`",
            parse_mode=ParseMode.MARKDOWN)
    else:
        await msg.reply_text(
            f"Bu mavzu emas (umumiy chat).\nGuruh ID: `{chat_id}`",
            parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_mavzu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Joriy mavzuni turga biriktiradi."""
    msg = update.message
    tid = msg.message_thread_id
    if not tid:
        await msg.reply_text("Bu buyruqni mavzu ichida yozing.")
        return
    if not context.args:
        await msg.reply_text(f"Turini yozing: {', '.join(TOPICS.keys())}")
        return
    kind = context.args[0].lower()
    if kind not in TOPICS:
        await msg.reply_text(f"Noto'g'ri tur. Mumkin: {', '.join(TOPICS.keys())}")
        return
    set_topic(kind, tid, TOPICS[kind])
    await msg.reply_text(f"✅ '{TOPICS[kind]}' mavzusi biriktirildi (ID: {tid})")


@owner_only
async def cmd_loyiha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Loyiha qo'shish: /loyiha megago Mega Go <notion_db_id>"""
    if len(context.args) < 3:
        await update.message.reply_text(
            "Foydalanish:\n`/loyiha megago Mega Go 37303e63c8d980e3aef6e18095043252`",
            parse_mode=ParseMode.MARKDOWN)
        return
    key = norm_key(context.args[0])
    given = context.args[-1].replace("-", "")
    name = " ".join(context.args[1:-1])

    wait = await update.message.reply_text("Notion tekshirilyapti...")
    try:
        db_id, title, how = notion_api.resolve_database_id(given)
    except Exception as e:
        await wait.edit_text(f"⚠️ {e}")
        return

    set_project(key, name, notion_db=db_id)
    note = "" if how == "jadval" else f"\n({how})"
    await wait.edit_text(
        f"✅ Loyiha saqlandi\n\n{name} (kalit: `{key}`)\n"
        f"Jadval: «{title}»{note}\nID: `{db_id}`",
        parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Joriy mavzuni loyihaning 'tayyor videolar' mavzusi qiladi."""
    msg = update.message
    tid = msg.message_thread_id
    if not tid:
        await msg.reply_text("Bu buyruqni 'tayyor videolar' mavzusi ichida yozing.")
        return
    if not context.args:
        await msg.reply_text("Loyiha kalitini yozing: `/video megago`",
                             parse_mode=ParseMode.MARKDOWN)
        return
    key = norm_key(context.args[0])
    p = get_project(key)
    if not p:
        await msg.reply_text(f"'{key}' loyihasi topilmadi. Avval /loyiha bilan qo'shing.")
        return
    set_project(key, p[1], video_thread=tid)
    await msg.reply_text(f"✅ '{p[1]}' tayyor videolar mavzusi biriktirildi (ID: {tid})")


@owner_only
async def cmd_stil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Loyiha stilistikasini saqlaydi.

    /stil amuzar
    Shrift: Montserrat Bold
    Ranglar: #0A6EBD, oq
    """
    text = update.message.text or ""
    lines = text.split("\n")
    first = lines[0].split(maxsplit=2)

    if len(first) < 2:
        keys = ", ".join(p[0] for p in all_projects()) or "yo'q"
        await update.message.reply_text(
            "Foydalanish:\n\n"
            "`/stil amuzar`\n"
            "`Shrift: Montserrat Bold`\n"
            "`Ranglar: #0A6EBD, oq`\n\n"
            f"Ko'rish uchun: `/stil amuzar`\nLoyihalar: {keys}",
            parse_mode=ParseMode.MARKDOWN)
        return

    key = norm_key(first[1])
    p = get_project(key)
    if not p:
        await update.message.reply_text(f"'{key}' loyihasi topilmadi.")
        return

    # Birinchi qatordan keyingi matn (yoki shu qatorning davomi)
    body_parts = []
    if len(first) > 2:
        body_parts.append(first[2])
    body_parts.extend(lines[1:])
    body = "\n".join(body_parts).strip()

    # Faqat ko'rish
    if not body:
        s = get_style(key)
        if not s:
            await update.message.reply_text(f"{p[1]} uchun stilistika hali yo'q.")
            return
        await update.message.reply_text(
            f"*{p[1]}* stilistikasi:\n\n"
            f"Shrift: {s.get('shrift') or '—'}\n"
            f"Ranglar: {s.get('ranglar') or '—'}",
            parse_mode=ParseMode.MARKDOWN)
        return

    shrift, ranglar = None, None
    for ln in body.split("\n"):
        low = ln.lower()
        if ":" not in ln:
            continue
        val = ln.split(":", 1)[1].strip()
        if low.startswith(("shrift", "font", "шрифт")):
            shrift = val
        elif low.startswith(("rang", "color", "цвет")):
            ranglar = val

    if not shrift and not ranglar:
        await update.message.reply_text(
            "«Shrift:» yoki «Ranglar:» qatorlari topilmadi.\n"
            "Har birini alohida qatorga yozing.")
        return

    # Eskisini saqlab qolish — faqat berilganini yangilash
    old = get_style(key)
    shrift = shrift or old.get("shrift")
    ranglar = ranglar or old.get("ranglar")
    set_style(key, shrift, ranglar, body)

    await update.message.reply_text(
        f"✅ {p[1]} stilistikasi saqlandi\n\n"
        f"Shrift: {shrift or '—'}\n"
        f"Ranglar: {ranglar or '—'}")


@owner_only
async def cmd_holat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["*Mavzular:*"]
    tps = all_topics()
    if tps:
        for kind, tid, title in tps:
            lines.append(f"  {title} — ID {tid}")
    else:
        lines.append("  (hali biriktirilmagan)")

    lines.append("\n*Loyihalar:*")
    prs = all_projects()
    if prs:
        for key, name, ndb, vt in prs:
            ndb_s = f"{ndb[:8]}..." if ndb else "yo'q"
            vt_s = str(vt) if vt else "yo'q"
            lines.append(f"  {name} (`{key}`)\n     Notion: {ndb_s} · video mavzu: {vt_s}")
    else:
        lines.append("  (hali qo'shilmagan)")

    group = os.environ.get("GROUP_ID", "sozlanmagan")
    lines.append(f"\nGuruh ID: `{group}`")

    if os.environ.get("DB_PATH"):
        lines.append(f"Baza: `{DB_PATH}` (doimiy ✅)")
    else:
        lines.append("Baza: vaqtinchalik ⚠️ — har deploy'da o'chadi")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_tekshir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Notion ulanishini tekshiradi."""
    # Claude API holati
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    lines = [f"{'✅' if has_key else '❌'} *Claude API:* `{MODEL}`"]
    if has_key:
        test = ask_llm("Faqat 'ishlayapti' deb javob ber.", "test", 20)
        lines.append(f"   Sinov: {test[:80]}")
    else:
        lines.append("   ANTHROPIC_API_KEY sozlanmagan")
    lines.append("")

    prs = all_projects()
    if not prs:
        lines.append("Loyiha qo'shilmagan.")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        return
    for key, name, ndb, _ in prs:
        if not ndb:
            lines.append(f"❌ {name}: Notion bazasi ulanmagan")
            continue
        try:
            title, props = notion_api.check_connection(ndb)
            lines.append(f"✅ {name}: «{title}»\n   Ustunlar: {', '.join(props)}")
        except Exception as e:
            lines.append(f"❌ {name}: {e}")
    await update.message.reply_text("\n".join(lines)[:TG_LIMIT],
                                    parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_royxat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Loyihadagi kontent ro'yxatini ko'rsatadi."""
    if not context.args:
        keys = ", ".join(p[0] for p in all_projects()) or "yo'q"
        await update.message.reply_text(f"Loyiha kalitini yozing. Mavjud: {keys}")
        return
    key = norm_key(context.args[0])
    p = get_project(key)
    if not p or not p[2]:
        await update.message.reply_text("Loyiha yoki Notion bazasi topilmadi.")
        return

    wait = await update.message.reply_text("Notion'dan o'qilyapti...")
    try:
        rows = notion_api.query_database(p[2])
    except Exception as e:
        await wait.edit_text(f"⚠️ {e}")
        return

    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    items = [notion_api.resolve_fields(r) for r in rows]
    items.sort(key=lambda f: (_int(f.get("no")) is None, _int(f.get("no")) or 0))

    lines = [f"*{p[1]}* — {len(items)} ta yozuv\n"]
    for f in items[:30]:
        no = _int(f.get("no"))
        nomi = f.get("nomi") or "(nomsiz)"
        holat = f.get("holat")
        holat = str(holat) if holat not in (None, "") else "—"
        if no is None and not f.get("nomi"):
            continue
        lines.append(f"{no}. {nomi[:45]} — {holat}")
    await wait.edit_text("\n".join(lines)[:TG_LIMIT], parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_ustun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot ustunlarni qanday o'qiyotganini ko'rsatadi (tashxis uchun)."""
    if not context.args:
        keys = ", ".join(p[0] for p in all_projects()) or "yo'q"
        await update.message.reply_text(f"Loyiha kalitini yozing. Mavjud: {keys}")
        return
    key = norm_key(context.args[0])
    p = get_project(key)
    if not p or not p[2]:
        await update.message.reply_text("Loyiha topilmadi.")
        return

    wait = await update.message.reply_text("O'qilyapti...")
    try:
        raw = notion_api._request("POST", f"/databases/{p[2]}/query", {"page_size": 3})
    except Exception as e:
        await wait.edit_text(f"⚠️ {e}")
        return

    results = raw.get("results", [])
    if not results:
        await wait.edit_text("Jadval bo'sh.")
        return

    lines = [f"*{p[1]}* — ustun turlari:\n"]
    props = results[0].get("properties", {})
    for name, prop in props.items():
        t = prop.get("type")
        val = notion_api._prop_value(prop)
        shown = str(val)[:30] if val is not None else "—"
        lines.append(f"`{name}` · _{t}_ → {shown}")

    lines.append("\n*Bot nimani tushundi:*")
    rows = []
    for page in results:
        row = {"_id": page["id"], "_url": page.get("url", "")}
        for name, prop in page.get("properties", {}).items():
            row[name] = notion_api._prop_value(prop)
        rows.append(notion_api.resolve_fields(row))

    for f in rows:
        lines.append(f"  no={f.get('no')} · nomi={str(f.get('nomi'))[:25]} · holat={f.get('holat')}")

    await wait.edit_text("\n".join(lines)[:TG_LIMIT], parse_mode=ParseMode.MARKDOWN)


# ==================== Asosiy: /yubor ====================

@owner_only
async def cmd_yubor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if len(context.args) < 1:
        await msg.reply_text(
            "Foydalanish: `/yubor megago 3`\n"
            "yoki aniq raqamlar: `/yubor megago 2,5,7`",
            parse_mode=ParseMode.MARKDOWN)
        return

    key = norm_key(context.args[0])
    p = get_project(key)
    if not p or not p[2]:
        await msg.reply_text(f"'{key}' loyihasi yoki Notion bazasi topilmadi.")
        return

    # Mavzular tekshiruvi
    missing = [TOPICS[k] for k in TOPICS if not get_topic(k)]
    if missing:
        await msg.reply_text(
            "Quyidagi mavzular biriktirilmagan:\n" + "\n".join(f"• {m}" for m in missing) +
            "\n\nHar mavzu ichida /mavzu buyrug'ini yozing.")
        return

    # Nechta / qaysilar
    arg = context.args[1] if len(context.args) > 1 else "1"
    explicit_nos = None
    if "," in arg:
        explicit_nos = [int(x) for x in arg.split(",") if x.strip().isdigit()]
        count = len(explicit_nos)
    else:
        try:
            count = int(arg)
        except ValueError:
            await msg.reply_text("Son noto'g'ri. Masalan: `/yubor megago 3`",
                                 parse_mode=ParseMode.MARKDOWN)
            return

    wait = await msg.reply_text(f"Notion'dan {p[1]} o'qilyapti...")

    try:
        rows = notion_api.query_database(p[2])
    except Exception as e:
        await wait.edit_text(f"⚠️ {e}")
        return

    # Ustun nomlarini moslashtirish (har jadvalda har xil bo'lishi mumkin)
    rows = [dict(notion_api.resolve_fields(r), _raw=r) for r in rows]

    def as_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    # Raqam bo'yicha tartiblash — bo'sh raqamlilar oxiriga
    rows.sort(key=lambda r: (as_int(r.get("no")) is None,
                             as_int(r.get("no")) or 0))

    # Tanlash
    if explicit_nos:
        selected = [r for r in rows if as_int(r.get("no")) in explicit_nos]
    else:
        selected = [r for r in rows if as_int(r.get("no")) is not None][:count]

    if not selected:
        await wait.edit_text("Mos kontent topilmadi.")
        return

    # Holat ustunini aniqlash
    try:
        status_name, status_type = notion_api.get_status_property_name(p[2])
    except Exception:
        status_name, status_type = None, None

    th_ssenariy = get_topic("ssenariy")
    th_video = get_topic("tz_video")
    th_dizayn = get_topic("tz_dizayn")

    done = []
    for idx, row in enumerate(selected, start=1):
        no = as_int(row.get("no"))
        nomi = row.get("nomi") or "(nomsiz)"
        await wait.edit_text(f"[{idx}/{len(selected)}] #{no} — {nomi[:40]}\nSsenariy o'qilyapti...")

        # Ssenariyni sahifa ichidan olish
        try:
            ssenariy = notion_api.get_page_text(row["_id"])
        except Exception as e:
            ssenariy = ""
            log.warning("Ssenariy o'qilmadi: %s", e)

        base = {
            "no": no,
            "nomi": nomi,
            "rubrika": row.get("rubrika"),
            "format": row.get("format"),
            "sana": row.get("sana"),
            "reference": row.get("reference"),
            "hook": row.get("hook"),
            "hook_video": row.get("hook_video"),
            "musiqa": row.get("musiqa"),
            "otish_3s": row.get("otish_3s"),
            "cta": row.get("cta"),
            "ssenariy": ssenariy,
        }

        # 1) Ssenariyni Ssenariylar mavzusiga
        head = f"#{no} · {nomi}\n{p[1]}"
        if row.get("sana"):
            head += f" · chiqish: {str(row['sana'])[:10]}"
        ss_text = f"{head}\n\n{ssenariy if ssenariy else '(ssenariy Notion sahifasida yozilmagan)'}"
        if row.get("_url"):
            ss_text += f"\n\nNotion: {row['_url']}"
        await send_to_topic(context, th_ssenariy, ss_text)

        # 2) Ijodiy qismlar — bitta LLM so'rovi (highlight, b-roll, cover matni)
        await wait.edit_text(
            f"[{idx}/{len(selected)}] #{no} — {nomi[:30]}\nTZ tayyorlanyapti...")
        creative_raw = ask_llm(P.CREATIVE_SYSTEM, P.build_creative_prompt(base), 1500)
        creative = P.parse_creative(creative_raw)

        style = get_style(key)
        dl_montajor, dl_dizayner = calc_deadlines(
            row.get("sana"), row.get("montajor_deadline"))

        # 3) Montajor TZ
        m_text = P.build_montajor_tz(base, style, creative, dl_montajor)
        m_head = f"#montajor #{no}\n{p[1]} · {nomi}\n{'─' * 20}\n"
        await send_to_topic(context, th_video, m_head + m_text)
        log_sent(key, no, "montajor", row["_id"])

        # 4) Dizayner TZ (+ referens rasmlari)
        refs = get_refs(key, no) if no is not None else []
        d_text = P.build_dizayner_tz(p[1], base, style, creative, dl_dizayner)
        d_head = f"#dizayner #{no}\n{p[1]} · {nomi}\n{'─' * 20}\n"
        await send_to_topic(context, th_dizayn, d_head + d_text, photos=refs)
        log_sent(key, no, "dizayner", row["_id"])

        # 3) Notion holatini yangilash
        if status_name:
            try:
                notion_api.update_status(row["_id"], status_name, status_type, STATUS_JARAYONDA)
            except Exception as e:
                log.warning("Holat yangilanmadi: %s", e)

        done.append(f"#{no} {nomi[:35]}")

    await wait.edit_text(
        f"✅ *{p[1]}* — {len(done)} ta kontent yuborildi\n\n" +
        "\n".join(done) +
        f"\n\nHolat «{STATUS_JARAYONDA}» ga o'tkazildi.",
        parse_mode=ParseMode.MARKDOWN)


# ==================== Referens rasmlari ====================

@owner_only
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shaxsiy chatda rasm + izoh 'megago 3' — referens sifatida saqlaydi."""
    msg = update.message
    caption = (msg.caption or "").strip()
    if not caption:
        await msg.reply_text("Izohiga loyiha va raqam yozing. Masalan: `megago 3`",
                             parse_mode=ParseMode.MARKDOWN)
        return

    m = re.match(r"^([a-zA-Z\s]+?)\s*(\d+)$", caption)
    if not m:
        await msg.reply_text("Format: `megago 3` (loyiha kaliti va raqam)",
                             parse_mode=ParseMode.MARKDOWN)
        return

    key = norm_key(m.group(1))
    no = int(m.group(2))
    p = get_project(key)
    if not p:
        keys = ", ".join(x[0] for x in all_projects()) or "yo'q"
        await msg.reply_text(f"'{key}' topilmadi. Mavjud: {keys}")
        return

    file_id = msg.photo[-1].file_id
    add_ref(key, no, file_id)
    total = len(get_refs(key, no))
    await msg.reply_text(f"✅ Referens saqlandi: {p[1]} #{no} (jami {total} ta)")


# ==================== Guruhdagi video ====================

async def on_group_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'tayyor videolar' mavzusiga video tushsa — Notion'da 'Tayyor' qiladi."""
    msg = update.message
    if not msg or not msg.message_thread_id:
        return

    proj = project_by_thread(msg.message_thread_id)
    if not proj:
        return

    key, name = proj
    caption = msg.caption or ""
    m = re.search(r"#(\d+)", caption)
    if not m:
        await msg.reply_text(
            "Qaysi kontent ekani ko'rsatilmagan. Izohga `#3` kabi raqam yozing.",
            parse_mode=ParseMode.MARKDOWN)
        return

    no = int(m.group(1))
    p = get_project(key)
    if not p or not p[2]:
        return

    try:
        rows = notion_api.query_database(p[2])
        def _as_int(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return None
        target = next(
            (r for r in rows if _as_int(notion_api.resolve_fields(r).get("no")) == no),
            None)
        if not target:
            await msg.reply_text(f"Notion'da #{no} topilmadi.")
            return
        status_name, status_type = notion_api.get_status_property_name(p[2])
        if status_name:
            notion_api.update_status(target["_id"], status_name, status_type, STATUS_TAYYOR)
    except Exception as e:
        log.warning("Holat yangilanmadi: %s", e)
        await msg.reply_text(f"⚠️ Notion yangilanmadi: {e}")
        return

    nomi = notion_api.resolve_fields(target).get("nomi") or ""
    await msg.reply_text(f"✅ Notion: #{no} «{STATUS_TAYYOR}»")

    owner = os.environ.get("OWNER_ID")
    if owner:
        try:
            await context.bot.send_message(
                chat_id=int(owner),
                text=f"🎬 {name} #{no} tayyor\n{nomi}\n\nNotion holati «{STATUS_TAYYOR}» ga o'tdi.")
        except Exception:
            pass


# ==================== Ishga tushirish ====================

def main():
    init_db()
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN topilmadi!")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("mavzu", cmd_mavzu))
    app.add_handler(CommandHandler("loyiha", cmd_loyiha))
    app.add_handler(CommandHandler("video", cmd_video))
    app.add_handler(CommandHandler("holat", cmd_holat))
    app.add_handler(CommandHandler("tekshir", cmd_tekshir))
    app.add_handler(CommandHandler("royxat", cmd_royxat))
    app.add_handler(CommandHandler("ustun", cmd_ustun))
    app.add_handler(CommandHandler("yubor", cmd_yubor))
    app.add_handler(CommandHandler("stil", cmd_stil))

    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, on_photo))
    app.add_handler(MessageHandler(
        (filters.VIDEO | filters.Document.VIDEO) & filters.ChatType.GROUPS, on_group_video))

    log.info("TZ bot ishga tushdi")
    app.run_polling()


if __name__ == "__main__":
    main()
