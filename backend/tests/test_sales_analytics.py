"""Tests for Sales Analytics endpoint used by 'Laporan Penjualan' page.

Endpoint under test:
  GET /api/sales/report/analytics
  Query params: date_from (YYYY-MM-DD), date_to (YYYY-MM-DD), customer (substring, case-insensitive)

NOTE:
  SaleIn model does NOT accept a `date` field — server assigns today's date automatically
  on creation. Therefore all TEST_ANALYTICS_-prefixed sales we create end up on today.
  Date-range assertions therefore use today / far-past ranges (empty range) rather than
  attempting to back-date rows.
"""
import os
import re
from datetime import datetime, timezone, timedelta

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    from pathlib import Path
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break

ANALYTICS_URL = f"{BASE_URL}/api/sales/report/analytics"


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
def seed(client):
    """Create 4 sales (all on today's date) for aggregation tests.

    Layout:
      s1: TEST_ANALYTICS_BuAni,  Banner,  qty=2, unit=30_000  -> subtotal 60_000
      s2: TEST_ANALYTICS_Umum,   Banner,  qty=1, unit=30_000  -> subtotal 30_000
      s3: TEST_ANALYTICS_BuAni,  Banner,  qty=3, unit=30_000  -> subtotal 90_000
      s4: TEST_ANALYTICS_Umum,   Sticker, qty=4, unit=12_500  -> subtotal 50_000

    Sums (filter customer='TEST_ANALYTICS_'):
      period_total   = 230_000
      transaction_ct = 4
      item_count     = 4
      top_product    = Banner (qty=6, total=180_000)  > Sticker (qty=4, total=50_000)
      daily_series   = {today: 230_000}
    """
    m = client.post(f"{BASE_URL}/api/inventory/materials", json={
        "name": "TEST_ANALYTICS_Flex", "category": "flexy", "unit": "meter",
        "current_stock": 500.0, "purchase_price": 10000, "selling_price": 25000,
        "min_stock": 0, "active": True,
    })
    assert m.status_code == 200, m.text
    mat = m.json()

    today = datetime.now(timezone.utc).date().isoformat()

    def create_sale(customer_name, qty, unit_price=30000, product_name="TEST_ANALYTICS_Banner"):
        payload = {
            "customer_name": customer_name,
            "customer_phone": "0810",
            "items": [{
                "material_id": mat["id"],
                "product_name": product_name,
                "length_m": 1,
                "width_m": 1,
                "quantity": qty,
                "unit_price": unit_price,
            }],
            "discount": 0,
            "cash_paid": unit_price * qty,
            "payment_method": "tunai",
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200, r.text
        return r.json()

    s1 = create_sale("TEST_ANALYTICS_BuAni", 2)
    s2 = create_sale("TEST_ANALYTICS_Umum", 1)
    s3 = create_sale("TEST_ANALYTICS_BuAni", 3)
    s4 = create_sale("TEST_ANALYTICS_Umum", 4, unit_price=12500, product_name="TEST_ANALYTICS_Sticker")

    data = {"s1": s1, "s2": s2, "s3": s3, "s4": s4, "material": mat, "today": today}
    yield data

    # Teardown
    for s in [s1, s2, s3, s4]:
        try:
            client.delete(f"{BASE_URL}/api/sales/{s['id']}")
        except Exception:
            pass
    try:
        client.delete(f"{BASE_URL}/api/inventory/materials/{mat['id']}")
    except Exception:
        pass


# ---------------- Schema / shape ----------------

class TestSchema:
    def test_requires_auth(self):
        anon = requests.Session()
        r = anon.get(ANALYTICS_URL)
        assert r.status_code in (401, 403), r.status_code

    def test_no_filter_returns_shape(self, client, seed):
        r = client.get(ANALYTICS_URL)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        for k in ("rows", "summary", "top_products", "daily_series"):
            assert k in data, f"key '{k}' missing"
        assert isinstance(data["rows"], list)
        if data["rows"]:
            row = data["rows"][0]
            for f in ("date", "customer_name", "sale_no", "product_name",
                      "size", "quantity", "unit_price", "total"):
                assert f in row, f"row missing '{f}'"
        for k in ("period_total", "weekly_total", "week_start",
                  "transaction_count", "item_count", "top_product"):
            assert k in data["summary"], f"summary missing '{k}'"
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", data["summary"]["week_start"])
        assert isinstance(data["top_products"], list)
        assert len(data["top_products"]) <= 10
        assert isinstance(data["daily_series"], list)

    def test_row_flatten_per_item(self, client, seed):
        """Rows must be per-item (each item in sale.items becomes one row)."""
        r = client.get(ANALYTICS_URL, params={"customer": "TEST_ANALYTICS_"})
        assert r.status_code == 200
        rows = r.json()["rows"]
        # 4 sales, each with 1 item → 4 rows
        our_rows = [x for x in rows if "TEST_ANALYTICS_" in x["customer_name"]]
        assert len(our_rows) == 4, our_rows


# ---------------- Date filter ----------------

class TestDateFilter:
    def test_date_range_empty_period(self, client):
        """Far-past date range should return zero data."""
        r = client.get(ANALYTICS_URL, params={"date_from": "1990-01-01", "date_to": "1990-01-31"})
        assert r.status_code == 200
        d = r.json()
        assert d["rows"] == []
        assert d["summary"]["transaction_count"] == 0
        assert d["summary"]["period_total"] == 0
        assert d["daily_series"] == []
        assert d["top_products"] == []

    def test_date_range_inclusive_today(self, client, seed):
        """date_from=date_to=today must include our seed sales (inclusive both sides)."""
        today = seed["today"]
        r = client.get(ANALYTICS_URL, params={"date_from": today, "date_to": today, "customer": "TEST_ANALYTICS_"})
        assert r.status_code == 200
        data = r.json()
        assert data["summary"]["transaction_count"] == 4
        for row in data["rows"]:
            assert row["date"] == today

    def test_date_to_before_today_excludes_today(self, client, seed):
        """date_to yesterday must NOT include today's TEST_ANALYTICS_ rows."""
        yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        r = client.get(ANALYTICS_URL, params={"date_to": yesterday, "customer": "TEST_ANALYTICS_"})
        assert r.status_code == 200
        assert r.json()["rows"] == []

    def test_date_from_future_returns_empty(self, client, seed):
        future = "2099-12-31"
        r = client.get(ANALYTICS_URL, params={"date_from": future, "customer": "TEST_ANALYTICS_"})
        assert r.status_code == 200
        assert r.json()["rows"] == []


# ---------------- Customer filter ----------------

class TestCustomerFilter:
    def test_customer_substring_match(self, client, seed):
        r = client.get(ANALYTICS_URL, params={"customer": "BuAni"})
        assert r.status_code == 200
        rows = r.json()["rows"]
        our = [x for x in rows if "TEST_ANALYTICS_" in x["customer_name"]]
        # BuAni sales: s1 + s3 = 2 rows
        assert len(our) == 2, our
        for row in our:
            assert "buani" in row["customer_name"].lower()

    def test_customer_case_insensitive(self, client, seed):
        r = client.get(ANALYTICS_URL, params={"customer": "buani"})
        assert r.status_code == 200
        our = [x for x in r.json()["rows"] if "TEST_ANALYTICS_" in x["customer_name"]]
        assert len(our) == 2

    def test_customer_no_match(self, client, seed):
        r = client.get(ANALYTICS_URL, params={"customer": "TEST_ANALYTICS_NoSuchCustXYZ"})
        assert r.status_code == 200
        data = r.json()
        assert data["rows"] == []
        assert data["summary"]["transaction_count"] == 0
        assert data["summary"]["period_total"] == 0
        assert data["top_products"] == []
        assert data["daily_series"] == []


# ---------------- Summary aggregation ----------------

class TestSummary:
    def test_summary_period_total(self, client, seed):
        r = client.get(ANALYTICS_URL, params={"customer": "TEST_ANALYTICS_"})
        assert r.status_code == 200
        d = r.json()
        # 60000 + 30000 + 90000 + 50000 = 230000
        assert d["summary"]["period_total"] == pytest.approx(230000, abs=1)
        assert d["summary"]["transaction_count"] == 4
        assert d["summary"]["item_count"] == 4

    def test_weekly_total_matches_daily_series_since_week_start(self, client, seed):
        r = client.get(ANALYTICS_URL, params={"customer": "TEST_ANALYTICS_"})
        assert r.status_code == 200
        d = r.json()
        week_start = d["summary"]["week_start"]
        expected = sum(x["total"] for x in d["daily_series"] if x["date"] >= week_start)
        assert d["summary"]["weekly_total"] == pytest.approx(expected, abs=1)
        # And since today >= week_start, weekly_total = 230000
        assert d["summary"]["weekly_total"] == pytest.approx(230000, abs=1)

    def test_week_start_is_monday(self, client):
        r = client.get(ANALYTICS_URL)
        assert r.status_code == 200
        ws = r.json()["summary"]["week_start"]
        d = datetime.strptime(ws, "%Y-%m-%d").date()
        assert d.weekday() == 0, f"week_start {ws} weekday={d.weekday()} (expected 0=Mon)"
        # week_start should be <= today
        assert d <= datetime.now(timezone.utc).date()

    def test_top_product_matches_top_products_first(self, client, seed):
        r = client.get(ANALYTICS_URL, params={"customer": "TEST_ANALYTICS_"})
        d = r.json()
        assert d["summary"]["top_product"] == d["top_products"][0]["name"]
        assert d["summary"]["top_product"] == "TEST_ANALYTICS_Banner"


# ---------------- Top products aggregation ----------------

class TestTopProducts:
    def test_top_products_sorted_desc_by_total(self, client, seed):
        r = client.get(ANALYTICS_URL, params={"customer": "TEST_ANALYTICS_"})
        assert r.status_code == 200
        top = r.json()["top_products"]
        totals = [p["total"] for p in top]
        assert totals == sorted(totals, reverse=True), totals
        assert len(top) <= 10

    def test_top_products_aggregate_same_product_across_sales(self, client, seed):
        r = client.get(ANALYTICS_URL, params={"customer": "TEST_ANALYTICS_"})
        top = r.json()["top_products"]
        # Banner qty summed: s1(2)+s2(1)+s3(3) = 6; total = 180_000
        banner = next((p for p in top if p["name"] == "TEST_ANALYTICS_Banner"), None)
        assert banner is not None, top
        assert banner["qty"] == 6
        assert banner["total"] == pytest.approx(180000, abs=1)
        assert isinstance(banner["qty"], int)

    def test_top_products_include_both_products(self, client, seed):
        r = client.get(ANALYTICS_URL, params={"customer": "TEST_ANALYTICS_"})
        names = [p["name"] for p in r.json()["top_products"]]
        assert "TEST_ANALYTICS_Banner" in names
        assert "TEST_ANALYTICS_Sticker" in names


# ---------------- Daily series aggregation ----------------

class TestDailySeries:
    def test_daily_series_sorted_asc(self, client):
        r = client.get(ANALYTICS_URL)
        ds = r.json()["daily_series"]
        dates = [x["date"] for x in ds]
        assert dates == sorted(dates), dates

    def test_daily_series_sums_same_date(self, client, seed):
        """All 4 seed sales fall on today's date → 230_000 attributed to today entry
        (verified within TEST_ANALYTICS_ customer filter)."""
        r = client.get(ANALYTICS_URL, params={"customer": "TEST_ANALYTICS_"})
        ds = r.json()["daily_series"]
        # Only today entry expected
        assert len(ds) == 1, ds
        assert ds[0]["date"] == seed["today"]
        assert ds[0]["total"] == pytest.approx(230000, abs=1)

    def test_daily_series_date_format(self, client):
        r = client.get(ANALYTICS_URL)
        for x in r.json()["daily_series"]:
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", x["date"]), x
