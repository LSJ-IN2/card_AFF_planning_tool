"""楽天カードと競合商品の還元額差が楽天カードCVに関係するか探索する。"""
import pandas as pd
import plotly.graph_objects as go
from plotly.colors import qualitative
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


def show_competitor_cv_analysis(history, planning_forecast=None):
    st.divider()
    st.subheader('競合商品還元額 × 楽天カードCV実績')
    st.caption('楽天カードを比較基準として固定表示し、競合3商品を初期選択します。差額がプラスなら競合カードの還元額が高い状態です。CVは全媒体合計です。')
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
    defaults = ['三井住友カード（NL）', 'エポスカード', '三菱UFJカード']
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
    st.caption('CV実績は媒体名で絞り込まず、①と⑤のTG実績を全媒体合算します。⑤の追加データはプランニングに影響しません。')
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
    # 予測はプランニングの計算結果を読み取り専用で参照する。
    plan = pd.DataFrame() if planning_forecast is None else planning_forecast.copy()
    if not plan.empty and {'date', 'forecast_cv'}.issubset(plan.columns):
        plan['date'] = pd.to_datetime(plan['date'], errors='coerce').dt.normalize()
        plan = plan.dropna(subset=['date'])
        plan['forecast_cv'] = pd.to_numeric(plan['forecast_cv'], errors='coerce').fillna(0)
        if metric == 'cv':
            plan['予測CV'] = plan['forecast_cv']
        else:
            if 'approval_rate' in plan.columns:
                plan['予測CV'] = plan['forecast_cv'] * pd.to_numeric(plan['approval_rate'], errors='coerce').fillna(0).clip(0, 1)
            else:
                plan = pd.DataFrame()
        if not plan.empty:
            plan = plan.groupby('date', as_index=False)['予測CV'].sum().sort_values('date')
    else:
        plan = pd.DataFrame()

    # 商品ごとに色を固定。予測は同色の破線で区別する。
    product_colors = {
        '楽天カード': '#C94B52',
        'エポスカード': '#238B72',
        '三井住友カード（NL）': '#4D76C7',
        '三菱UFJカード': '#A17BC5',
    }
    fallback_colors = [c for c in qualitative.Dark24 if c.lower() not in
                       {v.lower() for v in product_colors.values()}]
    other_products = sorted(set(products) - set(product_colors))
    product_colors.update({name: fallback_colors[i % len(fallback_colors)]
                           for i, name in enumerate(other_products)})
    cv_color = '#8B98A8'
    fig = go.Figure()
    cv_daily = history.copy()
    cv_daily['date'] = pd.to_datetime(cv_daily['date'], errors='coerce').dt.normalize()
    cv_daily = cv_daily.loc[cv_daily['date'].between(pd.Timestamp(start), pd.Timestamp(end))]
    cv_daily[metric] = pd.to_numeric(cv_daily[metric], errors='coerce').fillna(0)
    cv_daily = cv_daily.groupby('date', as_index=False)[metric].sum()
    fig.add_trace(go.Bar(x=cv_daily['date'], y=cv_daily[metric],
                         name=f'楽天カード全媒体合計{metric_label}', opacity=0.55,
                         marker_color=cv_color))
    if not plan.empty:
        fig.add_trace(go.Bar(x=plan['date'], y=plan['予測CV'],
                             name=f'楽天カード全媒体合計{metric_label}（プランニング予測）',
                             opacity=0.85, marker_color=cv_color, marker_pattern_shape='/'))
    base = next(iter(series.values()))
    fig.add_trace(go.Scatter(x=base['date'], y=base['自社還元額'],
                             name='楽天カード還元額', mode='lines', line_shape='hv', yaxis='y2',
                             line=dict(color=product_colors[own_product], width=2.5)))
    for product, df in series.items():
        fig.add_trace(go.Scatter(x=df['date'], y=df['競合還元額'],
                                 name=product, mode='lines', line_shape='hv', yaxis='y2',
                                 line=dict(color=product_colors[product], width=2.5)))
    # 競合還元額予測も同じグラフに表示。予測方式は上部の競合分析設定と共通。
    from competitor_forecast import forecast_rewards
    method = st.session_state.get('competitor_forecast_method', '過去傾向（マジ得考慮）')
    adjustment = st.session_state.get('competitor_forecast_adjustment', 0) if method == 'シナリオ（指定額を加算）' else 0
    horizon_months = 3
    if not plan.empty:
        last_survey = pd.to_datetime(comp['調査日']).max()
        horizon_months = max(3, int((plan['date'].max() - last_survey).days / 28) + 2)
        horizon_months = min(horizon_months, 36)
    future, _ = forecast_rewards(comp, st.session_state.get('competitor_cpn_master'),
                                 method=method, adjustment=adjustment, horizon_months=horizon_months)
    if not future.empty:
        for product in [own_product] + list(series):
            f = future.loc[(future['商品'] == product) & (future['媒体'] == media) &
                           (future['セグメント'] == segment)].sort_values('調査日')
            if f.empty:
                continue
            last = _daily_amount(comp, product, media, segment, '実績')
            if not last.empty:
                anchor = last.iloc[-1]
                x = pd.concat([pd.Series([anchor['調査日_実績']]), f['調査日']], ignore_index=True)
                y = pd.concat([pd.Series([anchor['実績']]), f['予測還元額']], ignore_index=True)
            else:
                x, y = f['調査日'], f['予測還元額']
            fig.add_trace(go.Scatter(x=x, y=y, name=f'{product}（還元額予測）',
                                     mode='lines', line_shape='hv', yaxis='y2',
                                     line=dict(color=product_colors[product], dash='dash', width=2.5)))
    if not plan.empty:
        st.caption('棒：楽天カードCV実績／プランニング予測。実線：還元額調査実績。破線：還元額予測シナリオ。CV予測には競合還元額による補正を加えていません。')
    else:
        st.caption('プランニング予測が算出されると、CV予測をこのグラフにも表示します。還元額の破線は参考シナリオです。')
    # 未来の開始を淡い背景で示す（実績期間は塗らない）。
    future_starts = []
    if not plan.empty:
        future_starts.append(plan['date'].min())
    if not future.empty:
        future_starts.append(pd.to_datetime(future['調査日'], errors='coerce').min())
    future_starts = [d for d in future_starts if pd.notna(d)]
    if future_starts:
        forecast_start = min(future_starts)
        fig.add_vrect(x0=forecast_start, x1=max(
            [forecast_start] + ([plan['date'].max()] if not plan.empty else []) +
            ([pd.to_datetime(future['調査日']).max()] if not future.empty else [])),
            fillcolor='rgba(148,163,184,0.10)', opacity=1,
            line_width=0, layer='below')
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
