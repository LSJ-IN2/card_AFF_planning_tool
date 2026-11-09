"""Optional historical TG CSV loading for competitor CV analysis only."""
from io import BytesIO
import hashlib
import pandas as pd
import streamlit as st
from data.loader import load_data


@st.cache_data(show_spinner=False, max_entries=5)
def _parse_extra(raw: bytes, exclude_compensation: bool):
    return load_data(BytesIO(raw), exclude_compensation=exclude_compensation)


def combine_for_competitor(current: pd.DataFrame, uploaded, exclude_compensation=True):
    """Daily aggregates, never fed to the planner. Date overlap excluded conservatively.

    Since loader aggregates the CSV before we see it, an overlapping day cannot be
    safely row-deduplicated without a stable unique transaction identifier.
    """
    if current is None:
        current = pd.DataFrame()
    frames = [current.copy()] if not current.empty else []
    occupied = set(pd.to_datetime(current['date'], errors='coerce').dt.normalize().dropna()) if not current.empty else set()
    seen_files = set()
    notices = []
    for f in uploaded or []:
        raw = f.getvalue()
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen_files:
            notices.append(f'{f.name}: 同一ファイルの重複を除外')
            continue
        seen_files.add(digest)
        try:
            x = _parse_extra(raw, exclude_compensation).copy()
        except Exception as exc:
            notices.append(f'{f.name}: 読込失敗（{exc}）')
            continue
        if x.empty:
            continue
        x['date'] = pd.to_datetime(x['date'], errors='coerce').dt.normalize()
        x = x.dropna(subset=['date'])
        overlap = x['date'].isin(occupied)
        if overlap.any():
            notices.append(f'{f.name}: 重複日 {x.loc[overlap, "date"].nunique()} 日分を除外（部分的な日付重複は自動統合しません）')
        x = x.loc[~overlap].copy()
        if not x.empty:
            frames.append(x)
            occupied.update(x['date'].unique())
    if not frames:
        return pd.DataFrame(), notices
    combined = pd.concat(frames, ignore_index=True, sort=False)
    # Reduce memory immediately; product and media filters are not needed for the
    # all-media CV total shown in competitor analysis.
    metrics = [c for c in ('cv','approved_cv') if c in combined.columns]
    daily = combined.groupby('date', as_index=False)[metrics].sum()
    return daily, notices
