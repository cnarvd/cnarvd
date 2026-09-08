import csv
import io
import re
import time
from dataclasses import dataclass
from typing import List

import altair as alt
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Holdco Business Review", page_icon="📊", layout="wide", initial_sidebar_state="collapsed")

# Immutable Vercel deployment that still owns the working Google-Sheet feed.
API_URL = "https://holdco-business-review-live-30hp592wv.vercel.app/api/sheet"
SECTIONS = ["Executive Summary", "Product", "Operation", "Sales", "Marketing SEO", "Marketing Performance"]
TAB_TO_SECTION = {
    "Exc. Summary": "Executive Summary",
    "Product": "Product",
    "Operation": "Operation",
    "Sales": "Sales",
    "Marketing Seo": "Marketing SEO",
    "Marketing Performance": "Marketing Performance",
}

st.markdown("""
<style>
html,body,[data-testid='stAppViewContainer'],.stApp{background:#06111f!important}
header[data-testid='stHeader']{background:transparent!important}
[data-testid='stToolbar']{visibility:hidden}.block-container{max-width:1500px;padding-top:.7rem;padding-bottom:1rem}
h1,h2,h3,p,span,div,label{color:#edf5ff}.br-title{font-size:1.08rem;font-weight:800}.br-sub{color:#8fb0d0;font-size:.78rem}
.slide{background:linear-gradient(180deg,#fff,#f7f9fc);color:#14243a;border-radius:18px;min-height:66vh;padding:25px 30px;box-shadow:0 24px 80px rgba(0,0,0,.27)}
.slide-title{font-size:1.55rem;font-weight:850;color:#14243a!important}.slide-meta{font-size:.78rem;color:#64778d!important;margin:4px 0 16px}
.kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.kpi{background:#fff;border:1px solid #dce6ef;border-radius:14px;padding:14px 16px;box-shadow:0 4px 18px rgba(21,49,79,.06)}
.kpi-label{font-size:.76rem;color:#60748a!important}.kpi-value{font-size:1.3rem;font-weight:800;color:#14243a!important;margin-top:4px}.foot{color:#7890aa;font-size:.72rem;margin-top:8px}.stButton button{border-radius:10px!important}
</style>
""", unsafe_allow_html=True)


def t(x):
    return "" if x is None else str(x).strip()


def norm(x):
    return re.sub(r"[\s._–—-]+", " ", t(x).lower()).strip()


def number(v):
    s = t(v).replace(",", "").replace("٬", "").replace("%", "").replace("٪", "").replace("−", "-")
    if not s or s in {"-", "—", "#DIV/0!", "#REF!", "#N/A"}:
        return None
    m = 1.0
    if s.upper().endswith("B"):
        m, s = 1_000_000_000.0, s[:-1]
    elif s.upper().endswith("M"):
        m, s = 1_000_000.0, s[:-1]
    try:
        return float(s) * m
    except Exception:
        return None


def pct_metric(label):
    n = norm(label)
    return any(k in n for k in ["conversion", "retention", "progress", "variance", "pace gap", "gap", "csat", "payment rate", "margin", "rate %"])


def money_metric(label):
    n = norm(label)
    return any(k in n for k in ["revenue", "gmv", "nmv", "gbv", "irt", "budget", "sales"]) and "order" not in n


def fmt(label, v):
    s = t(v)
    if not s or s in {"-", "—", "#DIV/0!", "#REF!", "#N/A"}:
        return s
    n = number(s)
    if pct_metric(label):
        if "%" in s or "٪" in s:
            base = number(s)
            return f"{base:.2f}%" if base is not None else s
        if n is not None:
            return f"{(n * 100 if abs(n) <= 1.5 else n):.2f}%"
    if money_metric(label) and n is not None:
        return f"{n / 1_000_000_000:.2f} BT" if abs(n) >= 100_000_000 else f"{n:,.0f}"
    if n is not None:
        return f"{int(round(n)):,}" if abs(n - round(n)) < 1e-9 else f"{n:,.2f}"
    return s


@st.cache_data(ttl=45, show_spinner=False)
def load_payload():
    r = requests.get(API_URL, timeout=25, headers={"Cache-Control": "no-cache", "User-Agent": "Holdco-BR/2"})
    r.raise_for_status()
    data = r.json()
    if not data.get("accessible"):
        raise RuntimeError("Sheet feed is not accessible")
    return data


def grid(csv_text):
    if not csv_text:
        return pd.DataFrame()
    rows = list(csv.reader(io.StringIO(csv_text)))
    width = max((len(r) for r in rows), default=0)
    return pd.DataFrame([r + [""] * (width - len(r)) for r in rows])


@dataclass
class Slide:
    sid: str
    section: str
    tab: str
    title: str
    period: str
    headers: List[str]
    rows: List[List[str]]
    kind: str = "table"


def title_above(df, r, c0):
    keys = ["report", "monthly", "revenue", "commercial", "okr", "performance", "trend", "sales", "non-appt", "call center", "support", "doctor", "physician", "marketing", "seo", "evisit", "appointment", "وضعیت", "اقدامات", "درآمد", "عملکرد"]
    best = ""
    for rr in range(max(0, r - 10), r):
        vals = [t(x) for x in df.iloc[rr].tolist() if t(x)]
        joined = " | ".join(vals)
        if any(k in joined.lower() for k in keys):
            best = joined[:140]
    return best


def generic_tables(tab, df):
    if df.empty:
        return []
    out, used = [], set()
    for r in range(len(df)):
        vals = [norm(x) for x in df.iloc[r].tolist()]
        non = [x for x in vals if x]
        if len(non) < 2:
            continue
        looks_header = any(x in {"metric", "items", "period", "date", "order", "product"} or any(k in x for k in ["metric", "items", "period", "order", "projection", "actual"]) for x in non)
        if not looks_header or r in used:
            continue
        raw = [t(x) for x in df.iloc[r].tolist()]
        cols = [i for i, x in enumerate(raw) if x]
        if not cols:
            continue
        c0 = min(cols)
        end = min(df.shape[1], c0 + min(8, max(3, max(cols) - c0 + 1)))
        rows, rr, blanks = [], r + 1, 0
        while rr < len(df) and rr < r + 18:
            row = [t(x) for x in df.iloc[rr, c0:end].tolist()]
            if not any(row):
                blanks += 1
                if blanks >= 2:
                    break
            else:
                blanks = 0
                rows.append(row)
            rr += 1
        if len(rows) < 2:
            continue
        headers = [t(x) or f"Col {i+1}" for i, x in enumerate(df.iloc[r, c0:end].tolist())]
        title = title_above(df, r, c0) or f"{tab} — Table {len(out)+1}"
        pm = re.search(r"\b(Q[1-4]|Tir|Mordad|Shahrivar|Khordad|Ordibehesht|Farvardin|Mehr|Aban|Azar|Dey|Bahman|Esfand)\b", title, re.I)
        out.append(Slide(f"{tab}:{r}:{c0}", TAB_TO_SECTION.get(tab, tab), tab, title, pm.group(1) if pm else "", headers, rows))
        used.update(range(r, rr))
    return out


def seo_tables(tab, df):
    out = []
    if df.empty:
        return out
    for r in range(len(df)):
        first = t(df.iloc[r, 0])
        if re.search(r"commercial\s+(okr|tir|mordad|shahrivar|mehr|aban|azar|q[1-4])", first, re.I):
            headers = [t(x) or f"Col {i+1}" for i, x in enumerate(df.iloc[r].tolist()[:6])]
            rows = [[t(x) for x in df.iloc[rr].tolist()[:6]] for rr in range(r + 1, min(r + 5, len(df))) if any(t(x) for x in df.iloc[rr].tolist()[:6])]
            out.append(Slide(f"{tab}:{r}", "Marketing SEO", tab, first, "", headers, rows))
    for r in range(len(df)):
        vals = [t(x) for x in df.iloc[r].tolist()[:4]]
        if "1404" in vals and "1405" in vals:
            rows = []
            for rr in range(r + 1, len(df)):
                row = [t(x) for x in df.iloc[rr].tolist()[:4]]
                if not any(row):
                    break
                rows.append(row)
            if rows:
                out.append(Slide(f"{tab}:weekly:{r}", "Marketing SEO", tab, "SEO Weekly Click Trend", "", ["Period", "1404", "1405", "Projection"], rows, "line"))
            break
    return out


def build(payload):
    slides = []
    for item in payload.get("tabs", []):
        if not item.get("ok"):
            continue
        tab = item.get("tab", "")
        df = grid(item.get("csv", ""))
        slides.extend(seo_tables(tab, df) if tab == "Marketing Seo" else generic_tables(tab, df))
    found = {x.tab for x in slides}
    for item in payload.get("tabs", []):
        tab = item.get("tab", "")
        if tab in found or not item.get("ok"):
            continue
        df = grid(item.get("csv", ""))
        if not df.empty:
            width = min(8, df.shape[1])
            slides.append(Slide(f"{tab}:overview", TAB_TO_SECTION.get(tab, tab), tab, f"{tab} Overview", "", [f"Col {i+1}" for i in range(width)], [[t(x) for x in row[:width]] for row in df.head(12).values.tolist()]))
    return slides


def frame(slide):
    width = max(len(slide.headers), max((len(r) for r in slide.rows), default=0))
    headers = (slide.headers + [f"Col {i+1}" for i in range(len(slide.headers), width)])[:width]
    data = []
    for row in slide.rows:
        row = (row + [""] * width)[:width]
        label = row[0] if row else ""
        data.append([fmt(label, v) for v in row])
    return pd.DataFrame(data, columns=headers)


def chart_df(slide):
    rows = []
    for r in slide.rows:
        if len(r) > 1 and t(r[0]) and number(r[1]) is not None:
            rows.append({"x": t(r[0]), "y": number(r[1])})
    return pd.DataFrame(rows)


for key, default in [("slide", 0), ("hidden", set()), ("studio", False), ("visual", {})]:
    st.session_state.setdefault(key, default)

# Soft page reload gives the sheet feed a fresh read while preserving URL/session behavior.
st.components.v1.html("<script>setTimeout(()=>window.parent.location.reload(),60000)</script>", height=0)

try:
    payload = load_payload()
    online = True
except Exception as exc:
    payload, online = {"tabs": []}, False
    st.error(f"Live Sheet unavailable: {exc}")

all_slides = build(payload)
visible = [x for x in all_slides if x.sid not in st.session_state.hidden]
if not visible:
    st.error("No live presentation tables found.")
    st.stop()

st.session_state.slide = min(st.session_state.slide, len(visible) - 1)
slide = visible[st.session_state.slide]

h1, h2, h3 = st.columns([2, 6, 2])
with h1:
    st.markdown('<div class="br-title">Business Review</div><div class="br-sub">Holdco · Live Presentation</div>', unsafe_allow_html=True)
with h2:
    available = [s for s in SECTIONS if any(x.section == s for x in visible)]
    chosen = st.segmented_control("Section", available, default=slide.section if slide.section in available else available[0], label_visibility="collapsed")
    if chosen and chosen != slide.section:
        st.session_state.slide = next(i for i, x in enumerate(visible) if x.section == chosen)
        st.rerun()
with h3:
    st.markdown(f"<div style='font-size:.8rem;color:#8fb0d0;text-align:left'>{'🟢 Live Sheet' if online else '🔴 Offline'}</div>", unsafe_allow_html=True)

c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 6])
with c1:
    if st.button("◀", use_container_width=True, disabled=st.session_state.slide == 0):
        st.session_state.slide -= 1; st.rerun()
with c2:
    if st.button("▶", use_container_width=True, disabled=st.session_state.slide >= len(visible) - 1):
        st.session_state.slide += 1; st.rerun()
with c3:
    if st.button("✏️ Edit", use_container_width=True):
        st.session_state.studio = not st.session_state.studio
with c4:
    if st.button("🗑 Hide", use_container_width=True):
        st.session_state.hidden.add(slide.sid)
        st.session_state.slide = max(0, min(st.session_state.slide, len(visible) - 2))
        st.rerun()
with c5:
    st.markdown(f"<div style='padding-top:8px;color:#7890aa;font-size:.78rem'>{st.session_state.slide+1} / {len(visible)} · {slide.section}</div>", unsafe_allow_html=True)

if st.session_state.studio:
    with st.expander("Presentation Studio", expanded=True):
        a, b, c, d = st.columns([2, 3, 2, 2])
        tabs = sorted({x.tab for x in all_slides})
        with a:
            selected_tab = st.selectbox("Tab", tabs, index=tabs.index(slide.tab) if slide.tab in tabs else 0)
        candidates = [x for x in all_slides if x.tab == selected_tab]
        titles = [x.title for x in candidates]
        with b:
            idx = candidates.index(slide) if slide in candidates else 0
            selected_title = st.selectbox("Table / Item", titles, index=idx)
        selected = candidates[titles.index(selected_title)]
        opts = ["Auto", "Table", "KPI Cards", "Bar Chart", "Line Chart"]
        current_visual = st.session_state.visual.get(selected.sid, "Auto")
        with c:
            visual = st.selectbox("Visual", opts, index=opts.index(current_visual))
        with d:
            st.write("")
            if st.button("Present this table", use_container_width=True):
                st.session_state.visual[selected.sid] = visual
                st.session_state.hidden.discard(selected.sid)
                new_visible = [x for x in all_slides if x.sid not in st.session_state.hidden]
                st.session_state.slide = next(i for i, x in enumerate(new_visible) if x.sid == selected.sid)
                st.rerun()
        if st.session_state.hidden and st.button(f"Restore hidden slides ({len(st.session_state.hidden)})"):
            st.session_state.hidden = set(); st.rerun()

visual = st.session_state.visual.get(slide.sid, "Auto")
if visual == "Auto":
    visual = "Line Chart" if slide.kind == "line" else "Table"

st.markdown('<div class="slide">', unsafe_allow_html=True)
st.markdown(f'<div class="slide-title">{slide.title}</div><div class="slide-meta">{slide.period or slide.tab} · Live from Google Sheet · refresh ≤ 60s</div>', unsafe_allow_html=True)
df = frame(slide)

if visual == "KPI Cards":
    cards = []
    for _, row in df.head(8).iterrows():
        label = t(row.iloc[0])
        val = next((t(v) for v in row.iloc[1:] if t(v)), "")
        if label and val:
            cards.append((label, val))
    st.markdown('<div class="kpi-grid">' + ''.join(f'<div class="kpi"><div class="kpi-label">{l}</div><div class="kpi-value">{v}</div></div>' for l, v in cards[:8]) + '</div>', unsafe_allow_html=True)
elif visual in {"Bar Chart", "Line Chart"}:
    cd = chart_df(slide)
    if cd.empty:
        st.dataframe(df, use_container_width=True, height=480, hide_index=True)
    else:
        base = alt.Chart(cd).encode(x=alt.X("x:N", title=None, sort=None), y=alt.Y("y:Q", title=None), tooltip=["x:N", alt.Tooltip("y:Q", format=",.2f")])
        chart = base.mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5) if visual == "Bar Chart" else base.mark_line(point=True, strokeWidth=3)
        st.altair_chart(chart.properties(height=430), use_container_width=True)
else:
    st.dataframe(df, use_container_width=True, height=500, hide_index=True)

st.markdown('</div>', unsafe_allow_html=True)
st.markdown(f"<div class='foot'>Live engine · {time.strftime('%H:%M:%S')} · Conversion → 2 decimals · Financials → BT (Billion Toman)</div>", unsafe_allow_html=True)
