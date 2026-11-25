"""All formulas for the India exports and capital-flows dashboard. No network, no Streamlit.

Conventions (class): S = USD per INR, so a rise in S is an INR appreciation; e = INR per USD, S = 1/e.
Quarterly BOP series are stored at the first day of their quarter (2026-04-01 = Q2 2026), in USD billions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def spot_S(inr_per_usd: pd.Series) -> pd.Series:
    """S = 1 / e (USD per INR)."""
    return 1.0 / inr_per_usd


def monthly_change(s: pd.Series, kind: str = "simple") -> pd.Series:
    """simple: (S_t - S_t-1)/S_t-1 ; log: log(S_t / S_t-1)."""
    if kind == "log":
        return np.log(s / s.shift(1))
    return s.pct_change()


def quarterly_average(monthly: pd.Series) -> pd.Series:
    """Average of the three months in each quarter; a quarter with fewer than 3 months is left out (NaN)."""
    g = monthly.resample("QS")
    out = g.mean()
    out[g.count() < 3] = np.nan
    return out.dropna()


def yoy(s: pd.Series, periods: int = 4) -> pd.Series:
    """Year-over-year change for quarterly data: s_t / s_t-4 - 1. Requires an unbroken quarterly index."""
    s = s.asfreq("QS")
    return s / s.shift(periods) - 1.0


def rolling_four_quarter_sum(s: pd.Series) -> pd.Series:
    """Trailing 4-quarter sum (a flow over the last year); NaN until 4 consecutive quarters exist."""
    s = s.asfreq("QS")
    return s.rolling(4).sum()


def share(part: pd.Series, total: pd.Series) -> pd.Series:
    """part / total on common dates."""
    a, b = part.align(total, join="inner")
    return a / b


def quarter_label(ts: pd.Timestamp) -> str:
    return f"Q{(ts.month - 1) // 3 + 1} {ts.year}"


def build_trade_panel(goods: pd.Series, services: pd.Series, computer: pd.Series) -> pd.DataFrame:
    """Quarterly export panel in USD billions. Total = goods + services (exports of goods and services)."""
    p = pd.concat({"goods": goods, "services": services, "computer": computer}, axis=1).dropna().asfreq("QS")
    p["total"] = p["goods"] + p["services"]
    p["services_share"] = p["services"] / p["total"]
    p["computer_share_of_services"] = p["computer"] / p["services"]
    p["services_ex_computer"] = p["services"] - p["computer"]
    return p


def export_vs_exchange_rate(panel: pd.DataFrame, inr_per_usd_monthly: pd.Series) -> pd.DataFrame:
    """YoY growth of USD exports vs YoY change in the quarterly-average INR per USD (positive = rupee weaker)."""
    e_q = quarterly_average(inr_per_usd_monthly)
    out = pd.DataFrame({
        "goods_yoy": yoy(panel["goods"]),
        "services_yoy": yoy(panel["services"]),
        "computer_yoy": yoy(panel["computer"]),
        "inr_per_usd_yoy": yoy(e_q),
    })
    return out.dropna(how="all")


def comovement(df: pd.DataFrame, export_col: str) -> dict:
    """Descriptive co-movement between an export growth column and the YoY change in INR per USD."""
    d = df[[export_col, "inr_per_usd_yoy"]].dropna()
    if len(d) < 8:
        return {"n": len(d), "corr": float("nan")}
    return {"n": int(len(d)), "corr": float(d[export_col].corr(d["inr_per_usd_yoy"]))}


def funding_gap(cab: pd.Series, fab: pd.Series) -> pd.DataFrame:
    """Financial account balance minus current account balance (USD bn).

    In the IMF's sign convention CAB = credits - debits (negative = deficit) and FAB = net acquisition of financial
    assets - net incurrence of liabilities (negative = net borrowing from abroad). In principle CAB + capital account
    + errors and omissions = FAB, so the gap is mostly errors and omissions and the capital account.
    """
    d = pd.concat({"CAB": cab, "FAB": fab}, axis=1).dropna()
    d["FAB_minus_CAB"] = d["FAB"] - d["CAB"]
    return d
