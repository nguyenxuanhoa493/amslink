#!/usr/bin/env python3
"""Sinh index.html (lộ trình học tập Amslink) từ data.db.

Trang gồm: sơ đồ lộ trình (bấm lớp → mở panel chi tiết unit/lesson/nhiệm vụ
ngay trong app) + dữ liệu nhúng JSON. Chạy lại sau khi sửa data.db:
    python3 build.py
"""
import base64
import html as H
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
DB = ROOT / "data.db"
OUT = ROOT / "index.html"
LOGO = ROOT / "assets" / "logo.png"

# ---------------------------------------------------------------- dữ liệu ---
conn = sqlite3.connect(DB)
cur = conn.cursor()

classes = {}   # name -> {id, url}
for cid, name, cat, url, intro in cur.execute(
        "SELECT id, name, category, url, COALESCE(intro,'') FROM classes"):
    classes[name] = {"id": cid, "cat": cat, "url": url, "intro": intro}

def rows(q, *a):
    return cur.execute(q, a).fetchall()

# --------------------------------------------- rút gọn nhãn nhiệm vụ -------
# Nhãn gốc kiểu "Các con luyện tập từ vựng về chủ đề nhà cửa" lặp đi lặp lại;
# rút phần chủ điểm ("nhà cửa") để in lên nút, tránh trùng với mô tả bài học.
_BOILER = re.compile(
    r"^(các con|các em|con|em|link|học|luyện tập|luyện tâp|luyện|làm|ôn tập|tập|"
    r"thêm|nâng cao|kiến thức|kĩ năng|kỹ năng|về|chủ đề|giữa|"
    r"từ vựng|ngữ pháp|đọc hiểu|tổng hợp|nghe|nói|viết|phát âm|"
    r"và|&|-|–|:|,|\.)\s*", re.I)


def topic_of(label):
    t = re.sub(r"\((THÊM|Luyện thêm)[^)]*\)?", " ", label, flags=re.I)
    t = re.sub(r"\b(bài tập|tại đây|ở đây|dưới đây|theo video|bên dưới)\b", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    prev = None
    while t != prev:
        prev = t
        t = _BOILER.sub("", t, count=1).strip()
    t = re.sub(r"\s*(thêm|nâng cao)\s*$", "", t, flags=re.I)
    t = t.strip(" :.,;-–&")
    return t[:-1].rstrip() if t.endswith("(") else t


def clean_desc(desc, labels):
    """Bỏ khỏi mô tả những câu đã thể hiện trên nút nhiệm vụ."""
    keys = [re.sub(r"\W+", " ", l).strip().lower() for l in labels if l]
    out = []
    for p in (s.strip() for s in desc.split(" • ")):
        pk = re.sub(r"\W+", " ", p).strip().lower()
        if len(pk) < 4:
            continue
        if re.match(r"^link luyện|^các con (học|luyện|làm)|^học thêm từ vựng", pk):
            continue
        n = min(len(pk), 28)
        if any(pk[:n] == k[:n] for k in keys if k):
            continue
        out.append(p)
    return " • ".join(out)


# JSON nhúng: {class_id: {n, cat, u, units:[[uname, [[lname, desc, tasks, imgs, vids],..]],..]}}
data = {}
for name, meta in classes.items():
    cid = meta["id"]
    units = []
    for uid, uname in rows("SELECT id, name FROM units WHERE class_id=? ORDER BY position", cid):
        lessons = []
        for lid, lname, desc in rows(
                "SELECT id, name, description FROM lessons WHERE unit_id=? ORDER BY position", uid):
            tasks = [[label, skill, prov, u, topic_of(label)]
                     for label, skill, prov, u in rows(
                         "SELECT label, skill, provider, url FROM tasks "
                         "WHERE lesson_id=? ORDER BY position", lid)]
            desc = clean_desc(desc or "", [t[0] for t in tasks])
            vids_n = rows("SELECT COUNT(*) FROM media WHERE lesson_id=? AND kind='video'",
                          lid)[0][0]
            if not vids_n:  # bỏ câu nhắc video khi bài không kèm video
                desc = " • ".join(p for p in desc.split(" • ")
                                  if p and not re.search(r"video", p, re.I))
            imgs = [u for (u,) in rows(
                "SELECT COALESCE(local_path, url) FROM media "
                "WHERE lesson_id=? AND kind='image' ORDER BY position", lid)]
            vids = [[u, t or ""] for (u, t) in rows(
                "SELECT url, local_path FROM media "
                "WHERE lesson_id=? AND kind='video' ORDER BY position", lid)]
            if lname or desc or tasks or imgs or vids:
                lessons.append([lname, desc, tasks, imgs, vids])
        units.append([uname, lessons])
    data[cid] = {"n": name, "cat": meta["cat"], "u": meta["url"],
                 "i": meta["intro"], "units": units}

n_tasks = rows("SELECT COUNT(*) FROM tasks")[0][0]
n_units = rows("SELECT COUNT(*) FROM units")[0][0]
conn.close()

missing = []


def ref(db_name):
    c = classes.get(db_name)
    if not c:
        missing.append(db_name)
    return c


def chip(db_name, label, cls, title=None):
    """Một ô trên sơ đồ: mở panel chi tiết nếu lớp có trong DB."""
    c = ref(db_name) if db_name else None
    if c:
        t = title or f"Xem tài liệu số hóa — {label}"
        return (f'<a class="chip live {cls}" href="#c/{c["id"]}" '
                f'title="{t}"><span>{label}</span></a>')
    return f'<div class="chip {cls}"><span>{label}</span></div>'


def dual(cls, label, parts):
    """Ô gộp 2 lớp (vd: 4 Điều kiện A1/A1+, 5 Cận Chuyên 1/2)."""
    inner = '<i class="sep">·</i>'.join(
        f'<a href="#c/{ref(n)["id"]}" title="Xem tài liệu số hóa — {t}">{s}</a>'
        for n, s, t in parts
    )
    return (f'<div class="chip live {cls} dual">'
            f'<span>{label}</span><span class="subs">{inner}</span></div>')


logo64 = base64.b64encode(LOGO.read_bytes()).decode()

place = lambda col, row, span=1: f'style="grid-column:{col};grid-row:{row}/span {span}"'

cells = []

# ---- đường kẻ chấm nền cho từng hàng trình độ (11 hàng) --------------------
for r in range(1, 12):
    cells.append(f'<div class="dotline" style="grid-row:{r}"></div>')

# ---- Cột A: 2–5 Điều kiện (chip xanh nhỏ) ----------------------------------
cells.append(f'<div class="stack" {place(1, 9)}>'
             + chip("5 ĐIỀU KIỆN", "5 Điều kiện", "dk sm")
             + dual("dk sm", "4 Điều kiện",
                    [("4 ĐIỀU KIỆN - A1", "A1", "4 Điều kiện A1"),
                     ("4 ĐIỀU KIỆN - A1+", "A1+", "4 Điều kiện A1+")])
             + '</div>')
cells.append('<div class="cell" ' + place(1, 10) + '>' + chip("3 ĐIỀU KIỆN", "3 Điều kiện", "dk sm") + '</div>')
cells.append('<div class="cell" ' + place(1, 11) + '>' + chip("2 ĐIỀU KIỆN", "2 Điều kiện", "dk sm") + '</div>')

# ---- Cột B: 2–5 Cận Chuyên (nâu) -------------------------------------------
cells.append('<div class="cell" ' + place(2, 7) + '>'
             + dual("cc brown", "5 Cận Chuyên",
                    [("5 CẬN CHUYÊN 1", "1", "5 Cận Chuyên 1"),
                     ("5 CẬN CHUYÊN 2", "2", "5 Cận Chuyên 2")])
             + '</div>')
cells.append('<div class="cell" ' + place(2, 8) + '>' + chip("4 CẬN CHUYÊN", "4 Cận Chuyên", "cc brown") + '</div>')
cells.append('<div class="cell" ' + place(2, 9) + '>' + chip("3 CẬN CHUYÊN", "3 Cận Chuyên", "cc brown") + '</div>')
cells.append('<div class="cell" ' + place(2, 10) + '>' + chip("2 CẬN CHUYÊN", "2 Cận Chuyên", "cc brown") + '</div>')

# ---- Cột C: 6–9 Điều kiện (xanh) -------------------------------------------
cells.append('<div class="cell" ' + place(3, 5) + '>' + chip("9 ĐIỀU KIỆN", "9 Điều kiện", "dk") + '</div>')
cells.append('<div class="cell" ' + place(3, 6) + '>' + chip("8 ĐIỀU KIỆN", "8 Điều kiện", "dk") + '</div>')
cells.append('<div class="cell" ' + place(3, 7) + '>' + chip("7 ĐIỀU KIỆN", "7 Điều kiện", "dk") + '</div>')
cells.append('<div class="cell" ' + place(3, 8) + '>' + chip("6 ĐIỀU KIỆN", "6 Điều kiện", "dk") + '</div>')

# ---- Cột D: 6–9 Cận Chuyên (cam) -------------------------------------------
cells.append('<div class="cell" ' + place(4, 3) + '>' + chip("9 CẬN CHUYÊN", "9 Cận Chuyên", "cc or1") + '</div>')
cells.append('<div class="cell" ' + place(4, 4) + '>' + chip("8 CẬN CHUYÊN", "8 Cận Chuyên", "cc or2") + '</div>')
cells.append('<div class="cell tall" ' + place(4, 5, 2) + '>' + chip("7 CẬN CHUYÊN", "7 Cận Chuyên", "cc or3 big") + '</div>')
cells.append('<div class="cell" ' + place(4, 7) + '>' + chip("6 CẬN CHUYÊN", "6 Cận Chuyên", "cc or4") + '</div>')

# ---- Cột 5: Đội tuyển Anh chuyên (không có dữ liệu) ------------------------
chuyen = [("9", 1, 1, "t1"), ("8", 2, 1, "t2"), ("7", 3, 2, "t3"),
          ("6", 5, 1, "t4"), ("5", 6, 2, "t5"), ("4", 8, 2, "t6")]
for n, row, span, tone in chuyen:
    cells.append(f'<div class="cell" {place(5, row, span)}>'
                 f'<div class="chip chuyen {tone}"><span><b>{n}</b><br>Chuyên</span></div></div>')

# ---- Cột 6: CEFR ------------------------------------------------------------
cefr = [("C1+/ C2", 1, "l1"), ("C1", 2, "l2"), ("B2+", 3, "l3"), ("B2", 4, "l3"),
        ("B1+", 5, "l4"), ("B1", 6, "l4"), ("A2+", 7, "l5"),
        ("A2", 8, "navy"), ("A1+", 9, "navy"), ("A1", 10, "navy"), ("PreA1", 11, "navy")]
for label, row, tone in cefr:
    cells.append(f'<div class="cell" {place(6, row)}><div class="chip cefr {tone}"><span>{label}</span></div></div>')

# ---- Cột 7: Giao tiếp Cambridge ---------------------------------------------
cells.append('<div class="cell tall" ' + place(7, 3, 2) + '>' + chip("FCE", "FCE", "camb fce") + '</div>')
cells.append('<div class="cell tall" ' + place(7, 5, 2) + '>' + chip("PET", "PET", "camb pet") + '</div>')
cells.append('<div class="cell tall" ' + place(7, 7, 2) + '>'
             + dual("camb navy", "",
                    [("FLYERS", "Flyers", "Flyers"), ("KET", "KET", "KET")])
             + '</div>')
cells.append('<div class="cell tall" ' + place(7, 9, 2) + '>' + chip("MOVERS", "Movers", "camb navy") + '</div>')
cells.append('<div class="cell" ' + place(7, 11) + '>' + chip("STARTERS", "Starters", "camb blue") + '</div>')
cells.append('<div class="cell" ' + place(7, 12) + '>'
             + '<div class="chip camb navy tiny"><span>Preschool/ Prestarters</span></div></div>')

# ---- Cột 8: IELTS ------------------------------------------------------------
ielts = [("8.5 - 9.0", 1, 1), ("7.0 - 8.0", 2, 1), ("5.5 - 6.5", 3, 2), ("4.0 - 5.0", 5, 2)]
for label, row, span in ielts:
    cells.append(f'<div class="cell" {place(8, row, span)}><div class="ielts">{label}</div></div>')

chart_cells = "\n      ".join(cells)

db_json = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

# ---------------------------------------------- nội dung "Lớp tự học 4.0" ---
FEATURES = [
    ("💻", "Công nghệ 4.0",
     "Tiếp cận ứng dụng học tập hiện đại và có tính tương tác cao."),
    ("🧭", "Lộ trình học ưu việt",
     "Lộ trình học tập có tính kế thừa, lặp lại và nâng cao dựa trên lộ trình học tập "
     "trên lớp học trực tiếp. Học sinh dễ dàng truy cập các bài học cũ để ôn tập và "
     "củng cố các kiến thức đã học."),
    ("📚", "Nội dung chuyên biệt",
     "Hệ thống các bài tập được thiết kế đa dạng, cá nhân hóa, và bám sát chương trình "
     "học trên lớp, giúp các con ôn tập kiến thức và rèn luyện kỹ năng làm bài thành thạo."),
    ("📈", "Dễ dàng theo dõi sự tiến bộ",
     "Bài làm được chấm và trả điểm tự động, giúp các em học sinh chủ động đối chiếu, "
     "xem lại kết quả và từ đó có kế hoạch ôn tập rõ ràng hơn."),
    ("📱", "Trải nghiệm mượt mà",
     "Truy cập đơn giản đa giao diện: smartphone, iPad, computer. Các thao tác được "
     "hướng dẫn cụ thể bởi đội ngũ chăm sóc khách hàng tại Amslink."),
]
features_html = "".join(
    f'<div class="feat"><div class="fic">{ic}</div>'
    f'<div><div class="fttl">{t}</div><p>{b}</p></div></div>'
    for ic, t, b in FEATURES)

INFO_HTML = f"""
<div class="dhead">
  <div class="flex items-start justify-between gap-3 flex-wrap">
    <div>
      <div class="cat">Amslink English Centre</div>
      <h2>Lớp tự học 4.0 là gì?</h2>
    </div>
    <div class="actions"><button onclick="closeDetail()">✕ Đóng</button></div>
  </div>
</div>
<div class="infowrap">
  <p>Là nền tảng tự học theo mô hình mới được Amslink xây dựng trong năm 2022 với sứ mệnh
  <b>“tạo ra trải nghiệm học tập khác biệt – học tập thông qua các công cụ mang tính tương
  tác cao”</b> – là giải pháp đột phá giúp các em học sinh tại Amslink thúc đẩy kỹ năng
  tự học trọn đời (Learner Autonomy) thông qua các hoạt động được số hóa như các trò chơi
  game về từ vựng, ngữ pháp, đọc hiểu được thiết kế sinh động trên các ứng dụng phổ biến
  như Quizizz, Quizlet, Wordwall,... giúp các em <b>“học mà chơi, chơi mà học”</b>,
  tự học nhưng không hề nhàm chán.</p>
  <p>Trong nhiều năm qua, Amslink đã không ngừng khẳng định vị trí và chất lượng trong
  lĩnh vực đào tạo tiếng Anh nói chung và đào tạo trực tuyến trong giai đoạn Covid nói
  riêng. Amslink tự hào vì đã nhận được sự tin tưởng của hơn <b>4000 học sinh</b> từ cấp 1
  đến cấp 2 và còn không ngừng gia tăng trong thời gian tới.</p>
  <h3>Điểm khác biệt của lớp tự học 4.0</h3>
  <div class="feats">{features_html}</div>
</div>
<div style="height:20px"></div>
"""
info_js = json.dumps(INFO_HTML, ensure_ascii=False).replace("</", "<\\/")

# ---------------------------------------------------------------- template ---
html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lộ trình học tập Amslink</title>
<link rel="icon" href="data:image/png;base64,{logo64}">
<script src="https://cdn.tailwindcss.com"></script>
<script>
tailwind.config = {{
  theme: {{ extend: {{
    colors: {{ navy: '#16256b', brand: '#e8262d', cream: '#fdeed3', lav: '#e9ebf6' }},
    fontFamily: {{ disp: ['"Baloo 2"', 'cursive'], body: ['"Be Vietnam Pro"', 'sans-serif'] }},
  }} }}
}};
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Baloo+2:wght@500;600;700;800&family=Be+Vietnam+Pro:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --navy:#16256b; --red:#e8262d; --or-red:#f05123; --orange:#f7941e;
    --amber:#f9a51a; --gold:#fbb040; --blue:#2d7dd2; --blue2:#3f6bb5;
    --brown:#a9805a; --brown2:#8a6844;
  }}
  body {{ background:
      radial-gradient(1100px 500px at 85% -10%, #fdeed3aa, transparent 60%),
      radial-gradient(900px 500px at -10% 110%, #d9defa, transparent 55%),
      #e9ebf6; }}

  .chart {{ display:grid; position:relative;
    grid-template-columns: 108px 128px 118px 132px 104px 96px 172px 104px;
    grid-auto-rows: 54px; gap: 8px 14px; min-width: 1060px; }}
  .hgrid {{ display:grid;
    grid-template-columns: 108px 128px 118px 132px 104px 96px 172px 104px;
    gap: 8px 14px; min-width: 1060px; }}

  .dotline {{ grid-column: 1 / -1; align-self:center; height:0;
    border-top: 2px dotted #9aa3c9; opacity:.55; }}
  .cell {{ display:flex; align-items:center; justify-content:stretch; z-index:1; }}
  .stack {{ display:flex; flex-direction:column; gap:5px; justify-content:center; z-index:1; }}

  .chip {{ position:relative; width:100%; display:flex; flex-direction:column;
    align-items:center; justify-content:center; text-align:center;
    font-family:'Baloo 2',cursive; font-weight:700; color:#fff; line-height:1.05;
    border-radius:10px; padding:6px 10px; min-height:38px;
    box-shadow: 0 2px 6px rgba(22,37,107,.14); }}
  .chip span {{ display:block; }}

  /* chip mũi tên (Điều kiện / Cận chuyên / CEFR) */
  .dk, .cc, .cefr {{ border-radius:7px;
    clip-path: polygon(0 0, calc(100% - 11px) 0, 100% 50%, calc(100% - 11px) 100%, 0 100%);
    box-shadow:none; padding-right:16px; }}
  .dk    {{ background: linear-gradient(135deg, #3f8fdd, var(--blue)); font-size:14.5px; min-height:40px; }}
  .dk.sm {{ font-size:12.5px; min-height:26px; padding-top:3px; padding-bottom:3px; }}
  .cc.brown {{ background: linear-gradient(135deg, var(--brown), var(--brown2)); font-size:14.5px; }}
  .cc.or1 {{ background: linear-gradient(135deg, #f68b1f, #ef6c1e); }}
  .cc.or2 {{ background: linear-gradient(135deg, #f79c1d, #f2801f); }}
  .cc.or3 {{ background: linear-gradient(160deg, #fbb040, #f07d1e); }}
  .cc.or4 {{ background: linear-gradient(135deg, #fbb040, #f79c1d); }}
  .cc {{ font-size:14.5px; }}
  .cc.big {{ height:100%; font-size:16px; clip-path:none; border-radius:10px;
    padding-right:10px; box-shadow:0 2px 6px rgba(22,37,107,.14); }}
  .tall {{ align-items:stretch; }}
  .tall .chip {{ height:100%; }}

  .chuyen {{ border-radius:14px; height:100%; font-size:13px; }}
  .chuyen b {{ font-size:22px; font-weight:800; }}
  .chuyen.t1 {{ background:linear-gradient(160deg,#f26522,#e8262d); }}
  .chuyen.t2 {{ background:linear-gradient(160deg,#f2701f,#ef4123); }}
  .chuyen.t3 {{ background:linear-gradient(160deg,#f68b1f,#f05123); }}
  .chuyen.t4 {{ background:linear-gradient(160deg,#f9a51a,#f68b1f); }}
  .chuyen.t5 {{ background:linear-gradient(160deg,#fbb040,#f79c1d); }}
  .chuyen.t6 {{ background:linear-gradient(160deg,#fcc059,#f9a51a); }}

  .cefr {{ font-size:13.5px; min-height:30px; padding-top:4px; padding-bottom:4px; }}
  .cefr.l1 {{ background:var(--red); }}
  .cefr.l2 {{ background:#ef4123; }}
  .cefr.l3 {{ background:var(--or-red); }}
  .cefr.l4 {{ background:var(--orange); }}
  .cefr.l5 {{ background:var(--gold); }}
  .cefr.navy {{ background:var(--navy); }}

  .camb {{ border-radius:8px; font-size:19px; letter-spacing:.5px; }}
  .camb.fce  {{ background:linear-gradient(160deg,#f26522,#ee3b24); font-size:26px; }}
  .camb.pet  {{ background:linear-gradient(160deg,#f9a51a,#f2801f); font-size:26px; }}
  .camb.navy {{ background:var(--navy); }}
  .camb.blue {{ background:var(--blue2); font-size:16px; }}
  .camb.tiny {{ font-size:12px; min-height:30px; padding:4px 8px; }}

  .ielts {{ width:100%; text-align:center; font-family:'Baloo 2',cursive;
    font-weight:800; font-size:17px; color:var(--red); }}

  /* ô gộp 2 lớp */
  .dual .subs {{ display:flex; gap:6px; justify-content:center; align-items:center;
    font-size:11px; margin-top:1px; }}
  .dual .subs a {{ color:#fff; background:rgba(255,255,255,.22); border-radius:5px;
    padding:0 7px; text-decoration:none; transition:background .15s; }}
  .dual .subs a:hover {{ background:rgba(255,255,255,.45); }}
  .dual .sep {{ color:rgba(255,255,255,.7); font-style:normal; }}
  .camb.dual {{ flex-direction:row; gap:0; }}
  .camb.dual .subs {{ font-size:19px; margin:0; gap:8px; }}
  .camb.dual .subs a {{ background:none; padding:2px 4px; border-radius:6px; }}
  .camb.dual .subs a:hover {{ background:rgba(255,255,255,.18); }}

  /* trạng thái bấm được */
  a.chip {{ text-decoration:none; cursor:pointer;
    transition: transform .18s cubic-bezier(.34,1.56,.64,1), box-shadow .18s, filter .18s; }}
  a.chip:hover {{ transform: translateY(-3px) scale(1.03); filter:brightness(1.07);
    z-index:5; }}
  a.chip:not(.dk):not(.cc):not(.cefr):hover {{ box-shadow:0 10px 22px rgba(22,37,107,.28); }}
  a.chip:active {{ transform: translateY(-1px) scale(1.0); }}
  div.chip.live {{ transition: transform .18s, filter .18s; }}
  div.chip.live:hover {{ transform: translateY(-2px); filter:brightness(1.06); }}

  /* header pills */
  .pill {{ font-family:'Baloo 2',cursive; font-weight:700; color:#fff; text-align:center;
    border-radius:14px; padding:10px 14px; line-height:1.15; font-size:14.5px;
    display:flex; align-items:center; justify-content:center;
    box-shadow:0 4px 12px rgba(232,38,45,.25); }}
  .pill.red {{ background:linear-gradient(160deg,#f0303a,var(--red)); }}
  .pill.cream {{ background:#fdeed3; color:var(--red);
    box-shadow:0 4px 12px rgba(22,37,107,.12); }}
  .pill.big {{ font-size:19px; letter-spacing:1px; }}
  .subpill {{ background:#fff; color:var(--navy); border-radius:9px; text-align:center;
    font-family:'Baloo 2',cursive; font-weight:700; font-size:12.5px; padding:4px 8px;
    box-shadow:0 2px 6px rgba(22,37,107,.10); }}
  .grouptitle {{ font-family:'Baloo 2',cursive; font-weight:800; color:var(--navy);
    letter-spacing:.5px; text-align:center; }}

  /* ------------------------------------------------ panel chi tiết ------ */
  #detail {{ position:fixed; inset:0; z-index:50; display:none; }}
  #detail.open {{ display:block; }}
  #detail .backdrop {{ position:absolute; inset:0; background:rgba(22,37,107,.45);
    backdrop-filter: blur(3px); }}
  #detail .panel {{ position:absolute; inset:0; margin:auto; overflow-y:auto;
    max-width: 920px; width:calc(100% - 24px); height:calc(100% - 40px);
    background:#f4f5fb; border-radius:22px; box-shadow:0 30px 80px rgba(10,18,60,.45);
    animation: pop .28s cubic-bezier(.34,1.4,.64,1); }}
  @keyframes pop {{ from {{ transform:translateY(26px) scale(.97); opacity:0 }}
                    to   {{ transform:none; opacity:1 }} }}

  .dhead {{ position:sticky; top:0; z-index:10; padding:20px 26px 14px;
    background:linear-gradient(160deg,#1d2f83,var(--navy));
    color:#fff; border-radius:22px 22px 0 0; }}
  .dhead h2 {{ font-family:'Baloo 2',cursive; font-weight:800; font-size:26px; line-height:1.1; }}
  .dhead .cat {{ font-size:12px; letter-spacing:.12em; opacity:.75; text-transform:uppercase; }}
  .dhead .stats {{ font-size:13px; opacity:.85; }}
  .dhead .actions {{ display:flex; gap:8px; }}
  .dhead .actions a, .dhead .actions button {{ font-size:12.5px; font-weight:600;
    background:rgba(255,255,255,.14); color:#fff; border:1px solid rgba(255,255,255,.25);
    border-radius:99px; padding:5px 13px; cursor:pointer; text-decoration:none;
    transition: background .15s; }}
  .dhead .actions a:hover, .dhead .actions button:hover {{ background:rgba(255,255,255,.3); }}

  .sfilter {{ display:flex; flex-wrap:wrap; gap:6px; padding:12px 26px 4px; }}
  .sfilter button {{ font-size:12px; font-weight:600; border-radius:99px;
    padding:4px 12px; background:#fff; color:var(--navy);
    box-shadow:0 1px 4px rgba(22,37,107,.12); cursor:pointer; transition:all .15s; }}
  .sfilter button.on {{ background:var(--navy); color:#fff; }}

  .unit {{ margin:12px 20px; background:#fff; border-radius:16px;
    box-shadow:0 2px 10px rgba(22,37,107,.08); overflow:hidden; }}
  .uhead {{ display:flex; align-items:center; gap:12px; padding:13px 18px;
    font-family:'Baloo 2',cursive; font-weight:700; color:var(--navy); font-size:17px;
    border-bottom:1px dashed #e3e6f5; }}
  .uhead .cnt {{ margin-left:auto; font-family:'Be Vietnam Pro'; font-size:11.5px;
    font-weight:600; color:#7a83ad; white-space:nowrap; }}

  .lesson {{ padding:16px 18px; border-bottom:1px dashed #e3e6f5;
    display:flex; gap:16px; align-items:flex-start; }}
  .lesson:last-child {{ border-bottom:none; }}
  .lmedia {{ flex:0 0 210px; display:flex; flex-direction:column; gap:8px; }}
  .lmedia a {{ display:block; border-radius:12px; overflow:hidden; position:relative;
    box-shadow:0 2px 8px rgba(22,37,107,.15); transition:transform .15s; }}
  .lmedia a:hover {{ transform:scale(1.03); }}
  .lmedia img {{ width:100%; display:block; }}
  .lmedia.wide {{ flex:1; flex-direction:row; flex-wrap:wrap; }}
  .lmedia.wide a {{ width:210px; }}
  .lmedia a.vid::after {{ content:'▶'; position:absolute; inset:0; display:flex;
    align-items:center; justify-content:center; color:#fff; font-size:26px;
    background:rgba(0,0,0,.28); text-shadow:0 1px 6px rgba(0,0,0,.6); }}
  .lbody {{ flex:1; min-width:0; }}
  @media (max-width: 640px) {{
    .lesson {{ flex-direction:column; }}
    .lmedia {{ flex-basis:auto; width:100%; flex-direction:row; flex-wrap:wrap; }}
    .lmedia a {{ width:calc(50% - 4px); }}
  }}
  .lesson h4 {{ font-family:'Baloo 2',cursive; font-weight:700; color:var(--or-red);
    font-size:15.5px; margin-bottom:4px; }}
  .lesson .desc {{ font-size:13.5px; color:#4d5578; line-height:1.55; margin-bottom:10px; }}
  .tasks {{ display:flex; flex-wrap:wrap; gap:10px; }}
  .task {{ display:inline-flex; align-items:center; gap:10px; font-size:14.5px;
    font-weight:700; color:var(--navy); background:#f0f2fb; border:2px solid #dfe3f6;
    border-radius:14px; padding:10px 18px 10px 10px; text-decoration:none;
    transition: all .15s; max-width:100%; }}
  .task:hover {{ background:var(--navy); color:#fff; border-color:var(--navy);
    transform:translateY(-2px); box-shadow:0 8px 18px rgba(22,37,107,.25); }}
  .task .sk {{ font-size:12.5px; font-weight:700; color:#fff; border-radius:10px;
    padding:5px 12px; white-space:nowrap; background:#7a83ad; }}
  .task .tp {{ max-width:300px; overflow:hidden; text-overflow:ellipsis;
    white-space:nowrap; }}
  .task .pv {{ opacity:.65; font-size:13px; white-space:nowrap; }}
  .task:hover .pv {{ opacity:.85; }}
  .task.done {{ background:#e7f6ec; border-color:#b6e3c4; color:#1c7a43; }}
  .task.done::after {{ content:"✓"; font-size:14px; font-weight:800; color:#1c9e52;
    margin-left:2px; }}
  .task.done:hover {{ background:#1c9e52; color:#fff; border-color:#1c9e52;
    box-shadow:0 8px 18px rgba(28,158,82,.28); }}
  .task.done:hover::after {{ color:#fff; }}
  .sk.s-tuvung {{ background:var(--orange); }}
  .sk.s-nguphap {{ background:var(--red); }}
  .sk.s-dochieu {{ background:var(--blue2); }}
  .sk.s-nghe {{ background:var(--blue); }}
  .sk.s-viet {{ background:#7b5cd6; }}
  .sk.s-noi, .sk.s-phatam {{ background:#d6499a; }}
  .sk.s-tonghop {{ background:var(--gold); color:#5c3a00; }}
  .sk.s-dethi {{ background:#b3131a; }}
  .sk.s-ontap {{ background:var(--brown); }}
  .sk.s-luyentap {{ background:#7a83ad; }}

  .empty {{ text-align:center; color:#7a83ad; padding:60px 20px; font-size:14px; }}

  /* giới thiệu lớp + trang thông tin chung */
  .introbox {{ margin:14px 20px 2px; background:#fff; border-radius:16px;
    padding:14px 18px; box-shadow:0 2px 10px rgba(22,37,107,.08);
    border-left:4px solid var(--gold); }}
  .introbox .ittl {{ font-family:'Baloo 2',cursive; font-weight:700;
    color:var(--navy); font-size:15.5px; margin-bottom:4px; }}
  .introbox p {{ font-size:13.5px; color:#4d5578; line-height:1.6; margin:4px 0; }}

  .infowrap {{ padding:18px 26px; }}
  .infowrap p {{ font-size:14px; color:#3c4468; line-height:1.7; margin-bottom:12px; }}
  .infowrap h3 {{ font-family:'Baloo 2',cursive; font-weight:800; color:var(--red);
    font-size:19px; margin:18px 0 12px; text-transform:uppercase; letter-spacing:.03em; }}
  .feats {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
  @media (max-width:640px) {{ .feats {{ grid-template-columns:1fr; }} }}
  .feat {{ display:flex; gap:12px; background:#fff; border-radius:14px; padding:14px;
    box-shadow:0 2px 10px rgba(22,37,107,.08); align-items:flex-start; }}
  .feat .fic {{ flex:0 0 40px; height:40px; border-radius:12px; background:#fdeed3;
    display:flex; align-items:center; justify-content:center; font-size:20px; }}
  .feat .fttl {{ font-family:'Baloo 2',cursive; font-weight:700; color:var(--navy);
    font-size:14.5px; margin-bottom:2px; }}
  .feat p {{ font-size:12.5px; margin:0; line-height:1.55; }}

  .infobtn {{ display:inline-flex; align-items:center; gap:6px; margin-top:8px;
    font-size:13px; font-weight:600; color:var(--navy); background:#fff;
    border-radius:99px; padding:5px 14px; text-decoration:none;
    box-shadow:0 2px 8px rgba(22,37,107,.12); transition:all .15s; }}
  .infobtn:hover {{ background:var(--navy); color:#fff; transform:translateY(-1px); }}
  .infobtn .ic {{ display:inline-flex; align-items:center; justify-content:center;
    width:17px; height:17px; border-radius:50%; background:var(--red); color:#fff;
    font-size:11px; font-weight:800; font-family:Georgia,serif; }}
  .infobtn:hover .ic {{ background:#fff; color:var(--red); }}
  ::selection {{ background:#e8262d; color:#fff; }}
</style>
</head>
<body class="font-body text-navy min-h-screen">

<header class="max-w-[1220px] mx-auto px-6 pt-8 pb-2 flex items-center gap-5">
  <img src="data:image/png;base64,{logo64}" alt="Amslink" class="h-16 w-auto drop-shadow-sm select-none" draggable="false">
  <div>
    <h1 class="font-disp font-extrabold text-3xl md:text-4xl leading-tight text-navy">
      Lộ trình học tập <span class="text-brand">Amslink</span>
    </h1>
    <p class="text-sm md:text-base text-navy/70 mt-0.5">
      Bấm vào lớp học trên sơ đồ để xem <b>tài liệu số hóa</b>: unit, bài học và nhiệm vụ luyện tập
    </p>
    <a class="infobtn" href="#info"><span class="ic">i</span> Lớp tự học 4.0 là gì?</a>
  </div>
</header>

<main class="max-w-[1220px] mx-auto px-6 pb-10">
  <div class="bg-white/55 backdrop-blur rounded-3xl shadow-xl shadow-navy/10 ring-1 ring-white/60 p-5 md:p-7 mt-4">
    <div class="overflow-x-auto pb-2 -mx-1 px-1">

      <!-- tiêu đề nhóm -->
      <div class="hgrid mb-2">
        <div class="grouptitle text-lg md:text-xl" style="grid-column:1/7">TIẾNG ANH NỀN TẢNG</div>
        <div class="grouptitle text-base md:text-lg" style="grid-column:7/9">TIẾNG ANH THỰC HÀNH</div>
      </div>

      <!-- hàng tiêu đề cột -->
      <div class="hgrid mb-1">
        <div class="pill red" style="grid-column:1/5">KHÓA NGỮ PHÁP<br>TỪ VỰNG CHUYÊN SÂU</div>
        <div class="pill red" style="grid-column:5">ĐỘI TUYỂN<br>ANH CHUYÊN</div>
        <div class="pill red big" style="grid-column:6">CEFR</div>
        <div class="pill cream" style="grid-column:7">KHÓA TIẾNG ANH<br>GIAO TIẾP TOÀN DIỆN</div>
        <div class="pill red big" style="grid-column:8">IELTS</div>
      </div>
      <div class="hgrid mb-4">
        <div class="subpill" style="grid-column:1/3">TIỂU HỌC</div>
        <div class="subpill" style="grid-column:3/5">THCS</div>
      </div>

      <!-- sơ đồ -->
      <div class="chart">
      {chart_cells}
      </div>
    </div>
  </div>

  <footer class="text-center text-xs text-navy/50 mt-5">
    Amslink English Centre · {len(classes)} lớp · {n_units} units · {n_tasks} nhiệm vụ ·
    Dữ liệu từ <code>data.db</code> · Cập nhật {date.today():%d/%m/%Y}
  </footer>
</main>

<!-- panel chi tiết lớp -->
<div id="detail" aria-hidden="true">
  <div class="backdrop" onclick="closeDetail()"></div>
  <div class="panel" id="panel"></div>
</div>

<script type="application/json" id="db">{db_json}</script>
<script>
const DB = JSON.parse(document.getElementById('db').textContent);
const INFO_HTML = {info_js};
const detail = document.getElementById('detail');
const panel = document.getElementById('panel');
let curId = null, curSkill = '';

const esc = s => String(s).replace(/[&<>"']/g,
  c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const skillClass = s => 's-' + s.normalize('NFD').replace(/[\\u0300-\\u036f]/g,'')
  .toLowerCase().replace(/đ/g,'d').replace(/[^a-z]/g,'');
const ytThumb = u => {{
  const m = u.match(/[?&]v=([\\w-]+)/);
  return m ? `https://img.youtube.com/vi/${{m[1]}}/mqdefault.jpg` : '';
}};
const imgSized = u => (u.startsWith('http') && !u.includes('=')) ? u + '=w400' : u;

const DONE_KEY = 'amslink_done_tasks';
let doneTasks;
try {{ doneTasks = new Set(JSON.parse(localStorage.getItem(DONE_KEY) || '[]')); }}
catch (e) {{ doneTasks = new Set(); }}
const saveDone = () => {{
  try {{ localStorage.setItem(DONE_KEY, JSON.stringify([...doneTasks])); }} catch (e) {{}}
}};
const markDone = url => {{
  if (doneTasks.has(url)) return;
  doneTasks.add(url);
  saveDone();
}};

function render(id) {{
  const c = DB[id];
  if (!c) return;
  curId = id;
  let nL = 0, nT = 0, skills = new Set();
  c.units.forEach(([_, ls]) => ls.forEach(l => {{
    nL++; l[2].forEach(t => {{ nT++; skills.add(t[1]); }});
  }}));

  let h = `
  <div class="dhead">
    <div class="flex items-start justify-between gap-3 flex-wrap">
      <div>
        <div class="cat">${{esc(c.cat)}}</div>
        <h2>${{esc(c.n)}}</h2>
        <div class="stats">${{c.units.length}} units · ${{nL}} bài học · ${{nT}} nhiệm vụ</div>
      </div>
      <div class="actions">
        <button onclick="closeDetail()">✕ Đóng</button>
      </div>
    </div>
  </div>`;

  if (c.i) {{
    const [ittl, ...ips] = c.i.split('\\n');
    h += `<div class="introbox"><div class="ittl">📖 ${{esc(ittl)}}</div>` +
         ips.map(p => `<p>${{esc(p)}}</p>`).join('') + '</div>';
  }}

  if (skills.size > 1) {{
    h += '<div class="sfilter"><button class="' + (curSkill?'':'on') +
         '" onclick="setSkill(\\'\\')">Tất cả</button>';
    [...skills].sort().forEach(s => {{
      h += `<button class="${{curSkill===s?'on':''}}" onclick="setSkill('${{esc(s)}}')">${{esc(s)}}</button>`;
    }});
    h += '</div>';
  }}

  let shown = 0;
  c.units.forEach(([uname, lessons], ui) => {{
    let body = '', unitTasks = 0;
    lessons.forEach(([lname, desc, tasks, imgs, vids]) => {{
      const ts = curSkill ? tasks.filter(t => t[1] === curSkill) : tasks;
      if (curSkill && !ts.length) return;
      unitTasks += ts.length;

      let media = '';
      if (!curSkill && (imgs.length || vids.length)) {{
        imgs.slice(0, 6).forEach(u => {{
          media += `<a href="${{esc(u)}}" target="_blank" rel="noopener">
            <img loading="lazy" src="${{esc(imgSized(u))}}" alt=""></a>`;
        }});
        vids.forEach(([u, local]) => {{
          const th = local || ytThumb(u);
          if (th) media += `<a class="vid" href="${{esc(u)}}" target="_blank" rel="noopener">
            <img loading="lazy" src="${{esc(th)}}" alt="video"></a>`;
        }});
      }}

      let inner = '';
      if (lname) inner += `<h4>${{esc(lname)}}</h4>`;
      if (desc && !curSkill) inner += `<div class="desc">${{esc(desc)}}</div>`;
      if (ts.length) {{
        inner += '<div class="tasks">';
        ts.forEach(([label, skill, prov, url, topic]) => {{
          inner += `<a class="task${{doneTasks.has(url) ? ' done' : ''}}" href="${{esc(url)}}"
            target="_blank" rel="noopener" data-url="${{esc(url)}}"
            title="${{esc(label || skill)}}">
            <span class="sk ${{skillClass(skill)}}">${{esc(skill)}}</span>` +
            (topic ? `<span class="tp">${{esc(topic)}}</span>` : '') +
            `<span class="pv">${{esc(prov)}}</span></a>`;
        }});
        inner += '</div>';
      }}

      if (media && inner)
        body += `<div class="lesson"><div class="lmedia">${{media}}</div>
                 <div class="lbody">${{inner}}</div></div>`;
      else if (media)
        body += `<div class="lesson"><div class="lmedia wide">${{media}}</div></div>`;
      else
        body += `<div class="lesson"><div class="lbody">${{inner}}</div></div>`;
    }});
    if (!body) return;
    shown++;
    h += `<div class="unit"><div class="uhead">${{esc(uname)}}
      <span class="cnt">${{unitTasks}} nhiệm vụ</span></div>${{body}}</div>`;
  }});
  if (!shown) h += '<div class="empty">Không có nhiệm vụ nào cho bộ lọc này.</div>';
  h += '<div style="height:20px"></div>';

  panel.innerHTML = h;
  panel.scrollTop = 0;
  detail.classList.add('open');
  detail.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
}}

panel.addEventListener('click', e => {{
  const a = e.target.closest('a.task');
  if (!a) return;
  const url = a.getAttribute('data-url');
  if (url) {{ markDone(url); a.classList.add('done'); }}
}});

function setSkill(s) {{ curSkill = s; render(curId); }}

function closeDetail() {{
  if (location.hash) history.pushState('', '', location.pathname);
  hide();
}}
function hide() {{
  detail.classList.remove('open');
  detail.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
  curId = null; curSkill = '';
}}

function showInfo() {{
  panel.innerHTML = INFO_HTML;
  panel.scrollTop = 0;
  detail.classList.add('open');
  detail.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
}}

function route() {{
  const m = location.hash.match(/^#c\\/(\\d+)$/);
  if (m && DB[m[1]]) {{ curSkill = ''; render(m[1]); }}
  else if (location.hash === '#info') showInfo();
  else hide();
}}
window.addEventListener('hashchange', route);
document.addEventListener('keydown', e => {{
  if (e.key === 'Escape' && detail.classList.contains('open')) closeDetail();
}});
route();
</script>

</body>
</html>
"""

OUT.write_text(html, encoding="utf-8")
size_kb = len(html.encode()) // 1024
print(f"✓ Đã sinh {OUT.name} ({size_kb} KB, {len(classes)} lớp, {n_units} units, {n_tasks} nhiệm vụ)")
if missing:
    print("⚠ Thiếu lớp trong data.db:", ", ".join(missing), file=sys.stderr)
