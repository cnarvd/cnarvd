import io
import re
import time
from dataclasses import dataclass
from typing import List

import altair as alt
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title='Holdco Business Review', page_icon='📊', layout='wide', initial_sidebar_state='collapsed')

API_URL='https://holdco-business-review-live.vercel.app/api/sheet'
SECTIONS=['Executive Summary','Product','Operation','Sales','Marketing SEO','Marketing Performance']
TAB_MAP={'Executive Summary':'Exc. Summary','Product':'Product','Operation':'Operation','Sales':'Sales','Marketing SEO':'Marketing Seo','Marketing Performance':'Marketing Performance'}

st.markdown('''
<style>
:root{--bg:#06111f;--panel:#0d1b2e;--text:#edf5ff;--muted:#93a7bd;--accent:#5aa7ff}
html,body,[data-testid="stAppViewContainer"],.stApp{background:var(--bg)!important}
header[data-testid="stHeader"]{background:transparent!important}
[data-testid="stToolbar"]{visibility:hidden}.block-container{max-width:1500px;padding-top:.8rem;padding-bottom:1rem}
h1,h2,h3,p,span,div,label{color:var(--text)}
.br-title{font-size:1.05rem;font-weight:750;line-height:1.1}.br-sub{color:#8fb0d0;font-size:.78rem}
.slide{background:linear-gradient(180deg,#fff 0%,#f6f9fc 100%);color:#14243a;border-radius:18px;min-height:66vh;padding:26px 30px;box-shadow:0 24px 80px rgba(0,0,0,.27)}
.slide h1,.slide h2,.slide h3,.slide p,.slide div,.slide span,.slide td,.slide th{color:#14243a!important}
.slide-title{font-size:1.55rem;font-weight:800;margin-bottom:6px}.slide-meta{font-size:.78rem;color:#62758d!important;margin-bottom:18px}
.kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.kpi{background:white;border:1px solid #dce6ef;border-radius:14px;padding:14px 16px;box-shadow:0 4px 18px rgba(21,49,79,.06)}
.kpi-label{font-size:.76rem;color:#60748a!important}.kpi-value{font-size:1.3rem;font-weight:800;margin-top:4px}.footerline{color:#7890aa;font-size:.72rem;margin-top:8px}.stButton button{border-radius:10px!important}
</style>
''',unsafe_allow_html=True)

def txt(x): return '' if x is None else str(x).strip()
def norm(s): return re.sub(r'[\s._–—-]+',' ',txt(s).lower()).strip()
def parse_num(v):
    s=txt(v).replace(',','').replace('%','').replace('−','-'); s=re.sub(r'\s+','',s)
    if not s or s in {'-','—','#DIV/0!','#REF!','#N/A'}: return None
    try:return float(s)
    except:return None

def is_pct_metric(label):
    n=norm(label)
    return any(k in n for k in ['conversion','rate %','retention','progress','gap','variance','csat','payment rate','margin','conversion rate'])

def is_money_metric(label):
    n=norm(label)
    return any(k in n for k in ['revenue','gmv','nmv','gbv','irt','sales','budget']) and 'order' not in n

def fmt_value(label,v):
    s=txt(v)
    if not s:return ''
    if s in {'-','—','#DIV/0!','#REF!','#N/A'}:return s
    n=parse_num(s)
    if is_pct_metric(label):
        if '%' in s:
            try:return f"{float(s.replace(',','').replace('%','')):.2f}%"
            except:return s
        if n is not None:return f"{(n*100 if abs(n)<=1.5 else n):.2f}%"
    if is_money_metric(label) and n is not None:
        if abs(n)>=100_000_000:return f"{n/1_000_000_000:.2f} BT"
        return f"{n:,.0f}"
    if n is not None:
        return f"{int(round(n)):,}" if abs(n-round(n))<1e-9 else f"{n:,.2f}"
    return s

@st.cache_data(ttl=45,show_spinner=False)
def load_payload():
    r=requests.get(API_URL,timeout=20,headers={'Cache-Control':'no-cache'});r.raise_for_status();return r.json()

def csv_to_grid(csv_text):
    if not csv_text:return pd.DataFrame()
    try:return pd.read_csv(io.StringIO(csv_text),header=None,dtype=str,keep_default_na=False)
    except:return pd.DataFrame([line.split(',') for line in csv_text.splitlines()])

def tab_to_section(tab):
    rev={v:k for k,v in TAB_MAP.items()};return rev.get(tab,tab)

@dataclass
class Slide:
    id:str;section:str;tab:str;title:str;period:str;headers:List[str];rows:List[List[str]];kind:str='table'

def find_title_above(df,row_idx,col_idx=0):
    keywords=['report','monthly','revenue','commercial','okr','performance','trend','sales','non-appt','call center','support','doctor','physician','marketing','seo','evisit','appointment','وضعیت','اقدامات','درآمد','عملکرد']
    best=''
    for r in range(max(0,row_idx-10),row_idx):
        vals=[txt(x) for x in df.iloc[r].tolist() if txt(x)];joined=' | '.join(vals)
        if any(k in joined.lower() for k in keywords):best=joined[:120]
    return best

def extract_generic_tables(tab,df):
    slides=[]
    if df.empty:return slides
    header_tokens={'metric','items','period','date','order','actual','projection','product'}
    candidates=[]
    for r in range(len(df)):
        vals=[norm(x) for x in df.iloc[r].tolist()];non=[v for v in vals if v]
        if not non:continue
        score=sum(1 for v in non if v in header_tokens or any(t in v for t in ['metric','items','period','order','actual','projection']))
        if score>=1 and len(non)>=2:candidates.append(r)
    used=set()
    for r in candidates:
        if r in used:continue
        row=[txt(x) for x in df.iloc[r].tolist()];cols=[i for i,x in enumerate(row) if x]
        if not cols:continue
        c0=min(cols);c1=max(cols);width=min(8,max(3,c1-c0+1));endc=min(df.shape[1],c0+width)
        data=[];rr=r+1;blank=0
        while rr<len(df) and rr<r+18:
            vals=[txt(x) for x in df.iloc[rr,c0:endc].tolist()]
            if not any(vals):
                blank+=1
                if blank>=2:break
            else:blank=0;data.append(vals)
            rr+=1
        if len(data)<2:continue
        headers=[txt(x) or f'Col {i+1}' for i,x in enumerate(df.iloc[r,c0:endc].tolist())]
        title=find_title_above(df,r,c0) or f'{tab} — Table {len(slides)+1}'
        pm=re.search(r'\b(Q[1-4]|Tir|Mordad|Shahrivar|Khordad|Ordibehesht|Farvardin|Mehr|Aban|Azar|Dey|Bahman|Esfand)\b',title,re.I)
        period=pm.group(1) if pm else ''
        slides.append(Slide(f'{tab}:{r}:{c0}',tab_to_section(tab),tab,title,period,headers,data));used.update(range(r,min(rr,r+18)))
    return slides

def extract_seo(tab,df):
    slides=[]
    if df.empty:return slides
    for r in range(len(df)):
        first=txt(df.iloc[r,0])
        if re.search(r'commercial\s+(okr|tir|mordad|shahrivar|mehr|aban|azar|q[1-4])',first,re.I):
            headers=[txt(x) or f'Col {i+1}' for i,x in enumerate(df.iloc[r].tolist()[:6])];rows=[]
            for rr in range(r+1,min(r+5,len(df))):
                vals=[txt(x) for x in df.iloc[rr].tolist()[:6]]
                if any(vals):rows.append(vals)
            slides.append(Slide(f'{tab}:{r}','Marketing SEO',tab,first,'',headers,rows))
    for r in range(len(df)):
        vals=[txt(x) for x in df.iloc[r].tolist()[:4]]
        if len(vals)>=3 and '1404' in vals and '1405' in vals:
            rows=[]
            for rr in range(r+1,len(df)):
                v=[txt(x) for x in df.iloc[rr].tolist()[:4]]
                if not any(v):break
                rows.append(v)
            if rows:slides.append(Slide(f'{tab}:weekly:{r}','Marketing SEO',tab,'SEO Weekly Click Trend','',['Period','1404','1405','Projection'],rows,'line'))
            break
    return slides

def build_slides(payload):
    slides=[]
    for item in payload.get('tabs',[]):
        tab=item.get('tab','')
        if not item.get('ok'):continue
        df=csv_to_grid(item.get('csv',''));slides.extend(extract_seo(tab,df) if tab=='Marketing Seo' else extract_generic_tables(tab,df))
    by_tab={s.tab for s in slides}
    for item in payload.get('tabs',[]):
        tab=item.get('tab','')
        if tab in by_tab or not item.get('ok'):continue
        df=csv_to_grid(item.get('csv',''))
        if not df.empty:
            headers=[f'Col {i+1}' for i in range(min(8,df.shape[1]))];rows=[[txt(x) for x in row[:8]] for row in df.head(12).values.tolist()]
            slides.append(Slide(f'{tab}:fallback',tab_to_section(tab),tab,f'{tab} Overview','',headers,rows))
    return slides

def table_df(slide):
    width=max(len(slide.headers),max([len(r) for r in slide.rows],default=0));headers=(slide.headers+[f'Col {i+1}' for i in range(len(slide.headers),width)])[:width];data=[]
    for row in slide.rows:
        row=(row+['']*width)[:width];label=row[0] if row else '';data.append([fmt_value(label,v) for v in row])
    return pd.DataFrame(data,columns=headers)

def numeric_chart_df(slide):
    rows=[]
    for row in slide.rows:
        if len(row)<2:continue
        x=txt(row[0]);y=parse_num(row[1])
        if x and y is not None:rows.append({'x':x,'y':y})
    return pd.DataFrame(rows)

for k,v in [('slide_index',0),('hidden_slides',set()),('studio_open',False),('visual_overrides',{})]:st.session_state.setdefault(k,v)
st.components.v1.html("<script>setTimeout(()=>{window.parent.location.reload();},60000);</script>",height=0)
try:
    payload=load_payload();online=bool(payload.get('accessible'))
except Exception as e:
    payload={'tabs':[]};online=False;st.error(f'Live Sheet unavailable: {e}')
all_slides=build_slides(payload);visible=[s for s in all_slides if s.id not in st.session_state.hidden_slides]
if not visible:st.error('No live presentation tables found.');st.stop()

top1,top2,top3=st.columns([2,6,2])
with top1:st.markdown('<div class="br-title">Business Review</div><div class="br-sub">Holdco · Live Presentation</div>',unsafe_allow_html=True)
with top2:
    sec_names=[s for s in SECTIONS if any(x.section==s for x in visible)];current=visible[min(st.session_state.slide_index,len(visible)-1)];cur_sec=current.section if current.section in sec_names else sec_names[0]
    chosen=st.segmented_control('Section',sec_names,selection_mode='single',default=cur_sec,label_visibility='collapsed')
    if chosen and chosen!=cur_sec:
        for i,s in enumerate(visible):
            if s.section==chosen:st.session_state.slide_index=i;st.rerun()
with top3:st.markdown(f"<div style='text-align:left;font-size:.8rem;color:#8fb0d0'>{'🟢 Live Sheet' if online else '🔴 Offline'}</div>",unsafe_allow_html=True)

idx=min(st.session_state.slide_index,len(visible)-1);slide=visible[idx]
a,b,c,d,e=st.columns([1,1,1,1,6])
with a:
    if st.button('◀',use_container_width=True,disabled=idx<=0):st.session_state.slide_index=max(0,idx-1);st.rerun()
with b:
    if st.button('▶',use_container_width=True,disabled=idx>=len(visible)-1):st.session_state.slide_index=min(len(visible)-1,idx+1);st.rerun()
with c:
    if st.button('✏️ Edit',use_container_width=True):st.session_state.studio_open=not st.session_state.studio_open
with d:
    if st.button('🗑 Hide',use_container_width=True):st.session_state.hidden_slides.add(slide.id);st.session_state.slide_index=max(0,min(idx,len(visible)-2));st.rerun()
with e:st.markdown(f"<div style='text-align:left;padding-top:8px;color:#7890aa;font-size:.78rem'>{idx+1} / {len(visible)} · {slide.section}</div>",unsafe_allow_html=True)

if st.session_state.studio_open:
    with st.expander('Presentation Studio',expanded=True):
        cc1,cc2,cc3,cc4=st.columns([2,3,2,2]);tabs=sorted(set(s.tab for s in all_slides))
        with cc1:sel_tab=st.selectbox('Tab',tabs,index=tabs.index(slide.tab) if slide.tab in tabs else 0)
        ts=[s for s in all_slides if s.tab==sel_tab];titles=[s.title for s in ts]
        with cc2:sel_title=st.selectbox('Table / Item',titles,index=(ts.index(slide) if slide in ts else 0))
        selected=ts[titles.index(sel_title)]
        with cc3:
            opts=['Auto','Table','KPI Cards','Bar Chart','Line Chart'];override=st.session_state.visual_overrides.get(selected.id,'Auto');visual=st.selectbox('Visual',opts,index=opts.index(override) if override in opts else 0)
        with cc4:
            st.write('')
            if st.button('Present this table',use_container_width=True):
                st.session_state.visual_overrides[selected.id]=visual;st.session_state.hidden_slides.discard(selected.id);nv=[s for s in all_slides if s.id not in st.session_state.hidden_slides];st.session_state.slide_index=next((i for i,s in enumerate(nv) if s.id==selected.id),0);st.rerun()
        if st.session_state.hidden_slides and st.button(f'Restore hidden slides ({len(st.session_state.hidden_slides)})'):st.session_state.hidden_slides=set();st.rerun()

visual=st.session_state.visual_overrides.get(slide.id,'Auto');visual='Line Chart' if visual=='Auto' and slide.kind=='line' else ('Table' if visual=='Auto' else visual)
st.markdown('<div class="slide">',unsafe_allow_html=True);st.markdown(f'<div class="slide-title">{slide.title}</div>',unsafe_allow_html=True);st.markdown(f'<div class="slide-meta">{slide.period or slide.tab} · Live from Google Sheet · refresh ≤ 60s</div>',unsafe_allow_html=True)
df=table_df(slide)
if visual=='KPI Cards':
    cards=[]
    for _,row in df.head(8).iterrows():
        label=txt(row.iloc[0]);value=next((txt(v) for v in row.iloc[1:] if txt(v)),'')
        if label and value:cards.append((label,value))
    html='<div class="kpi-grid">'+''.join([f'<div class="kpi"><div class="kpi-label">{l}</div><div class="kpi-value">{v}</div></div>' for l,v in cards[:8]])+'</div>';st.markdown(html,unsafe_allow_html=True)
elif visual in {'Bar Chart','Line Chart'}:
    cdf=numeric_chart_df(slide)
    if not cdf.empty:
        chart=alt.Chart(cdf).encode(x=alt.X('x:N',title=None,sort=None),y=alt.Y('y:Q',title=None),tooltip=['x:N',alt.Tooltip('y:Q',format=',.2f')]);chart=chart.mark_bar(cornerRadiusTopLeft=5,cornerRadiusTopRight=5) if visual=='Bar Chart' else chart.mark_line(point=True,strokeWidth=3);st.altair_chart(chart.properties(height=430),use_container_width=True)
    else:st.dataframe(df,use_container_width=True,height=430,hide_index=True)
else:st.dataframe(df,use_container_width=True,height=500,hide_index=True)
st.markdown('</div>',unsafe_allow_html=True);st.markdown(f"<div class='footerline'>Live presentation engine · {time.strftime('%H:%M:%S')} · Conversion → 2 decimals · Financials → BT</div>",unsafe_allow_html=True)
