"""India exports and capital flows monitor (FINC 470 final project, version 2).

Reads only the CSVs and refresh_log.json written by fetch_data.py. Run:  streamlit run app.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import calculations as calc

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
# Append "; calculations checked manually" only after you have completed VERIFICATION.md.
AI_USE_NOTE = "AI use: Claude Sonnet 5.5, Nov 25, 2026."
BLUE, ORANGE, GRAY, GREEN, PURPLE = "#1f77b4", "#d95f02", "#7f7f7f", "#2a9d8f", "#7b3294"
QUESTION = ("How has India's export mix, especially services, and its financing through capital flows "
            "moved with the rupee?")
REQUIRED = ["imf_inr_per_usd", "bop_goods_exports", "bop_services_exports", "bop_computer_services",
            "bop_current_account", "bop_financial_account"]


def load_log() -> dict:
    try:
        return json.loads((DATA_DIR / "refresh_log.json").read_text())
    except Exception:  # noqa: BLE001
        return {}


def load_series(series_id: str) -> pd.Series | None:
    path = DATA_DIR / f"{series_id}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["date"])
    return df.set_index("date")["value"].sort_index()


def fmt_ts(ts: str | None) -> str:
    return ts.replace("T", " ").replace("Z", " UTC") if ts else "never"


def style(fig: go.Figure, height: int = 420) -> go.Figure:
    fig.update_layout(height=height, hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10),
                      legend=dict(orientation="h", y=-0.15))
    return fig


def fig_spot(e: pd.Series, S: pd.Series, kind: str) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.68, 0.32], vertical_spacing=0.06,
                        specs=[[{"secondary_y": True}], [{"secondary_y": False}]])
    fig.add_trace(go.Scatter(x=S.index, y=S, name="S (USD per INR)", line=dict(color=BLUE)),
                  row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=e.index, y=e, name="INR per USD (secondary axis)",
                             line=dict(color=ORANGE, dash="dot")), row=1, col=1, secondary_y=True)
    chg = calc.monthly_change(S, kind) * 100
    label = "Monthly % change in S (simple)" if kind == "simple" else "Monthly log change in S (x100)"
    fig.add_trace(go.Bar(x=chg.index, y=chg, name=label, marker_color=GRAY), row=2, col=1)
    fig.update_yaxes(title_text="USD per INR", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="INR per USD", row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="%", row=2, col=1)
    return style(fig, 520)


def fig_goods_services(p: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.65, 0.35], vertical_spacing=0.07)
    fig.add_trace(go.Scatter(x=p.index, y=p["goods"], name="Goods exports", line=dict(color=BLUE)), row=1, col=1)
    fig.add_trace(go.Scatter(x=p.index, y=p["services"], name="Services exports", line=dict(color=ORANGE)), row=1, col=1)
    fig.add_trace(go.Scatter(x=p.index, y=p["services_share"] * 100, name="Services share of goods + services exports",
                             line=dict(color=GREEN)), row=2, col=1)
    fig.update_yaxes(title_text="USD billions per quarter", row=1, col=1)
    fig.update_yaxes(title_text="% of total", row=2, col=1)
    return style(fig, 520)


def fig_computer(p: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.6, 0.4], vertical_spacing=0.07)
    fig.add_trace(go.Scatter(x=p.index, y=p["computer"], name="Computer services exports", line=dict(color=PURPLE)),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=p.index, y=p["services_ex_computer"], name="All other services exports",
                             line=dict(color=GRAY)), row=1, col=1)
    yy_c, yy_o = calc.yoy(p["computer"]) * 100, calc.yoy(p["services_ex_computer"]) * 100
    fig.add_trace(go.Bar(x=yy_c.index, y=yy_c, name="Computer services, YoY %", marker_color=PURPLE), row=2, col=1)
    fig.add_trace(go.Scatter(x=yy_o.index, y=yy_o, name="Other services, YoY %", line=dict(color=GRAY, dash="dot")),
                  row=2, col=1)
    fig.add_hline(y=0, line_color=GRAY, line_width=1, row=2, col=1)
    fig.update_yaxes(title_text="USD billions per quarter", row=1, col=1)
    fig.update_yaxes(title_text="% vs same quarter last year", row=2, col=1)
    return style(fig, 520)


def fig_flows(g: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=g.index, y=g["CAB"], name="Current account balance (credits − debits)", marker_color=BLUE))
    fig.add_trace(go.Scatter(x=g.index, y=g["FAB"], name="Financial account balance (assets − liabilities)",
                             line=dict(color=ORANGE)))
    fig.add_hline(y=0, line_color=GRAY, line_width=1)
    fig.update_yaxes(title_text="USD billions per quarter")
    return style(fig, 420)


def fig_exports_fx(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["goods_yoy"] * 100, name="Goods exports, YoY %", line=dict(color=BLUE)))
    fig.add_trace(go.Scatter(x=df.index, y=df["services_yoy"] * 100, name="Services exports, YoY %",
                             line=dict(color=ORANGE)))
    fig.add_trace(go.Scatter(x=df.index, y=df["inr_per_usd_yoy"] * 100, name="INR per USD, YoY % (up = rupee weaker)",
                             line=dict(color=GRAY, dash="dash")))
    fig.add_hline(y=0, line_color=GRAY, line_width=1)
    fig.update_yaxes(title_text="% change vs same quarter last year")
    return style(fig, 420)


st.set_page_config(page_title="India exports and capital flows", layout="wide")
st.title("India exports and capital flows monitor")
st.caption(QUESTION)

log = load_log()
series_log = log.get("series", {})
data = {i: load_series(i) for i in REQUIRED}
missing = [i for i, s in data.items() if s is None]
if not log or missing:
    st.error("Some data are missing. Run `python fetch_data.py` locally, or run the **Refresh data** workflow in the "
             "repository's Actions tab, then reload this page.")
    if series_log:
        st.dataframe(pd.DataFrame(series_log.values())[["id", "status", "error"]], hide_index=True)
    st.stop()

stale = [e["id"] for e in series_log.values() if e.get("status") != "ok"]
c1, c2, c3 = st.columns(3)
c1.metric("Last successful refresh (all series)", fmt_ts(log.get("last_full_success_utc")))
c2.metric("Last refresh attempt", fmt_ts(log.get("last_run_utc")))
c3.metric("Series status", "All current" if not stale else f"{len(stale)} stale or failed")
if stale:
    st.warning("Showing last good data for: " + ", ".join(stale) + ". See the status table for the error.")
with st.expander("Series status: latest observation vs last refresh", expanded=False):
    tbl = pd.DataFrame([{
        "Series": e["name"], "Source": e["source"], "Frequency": e["frequency"], "Units": e["units"],
        "Latest observation": e.get("latest_observation_date"),
        "Last successful fetch (UTC)": fmt_ts(e.get("last_success_utc")),
        "Status": e.get("status"), "Rows": e.get("rows"),
    } for e in series_log.values()])
    st.dataframe(tbl, hide_index=True, width="stretch")
    st.caption("Quarterly dates show the first day of the quarter (2026-04-01 = Q2 2026). The latest observation date "
               "is the newest data point published by the source, not the refresh time.")

e_m = data["imf_inr_per_usd"]
S_m = calc.spot_S(e_m)
panel_all = calc.build_trade_panel(data["bop_goods_exports"], data["bop_services_exports"], data["bop_computer_services"])
flows_all = calc.funding_gap(data["bop_current_account"], data["bop_financial_account"])
if len(panel_all) < 12:
    st.error("Not enough overlapping quarterly export data (need at least 12 quarters).")
    st.stop()

with st.sidebar:
    st.header("Settings")
    years = list(range(panel_all.index.min().year, panel_all.index.max().year + 1))
    start_year = st.select_slider("Start year", options=years, value=2010 if 2010 in years else years[0])
    chg_kind = st.radio("Chart 1 monthly change", ["simple", "log"], horizontal=True)
start = pd.Timestamp(f"{start_year}-01-01")

panel = panel_all.loc[start:]
flows = flows_all.loc[start:]
fx = calc.export_vs_exchange_rate(panel_all, e_m).loc[start:]


def sources(ids: list[str], units: str, freq: str, transform: str) -> None:
    lines = [f"**Units:** {units} · **Frequency:** {freq} · **Transformation:** {transform}", ""]
    for i in ids:
        e = series_log.get(i, {})
        latest = e.get("latest_observation_date")
        shown = calc.quarter_label(pd.Timestamp(latest)) if latest and e.get("frequency") == "Quarterly" else latest
        lines.append(f"- {e.get('name', i)}: [{e.get('source', '')}]({e.get('source_url', '')}), "
                     f"latest observation **{shown or 'n/a'}**")
    st.markdown("\n".join(lines))


st.header("1. Spot exchange rate")
st.plotly_chart(fig_spot(e_m.loc[start:], S_m.loc[start:], chg_kind), width="stretch")
sources(["imf_inr_per_usd"], "S in USD per INR (left); INR per USD (right); changes in %", "Monthly (IMF period averages)",
        "S = 1/e where e = INR per USD; % change = (S_t − S_t−1)/S_t−1, or log(S_t/S_t−1)")

st.header("2. Goods and services exports")
st.plotly_chart(fig_goods_services(panel), width="stretch")
last = panel.iloc[-1]
m1, m2, m3 = st.columns(3)
m1.metric(f"Goods exports, {calc.quarter_label(panel.index[-1])}", f"${last['goods']:.1f} bn")
m2.metric("Services exports", f"${last['services']:.1f} bn")
m3.metric("Services share of total", f"{last['services_share'] * 100:.0f}%")
sources(["bop_goods_exports", "bop_services_exports"], "USD billions per quarter; share in %", "Quarterly",
        "Total = goods + services; share = services / total. Balance-of-payments basis, so values differ from customs data")

st.header("3. Computer services exports (the IT and AI-exposed part of services)")
st.plotly_chart(fig_computer(panel), width="stretch")
st.caption("IMF line 'Computer services' only. It excludes telecommunications and information services, and it does "
           "not isolate AI: it is a close proxy for software and IT-services exports.")
sources(["bop_computer_services", "bop_services_exports"], "USD billions per quarter; growth in %", "Quarterly",
        "Other services = services − computer services; YoY = x_t / x_t−4 − 1")

st.header("4. Money flows: current account and financial account")
st.plotly_chart(fig_flows(flows), width="stretch")
st.caption("Sign convention (IMF): a negative current account balance is a deficit. A negative financial account "
           "balance means net borrowing from abroad, that is, more money flowed in than out. The financial account "
           "includes changes in official reserves. In principle current account + capital account + errors and "
           "omissions = financial account.")
sources(["bop_current_account", "bop_financial_account"], "USD billions per quarter", "Quarterly",
        "None (levels as published, scaled to billions using the IMF's UNIT_MULT)")

st.header("5. Exports and the exchange rate")
st.plotly_chart(fig_exports_fx(fx), width="stretch")
cs, cg = calc.comovement(fx, "services_yoy"), calc.comovement(fx, "goods_yoy")
k1, k2, k3 = st.columns(3)
k1.metric("Quarters compared", cs["n"])
k2.metric("Correlation: services growth vs INR per USD change", "n/a" if np.isnan(cs["corr"]) else f"{cs['corr']:.2f}")
k3.metric("Correlation: goods growth vs INR per USD change", "n/a" if np.isnan(cg["corr"]) else f"{cg['corr']:.2f}")
st.caption("Descriptive only. Overlapping year-over-year windows are not independent observations, and a correlation "
           "does not show that the exchange rate caused export growth. The USD value of exports invoiced in dollars "
           "need not rise when the rupee weakens.")
sources(["imf_inr_per_usd", "bop_goods_exports", "bop_services_exports"], "% change vs same quarter last year", "Quarterly",
        "INR per USD is the average of the 3 monthly IMF values in each quarter (quarters with fewer than 3 months "
        "are left out); YoY = x_t / x_t−4 − 1")

with st.expander("Quotation convention and methods", expanded=False):
    st.markdown("""
- **Convention (class):** S = USD per unit of foreign currency, here **USD per INR**. A rise in S is an INR *appreciation*.
  Sources quote **INR per USD (e)**, so S = 1/e. INR per USD is shown as a secondary line in chart 1.
- **Balance-of-payments series** are in current US dollars. The IMF delivers them with a unit multiplier, which the
  code applies to convert to billions; if the multiplier is missing, the fetch fails instead of guessing.
- **Growth rates** are year over year (same quarter a year earlier), so seasonality does not distort them.
""")
with st.expander("Limitations", expanded=False):
    st.markdown("""
- Quarterly balance-of-payments data are published with a lag of a quarter or more, so they end earlier than the monthly exchange rate.
- 'Computer services' is a proxy for IT and software exports, not a measure of AI. The dashboard shows timing, not cause.
- The financial account total mixes portfolio, direct and other investment and reserves. The IMF headline series used here
  do not split them, so the dashboard cannot say what kind of money flowed.
- Exports are measured in US dollars. A weaker rupee does not by itself change the dollar value of dollar-invoiced exports.
- Interest rates, interest parity and the carry trade are not covered.
- Balance-of-payments figures are revised; the latest refresh shows the revised values.
""")

export = panel.join(flows, how="outer").join(fx, how="left")
st.download_button("Download quarterly data for the selected sample (CSV)", export.to_csv().encode("utf-8"),
                   file_name=f"india_exports_quarterly_{start_year}.csv", mime="text/csv")
st.caption(AI_USE_NOTE)
