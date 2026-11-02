"""楽天カードと競合商品の還元額差が楽天カードCVに関係するか探索する。"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from competitor_analysis import parse_competitor_workbook


def _daily_amount(comp, product, media, segment, label):
    x = comp.loc[(comp['商品'] == product) & (comp['媒体'] == media) & (comp['セグメント'] == segment), ['調査日','還元額']].copy()
    x['調査日'] = pd.to_datetime(x['調査日']).dt.normalize()
    return x.sort_values('調査日').drop_duplicates('調査日', keep='last').rename(columns={'調査日':f'調査日_{label}', '還元額':label})


def _join(history, comp, media_cv, media_reward, segment, own_product, rival_product, metric, max_age, start, end):
    own = history.copy()
    own['date'] = pd.to_datetime(own['date'], errors='coerce').dt.normalize()
    own = own.loc[(own['media'].astype(str) == media_cv) & own['date'].between(start, end)].copy()
    own[metric] = pd.to_numeric(own[metric], errors='coerce').fillna(0)
    own = own.dropna(subset=['date']).groupby('date', as_index=False)[metric].sum().rename(columns={metric:'CV'}).sort_values('date')
    if own.empty:
        return pd.DataFrame()
    for product, label in ((own_product,'自社還元額'),(rival_product,'競合還元額')):
        vals = _daily_amount(comp, product, media_reward, segment, label)
        if vals.empty: return pd.DataFrame()
        own = pd.merge_asof(own.sort_values('date'), vals, left_on='date', right_on=f'調査日_{label}', direction='backward')
        own = own.loc[(own['date'] - own[f'調査日_{label}']).dt.days.between(0,max_age)].copy()
        if own.empty: return pd.DataFrame()
    own['還元額差（競合−自社）'] = own['競合還元額'] - own['自社還元額']
    return own


def show_competitor_cv_analysis(history):
    st.divider()
    st.subheader('競合商品還元額 × 楽天カードCV実績')
    st.caption('同じポイントサイト内の楽天カードと競合カードを比較します。差額がプラスなら競合カードの還元額が高い状態です。')
    file = st.session_state.get('competitor_workbook')
    if file is None:
        st.info('競合還元額調査Excelをアップロードしてください。')
        return
    if history is None or history.empty:
        st.info('楽天カードのCV実績をアップロードしてください。')
        return
    try:
        comp, _ = parse_competitor_workbook(file.getvalue())
    except Exception as exc:
        st.error(f'競合データの読み込みに失敗しました: {exc}')
        return
    if comp.empty: return
    products = sorted(comp['商品'].dropna().unique())
    own_product = '楽天カード'
    if own_product not in products:
        st.warning('競合Excelに「楽天カード」列がありません。')
        return
    rivals = [x for x in products if x != own_product]
    if not rivals: return
    a,b,c = st.columns(3)
    with a:
        rival = st.selectbox('比較する競合商品', rivals, key='product_rival')
    with b:
        segments = sorted(set(comp['セグメント'].dropna()))
        segment = st.selectbox('セグメント', segments, index=segments.index('1軍') if '1軍' in segments else 0, key='product_segment')
    with c:
        metric_label = st.selectbox('楽天カードの実績指標', ['申込件数','発行件数'], key='product_metric')
    metric = 'cv' if metric_label == '申込件数' else 'approved_cv'
    if metric not in history.columns:
        st.warning(f'実績データに {metric} がありません。')
        return
    eligible = sorted(set(comp.loc[(comp['商品']==own_product)&(comp['セグメント']==segment),'媒体']) & set(comp.loc[(comp['商品']==rival)&(comp['セグメント']==segment),'媒体']))
    if not eligible:
        st.info('両商品の還元額が存在する媒体がありません。')
        return
    media = st.selectbox('還元額を比較するポイントサイト',eligible,key='product_reward_media')
    actual_media = sorted(history['media'].dropna().astype(str).unique())
    cv_media = st.selectbox('対応する楽天カードCV実績の媒体名',actual_media,index=actual_media.index(media) if media in actual_media else 0,key='product_cv_media')
    if cv_media != media:
        st.warning('媒体名が一致していません。異なる表記の場合は同一媒体であることを確認して選択してください。')
    dmin = pd.to_datetime(history['date'],errors='coerce').min()
    dmax = pd.to_datetime(history['date'],errors='coerce').max()
    if pd.isna(dmin) or pd.isna(dmax): return
    date_range = st.date_input('CV実績の分析期間',value=(dmin.date(),dmax.date()),key='product_cv_dates')
    if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
        st.info('開始日と終了日を選択してください。')
        return
    start, end = date_range
    age = st.slider('還元額調査値の引継ぎ上限（日）',1,30,7,key='product_cv_age')
    joined = _join(history,comp,cv_media,media,segment,own_product,rival,metric,age,pd.Timestamp(start),pd.Timestamp(end))
    if joined.empty:
        st.info('条件に合う日付がありません。実績と調査日の重なりや媒体対応を確認してください。')
        return
    st.caption(f'比較可能日数：{len(joined):,}日／競合−楽天カードの還元額差を使用。調査値は最大{age}日間のみ引き継ぎます。')
    st.markdown('#### ① 楽天カードCVと両商品の還元額推移')
    fig = go.Figure()
    fig.add_trace(go.Bar(x=joined['date'],y=joined['CV'],name=f'楽天カード{metric_label}'))
    for label in ['自社還元額','競合還元額']:
        fig.add_trace(go.Scatter(x=joined['date'],y=joined[label],name=label,mode='lines',line_shape='hv',yaxis='y2'))
    fig.update_layout(height=400,hovermode='x unified',yaxis=dict(title='CV（件）',showgrid=False),yaxis2=dict(title='還元額（円）',overlaying='y',side='right',showgrid=False),legend=dict(orientation='h',y=1.15))
    st.plotly_chart(fig,use_container_width=True)
    st.markdown('#### ② 競合−楽天カードの還元額差 × 楽天カードCV')
    fig2 = go.Figure(go.Scatter(x=joined['還元額差（競合−自社）'],y=joined['CV'],mode='markers',customdata=joined['date'].dt.strftime('%Y/%m/%d'),hovertemplate='差額 %{x:,.0f}円 / CV %{y:,.0f}件<br>%{customdata}<extra></extra>'))
    fig2.update_layout(height=360,xaxis_title='競合−楽天カード還元額（円）',yaxis_title=f'楽天カード{metric_label}（件）')
    st.plotly_chart(fig2,use_container_width=True)
    st.markdown('#### ③ 還元額差帯別の楽天カード平均CV')
    joined['差額帯下限'] = (joined['還元額差（競合−自社）']//1000*1000).astype(int)
    summary = joined.groupby('差額帯下限',as_index=False).agg(平均CV=('CV','mean'),日数=('date','count')).sort_values('差額帯下限')
    summary['差額帯'] = summary['差額帯下限'].map(lambda v:f'{v:+,}〜{v+999:+,}円')
    st.dataframe(summary[['差額帯','平均CV','日数']],hide_index=True,use_container_width=True)
    st.caption('これは探索的な比較です。曜日・広告露出・楽天カード自体の施策・季節性などの影響を除外していないため、CV減少の因果関係は断定できません。実績が楽天カード以外を含む場合は商品IDでの絞り込みが必要です。')
