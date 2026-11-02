"""楽天カードと競合商品の還元額差が楽天カードCVに関係するか探索する。"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from competitor_analysis import parse_competitor_workbook


def _daily_amount(comp, product, media, segment, label):
    x = comp.loc[(comp['商品'] == product) & (comp['媒体'] == media) & (comp['セグメント'] == segment), ['調査日','還元額']].copy()
    x['調査日'] = pd.to_datetime(x['調査日']).dt.normalize()
    return x.sort_values('調査日').drop_duplicates('調査日', keep='last').rename(columns={'調査日':f'調査日_{label}', '還元額':label})


def _join(history, comp, media_reward, segment, own_product, rival_product, metric, start, end):
    own = history.copy()
    own['date'] = pd.to_datetime(own['date'], errors='coerce').dt.normalize()
    own = own.loc[own['date'].between(start, end)].copy()
    own[metric] = pd.to_numeric(own[metric], errors='coerce').fillna(0)
    own = own.dropna(subset=['date']).groupby('date', as_index=False)[metric].sum().rename(columns={metric:'CV'}).sort_values('date')
    if own.empty:
        return pd.DataFrame()
    for product, label in ((own_product,'自社還元額'),(rival_product,'競合還元額')):
        vals = _daily_amount(comp, product, media_reward, segment, label)
        if vals.empty: return pd.DataFrame()
        own = pd.merge_asof(own.sort_values('date'), vals, left_on='date', right_on=f'調査日_{label}', direction='backward')
        own = own.dropna(subset=[label]).copy()
        if own.empty: return pd.DataFrame()
    own['還元額差（競合−自社）'] = own['競合還元額'] - own['自社還元額']
    return own


def show_competitor_cv_analysis(history):
    st.divider()
    st.subheader('競合商品還元額 × 楽天カードCV実績')
    st.caption('指定したポイントサイト内で楽天カードと競合カードの還元額を比較し、楽天カードの全媒体合計CVとの関係を調べます。差額がプラスなら競合カードの還元額が高い状態です。')
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
    comp = comp.copy()
    comp['商品'] = comp['商品'].replace({'Yahoo! JAPANカード': 'Paypayカード', 'PayPayカード': 'Paypayカード'})
    comp = comp.sort_values('調査日').drop_duplicates(['調査日','媒体','セグメント','商品'], keep='last')
    products = sorted(comp['商品'].dropna().unique())
    own_product = '楽天カード'
    if own_product not in products:
        st.warning('競合Excelに「楽天カード」列がありません。')
        return
    rivals = [x for x in products if x != own_product]
    if not rivals: return
    defaults = ['三井住友カード（NL）', '三井住友カード ゴールド（NL）', 'エポスカード', 'Paypayカード']
    # 調査ファイルの旧商品名を、表示・選択時に統一する。
    # 旧「三井住友カード」はNLと同一と断定できないため、自動統合しない。
    a,b,c = st.columns([2,1,1])
    with a:
        selected = st.multiselect('比較する競合商品（複数選択可）', rivals,
                                  default=[x for x in defaults if x in rivals],
                                  key='product_rivals_multi')
        if not selected:
            st.info('比較する競合商品を1つ以上選択してください。')
            return
    with b:
        segments = sorted(set(comp['セグメント'].dropna()))
        segment = st.selectbox('セグメント', segments, index=segments.index('1軍') if '1軍' in segments else 0, key='product_segment')
    with c:
        metric_label = st.selectbox('楽天カードの実績指標', ['申込件数','発行件数'], key='product_metric')
    metric = 'cv' if metric_label == '申込件数' else 'approved_cv'
    if metric not in history.columns:
        st.warning(f'実績データに {metric} がありません。')
        return
    eligible = sorted(set(comp.loc[(comp['商品']==own_product)&(comp['セグメント']==segment),'媒体']) & set(comp.loc[(comp['商品'].isin(selected))&(comp['セグメント']==segment),'媒体']))
    if not eligible:
        st.info('楽天カードと選択した競合商品の還元額が存在する媒体がありません。')
        return
    media = st.selectbox('還元額を比較するポイントサイト',eligible,key='product_reward_media')
    st.caption('CV実績は媒体名で絞り込まず、アップロードされた対象実績を全媒体合算します。')
    dmin = pd.to_datetime(history['date'],errors='coerce').min()
    dmax = pd.to_datetime(history['date'],errors='coerce').max()
    if pd.isna(dmin) or pd.isna(dmax): return
    date_range = st.date_input('CV実績の分析期間',value=(dmin.date(),dmax.date()),key='product_cv_dates')
    if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
        st.info('開始日と終了日を選択してください。')
        return
    start, end = date_range
    series = {}
    for rival in selected:
        joined = _join(history, comp, media, segment, own_product, rival, metric,
                       pd.Timestamp(start), pd.Timestamp(end))
        if not joined.empty:
            series[rival] = joined
    if not series:
        st.info('条件に合う日付がありません。実績と調査日の重なりや媒体対応を確認してください。')
        return
    missing = [p for p in selected if p not in series]
    if missing:
        st.warning('このポイントサイトで比較可能なデータがない商品: ' + '、'.join(missing))
    st.caption('還元額は各商品の直近調査値を次の調査日まで引き継ぎます（分析期間開始前の調査値も利用）。比較可能日数は商品ごとに異なる場合があります。')
    st.markdown('#### ① 楽天カードCVと選択商品の還元額推移')
    fig = go.Figure()
    cv_daily = history.copy()
    cv_daily['date'] = pd.to_datetime(cv_daily['date'], errors='coerce').dt.normalize()
    cv_daily = cv_daily.loc[cv_daily['date'].between(pd.Timestamp(start), pd.Timestamp(end))]
    cv_daily[metric] = pd.to_numeric(cv_daily[metric], errors='coerce').fillna(0)
    cv_daily = cv_daily.groupby('date', as_index=False)[metric].sum()
    fig.add_trace(go.Bar(x=cv_daily['date'], y=cv_daily[metric],
                         name=f'楽天カード全媒体合計{metric_label}', opacity=0.45))
    base = next(iter(series.values()))
    fig.add_trace(go.Scatter(x=base['date'], y=base['自社還元額'],
                             name='楽天カード還元額', mode='lines', line_shape='hv', yaxis='y2'))
    for product, df in series.items():
        fig.add_trace(go.Scatter(x=df['date'], y=df['競合還元額'],
                                 name=product, mode='lines', line_shape='hv', yaxis='y2'))
    fig.update_layout(height=430, hovermode='x unified',
                      yaxis=dict(title='CV（件）', showgrid=False),
                      yaxis2=dict(title='還元額（円）', overlaying='y', side='right', showgrid=False),
                      legend=dict(orientation='h', y=1.22))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown('#### ② 競合−楽天カードの還元額差 × 楽天カードCV')
    fig2 = go.Figure()
    for product, df in series.items():
        fig2.add_trace(go.Scatter(
            x=df['還元額差（競合−自社）'], y=df['CV'], mode='markers', name=product,
            customdata=df['date'].dt.strftime('%Y/%m/%d'),
            hovertemplate='%{fullData.name}<br>差額 %{x:,.0f}円 / CV %{y:,.0f}件<br>%{customdata}<extra></extra>'))
    fig2.update_layout(height=420, xaxis_title='競合−楽天カード還元額（円）',
                       yaxis_title=f'楽天カード全媒体合計{metric_label}（件）',
                       legend=dict(orientation='h', y=1.15))
    st.plotly_chart(fig2, use_container_width=True)

    st.markdown('#### ③ 還元額差帯別の楽天カード平均CV')
    summaries = []
    for product, df in series.items():
        data = df.copy()
        data['差額帯下限'] = (data['還元額差（競合−自社）']//1000*1000).astype(int)
        summary = data.groupby('差額帯下限', as_index=False).agg(
            平均CV=('CV', 'mean'), 日数=('date', 'count')).sort_values('差額帯下限')
        summary['競合商品'] = product
        summary['差額帯'] = summary['差額帯下限'].map(lambda v: f'{v:+,}〜{v+999:+,}円')
        summaries.append(summary[['競合商品', '差額帯', '平均CV', '日数']])
    st.dataframe(pd.concat(summaries, ignore_index=True), hide_index=True,
                 use_container_width=True)
    st.caption('選択したポイントサイトの還元額と全媒体合計CVの比較であり、媒体ごとのCVとの直接対応ではありません。これは探索的な比較です。曜日・広告露出・楽天カード自体の施策・季節性などの影響を除外していないため、CV減少の因果関係は断定できません。実績が楽天カード以外を含む場合は商品IDでの絞り込みが必要です。')
