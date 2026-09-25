"""
Notion API bilan ishlash.
Hujjat: https://developers.notion.com
"""

import os
import json
import urllib.request
import urllib.error

NOTION_VERSION = "2022-06-28"
BASE = "https://api.notion.com/v1"


def _headers():
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        raise RuntimeError("NOTION_TOKEN environment variable topilmadi")
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _request(method, path, payload=None):
    url = f"{BASE}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")[:400]
        raise RuntimeError(f"Notion API xatoligi ({e.code}): {body}")


# ---------- O'qish ----------

def _plain(rich):
    """rich_text massivini oddiy matnga aylantiradi."""
    return "".join(r.get("plain_text", "") for r in (rich or [])).strip()


def _prop_value(prop):
    """Notion property'dan oddiy qiymat chiqaradi."""
    if not prop:
        return None
    t = prop.get("type")
    if t == "title":
        return _plain(prop.get("title"))
    if t == "rich_text":
        return _plain(prop.get("rich_text"))
    if t == "number":
        return prop.get("number")
    if t == "select":
        sel = prop.get("select")
        return sel.get("name") if sel else None
    if t == "status":
        st = prop.get("status")
        return st.get("name") if st else None
    if t == "multi_select":
        return ", ".join(s.get("name", "") for s in prop.get("multi_select", []))
    if t == "date":
        d = prop.get("date")
        return d.get("start") if d else None
    if t == "url":
        return prop.get("url")
    if t == "checkbox":
        return prop.get("checkbox")
    if t == "files":
        files = prop.get("files", [])
        out = []
        for f in files:
            if f.get("type") == "external":
                out.append(f["external"]["url"])
            elif f.get("type") == "file":
                out.append(f["file"]["url"])
        return ", ".join(out)
    if t == "unique_id":
        # Notion'ning avtomatik ID ustuni (ID, №, va h.k.)
        uid = prop.get("unique_id") or {}
        return uid.get("number")
    if t == "formula":
        f = prop.get("formula") or {}
        ft = f.get("type")
        if ft == "string":
            return f.get("string")
        if ft == "number":
            return f.get("number")
        if ft == "boolean":
            return f.get("boolean")
        if ft == "date":
            d = f.get("date")
            return d.get("start") if d else None
        return None
    if t == "rollup":
        r = prop.get("rollup") or {}
        rt = r.get("type")
        if rt == "number":
            return r.get("number")
        if rt == "date":
            d = r.get("date")
            return d.get("start") if d else None
        if rt == "array":
            vals = [_prop_value(x) for x in r.get("array", [])]
            return ", ".join(str(v) for v in vals if v is not None)
        return None
    if t == "people":
        return ", ".join(p.get("name", "") for p in prop.get("people", []))
    if t == "created_time":
        return prop.get("created_time")
    return None


# Ustun nomlari har jadvalda har xil bo'lishi mumkin.
# Bot ularni shu ro'yxat bo'yicha taniydi (katta-kichik harf farqi yo'q).
FIELD_ALIASES = {
    "no": ["no", "№", "#", "raqam", "tartib"],
    "nomi": ["kontent nomi", "mavzu | senariy", "mavzu", "nomi", "name",
             "kontent", "sarlavha", "title"],
    "holat": ["holat", "status", "холат"],
    "sana": ["sana", "deadline", "chiqish sanasi", "date", "muddat"],
    "rubrika": ["rubrikalar", "rubrika", "kategoriya", "turkum"],
    "format": ["format", "formati"],
    "reference": ["reference", "referens", "havola", "link"],
    "eslatma": ["eslatmalar", "eslatma", "izoh", "notes"],
    "hook": ["hook", "ochilish"],
    "montaj": ["montaj", "montaj izohi"],
    "maqsad": ["maqsad", "goal"],
    "hook_video": ["hook video", "hook videosi", "hook havola", "hook link"],
    "musiqa": ["musiqa", "music", "musiqa referens", "muzika"],
    "montajor_deadline": ["montajor deadline", "montaj deadline", "montajor muddati"],
    "otish_3s": ["3s o'tish", "3s o‘tish", "3s otish", "3 soniya o'tish", "o'tish"],
    "cta": ["cta", "cta knopka", "obuna knopka"],
}


def resolve_fields(row):
    """
    Notion qatoridagi ustunlarni bot tushunadigan nomlarga moslashtiradi.
    Masalan «№» va «NO» — ikkalasi ham 'no' bo'ladi.
    """
    lowered = {str(k).strip().lower(): k for k in row.keys() if not str(k).startswith("_")}
    out = {}
    for canon, names in FIELD_ALIASES.items():
        for n in names:
            if n in lowered:
                out[canon] = row.get(lowered[n])
                break
        else:
            out[canon] = None
    out["_id"] = row.get("_id")
    out["_url"] = row.get("_url")
    return out


def query_database(database_id, page_size=100):
    """Bazadagi barcha yozuvlarni NO bo'yicha o'sish tartibida qaytaradi."""
    results = []
    cursor = None
    while True:
        payload = {"page_size": min(page_size, 100)}
        if cursor:
            payload["start_cursor"] = cursor
        data = _request("POST", f"/databases/{database_id}/query", payload)
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    rows = []
    for page in results:
        props = page.get("properties", {})
        row = {"_id": page["id"], "_url": page.get("url", "")}
        for name, prop in props.items():
            row[name] = _prop_value(prop)
        rows.append(row)

    # NO bo'yicha tartiblash (ustun nomi har xil bo'lishi mumkin)
    def sort_key(r):
        no = resolve_fields(r).get("no")
        try:
            no = int(no) if no is not None else None
        except (TypeError, ValueError):
            no = None
        return (no is None, no if no is not None else 0)

    rows.sort(key=sort_key)
    return rows


def _block_text(block):
    """Bitta blokdan matn chiqaradi."""
    t = block.get("type")
    body = block.get(t, {})
    text = _plain(body.get("rich_text"))
    if not text:
        return ""
    if t == "heading_1":
        return f"\n{text}\n"
    if t in ("heading_2", "heading_3"):
        return f"\n{text}\n"
    if t == "bulleted_list_item":
        return f"• {text}"
    if t == "numbered_list_item":
        return f"- {text}"
    if t == "to_do":
        mark = "[x]" if body.get("checked") else "[ ]"
        return f"{mark} {text}"
    if t == "quote":
        return f"> {text}"
    if t == "code":
        return f"```\n{text}\n```"
    return text


def get_page_text(page_id, max_depth=2):
    """Sahifa ichidagi matnni (ssenariyni) o'qiydi."""
    lines = []

    def walk(block_id, depth):
        if depth > max_depth:
            return
        cursor = None
        while True:
            path = f"/blocks/{block_id}/children?page_size=100"
            if cursor:
                path += f"&start_cursor={cursor}"
            data = _request("GET", path)
            for b in data.get("results", []):
                txt = _block_text(b)
                if txt:
                    lines.append(txt)
                if b.get("has_children"):
                    walk(b["id"], depth + 1)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

    walk(page_id, 0)
    return "\n".join(lines).strip()


# ---------- Yozish ----------

def get_status_property_name(database_id):
    """Holat ustunining nomi va turini aniqlaydi (status yoki select)."""
    data = _request("GET", f"/databases/{database_id}")
    for name, prop in data.get("properties", {}).items():
        if prop.get("type") in ("status", "select") and name.lower() in (
            "holat", "status", "холат"
        ):
            return name, prop["type"]
    # topilmasa — birinchi status turidagi ustun
    for name, prop in data.get("properties", {}).items():
        if prop.get("type") == "status":
            return name, "status"
    return None, None


def update_status(page_id, prop_name, prop_type, value):
    """Yozuvning holatini o'zgartiradi."""
    if prop_type == "status":
        props = {prop_name: {"status": {"name": value}}}
    else:
        props = {prop_name: {"select": {"name": value}}}
    return _request("PATCH", f"/pages/{page_id}", {"properties": props})


def check_connection(database_id):
    """Ulanishni tekshiradi, baza nomini qaytaradi."""
    data = _request("GET", f"/databases/{database_id}")
    title = _plain(data.get("title"))
    props = list(data.get("properties", {}).keys())
    return title, props


def resolve_database_id(given_id):
    """
    Berilgan ID jadvalnikimi yoki sahifanikimi — aniqlaydi.
    Sahifa bo'lsa, ichidagi birinchi jadvalni topib qaytaradi.

    Qaytaradi: (database_id, title, nima_topilgani)
    """
    gid = (given_id or "").replace("-", "").strip()

    # 1) To'g'ridan-to'g'ri jadval bo'lishi mumkin
    try:
        data = _request("GET", f"/databases/{gid}")
        return gid, _plain(data.get("title")), "jadval"
    except RuntimeError:
        pass

    # 2) Sahifa bo'lsa — ichidan jadvalni qidiramiz
    found = []

    def walk(block_id, depth):
        if depth > 2 or found:
            return
        cursor = None
        while True:
            path = f"/blocks/{block_id}/children?page_size=100"
            if cursor:
                path += f"&start_cursor={cursor}"
            try:
                data = _request("GET", path)
            except RuntimeError:
                return
            for b in data.get("results", []):
                if b.get("type") == "child_database":
                    title = b.get("child_database", {}).get("title", "")
                    found.append((b["id"].replace("-", ""), title))
                    return
                if b.get("has_children"):
                    walk(b["id"], depth + 1)
                    if found:
                        return
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

    walk(gid, 0)

    if found:
        db_id, title = found[0]
        return db_id, title, "sahifa ichidan topildi"

    raise RuntimeError(
        "Bu ID bo'yicha jadval topilmadi. Sahifa integratsiyaga ulanganini tekshiring "
        "yoki jadval havolasini bering."
    )
