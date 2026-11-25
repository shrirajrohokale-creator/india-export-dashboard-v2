# India exports and capital flows monitor (version 2)

FINC 470 final project, second version. A Streamlit dashboard that tracks India's goods and services exports, the
IT part of services, the money flows that finance the current account, and the exchange rate, and asks:

> How has India's export mix, especially services, and its financing through capital flows moved with the rupee?

Data refresh automatically through a scheduled GitHub Action. The dashboard only reads the saved CSVs and a refresh log.
All six series come from one primary source, the IMF SDMX API (agency IMF.STA).

## Data (6 series)

| Series id | What | IMF dataflow and key | Frequency | Units |
|---|---|---|---|---|
| `imf_inr_per_usd` | INR per USD | `ER`, `IND.XDC_USD.PA_RT.M` | Monthly (period average) | INR per 1 USD |
| `bop_goods_exports` | Goods exports (credit) | `BOP`, `IND.CD_T.G.USD.Q` | Quarterly | USD billions |
| `bop_services_exports` | Services exports (credit) | `BOP`, `IND.CD_T.S.USD.Q` | Quarterly | USD billions |
| `bop_computer_services` | Computer services exports (credit) | `BOP`, `IND.CD_T.SI2.USD.Q` | Quarterly | USD billions |
| `bop_current_account` | Current account balance (credits less debits) | `BOP`, `IND.NETCD_T.CAB.USD.Q` | Quarterly | USD billions |
| `bop_financial_account` | Financial account balance (assets less liabilities) | `BOP`, `IND.NNAFANIL_T.FAB.USD.Q` | Quarterly | USD billions |

The BOP keys came from a read-only probe of the live IMF API (`tools/probe_export_sources.py`): each returned India data
through Q2 2026. Dimension order is COUNTRY, BOP_ACCOUNTING_ENTRY, INDICATOR, UNIT, FREQUENCY.

**Quarter dates.** Quarters are stored as the first day of the quarter: `2026-04-01` is Q2 2026 (April to June, calendar
quarters). India's fiscal year starts in April, so the RBI calls that quarter Q1 of 2026-27.

**Scaling.** The code converts BOP values to USD billions with the `UNIT_MULT` column the IMF sends. If that column is
missing, the fetch fails with a clear message instead of guessing. A plausibility check (`expect_abs_bn` in `fetch_data.py`)
also refuses a series whose latest value is far outside a sensible range, which would indicate a unit error. These bounds
are guard rails, not data.

## Charts

| # | Chart | Transformation |
|---|---|---|
| 1 | Spot S (USD per INR) with INR per USD as secondary line, monthly change | S = 1/e; (S_t − S_t−1)/S_t−1 or log(S_t/S_t−1) |
| 2 | Goods and services exports, services share | total = goods + services; share = services / total |
| 3 | Computer services vs all other services, with YoY growth | other = services − computer; YoY = x_t / x_t−4 − 1 |
| 4 | Current account vs financial account balance | none (as published, in USD billions) |
| 5 | YoY growth of goods and services exports vs YoY change in INR per USD | quarterly average of the 3 monthly values (quarters with fewer are dropped) |

A rise in S is an INR appreciation. Each chart shows units, frequency, source link, transformation and the latest
observation date of every series it uses. The page header shows the **last successful refresh** separately.

Sign convention (IMF): a negative current account balance is a deficit. A negative financial account balance means net
borrowing from abroad (more money in than out).

## Set up on GitHub

1. Create a repository and upload the contents of this folder (keep the `.github/workflows/` folder).
2. Repository **Settings > Actions > General > Workflow permissions**: choose **Read and write permissions**.
3. Open the **Actions** tab, select **Refresh data**, and click **Run workflow**. This fetches the data, commits
   `data/*.csv` and `data/refresh_log.json`, and writes a status table in the run summary.
4. Take a screenshot of the finished run (evidence of a successful refresh).
5. It then runs daily at 11:17 UTC. GitHub can pause scheduled workflows in repositories with no recent activity.

### View the dashboard

- **Locally:** `pip install -r requirements.txt`, then `streamlit run app.py` (Python 3.12).
- **Hosted:** deploy the repository on Streamlit Community Cloud with main file `app.py`.

## If the first run fails

Run `python fetch_data.py --probe` on your computer. It prints, for every series, first and latest date, row count, latest
value and gaps, and writes nothing. The most likely first-run problem is the scale check: the error message names the series,
the latest value and the range it expected. Do not edit the bounds to make it pass without checking the value against the
IMF Data portal first.

A failed fetch never overwrites existing data. The series is marked stale and the dashboard shows a warning. A refresh
that finds no new data still counts as a success.

## Tests

```
pip install -r requirements-dev.txt
pytest
```

24 offline tests cover the formulas (hand-calculable numbers) and the data layer (quarter parsing, unit scaling, scale guard,
negative balances, stale handling, truncated responses, no-new-data runs). They use synthetic data, not live IMF data.

## What was not tested

The live IMF fetch of these exact series through this code was not run by the author's tooling (the development sandbox
cannot reach the IMF). The keys come from a probe that did reach the IMF, but the CSV column layout (especially `UNIT_MULT`)
is confirmed only when the first workflow run succeeds. The dashboard was smoke-tested on synthetic data only.

## Limitations

- Quarterly balance-of-payments data lag the monthly exchange rate by a quarter or more.
- "Computer services" is a proxy for IT exports, not a measure of AI; the dashboard shows timing, not cause.
- The financial account total mixes portfolio, direct and other investment and reserve changes. These headline series do
  not split them.
- Exports are in US dollars: a weaker rupee does not by itself change the dollar value of dollar-invoiced exports.
- Interest rates, interest parity and the carry trade are not covered.
- Overlapping year-over-year windows are not independent observations; correlations are descriptive.
- Balance-of-payments figures are revised, so a refresh can change past values.
