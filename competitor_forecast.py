"""Exploratory 3-month competitor reward scenarios; never modifies CV planning."""
import pandas as pd
import numpy as np


def forecast_rewards(observed, cpn_master=None, method='過去傾向（マジ得考慮）', adjustment=0, horizon_months=3, planned_magi_dates=None):
    """Observed: 調査日, 媒体, セグメント, 商品, 還元額. Forecast from last observed day.

    A change-event model, with small-sample fallback to constant. Historical CPN
    associations are descriptive, not causal, and are applied only if enough events.
    """
    if observed is None or observed.empty:
        return pd.DataFrame(), pd.DataFrame()
    x = observed.copy()
    x['調査日'] = pd.to_datetime(x['調査日']).dt.normalize()
    x = x.sort_values('調査日').drop_duplicates(['調査日','媒体','セグメント','商品'], keep='last')
    anchor = x['調査日'].max()
    horizon = anchor + pd.DateOffset(months=horizon_months)
    days = pd.date_range(anchor + pd.Timedelta(days=1), horizon, freq='D')
    if len(days) == 0:
        return pd.DataFrame(), pd.DataFrame()
    magi_dates = set()
    if cpn_master is not None and not cpn_master.empty and {'日付','CPN名'}.issubset(cpn_master.columns):
        c = cpn_master.copy()
        c['日付'] = pd.to_datetime(c['日付'], errors='coerce').dt.normalize()
        magi_dates = set(c.loc[c['CPN名'].astype(str).str.strip().eq('マジ得'), '日付'].dropna())
    # Future campaign dates come from the current planning output, not the
    # historical CPN master. Historical dates remain the training labels.
    planned_magi = set()
    if planned_magi_dates is not None:
        planned_magi = set(pd.to_datetime(list(planned_magi_dates), errors='coerce').normalize().dropna())
    future_magi_dates = planned_magi if planned_magi_dates is not None else magi_dates
    records, diagnostics = [], []
    for (media, segment, product), g in x.groupby(['媒体','セグメント','商品'], sort=False):
        g = g.sort_values('調査日')
        last = float(g['還元額'].iloc[-1])
        # A change is observed between consecutive surveys, not necessarily on the
        # exact day of the change. We do not fabricate a precise historical date.
        changes = g['還元額'].diff().dropna()
        changed = changes[changes.ne(0)]
        observation_days = max(1, (g['調査日'].max() - g['調査日'].min()).days)
        event_rate = len(changed) / observation_days
        avg_delta = float(changed.mean()) if len(changed) else 0.0
        # Conservative cap: no more than one expected change per 14 days.
        event_rate = min(event_rate, 1 / 14)
        # Event-day association estimated from observed survey dates, only if both
        # regimes and >=3 changes exist; otherwise fall back to unconditioned model.
        magi_factor = 1.0
        if len(changed) >= 3 and magi_dates:
            tmp = g[['調査日','還元額']].copy()
            tmp['changed'] = tmp['還元額'].diff().fillna(0).ne(0)
            tmp['magi'] = tmp['調査日'].isin(magi_dates)
            if tmp['magi'].sum() >= 3 and (~tmp['magi']).sum() >= 3:
                rate_m = tmp.loc[tmp['magi'], 'changed'].mean()
                rate_n = tmp.loc[~tmp['magi'], 'changed'].mean()
                if rate_n > 0:
                    magi_factor = float(np.clip(rate_m / rate_n, 0.5, 2.0))
        # Estimate an amount difference, not merely the frequency of changes.
        # Only compare regimes with at least two surveyed dates each. Keep the
        # base forecast independent so the adjustment ends with the campaign.
        magi_adjustment = 0.0
        if magi_dates:
            observed_magi = g['調査日'].isin(magi_dates)
            if observed_magi.sum() >= 2 and (~observed_magi).sum() >= 2:
                magi_values = pd.to_numeric(g.loc[observed_magi, '還元額'], errors='coerce').dropna()
                normal_values = pd.to_numeric(g.loc[~observed_magi, '還元額'], errors='coerce').dropna()
                if len(magi_values) >= 2 and len(normal_values) >= 2:
                    difference = float(magi_values.median() - normal_values.median())
                    # Restrict to the downward association requested; avoid
                    # treating a sparse observational pattern as certain.
                    magi_adjustment = float(np.clip(difference * 0.7, -5000, 0))
        # The last observed amount may itself be a campaign amount. Remove its
        # estimated campaign effect to obtain the normal-regime baseline.
        last_was_magi = g['調査日'].iloc[-1] in magi_dates
        baseline = max(0.0, last - (magi_adjustment if last_was_magi else 0.0))
        amount = baseline
        for day in days:
            if method == 'シナリオ（指定額を加算）':
                amount = max(0, last + adjustment)
            elif method == '現状維持':
                amount = last
            else:
                # Expected movement is a smoothed *scenario*, not a confident point
                # prediction. Cap drift to avoid extreme extrapolation.
                scale = magi_factor if day in future_magi_dates else 1.0
                amount = float(np.clip(amount + avg_delta * event_rate * scale, max(0,baseline-10000),baseline+10000))
            predicted = amount
            if method == '過去傾向（マジ得考慮）' and day in future_magi_dates:
                predicted = max(0.0, amount + magi_adjustment)
            records.append((day, media, segment, product, round(predicted, 1)))
        diagnostics.append((media, segment, product, len(g), len(changed), round(event_rate, 4), round(magi_factor, 2)))
    result = pd.DataFrame(records, columns=['調査日','媒体','セグメント','商品','予測還元額'])
    diag = pd.DataFrame(diagnostics, columns=['媒体','セグメント','商品','調査件数','変動回数','推定日次変動率','マジ得変動倍率'])
    return result, diag
