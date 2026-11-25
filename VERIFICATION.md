# Verification (fill in after the first successful refresh)

Compare **one observation per series** with its original publisher. Quote the dashboard value and the source value.

| Series | Period | Dashboard value | Original source | Source value | Result |
|---|---|---|---|---|---|
| INR per USD (monthly average) | | | IMF Data portal; independent check: average of the Fed H.10 daily rates for that month | | |
| Goods exports | | | RBI quarterly balance of payments release and the IMF Data portal | | |
| Services exports | | | same | | |
| Computer services exports | | | same | | |
| Current account balance | | | same | | |
| Financial account balance | | | same | | |

Notes for the comparison:
- IMF quarters are **calendar quarters**; RBI uses fiscal quarters. IMF Q2 2026 (April to June) is the RBI's Q1 of 2026-27.
- The RBI publishes in USD million; the dashboard shows USD billions.
- Sign: the IMF reports the current account as credits less debits (a deficit is negative). The financial account is
  assets less liabilities (net borrowing from abroad is negative). The RBI may present the same flows with the opposite sign.
- "Computer services" in the IMF series may not match the RBI's "software services" line one for one. Say which line you
  compared.
- Balance-of-payments data are revised, so compare the vintage the dashboard shows with the current published figure.

## Independent calculations

Recompute one value per chart from the downloaded CSV files and compare with the dashboard:

| Chart | Calculation | Dashboard |
|---|---|---|
| 1 | S = 1 / (INR per USD) for the latest month | |
| 2 | services / (goods + services) for the latest quarter | |
| 3 | YoY for computer services: latest quarter / same quarter a year earlier − 1 | |
| 4 | financial account − current account for the latest quarter | |
| 5 | YoY change in the quarterly average of INR per USD (average of the 3 months) | |
