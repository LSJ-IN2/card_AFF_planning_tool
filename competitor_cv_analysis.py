"""探索的な競合還元額差と媒体別CVの分析（予測モデルとは独立）。"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from competitor_analysis import parse_competitor_workbook


def _align(own, comp, media, other, product, segment, metric, max_age):
    own = own.copy()
    own["date"] = pd.to_datetime(own["date"], errors="coerce").dt.normalize()
    if media != "全媒体合計":
        own = own[own["media"].astype(str) == media]
    own[metric] = pd.to_numeric(own[metric], errors="coerce").fillna(0)
    own = own.dropna(subset=["date"]).groupby("date", as_index=False)[metric].sum().rename(columns={metric:"CV"}).sort_values("date")
    def series(name, column):
        data = comp[(comp["商品"] == product) & (comp["セグメント"] == segment) & (comp["媒体"] == name)].copy()
        return data.sort_values("調査日").drop_duplicates("調査日", keep="last").rename(columns={"調査日":f"調査日_{column}", "還元額":column})[[f"調査日_{column}",column]]
    left = series(media, "基準還元額") if media != "全媒体合計" else None
    right = series(other, "比較先還元額")
    if right.empty or (left is not None and left.empty):
        return pd.DataFrame()
    result = own
    if left is not None:
        result = pd.merge_asof(result, left, left_on="date", right_on="調査日_基準還元額", direction="backward")
        result = result[(result["date"]-result["調査日_基準還元額"]).dt.days <= max_age]
    result = pd.merge_asof(result.sort_values("date"),right,left_on="date",right_on="調査日_比較先還元額",direction="backward")
    result = result[(result["date"]-result["調査日_比較先還元額"]).dt.days <= max_age]
    result = result.dropna(subset=["比較先還元額"])
    if left is not None:
        result = result.dropna(subset=["基準還元額"])
        result["還元額差"] = result["基準還元額"]-result["比較先還元額"]
    return result


def show_competitor_cv_analysis(history):
    st.divider()
    st.subheader("競合還元額 × 自社CV実績")
    file = st.session_state.get("competitor_workbook")
    if file is None:
        st.info("競合Excelをアップロードすると関連分析を利用できます。")
        return
    if history is None or history.empty:
        st.info("自社実績データもアップロードしてください。")
        return
    try:
        comp, _ = parse_competitor_workbook(file.getvalue())
    except Exception as exc:
        st.error(f"競合Excelを読み込めません: {exc}")
        return
    if comp.empty:
        st.info("競合還元額データがありません。")
        return
    products = sorted(comp["商品"].dropna().unique())
    product = st.selectbox("商品",products,index=products.index("楽天カード") if "楽天カード" in products else 0,key="rel_product")
    segments = [x for x in ("1軍","2軍") if x in comp["セグメント"].unique()]
    if not segments:
        st.warning("1軍・2軍のデータが見つかりません。")
        return
    segment = st.selectbox("セグメント",segments,key="rel_segment")
    media = sorted(comp.loc[(comp["商品"]==product)&(comp["セグメント"]==segment),"媒体"].unique())
    if not media:
        st.info("対象媒体がありません。")
        return
    c1,c2,c3=st.columns(3)
    with c1:
        own_media=st.selectbox("自社実績の対象媒体",["全媒体合計"]+sorted(history["media"].dropna().astype(str).unique()),key="rel_own")
    with c2:
        competitor_media=st.selectbox("比較先の競合媒体",media,key="rel_other")
    with c3:
        metric_label=st.selectbox("実績指標",["申込件数","発行件数"],key="rel_metric")
    metric="cv" if metric_label=="申込件数" else "approved_cv"
    if metric not in history.columns:
        st.warning(f"実績データに {metric} 列がありません。")
        return
    max_age=st.slider("調査値の引継ぎ上限（日）",1,30,7,key="rel_age")
    # 全媒体合計には単一の基準還元額がないため、差額分析は媒体指定時だけ実行する
    joined=_align(history,comp,own_media,competitor_media,product,segment,metric,max_age)
    if joined.empty:
        st.info("条件に合う比較可能なデータがありません。媒体名の表記も確認してください。")
        return
    st.caption(f"比較可能日数：{len(joined):,}日。未調査日は直近値を最大{max_age}日間引継ぎ。自社商品IDとの一致は自動保証されません。")
    st.markdown("#### ① 自社CVと競合還元額の時系列比較")
    fig=go.Figure()
    fig.add_trace(go.Bar(x=joined["date"],y=joined["CV"],name=metric_label))
    fig.add_trace(go.Scatter(x=joined["date"],y=joined["比較先還元額"],mode="lines",line_shape="hv",name="競合還元額",yaxis="y2"))
    fig.update_layout(height=390,hovermode="x unified",yaxis=dict(title="獲得件数",showgrid=False),yaxis2=dict(title="還元額（円）",overlaying="y",side="right",showgrid=False),legend=dict(orientation="h",y=1.12))
    st.plotly_chart(fig,use_container_width=True,key="rel_time")
    if own_media=="全媒体合計":
        st.info("②③は媒体別の還元額差が必要です。『自社実績の対象媒体』で個別媒体を選択してください。")
        return
    if own_media not in media:
        st.warning("自社実績の媒体名が競合Excelと一致しません。媒体名対応表が必要です。")
        return
    if own_media==competitor_media:
        st.info("還元額差を分析するには、比較先に別媒体を選んでください。")
        return
    st.markdown("#### ② 還元額差 × 自社CV")
    st.caption("還元額差＝対象媒体の還元額 − 比較先媒体の還元額。CPAとの差ではありません。")
    scatter=go.Figure(go.Scatter(x=joined["還元額差"],y=joined["CV"],mode="markers",customdata=joined["date"].dt.strftime("%Y/%m/%d"),hovertemplate="差額 %{x:,.0f}円 / CV %{y:,.0f}件<br>%{customdata}<extra></extra>"))
    scatter.update_layout(height=350,xaxis_title="還元額差（円）",yaxis_title=f"{metric_label}（件）")
    st.plotly_chart(scatter,use_container_width=True,key="rel_scatter")
    st.markdown("#### ③ 還元額差別の平均CV比較表")
    joined["差額帯"]=(joined["還元額差"]//1000*1000).astype(int)
    summary=joined.groupby("差額帯",as_index=False).agg(平均CV=("CV","mean"),比較日数=("date","count"))
    summary["差額帯"]=summary["差額帯"].map(lambda x:f"{x:+,}〜{x+999:+,}円")
    st.dataframe(summary,hide_index=True,use_container_width=True)
    st.caption("相関は因果関係ではありません。曜日・自社施策・露出等の影響は未調整です。")
