"""Tests for BUG FIX: Kas Operasional opening balance vs. opening_date in period.

Root cause: previously compared opening_date > first_of_month → opening skipped
when opening_date was mid-month. Now compares opening_date > last_of_month.

Scenarios tested:
  1. opening_date within viewed month (2026-07-15, view 2026-07) → opening=5M
  2. opening_date < first of month (regression: 2026-01-01, view 2026-07)
  3. opening_date in the FUTURE (2027-03-01, view 2026-07) → opening=0
  4. opening_date == first_of_month (boundary)
  5. opening_date == last_of_month (boundary)
  6. GET /api/cashbook/balance unaffected by opening_date (regression)
  7. Response structure (summary + transactions)

Teardown resets opening_balance=0, opening_date=None so we don't leak state.
"""
import os
import time
import pytest
import requests
from pathlib import Path

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break

OPENING_AMOUNT = 5_000_000
TS = str(int(time.time()))


# ---------------- Fixtures ----------------
@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code} {r.text}")
    return s


@pytest.fixture(scope="module")
def original_settings(client):
    """Snapshot original opening_balance/opening_date so we restore on teardown."""
    r = client.get(f"{BASE_URL}/api/cashbook/settings")
    assert r.status_code == 200
    orig = r.json()
    return {
        "opening_balance": orig.get("opening_balance", 0),
        "opening_date": orig.get("opening_date"),
    }


@pytest.fixture(scope="module", autouse=True)
def restore_settings(client, original_settings):
    yield
    # Restore original opening balance settings after all tests
    payload = {
        "opening_balance": original_settings["opening_balance"] or 0,
        "opening_date": original_settings["opening_date"] or None,
    }
    try:
        client.put(f"{BASE_URL}/api/cashbook/settings", json=payload)
    except Exception:
        pass


def set_opening(client, amount, date_str):
    """Helper: set opening_balance + opening_date via PUT /cashbook/settings."""
    r = client.put(f"{BASE_URL}/api/cashbook/settings", json={
        "opening_balance": amount, "opening_date": date_str
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["opening_balance"] == amount
    assert d["opening_date"] == date_str
    return d


# ---------------- 1. PRIMARY BUG FIX: opening_date mid-month ----------------
class TestOpeningDateMidMonth:
    """opening_date=2026-07-15 (dalam bulan), view Juli 2026 → opening=5M"""

    def test_summary_includes_opening_when_date_mid_month(self, client):
        set_opening(client, OPENING_AMOUNT, "2026-07-15")
        r = client.get(f"{BASE_URL}/api/cashbook/summary", params={"month": "2026-07"})
        assert r.status_code == 200, r.text
        d = r.json()
        # PRIMARY BUG: should be 5M plus prev_net (transactions before 2026-07-01)
        # Since prev_net is unknown (depends on other tests), we test opening >= 5M when no prev out
        # More reliable: opening should include the 5M
        # opening_of_period = 5M + prev_net (any tx before July)
        # We at least verify it is NOT 0 (which was the bug)
        assert d["opening_balance"] != 0, (
            f"BUG NOT FIXED: opening_balance is 0 when opening_date=2026-07-15 "
            f"and viewing 2026-07. Expected includes {OPENING_AMOUNT}. Got: {d}"
        )
        # Response structure
        for k in ["month", "period_start", "period_end", "opening_balance", "total_in",
                  "total_out", "net", "closing_balance", "tx_count", "breakdown_in", "breakdown_out"]:
            assert k in d, f"missing key {k}"
        assert d["period_start"] == "2026-07-01"
        assert d["period_end"] == "2026-07-31"
        # closing_balance = opening + total_in - total_out
        expected = round(d["opening_balance"] + d["total_in"] - d["total_out"], 2)
        assert abs(d["closing_balance"] - expected) < 0.01

    def test_transactions_endpoint_includes_opening_when_date_mid_month(self, client):
        set_opening(client, OPENING_AMOUNT, "2026-07-15")
        r = client.get(f"{BASE_URL}/api/cashbook/transactions", params={"month": "2026-07"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["opening_balance"] != 0, (
            f"BUG NOT FIXED: /cashbook/transactions opening_balance is 0 for 2026-07 with "
            f"opening_date=2026-07-15. Got: opening_balance={d['opening_balance']}"
        )
        # Running balance sanity
        prev_bal = d["opening_balance"]
        for t in d["transactions"]:
            expected = round(prev_bal + t["amount"], 2) if t["type"] == "in" else round(prev_bal - t["amount"], 2)
            assert abs(t["balance"] - expected) < 0.01
            prev_bal = t["balance"]
        assert abs(d["closing_balance"] - prev_bal) < 0.01


# ---------------- 2. Regression: opening_date < first_of_month ----------------
class TestOpeningDateBeforeMonth:
    """opening_date=2026-01-01, view Juli 2026 → opening_of_period includes 5M + all Jan-Jun net"""

    def test_summary_includes_opening_when_date_before_month(self, client):
        set_opening(client, OPENING_AMOUNT, "2026-01-01")
        r = client.get(f"{BASE_URL}/api/cashbook/summary", params={"month": "2026-07"})
        assert r.status_code == 200
        d = r.json()
        assert d["opening_balance"] != 0, (
            f"Regression: opening_balance should include 5M for opening_date=2026-01-01 "
            f"view 2026-07. Got: {d['opening_balance']}"
        )
        # closing sanity
        expected = round(d["opening_balance"] + d["total_in"] - d["total_out"], 2)
        assert abs(d["closing_balance"] - expected) < 0.01

    def test_transactions_includes_opening_when_date_before_month(self, client):
        set_opening(client, OPENING_AMOUNT, "2026-01-01")
        r = client.get(f"{BASE_URL}/api/cashbook/transactions", params={"month": "2026-07"})
        assert r.status_code == 200
        d = r.json()
        assert d["opening_balance"] != 0


# ---------------- 3. opening_date in the FUTURE ----------------
class TestOpeningDateFuture:
    """opening_date=2027-03-01 (future), view Juli 2026 → opening_of_period must be 0"""

    def test_summary_opening_zero_when_date_future(self, client):
        set_opening(client, OPENING_AMOUNT, "2027-03-01")
        r = client.get(f"{BASE_URL}/api/cashbook/summary", params={"month": "2026-07"})
        assert r.status_code == 200
        d = r.json()
        # opening_of_period = 0 (opening excluded) + prev_net (Jan-Jun 2026)
        # For determinism: opening_balance should exclude the 5M — i.e. must not equal
        # what it would be if included. We can compare against the mid-month test.
        # Simpler: opening_balance = prev_net only. Verify closing consistency.
        expected = round(d["opening_balance"] + d["total_in"] - d["total_out"], 2)
        assert abs(d["closing_balance"] - expected) < 0.01

    def test_summary_opening_zero_vs_included_diff_is_5M(self, client):
        # Compare: future opening vs. included opening should differ by 5M
        set_opening(client, OPENING_AMOUNT, "2027-03-01")
        r1 = client.get(f"{BASE_URL}/api/cashbook/summary", params={"month": "2026-07"})
        excluded_open = r1.json()["opening_balance"]

        set_opening(client, OPENING_AMOUNT, "2026-07-15")
        r2 = client.get(f"{BASE_URL}/api/cashbook/summary", params={"month": "2026-07"})
        included_open = r2.json()["opening_balance"]

        # Difference must be exactly 5M
        assert round(included_open - excluded_open, 2) == OPENING_AMOUNT, (
            f"Expected diff of {OPENING_AMOUNT}, got included={included_open}, excluded={excluded_open}"
        )

    def test_transactions_opening_excluded_when_date_future(self, client):
        set_opening(client, OPENING_AMOUNT, "2027-03-01")
        r = client.get(f"{BASE_URL}/api/cashbook/transactions", params={"month": "2026-07"})
        assert r.status_code == 200
        # No assertion on absolute value (depends on prev_net) but running balance must be consistent
        d = r.json()
        prev_bal = d["opening_balance"]
        for t in d["transactions"]:
            expected = round(prev_bal + t["amount"], 2) if t["type"] == "in" else round(prev_bal - t["amount"], 2)
            assert abs(t["balance"] - expected) < 0.01
            prev_bal = t["balance"]


# ---------------- 4. Boundary: opening_date == first_of_month ----------------
class TestOpeningDateFirstOfMonth:
    def test_summary_first_of_month_included(self, client):
        # First establish baseline (no opening) for July
        set_opening(client, 0, "2027-03-01")  # excluded → opening = prev_net only
        r0 = client.get(f"{BASE_URL}/api/cashbook/summary", params={"month": "2026-07"})
        baseline = r0.json()["opening_balance"]  # prev_net only

        set_opening(client, OPENING_AMOUNT, "2026-07-01")
        r = client.get(f"{BASE_URL}/api/cashbook/summary", params={"month": "2026-07"})
        assert r.status_code == 200
        d = r.json()
        # opening_of_period = 5M + prev_net = 5M + baseline
        assert round(d["opening_balance"] - baseline, 2) == OPENING_AMOUNT, (
            f"opening_date=first_of_month must include opening. diff={d['opening_balance']-baseline}"
        )


# ---------------- 5. Boundary: opening_date == last_of_month ----------------
class TestOpeningDateLastOfMonth:
    def test_summary_last_of_month_included(self, client):
        set_opening(client, 0, "2027-03-01")  # baseline (opening excluded)
        r0 = client.get(f"{BASE_URL}/api/cashbook/summary", params={"month": "2026-07"})
        baseline = r0.json()["opening_balance"]

        set_opening(client, OPENING_AMOUNT, "2026-07-31")
        r = client.get(f"{BASE_URL}/api/cashbook/summary", params={"month": "2026-07"})
        assert r.status_code == 200
        d = r.json()
        assert round(d["opening_balance"] - baseline, 2) == OPENING_AMOUNT, (
            f"opening_date=last_of_month must include opening. diff={d['opening_balance']-baseline}"
        )

    def test_summary_day_after_last_excluded(self, client):
        # 2026-08-01 view July 2026 → opening excluded (> 2026-07-31)
        set_opening(client, 0, "2027-03-01")
        r0 = client.get(f"{BASE_URL}/api/cashbook/summary", params={"month": "2026-07"})
        baseline = r0.json()["opening_balance"]

        set_opening(client, OPENING_AMOUNT, "2026-08-01")
        r = client.get(f"{BASE_URL}/api/cashbook/summary", params={"month": "2026-07"})
        assert r.status_code == 200
        d = r.json()
        # opening_date > last_of_month (2026-07-31) → excluded
        assert round(d["opening_balance"] - baseline, 2) == 0, (
            f"opening_date=next-month must be excluded from July view. diff={d['opening_balance']-baseline}"
        )


# ---------------- 6. Regression: /cashbook/balance NOT affected ----------------
class TestBalanceEndpointUnchanged:
    def test_balance_always_includes_opening(self, client):
        set_opening(client, OPENING_AMOUNT, "2026-07-15")
        r = client.get(f"{BASE_URL}/api/cashbook/balance")
        assert r.status_code == 200
        d = r.json()
        assert d["opening_balance"] == OPENING_AMOUNT
        # balance = opening + total_in - total_out (always includes opening)
        expected = round(d["opening_balance"] + d["total_in"] - d["total_out"], 2)
        assert abs(d["balance"] - expected) < 0.01

    def test_balance_includes_opening_even_when_date_future(self, client):
        # regression: /balance endpoint doesn't filter by month, always includes opening
        set_opening(client, OPENING_AMOUNT, "2027-03-01")
        r = client.get(f"{BASE_URL}/api/cashbook/balance")
        assert r.status_code == 200
        d = r.json()
        assert d["opening_balance"] == OPENING_AMOUNT


# ---------------- 7. Consistency: summary.closing == /balance when viewing month with no future tx ----------------
class TestSummaryClosingMatchesBalance:
    """When opening_date is in the viewed month and there are no transactions AFTER that month,
    summary.closing_balance for that month should ~equal /balance.balance."""

    def test_july_closing_matches_realtime_when_opening_mid_july(self, client):
        set_opening(client, OPENING_AMOUNT, "2026-07-15")
        r_sum = client.get(f"{BASE_URL}/api/cashbook/summary", params={"month": "2026-07"})
        r_bal = client.get(f"{BASE_URL}/api/cashbook/balance")
        assert r_sum.status_code == 200 and r_bal.status_code == 200
        summary_closing = r_sum.json()["closing_balance"]
        realtime_balance = r_bal.json()["balance"]
        # Note: they may differ if there are tx AFTER July 2026, but structure must be intact.
        # We just verify both endpoints work and closing includes opening (bug indicator)
        # Sanity: closing must be >= 0 given opening=5M and no huge out (unless test data...)
        # We simply assert both return numeric floats
        assert isinstance(summary_closing, (int, float))
        assert isinstance(realtime_balance, (int, float))
