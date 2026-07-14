#!/usr/bin/env python3
"""Cào dữ liệu chi tiết (unit, lesson, skill, mô tả, ảnh, video, link nhiệm vụ)
từ 24 trang "tài liệu số hóa" trong data.db.

Chạy:  python3 scrape.py            # cào tất cả
       python3 scrape.py STARTERS   # cào 1 lớp (theo name trong bảng classes)
"""
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

DB = Path(__file__).parent / "data.db"
MEDIA_DIR = Path(__file__).parent / "assets" / "media"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}

# ----------------------------------------------------------------- parser ---
BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td"}


class SiteParser(HTMLParser):
    """Đọc trang Google Sites theo thứ tự tài liệu, gom text theo đoạn văn.

    Sinh ra dãy token:
      ('HEAD', level, text)    - tiêu đề h1..h6
      ('TEXT', text)           - một đoạn văn
      ('LINK', href, anchor_text, label_text_truoc_link_trong_doan)
      ('IMG', src) / ('VIDEO', src)
    """

    def __init__(self):
        super().__init__()
        self.tokens = []
        self.skip = 0
        self.block_stack = []
        self.para = []       # text của đoạn hiện tại (trước & sau link)
        self.href = None
        self.atext = []

    # -- helpers --
    def _flush_block(self, tag):
        txt = re.sub(r"\s+", " ", "".join(self.para)).strip(" .·:")
        if txt:
            if tag.startswith("h"):
                self.tokens.append(("HEAD", tag, txt))
            else:
                self.tokens.append(("TEXT", txt))
        self.para = []

    # -- HTMLParser events --
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
            return
        if self.skip:
            return
        if tag in BLOCK_TAGS:
            self.block_stack.append(tag)
        elif tag == "a":
            self.href = a.get("href", "")
            self.atext = []
        elif tag == "img":
            src = a.get("src") or ""
            if "googleusercontent.com/sitesv/" in src:
                self.tokens.append(("IMG", src))
        elif tag == "iframe":
            src = a.get("src") or ""
            m = re.search(r"youtube(?:-nocookie)?\.com/embed/([\w-]{6,})", src)
            if m:
                self.tokens.append(("VIDEO", f"https://www.youtube.com/watch?v={m.group(1)}"))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "a" and self.href is not None:
            anchor = re.sub(r"\s+", " ", "".join(self.atext)).strip()
            label = re.sub(r"\s+", " ", "".join(self.para)).strip(" .·")
            self.tokens.append(("LINK", self.href, anchor, label))
            self.para.append(" ")  # giữ khoảng cách sau link trong đoạn
            self.href = None
        elif tag in BLOCK_TAGS and self.block_stack:
            self.block_stack.pop()
            if not self.block_stack:
                self._flush_block(tag)

    def handle_data(self, data):
        if self.skip:
            return
        if self.href is not None:
            self.atext.append(data)
        elif self.block_stack:
            self.para.append(data)


# ------------------------------------------------------------ phân loại ----
UNIT_RE = re.compile(
    r"^(skills?\s+unit|g&v\s+unit|grammar\s+unit|unit\s*\d|đề\s*thi|mock\s*test|"
    r"review\s*\d|ôn\s*tập|starter\s*unit|kiểm\s*tra)", re.I)
LESSON_RE = re.compile(r"^lesson[\s\d+&-]*$|^(unit\s*\d+\s*[-–]\s*lesson)", re.I)

SKILLS = [
    ("từ vựng", "Từ vựng"), ("vocabulary", "Từ vựng"),
    ("ngữ pháp", "Ngữ pháp"), ("grammar", "Ngữ pháp"),
    ("đọc", "Đọc hiểu"), ("reading", "Đọc hiểu"),
    ("nghe", "Nghe"), ("listening", "Nghe"),
    ("viết", "Viết"), ("writing", "Viết"),
    ("nói", "Nói"), ("speaking", "Nói"), ("phát âm", "Phát âm"),
    ("tổng hợp", "Tổng hợp"), ("đề thi", "Đề thi"), ("thi thử", "Đề thi"),
    ("test", "Đề thi"), ("review", "Ôn tập"), ("ôn tập", "Ôn tập"),
]

# chủ điểm ngữ pháp thường gặp trong nhãn "luyện tập về ..."
GRAMMAR_TERMS = (
    "tense", "thì ", "pronoun", "noun", "adjective", "adverb", "preposition",
    "comparative", "superlative", "article", "quantifier", "present", "past",
    "future", "modal", "passive", "conditional", "tobe", "to be", "to do",
    "plural", "possessive", "countable", "verb", "simple", "continuous",
    "perfect", "there is", "there are", "some", "any", "much", "many",
    "enough", "too", "as... as", "as...as", "wh-", "question", "imperative",
    "gerund", "infinitive", "relative clause", "reported", "câu",
)

PROVIDERS = [
    ("wordwall.net", "Wordwall"), ("quizizz.com", "Quizizz"),
    ("liveworksheets.com", "Liveworksheets"), ("quizlet.com", "Quizlet"),
    ("forms.gle", "Google Forms"), ("docs.google.com/forms", "Google Forms"),
    ("youtube.com", "YouTube"), ("youtu.be", "YouTube"),
    ("drive.google.com", "Google Drive"), ("docs.google.com", "Google Docs"),
]

SKIP_LINK = re.compile(
    r"^(#|/|mailto:|javascript:)|sites\.google\.com|accounts\.google|"
    r"policies\.google|support\.google|workspace\.google|google\.com/(intl|forms/about)|"
    r"gstatic\.com|new\.express\.adobe")


def skill_of(label, anchor):
    s = (label + " " + anchor).lower()
    for kw, name in SKILLS:
        if kw in s:
            return name
    if any(t in s for t in GRAMMAR_TERMS):
        return "Ngữ pháp"
    return "Luyện tập"


def provider_of(url):
    for dom, name in PROVIDERS:
        if dom in url:
            return name
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    return m.group(1) if m else "?"


# -------------------------------------------------------- tải media local --
# URL ảnh Google Sites (lh3/sitesv) là link có token hết hạn sau ~1 giờ,
# nên phải tải NGAY trong lúc cào. File đặt tên theo hash nội dung để không
# trùng lặp giữa các lần cào. Thumbnail YouTube ổn định, đặt tên theo video id.
def download_media(kind, src):
    """Tải 1 media về assets/media/, trả về đường dẫn tương đối (None nếu lỗi)."""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if kind == "VIDEO":
            vid = re.search(r"[?&]v=([\w-]+)", src).group(1)
            path = MEDIA_DIR / f"vid_{vid}.jpg"
            if not path.exists():
                req = urllib.request.Request(
                    f"https://img.youtube.com/vi/{vid}/mqdefault.jpg", headers=UA)
                path.write_bytes(urllib.request.urlopen(req, timeout=30).read())
            return f"assets/media/{path.name}"
        # ảnh: xin bản 640px cho nhẹ (thay size param có sẵn nếu có)
        fetch = re.sub(r"=w\d+$", "=w640", src)
        if "=" not in fetch:
            fetch = fetch + "=w640"
        req = urllib.request.Request(fetch, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            ext = EXT.get(r.headers.get_content_type(), ".jpg")
        import hashlib
        path = MEDIA_DIR / f"img_{hashlib.sha1(body).hexdigest()[:16]}{ext}"
        if not path.exists():
            path.write_bytes(body)
        return f"assets/media/{path.name}"
    except Exception:
        return None


# --------------------------------------------------- giới thiệu từng lớp ---
def scrape_intro(url):
    """Lấy đoạn "Thông tin về ..." từ trang giới-thiệu của lớp."""
    gt_url = re.sub(r"/[^/]+$", "/giới-thiệu", url)
    gt_url = urllib.parse.quote(gt_url, safe=":/?&=%")
    req = urllib.request.Request(gt_url, headers=UA)
    raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    p = SiteParser()
    p.feed(raw)

    paras, started = [], False
    for tok in p.tokens:
        if tok[0] == "HEAD" and started:
            break
        if tok[0] != "TEXT":
            continue
        t = tok[-1]
        if not started and t.lower().startswith("thông tin về"):
            started = True
            paras.append(t)
        elif started:
            if t.upper().startswith("KHUNG THAM CHIẾU") or len(paras) > 8:
                break
            paras.append(t)
    return "\n".join(paras)


# ------------------------------------------------------------- scraping ----
def scrape_class(cur, class_id, name, url):
    url = urllib.parse.quote(url, safe=":/?&=%")
    req = urllib.request.Request(url, headers=UA)
    raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    p = SiteParser()
    p.feed(raw)

    # bỏ phần điều hướng: bắt đầu từ sau tiêu đề trang "TÀI LIỆU SỐ HÓA"
    tokens = p.tokens
    for i, t in enumerate(tokens):
        if t[0] in ("HEAD", "TEXT") and t[-1].upper().startswith("TÀI LIỆU SỐ HÓA"):
            tokens = tokens[i + 1:]
            break

    unit_id = lesson_id = None
    unit_pos = lesson_pos = task_pos = media_pos = 0
    desc_parts = []
    last_text = ""
    counts = {"units": 0, "lessons": 0, "tasks": 0, "media": 0, "media_err": 0}

    def flush_desc():
        if lesson_id and desc_parts:
            cur.execute("UPDATE lessons SET description = ? WHERE id = ?",
                        (" • ".join(desc_parts), lesson_id))
            desc_parts.clear()

    def new_unit(title):
        nonlocal unit_id, unit_pos, lesson_id, lesson_pos
        flush_desc()
        unit_pos += 1
        cur.execute("INSERT INTO units (class_id, name, position) VALUES (?,?,?)",
                    (class_id, title, unit_pos))
        unit_id = cur.lastrowid
        lesson_id = None
        lesson_pos = 0
        counts["units"] += 1

    def new_lesson(title):
        nonlocal lesson_id, lesson_pos
        flush_desc()
        if unit_id is None:
            new_unit("(Chung)")
        lesson_pos += 1
        cur.execute("INSERT INTO lessons (unit_id, name, description, position) VALUES (?,?,?,?)",
                    (unit_id, title, "", lesson_pos))
        lesson_id = cur.lastrowid
        counts["lessons"] += 1

    def ensure_lesson():
        if lesson_id is None:
            new_lesson("")

    for tok in tokens:
        kind = tok[0]
        if kind == "HEAD":
            _, tag, text = tok
            m = re.match(r"(unit\s*\d+)\s*[-–]\s*(lesson[^:]*):?\s*(.*)", text, re.I)
            if m:  # kiểu Cambridge: "UNIT 1 - LESSON 1+2: Hello!"
                title = f"{m.group(1).upper()}" + (f": {m.group(3)}" if m.group(3) else "")
                cur.execute("SELECT id, name FROM units WHERE class_id=? ORDER BY id DESC LIMIT 1",
                            (class_id,))
                row = cur.fetchone()
                if not row or row[1] != title:
                    new_unit(title)
                new_lesson(m.group(2).upper().strip())
            elif LESSON_RE.match(text):
                new_lesson(text)
            elif UNIT_RE.match(text) or unit_id is None:
                new_unit(text)
            else:
                # heading phụ trong unit (vd "KĨ NĂNG", "TỪ VỰNG & NGỮ PHÁP")
                # → là nhóm bài trong unit hiện tại, không tách unit mới
                new_lesson(text)
            last_text = ""
        elif kind == "TEXT":
            _, text = tok
            if UNIT_RE.match(text) and len(text) < 120:
                new_unit(text)
            elif LESSON_RE.match(text) and len(text) < 40:
                new_lesson(text)
            else:
                if lesson_id or unit_id:
                    ensure_lesson()
                    if len(text) > 2:
                        desc_parts.append(text)
                last_text = text
        elif kind == "LINK":
            _, href, anchor, label = tok
            if SKIP_LINK.search(href):
                continue
            ensure_lesson()
            lbl = label or last_text
            task_pos += 1
            cur.execute(
                "INSERT INTO tasks (lesson_id, label, skill, provider, url, position) "
                "VALUES (?,?,?,?,?,?)",
                (lesson_id, lbl, skill_of(lbl, anchor), provider_of(href), href, task_pos))
            counts["tasks"] += 1
        elif kind in ("IMG", "VIDEO"):
            if unit_id is None:
                continue  # logo/banner trước nội dung
            ensure_lesson()
            _, src = tok
            cur.execute("SELECT 1 FROM media WHERE lesson_id=? AND url=?", (lesson_id, src))
            if cur.fetchone():
                continue
            media_pos += 1
            local = download_media(kind, src)
            cur.execute(
                "INSERT INTO media (lesson_id, kind, url, position, local_path) "
                "VALUES (?,?,?,?,?)",
                (lesson_id, "image" if kind == "IMG" else "video", src, media_pos, local))
            counts["media"] += 1
            if local is None:
                counts["media_err"] += 1

    flush_desc()
    return counts


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS units (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER NOT NULL REFERENCES classes(id),
        name TEXT NOT NULL,
        position INTEGER
    );
    CREATE TABLE IF NOT EXISTS lessons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unit_id INTEGER NOT NULL REFERENCES units(id),
        name TEXT,
        description TEXT,
        position INTEGER
    );
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lesson_id INTEGER NOT NULL REFERENCES lessons(id),
        label TEXT,
        skill TEXT,
        provider TEXT,
        url TEXT NOT NULL,
        position INTEGER
    );
    CREATE TABLE IF NOT EXISTS media (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lesson_id INTEGER NOT NULL REFERENCES lessons(id),
        kind TEXT,
        url TEXT NOT NULL,
        position INTEGER,
        local_path TEXT
    );
    """)
    if "local_path" not in [c[1] for c in cur.execute("PRAGMA table_info(media)")]:
        cur.execute("ALTER TABLE media ADD COLUMN local_path TEXT")
    if "intro" not in [c[1] for c in cur.execute("PRAGMA table_info(classes)")]:
        cur.execute("ALTER TABLE classes ADD COLUMN intro TEXT")

    rows = cur.execute("SELECT id, name, url FROM classes ORDER BY id").fetchall()

    # chế độ chỉ cập nhật phần giới thiệu:  python3 scrape.py --intro
    if only == "--intro":
        for class_id, name, url in rows:
            try:
                intro = scrape_intro(url)
                cur.execute("UPDATE classes SET intro=? WHERE id=?", (intro, class_id))
                conn.commit()
                print(f"✓ {name:<20} intro={len(intro)} ký tự")
            except Exception as e:
                print(f"✗ {name:<20} LỖI intro: {e}")
            time.sleep(0.3)
        conn.close()
        return

    if only:
        rows = [r for r in rows if r[1] == only]
        if not rows:
            sys.exit(f"Không thấy lớp '{only}' trong data.db")

    for class_id, name, url in rows:
        # xóa dữ liệu cũ của lớp này rồi cào lại
        cur.execute("""DELETE FROM tasks WHERE lesson_id IN
            (SELECT l.id FROM lessons l JOIN units u ON l.unit_id=u.id WHERE u.class_id=?)""",
                    (class_id,))
        cur.execute("""DELETE FROM media WHERE lesson_id IN
            (SELECT l.id FROM lessons l JOIN units u ON l.unit_id=u.id WHERE u.class_id=?)""",
                    (class_id,))
        cur.execute("DELETE FROM lessons WHERE unit_id IN (SELECT id FROM units WHERE class_id=?)",
                    (class_id,))
        cur.execute("DELETE FROM units WHERE class_id=?", (class_id,))
        try:
            c = scrape_class(cur, class_id, name, url)
            try:
                cur.execute("UPDATE classes SET intro=? WHERE id=?",
                            (scrape_intro(url), class_id))
            except Exception:
                pass  # trang giới-thiệu lỗi không làm hỏng dữ liệu chính
            conn.commit()
            err = f" (⚠ {c['media_err']} media lỗi)" if c["media_err"] else ""
            print(f"✓ {name:<20} units={c['units']:<3} lessons={c['lessons']:<4} "
                  f"tasks={c['tasks']:<4} media={c['media']}{err}")
        except Exception as e:
            conn.rollback()
            print(f"✗ {name:<20} LỖI: {e}")
        time.sleep(0.3)

    # dọn file media mồ côi (chỉ khi cào toàn bộ)
    if not only and MEDIA_DIR.exists():
        used = {p for (p,) in cur.execute(
            "SELECT DISTINCT local_path FROM media WHERE local_path IS NOT NULL")}
        removed = 0
        for f in MEDIA_DIR.iterdir():
            if f"assets/media/{f.name}" not in used:
                f.unlink()
                removed += 1
        if removed:
            print(f"  đã dọn {removed} file media không còn dùng")

    # tổng kết
    for t in ("units", "lessons", "tasks", "media"):
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  tổng {t}: {n}")
    n_local = cur.execute(
        "SELECT COUNT(*) FROM media WHERE local_path IS NOT NULL").fetchone()[0]
    print(f"  media đã lưu local: {n_local}")
    conn.close()


if __name__ == "__main__":
    main()
