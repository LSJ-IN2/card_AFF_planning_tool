"""競合還元額と自社実績の探索的比較（予測には影響しない）。"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from competitor_analysis import parse_competitor_workbook


def show_competitor_cv_analysis(history):
    with st.expander('🔎 第二弾① 競合還元額 × 自社実績', expanded=False):
        file = st.session_state.get('competitor_workbook')
        if file is None:
            st.info('競合還元額Excelを上部のアップロード欄に登録してください。')
            return
        if history is None or history.empty:
            st.info('自社実績データが必要です。')
            return
        try:
            comp, _ = parse_competitor_workbook(file.getvalue())
        except Exception as exc:
            st.error(f'競合Excelの読み込みに失敗: {exc}')
            return
        if comp.empty:
            st.warning('競合データがありません。')
            return
        product = st.selectbox('競合商品', sorted(comp['商品'].unique()), key='cv_comp_product')
        segment = st.selectbox('競合セグメント', ['1軍', '2軍'], key='cv_comp_segment')
        candidates = sorted(comp.loc[(comp['商品'] == product) & (comp['セグメント'] == segment), '媒体'].unique())
        if not candidates:
            st.info('該当する媒体がありません。')
            return
        c1, c2, c3 = st.columns(3)
        with c1:
            competitor_media = st.selectbox('競合媒体', candidates, key='cv_comp_media')
        with c2:
            own_media = st.selectbox('自社実績の範囲', ['全媒体合計'] + sorted(history['media'].dropna().astype(str).unique()), key='cv_own_media')
        with c3:
            metric_label = st.selectbox('獲得指標', ['申込件数', '発行件数'], key='cv_metric')
        metric = 'cv' if metric_label == '申込件数' else 'approved_cv'
        max_age = st.slider('調査値の最大引継ぎ日数', 1, 30, 7, key='cv_comp_max_age')
        own = history.copy()
        own['date'] = pd.to_datetime(own['date'], errors='coerce').dt.normalize()
        if own_media != '全媒体合計':
            own = own[own['media'].astype(str) == own_media]
        own = own.groupby('date', as_index=False)[metric].sum().rename(columns={metric: '獲得件数'}).sort_values('date')
        selected = comp[(comp['商品'] == product) & (comp['セグメント'] == segment) & (comp['媒体'] == competitor_media)]
        selected = selected.sort_values('調査日').drop_duplicates('調査日', keep='last').rename(columns={'調査日': '調査元日', '還元額': '競合還元額'})
        joined = pd.merge_asof(own, selected[['調査元日', '競合還元額']].sort_values('調査元日'), left_on='date', right_on='調査元日', direction='backward').dropna(subset=['競合還元額'])
        joined = joined[(joined['date'] - joined['調査元日']).dt.days <= max_age].copy()
        if len(joined) < 5:
            st.warning('比較可能な日付が5日未満です。')
            return
        st.caption(f'比較対象：{len(joined):,}日。未調査日は直近観測値を最大{max_age}日引き継ぎます。')
        fig = go.Figure()
        fig.add_trace(go.Bar(x=joined['date'], y=joined['獲得件数'], name=metric_label))
        fig.add_trace(go.Scatter(x=joined['date'], y=joined['競合還元額'], name='競合還元額', mode='lines', line_shape='hv', yaxis='y2'))
        fig.update_layout(height=380, hovermode='x unified', yaxis=dict(title='獲得件数', showgrid=False), yaxis2=dict(title='還元額（円）', overlaying='y', side='right', showgrid=False), legend=dict(orientation='h', y=1.15))
        st.plotly_chart(fig, use_container_width=True, key='cv_comp_time_chart')
        corr = joined['競合還元額'].corr(joined['獲得件数'])
        st.metric('単純相関係数（参考）', f'{corr:.2f}' if pd.notna(corr) else '算出不可')
        fig2 = go.Figure(go.Scatter(x=joined['競合還元額'], y=joined['獲得件数'], mode='markers'))
        fig2.update_layout(height=340, xaxis_title='競合還元額（円）', yaxis_title=f'{metric_label}（件）')
        st.plotly_chart(fig2, use_container_width=True, key='cv_comp_scatter_chart')
        joined['還元額帯'] = (joined['競合還元額'] // 1000 * 1000).astype(int)
        summary = joined.groupby('還元額帯', as_index=False).agg(平均獲得件数=('獲得件数', 'mean'), 比較日数=('date', 'count'))
        summary['還元額帯'] = summary['還元額帯'].map(lambda v: f'{v:,}〜{v+999:,}円')
        st.subheader('競合還元額帯別の平均獲得件数')
        st.dataframe(summary, hide_index=True, use_container_width=True)
        st.caption('探索的な関連分析です。曜日・自社施策・媒体構成などの交絡要因は未調整で、因果関係を示しません。競合商品と自社商品IDは自動対応しないため、分析対象を揃えてください。')
