"""3-2 research primitives. No historical winner selection or automatic training.

The legacy simulator is deliberately not an evaluation entry for this revision.
Use these invariants when constructing a new dataset/replay with complete data.
"""
import numpy as np
import pandas as pd


def historical_members(metadata, start, end):
    """Retain any stock whose listing lifetime overlaps the research window."""
    ipo = pd.to_datetime(metadata['ipoDate'], errors='raise')
    out = pd.to_datetime(metadata['outDate'].replace('', pd.NaT), errors='raise')
    if ipo.isna().any():
        raise ValueError('Listing date missing: universe cannot be certified')
    return metadata[(ipo <= pd.Timestamp(end)) & (out.isna() | (out >= pd.Timestamp(start)))].copy()


def stop_labels_before_cutoff(panel, cutoff='2024-12-31'):
    """Labels on full, unfiltered symbol bars; exactly 22 future observations.

    Slice raw input before making labels so no post-cutoff observation is read.
    Feature/eligibility filtering must occur AFTER joining these labels.
    Label uses future opens relative to anchor close, preserving old definition.
    """
    panel = panel[pd.to_datetime(panel.date) <= pd.Timestamp(cutoff)].copy()
    records = []
    for symbol, group in panel.groupby('symbol'):
        group = group.sort_values('date').reset_index(drop=True)
        for i in range(max(0, len(group) - 22)):
            future = group.iloc[i + 1:i + 23]
            base = float(group.iloc[i].close)
            returns = future.open.to_numpy(float) / base - 1
            if base <= 0 or not np.isfinite(returns).all():
                continue
            stop, profit = np.flatnonzero(returns <= -.07), np.flatnonzero(returns >= .24)
            first_stop = int(stop[0]) if len(stop) else 10000
            first_profit = int(profit[0]) if len(profit) else 10000
            records.append({'symbol': symbol, 'date': group.iloc[i].date,
                            'label_end': future.iloc[-1].date,
                            'stop_first': int(first_stop < first_profit)})
    return pd.DataFrame(records, columns=['symbol', 'date', 'label_end', 'stop_first'])


def capacity_fill(requested, period_volume, used=0, participation=.25):
    """Replay-only ex-post fill cap; NEVER use today's total volume as signal input.

    used aggregates all fills for a symbol in the matching interval. This cap is
    necessary but not sufficient: matching must also enforce cash, T+1, lots,
    suspension, price limits, fees, corporate actions and order timestamps.
    """
    if not 0 <= participation <= 1 or min(requested, period_volume, used) < 0:
        raise ValueError('Invalid capacity inputs')
    return min(int(requested), max(0, int(period_volume * participation) - int(used)))
