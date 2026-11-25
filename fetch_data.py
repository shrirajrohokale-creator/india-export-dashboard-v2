#!/usr/bin/env python3
"""Fetch the dashboard's source series and write data/*.csv + data/refresh_log.json.

Series (all from the IMF SDMX API, agency IMF.STA; key order is COUNTRY.[ENTRY.]INDICATOR.[UNIT|SECTOR].FREQUENCY):
  imf_inr_per_usd        ER     IND.XDC_USD.PA_RT.M                         monthly, INR per USD (period average)
  bop_goods_exports      BOP    IND.CD_T.G.USD.Q                            quarterly, goods exports (credit), USD
  bop_services_exports   BOP    IND.CD_T.S.USD.Q                            quarterly, services exports (credit), USD
  bop_computer_services  BOP    IND.CD_T.SI2.USD.Q                          quarterly, computer services exports, USD
  bop_current_account    BOP    IND.NETCD_T.CAB.USD.Q                       quarterly, current account balance, USD
  bop_financial_account  BOP    IND.NNAFANIL_T.FAB.USD.Q                    quarterly, financial account balance, USD
These keys were found by a read-only probe of the live IMF API (see README). The BOP/IRFCL values are scaled to USD
billions using the response's scale column (UNIT_MULT or SCALE); if that column is missing the fetch FAILS rather than guessing.

Rules this script follows:
  * A failed fetch NEVER overwrites good data. The old CSV is kept and the series is marked "stale".
  * A response with far fewer rows than the stored file is treated as a failure.
  * No bundled snapshots or hard-coded values are ever substituted.
  * "last_success_utc" (when we last fetched OK) is stored separately from
    "latest_observation_date" (the newest data point in the series).

Usage:
  python fetch_data.py            # refresh everything, write CSVs and the log
  python fetch_data.py --probe    # read-only check of every source (no files written)
  python fetch_data.py --only fred_dexinus
Exit code is 1 if any series failed to refresh.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
LOG_PATH = DATA_DIR / "refresh_log.json"

IMF_BASE = "https://api.imf.org/external/sdmx/3.0"
IMF_AGENCY = "IMF.STA"
IMF_VERSIONS = ["+", "~"]  # "+" = latest stable version in SDMX 3.0
IMF_START = "2000-01"
IMF_HEADERS_CSV = {"Accept": "application/vnd.sdmx.data+csv;version=2.0.0, text/csv;q=0.9"}
IMF_HEADERS_JSON = {"Accept": "application/vnd.sdmx.data+json;version=2.0.0, application/json;q=0.9"}
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
USER_AGENT = "india-exports-dashboard/1.0 (student project; contact via GitHub repo)"
TIMEOUT = 60
MIN_ROWS_RATIO = 0.9  # refuse to overwrite if the new pull has <90% of the stored rows

SERIES = [
    {
        "id": "imf_inr_per_usd",
        "name": "INR per USD, monthly average",
        "source": "IMF (SDMX API, dataflow IMF.STA/ER)",
        "source_url": "https://data.imf.org",
        "units": "INR per 1 USD",
        "frequency": "Monthly (period average)",
        "kind": "imf", "flow": "ER", "key": "IND.XDC_USD.PA_RT.M",
        "period": "M", "to_bn": False, "signed": False, "expect_abs_bn": None,
    },
    {
        "id": "bop_goods_exports",
        "name": "India goods exports (BOP credit)",
        "source": "IMF (SDMX API, dataflow IMF.STA/BOP)",
        "source_url": "https://data.imf.org",
        "units": "USD billions",
        "frequency": "Quarterly",
        "kind": "imf", "flow": "BOP", "key": "IND.CD_T.G.USD.Q",
        "period": "Q", "to_bn": True, "signed": False, "expect_abs_bn": (30, 300),
    },
    {
        "id": "bop_services_exports",
        "name": "India services exports (BOP credit)",
        "source": "IMF (SDMX API, dataflow IMF.STA/BOP)",
        "source_url": "https://data.imf.org",
        "units": "USD billions",
        "frequency": "Quarterly",
        "kind": "imf", "flow": "BOP", "key": "IND.CD_T.S.USD.Q",
        "period": "Q", "to_bn": True, "signed": False, "expect_abs_bn": (30, 300),
    },
    {
        "id": "bop_computer_services",
        "name": "India computer services exports (BOP credit)",
        "source": "IMF (SDMX API, dataflow IMF.STA/BOP)",
        "source_url": "https://data.imf.org",
        "units": "USD billions",
        "frequency": "Quarterly",
        "kind": "imf", "flow": "BOP", "key": "IND.CD_T.SI2.USD.Q",
        "period": "Q", "to_bn": True, "signed": False, "expect_abs_bn": (5, 150),
    },
    {
        "id": "bop_current_account",
        "name": "India current account balance (credits less debits)",
        "source": "IMF (SDMX API, dataflow IMF.STA/BOP)",
        "source_url": "https://data.imf.org",
        "units": "USD billions",
        "frequency": "Quarterly",
        "kind": "imf", "flow": "BOP", "key": "IND.NETCD_T.CAB.USD.Q",
        "period": "Q", "to_bn": True, "signed": True, "expect_abs_bn": (0, 100),
    },
    {
        "id": "bop_financial_account",
        "name": "India financial account balance (assets less liabilities)",
        "source": "IMF (SDMX API, dataflow IMF.STA/BOP)",
        "source_url": "https://data.imf.org",
        "units": "USD billions",
        "frequency": "Quarterly",
        "kind": "imf", "flow": "BOP", "key": "IND.NNAFANIL_T.FAB.USD.Q",
        "period": "Q", "to_bn": True, "signed": True, "expect_abs_bn": (0, 150),
    },
]
SPEC_BY_ID = {s["id"]: s for s in SERIES}


# --------------------------------------------------------------------------- #
# HTTP helper
# --------------------------------------------------------------------------- #
def _http_get(url: str, params: dict | None = None, headers: dict | None = None, retries: int = 3):
    """GET with retries on network errors and 5xx. Returns (response | None, message)."""
    last = "no response"
    for attempt in range(retries):
        try:
            r = requests.get(
                url, params=params, timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT, **(headers or {})},
            )
        except requests.RequestException as exc:
            last = f"network error: {exc}"
        else:
            if r.status_code < 500:
                return r, "ok"
            last = f"HTTP {r.status_code}"
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    return None, last


# --------------------------------------------------------------------------- #
# IMF parsing (carried over from the Real Exchange Rate app, which ran live)
# --------------------------------------------------------------------------- #
def _parse_period(value) -> pd.Timestamp:
    """'1976-M01' / '1976-01' -> first day of that month; '2026-Q2' -> first day of that quarter."""
    text = str(value).strip()
    q = re.match(r"^(\d{4})-?Q([1-4])$", text)
    if q:
        return pd.Timestamp(year=int(q.group(1)), month=3 * (int(q.group(2)) - 1) + 1, day=1)
    m = re.match(r"^(\d{4})-?M?(\d{1,2})$", text)
    if not m:
        return pd.NaT
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return pd.NaT
    return pd.Timestamp(year=year, month=month, day=1)


def _to_series(periods: pd.Series, values: pd.Series) -> pd.Series:
    idx = periods.map(_parse_period)
    s = pd.Series(pd.to_numeric(values, errors="coerce").to_numpy(), index=pd.DatetimeIndex(idx))
    s = s[s.index.notna()].dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


_SCALE_NAMES = {"units": 0, "unit": 0, "ones": 0, "thousands": 3, "thousand": 3, "millions": 6, "million": 6,
                "billions": 9, "billion": 9, "trillions": 12, "trillion": 12}


def _scale_power(value) -> float:
    """Scale cell -> power of ten. Accepts 0/3/6/9, '6', or a name like 'Millions'. Anything else -> NaN."""
    if pd.isna(value):
        return 0.0  # an empty scale cell means no scaling
    text = str(value).strip().lower()
    if text in _SCALE_NAMES:
        return float(_SCALE_NAMES[text])
    try:
        return float(text)
    except ValueError:
        return float("nan")


def _parse_imf_csv(text: str, to_bn: bool = False) -> pd.Series:
    df = pd.read_csv(io.StringIO(text))
    cols = {c.upper().split(":")[0].strip(): c for c in df.columns}
    t_col, v_col = cols.get("TIME_PERIOD"), cols.get("OBS_VALUE")
    if t_col is None or v_col is None:
        return pd.Series(dtype=float)
    values = pd.to_numeric(df[v_col], errors="coerce")
    if to_bn:
        # Scale to USD billions with the response's own scale column (power of ten): UNIT_MULT, or SCALE in the
        # IMF's SDMX 3.0 CSV. Never guess it. The magnitude guard in validate() is a second check on the result.
        m_col = cols.get("UNIT_MULT") or cols.get("SCALE")
        if m_col is None:
            raise ValueError("no UNIT_MULT or SCALE column in the response, cannot scale to USD billions safely; "
                             f"columns are {list(df.columns)[:12]}, first value {values.dropna().iloc[:1].tolist()}")
        mult = df[m_col].map(_scale_power)
        if mult.isna().any():
            bad = df.loc[mult.isna(), m_col].astype(str).unique()[:5].tolist()
            raise ValueError(f"cannot read the scale column {m_col!r}: values {bad}")
        values = values * (10.0 ** mult) / 1e9
    return _to_series(df[t_col], values)


def _parse_imf_json(payload: dict) -> pd.Series:
    """SDMX-JSON (2.0 style) for a single-series response."""
    data = payload.get("data", payload)
    structure = data["structures"][0] if "structures" in data else data["structure"]
    time_values = structure["dimensions"]["observation"][0]["values"]
    periods, values = [], []
    for ds in data["dataSets"]:
        for series in ds.get("series", {}).values():
            for idx, obs in series.get("observations", {}).items():
                tv = time_values[int(idx)]
                periods.append(tv.get("id") or tv.get("value"))
                values.append(obs[0])
    return _to_series(pd.Series(periods), pd.Series(values))


def fetch_imf(flow: str, key: str, to_bn: bool = False) -> pd.Series:
    msgs: list[str] = []  # keep EVERY failure reason, so the log shows the CSV attempt too
    for version in IMF_VERSIONS:
        url = f"{IMF_BASE}/data/dataflow/{IMF_AGENCY}/{flow}/{version}/{key}"
        for fmt, headers in (("csv", IMF_HEADERS_CSV), ("json", IMF_HEADERS_JSON)):
            tag = f"{version}/{fmt}"
            r, msg = _http_get(url, params={"startPeriod": IMF_START}, headers=headers)
            if r is None:
                msgs.append(f"[{tag}] {msg}")
                continue
            if r.status_code == 404:
                msgs.append(f"[{tag}] no data (404)")
                break  # this version has no such series; try the next version
            if r.status_code != 200:
                msgs.append(f"[{tag}] HTTP {r.status_code}")
                continue
            try:
                ctype = r.headers.get("Content-Type", "").lower()
                if "json" in ctype:
                    if to_bn:
                        msgs.append(f"[{tag}] got JSON, but scaling needs the CSV format")
                        continue
                    s = _parse_imf_json(r.json())
                else:
                    s = _parse_imf_csv(r.text, to_bn)
            except Exception as exc:  # noqa: BLE001
                msgs.append(f"[{tag}] could not parse response ({exc}); content-type {ctype!r}; "
                            f"starts with {r.text[:160]!r}")
                continue
            if len(s):
                return s
            msgs.append(f"[{tag}] empty series; content-type {ctype!r}; starts with {r.text[:160]!r}")
    raise RuntimeError(f"IMF {flow}/{key}: " + " | ".join(msgs))


# --------------------------------------------------------------------------- #
# FRED / Federal Reserve H.10
# --------------------------------------------------------------------------- #
def _parse_fred_csv(text: str, series_id: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text))
    if df.shape[1] < 2:
        raise ValueError("unexpected FRED CSV layout")
    date_col = df.columns[0]  # 'observation_date' (new) or 'DATE' (old)
    val_col = series_id if series_id in df.columns else df.columns[1]
    s = pd.Series(
        pd.to_numeric(df[val_col], errors="coerce").to_numpy(),  # '.' (no data) -> NaN
        index=pd.to_datetime(df[date_col], errors="coerce"),
    )
    s = s[s.index.notna()].dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


def fetch_fred(series_id: str) -> pd.Series:
    r, msg = _http_get(FRED_CSV_URL, params={"id": series_id})
    if r is None:
        raise RuntimeError(f"FRED {series_id}: {msg}")
    if r.status_code != 200:
        raise RuntimeError(f"FRED {series_id}: HTTP {r.status_code}")
    s = _parse_fred_csv(r.text, series_id)
    if s.empty:
        raise RuntimeError(f"FRED {series_id}: empty series")
    return s


def fetch(spec: dict) -> pd.Series:
    if spec["kind"] == "imf":
        return fetch_imf(spec["flow"], spec["key"], spec.get("to_bn", False))
    if spec["kind"] == "fred":
        return fetch_fred(spec["fred_id"])
    raise ValueError(f"unknown kind {spec['kind']}")


# --------------------------------------------------------------------------- #
# Validation, storage, log
# --------------------------------------------------------------------------- #
def validate(s: pd.Series, spec: dict | None = None) -> tuple[pd.Series, int]:
    """Clean, sorted, unique-index series plus the number of non-positive values dropped.

    Signed series (balances) keep negatives. If the spec has "expect_abs_bn" = (lo, hi), the latest value in USD billions
    must fall inside it. That is only a guard against a unit/scale error (e.g. millions read as units); it never
    replaces or edits data.
    """
    spec = spec or {}
    if s.empty:
        raise ValueError("series is empty")
    s = s[~s.index.duplicated(keep="last")].sort_index()
    bad = 0
    if not spec.get("signed"):
        bad = int((s <= 0).sum())
        s = s[s > 0]
        if s.empty:
            raise ValueError("no positive values")
    bounds = spec.get("expect_abs_bn")
    if bounds:
        latest = abs(float(s.iloc[-1]))
        if not bounds[0] <= latest <= bounds[1]:
            raise ValueError(f"scale check failed: latest value {s.iloc[-1]:.4g} (USD bn) is outside the plausible "
                             f"range {bounds[0]} to {bounds[1]}; check the units before trusting this series")
    return s, bad


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _csv_path(series_id: str) -> Path:
    return DATA_DIR / f"{series_id}.csv"


def _count_rows(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return len(pd.read_csv(path))
    except Exception:  # noqa: BLE001
        return 0


def _write_csv(s: pd.Series, path: Path) -> None:
    tmp = path.with_suffix(".csv.tmp")
    s.rename("value").rename_axis("date").to_csv(tmp, date_format="%Y-%m-%d")
    os.replace(tmp, path)


def load_log() -> dict:
    try:
        return json.loads(LOG_PATH.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _write_log(log: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LOG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(log, indent=2, sort_keys=False) + "\n")
    os.replace(tmp, LOG_PATH)


def refresh_one(spec: dict, prev_entry: dict) -> tuple[dict, bool]:
    """Refresh one series. On any failure the stored CSV is left untouched."""
    now = now_iso()
    path = _csv_path(spec["id"])
    entry = {
        "id": spec["id"], "name": spec["name"], "source": spec["source"],
        "source_url": spec["source_url"], "units": spec["units"], "frequency": spec["frequency"],
        "file": f"data/{spec['id']}.csv",
        "last_attempt_utc": now,
        # carried over from the previous run until this run succeeds:
        "last_success_utc": prev_entry.get("last_success_utc"),
        "first_observation_date": prev_entry.get("first_observation_date"),
        "latest_observation_date": prev_entry.get("latest_observation_date"),
        "rows": prev_entry.get("rows"),
    }
    prev_rows = _count_rows(path)
    try:
        s, dropped = validate(fetch(spec), spec)
        if prev_rows and len(s) < MIN_ROWS_RATIO * prev_rows:
            raise ValueError(f"fetched {len(s)} rows but {prev_rows} are stored; refusing to overwrite")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _write_csv(s, path)
    except Exception as exc:  # noqa: BLE001
        entry["status"] = "stale" if path.exists() else "failed"
        entry["error"] = f"{type(exc).__name__}: {exc}"
        return entry, False

    latest = s.index.max().strftime("%Y-%m-%d")
    entry.update(
        status="ok",
        error="",
        last_success_utc=now,
        first_observation_date=s.index.min().strftime("%Y-%m-%d"),
        latest_observation_date=latest,
        rows=int(len(s)),
        rows_added=int(len(s) - prev_rows) if prev_rows else int(len(s)),
        new_latest_observation=bool(latest != prev_entry.get("latest_observation_date")),
        notes=f"dropped {dropped} non-positive value(s)" if dropped else "",
    )
    return entry, True


def refresh(only: list[str] | None = None) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    prev = load_log()
    prev_series = prev.get("series", {})
    started = now_iso()
    series_log, all_ok = {}, True
    for spec in SERIES:
        if only and spec["id"] not in only:
            if spec["id"] in prev_series:
                series_log[spec["id"]] = prev_series[spec["id"]]
            continue
        entry, ok = refresh_one(spec, prev_series.get(spec["id"], {}))
        series_log[spec["id"]] = entry
        all_ok = all_ok and ok
        print(f"[{entry['status']:6}] {spec['id']:18} latest={entry.get('latest_observation_date')} "
              f"rows={entry.get('rows')} {entry.get('error', '')}")
    finished = now_iso()
    full = all_ok and not only
    log = {
        "run_started_utc": started,
        "last_run_utc": finished,
        "all_series_ok": all_ok,
        # Only a run that refreshed EVERY series successfully counts as a full success.
        "last_full_success_utc": finished if full else prev.get("last_full_success_utc"),
        "series": series_log,
    }
    _write_log(log)
    return log


def write_step_summary(log: dict) -> None:
    """Append a markdown table to the GitHub Actions run summary (useful as evidence)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "### Data refresh",
        f"Last run (UTC): `{log['last_run_utc']}`  ",
        f"Last full success (UTC): `{log.get('last_full_success_utc')}`",
        "",
        "| Series | Status | Latest observation | Rows | Last success (UTC) |",
        "|---|---|---|---|---|",
    ]
    for e in log["series"].values():
        lines.append(f"| {e['id']} | {e['status']} | {e.get('latest_observation_date')} | "
                     f"{e.get('rows')} | {e.get('last_success_utc')} |")
        if e.get("error"):
            lines.append(f"|  | error: {e['error']} | | | |")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# Probe (read-only)
# --------------------------------------------------------------------------- #
def probe() -> int:
    """Print availability facts for every source. Writes nothing."""
    failures = 0
    for spec in SERIES:
        print(f"\n== {spec['id']}  ({spec['source']})")
        try:
            s, dropped = validate(fetch(spec), spec)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"   FAILED: {type(exc).__name__}: {exc}")
            continue
        print(f"   first={s.index.min():%Y-%m-%d} latest={s.index.max():%Y-%m-%d} rows={len(s)} latest value={s.iloc[-1]:.4g} "
              f"non-positive dropped={dropped}")
        if spec["kind"] == "imf":
            full = pd.date_range(s.index.min(), s.index.max(), freq="QS" if spec.get("period") == "Q" else "MS")
            missing = full.difference(s.index)
            print(f"   missing periods inside range: {len(missing)}"
                  + (f" (first few: {[d.strftime('%Y-%m') for d in missing[:5]]})" if len(missing) else ""))
            chg = (s.pct_change().abs() if not spec.get("signed") else s.diff().abs() / s.abs().median()).dropna().sort_values(ascending=False).head(3)
            print("   largest period-on-period moves (look for series breaks): "
                  + ", ".join(f"{d:%Y-%m} {v * 100:.1f}%" for d, v in chg.items()))
        else:
            last_year = s[s.index >= s.index.max() - pd.Timedelta(days=365)]
            print(f"   observations in the last 365 days: {len(last_year)}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", action="store_true", help="read-only availability check")
    ap.add_argument("--only", nargs="+", choices=list(SPEC_BY_ID), help="refresh only these series")
    args = ap.parse_args(argv)
    if args.probe:
        return probe()
    log = refresh(args.only)
    write_step_summary(log)
    return 0 if log["all_series_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
