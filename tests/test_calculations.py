"""Offline tests for calculations.py using small numbers that can be checked by hand."""
import numpy as np
import pandas as pd
import pytest

import calculations as calc


def q(vals, start="2020-01-01"):
    return pd.Series(vals, index=pd.date_range(start, periods=len(vals), freq="QS"), dtype=float)


def test_spot_is_reciprocal():
    s = calc.spot_S(pd.Series([80.0, 100.0]))
    assert s.tolist() == [0.0125, 0.01]


def test_monthly_change_simple_and_log():
    s = pd.Series([1.0, 1.1])
    assert calc.monthly_change(s).iloc[1] == pytest.approx(0.1)
    assert calc.monthly_change(s, "log").iloc[1] == pytest.approx(np.log(1.1))


def test_quarterly_average_needs_three_months():
    m = pd.Series([80, 82, 84, 86, 88], index=pd.date_range("2024-01-01", periods=5, freq="MS"), dtype=float)
    out = calc.quarterly_average(m)
    assert out.index.tolist() == [pd.Timestamp("2024-01-01")]  # Q2 has only 2 months, dropped
    assert out.iloc[0] == pytest.approx(82.0)


def test_yoy_uses_same_quarter_last_year():
    s = q([100, 100, 100, 100, 110, 120, 100, 100])
    y = calc.yoy(s)
    assert y.iloc[4] == pytest.approx(0.10) and y.iloc[5] == pytest.approx(0.20)
    assert y.iloc[:4].isna().all()


def test_yoy_does_not_bridge_a_missing_quarter():
    s = q([100, 100, 100, 100, 110, 120, 100, 100]).drop(pd.Timestamp("2021-04-01"))
    y = calc.yoy(s)
    assert np.isnan(y.loc[pd.Timestamp("2021-04-01")])  # the missing quarter stays missing


def test_rolling_four_quarter_sum():
    r = calc.rolling_four_quarter_sum(q([1, 2, 3, 4, 5]))
    assert np.isnan(r.iloc[2]) and r.iloc[3] == 10 and r.iloc[4] == 14


def test_trade_panel_total_and_shares():
    p = calc.build_trade_panel(q([60.0, 60.0]), q([40.0, 40.0]), q([10.0, 20.0]))
    assert p["total"].tolist() == [100.0, 100.0]
    assert p["services_share"].tolist() == [0.4, 0.4]
    assert p["computer_share_of_services"].tolist() == [0.25, 0.5]
    assert p["services_ex_computer"].tolist() == [30.0, 20.0]


def test_export_vs_exchange_rate_and_comovement():
    n = 12
    panel = calc.build_trade_panel(q([100.0] * n), q([50 + i for i in range(n)]), q([10.0] * n))
    months = pd.date_range("2020-01-01", periods=3 * n, freq="MS")
    e = pd.Series(np.linspace(70, 90, 3 * n), index=months)
    df = calc.export_vs_exchange_rate(panel, e)
    assert {"goods_yoy", "services_yoy", "computer_yoy", "inr_per_usd_yoy"} <= set(df.columns)
    assert df["goods_yoy"].dropna().eq(0).all()
    r = calc.comovement(df, "services_yoy")
    assert r["n"] >= 5 or np.isnan(r["corr"])


def test_funding_gap_sign_and_difference():
    g = calc.funding_gap(q([-10.0, -20.0]), q([-12.0, -15.0]))
    assert g["FAB_minus_CAB"].tolist() == [-2.0, 5.0]


def test_quarter_label():
    assert calc.quarter_label(pd.Timestamp("2026-04-01")) == "Q2 2026"
    assert calc.quarter_label(pd.Timestamp("2026-01-01")) == "Q1 2026"
