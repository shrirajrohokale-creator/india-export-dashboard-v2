"""Offline tests for the data layer (no network)."""
import json

import pandas as pd
import pytest

import fetch_data as fd


@pytest.fixture()
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(fd, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fd, "LOG_PATH", tmp_path / "refresh_log.json")
    return tmp_path


def good_series(spec, n=100, drop_last=0):
    """A plausible series for this spec (latest value inside its plausibility range)."""
    freq = "QS" if spec["period"] == "Q" else "MS"
    b = spec.get("expect_abs_bn")
    top = (b[0] + b[1]) / 2 if b else 90.0
    vals = [top - (n - 1 - i) * 0.1 for i in range(n)]
    if spec.get("signed"):
        vals = [-v for v in vals]
    s = pd.Series(vals, index=pd.date_range("2000-01-01", periods=n, freq=freq))
    return s.iloc[: len(s) - drop_last] if drop_last else s


def test_parse_period_months_and_quarters():
    assert fd._parse_period("2026-M09") == pd.Timestamp("2026-09-01")
    assert fd._parse_period("2026-09") == pd.Timestamp("2026-09-01")
    assert fd._parse_period("2026-Q2") == pd.Timestamp("2026-04-01")
    assert fd._parse_period("2026-Q4") == pd.Timestamp("2026-10-01")
    assert pd.isna(fd._parse_period("2026-Q5")) and pd.isna(fd._parse_period("junk"))


def test_parse_imf_csv_monthly_unscaled():
    text = "DATAFLOW,TIME_PERIOD,OBS_VALUE\nx,1976-M01,100\nx,1976-M02,101\nx,1976-M03,\n"
    s = fd._parse_imf_csv(text)
    assert s.tolist() == [100.0, 101.0]


def test_parse_imf_csv_scales_with_unit_mult():
    text = "TIME_PERIOD,OBS_VALUE,UNIT_MULT\n2026-Q1,105000,6\n2026-Q2,110000,6\n"
    s = fd._parse_imf_csv(text, to_bn=True)
    assert s.tolist() == pytest.approx([105.0, 110.0])  # 105,000 million = 105 billion
    assert s.index[0] == pd.Timestamp("2026-01-01")


def test_scaling_without_unit_mult_fails_instead_of_guessing():
    with pytest.raises(ValueError, match="UNIT_MULT"):
        fd._parse_imf_csv("TIME_PERIOD,OBS_VALUE\n2026-Q1,105000\n", to_bn=True)


def test_validate_keeps_negative_balances_but_drops_nonpositive_prices():
    idx = pd.date_range("2024-01-01", periods=3, freq="QS")
    bal = pd.Series([-20.0, 5.0, -30.0], index=idx)
    spec_signed = {"signed": True, "expect_abs_bn": (0, 100)}
    s, bad = fd.validate(bal, spec_signed)
    assert s.tolist() == [-20.0, 5.0, -30.0] and bad == 0
    s, bad = fd.validate(pd.Series([1.0, 0.0, 2.0], index=idx), {})
    assert s.tolist() == [1.0, 2.0] and bad == 1


def test_scale_check_rejects_million_fold_error():
    idx = pd.date_range("2024-01-01", periods=3, freq="QS")
    wrong = pd.Series([1.05e8, 1.06e8, 1.07e8], index=idx)  # units read as billions
    with pytest.raises(ValueError, match="scale check failed"):
        fd.validate(wrong, {"expect_abs_bn": (30, 300)})


def test_series_specs_are_complete():
    for spec in fd.SERIES:
        assert {"id", "name", "source", "units", "frequency", "kind", "flow", "key", "period"} <= set(spec)
        assert spec["period"] in ("M", "Q")
        if spec["to_bn"]:
            assert spec["expect_abs_bn"] is not None  # every scaled series has a scale guard
    assert len({s["id"] for s in fd.SERIES}) == len(fd.SERIES) == 6


def test_successful_refresh_writes_csv_and_log(tmp_data, monkeypatch):
    monkeypatch.setattr(fd, "fetch", lambda spec: good_series(spec))
    log = fd.refresh()
    assert log["all_series_ok"] is True and log["last_full_success_utc"]
    for spec in fd.SERIES:
        assert (tmp_data / f"{spec['id']}.csv").exists()
        e = log["series"][spec["id"]]
        assert e["status"] == "ok" and e["rows"] == 100
        assert e["last_success_utc"].endswith("Z") and e["latest_observation_date"]
    assert json.loads((tmp_data / "refresh_log.json").read_text())["all_series_ok"] is True


def test_failed_fetch_keeps_old_data_and_marks_stale(tmp_data, monkeypatch):
    monkeypatch.setattr(fd, "fetch", lambda spec: good_series(spec))
    first = fd.refresh()
    before = (tmp_data / "bop_goods_exports.csv").read_text()

    def boom(spec):
        raise RuntimeError("source down")

    monkeypatch.setattr(fd, "fetch", boom)
    second = fd.refresh()
    assert second["all_series_ok"] is False
    assert second["last_full_success_utc"] == first["last_full_success_utc"]
    e = second["series"]["bop_goods_exports"]
    assert e["status"] == "stale" and "source down" in e["error"]
    assert (tmp_data / "bop_goods_exports.csv").read_text() == before


def test_scale_error_on_refresh_keeps_old_data(tmp_data, monkeypatch):
    monkeypatch.setattr(fd, "fetch", lambda spec: good_series(spec))
    fd.refresh()
    before = (tmp_data / "bop_services_exports.csv").read_text()
    monkeypatch.setattr(fd, "fetch", lambda spec: good_series(spec) * 1e6)
    log = fd.refresh()
    e = log["series"]["bop_services_exports"]
    assert e["status"] == "stale" and "scale check failed" in e["error"]
    assert (tmp_data / "bop_services_exports.csv").read_text() == before


def test_truncated_response_does_not_overwrite(tmp_data, monkeypatch):
    monkeypatch.setattr(fd, "fetch", lambda spec: good_series(spec, 100))
    fd.refresh()
    before = (tmp_data / "bop_current_account.csv").read_text()
    monkeypatch.setattr(fd, "fetch", lambda spec: good_series(spec, 10))
    log = fd.refresh()
    assert log["series"]["bop_current_account"]["status"] == "stale"
    assert (tmp_data / "bop_current_account.csv").read_text() == before


def test_refresh_with_no_new_data_still_counts_as_success(tmp_data, monkeypatch):
    monkeypatch.setattr(fd, "fetch", lambda spec: good_series(spec))
    fd.refresh()
    log = fd.refresh()
    e = log["series"]["bop_computer_services"]
    assert log["all_series_ok"] is True
    assert e["rows_added"] == 0 and e["new_latest_observation"] is False


def test_new_quarter_is_reported_as_new_observation(tmp_data, monkeypatch):
    monkeypatch.setattr(fd, "fetch", lambda spec: good_series(spec, 100, drop_last=1))
    fd.refresh()
    monkeypatch.setattr(fd, "fetch", lambda spec: good_series(spec, 100))
    log = fd.refresh()
    e = log["series"]["bop_financial_account"]
    assert e["rows_added"] == 1 and e["new_latest_observation"] is True


def test_first_run_failure_is_marked_failed_not_faked(tmp_data, monkeypatch):
    def boom(spec):
        raise RuntimeError("blocked")

    monkeypatch.setattr(fd, "fetch", boom)
    log = fd.refresh()
    assert all(e["status"] == "failed" for e in log["series"].values())
    assert not list(tmp_data.glob("*.csv"))
    assert log["last_full_success_utc"] is None
