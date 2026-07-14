"""
Backend tests for Master Kategori (unified) module.

Covers:
- CRUD /api/categories (list/create/update/delete)
- Filters: type=..., only_active
- Validation: invalid type, empty name, duplicate name (case-insensitive)
- Backfill /api/categories/backfill
- Stats /api/categories/stats
- Cascade rename (category -> master collections)
- Delete guard when category still in use
- Auto-upsert hooks in MaterialIn / CustomerIn / SupplierIn / ProductIn (create & update)
- Regression: MATERIAL_CATEGORIES enum NOT enforced anymore (arbitrary category allowed)
- Regression: category optional for product/customer/supplier
- Regression: 'flexy' pre-existing category still usable
"""
import uuid
import pytest
import requests

# --------- fixtures ---------

@pytest.fixture(scope="module")
def BASE_URL():
    from pathlib import Path
    p = Path("/app/frontend/.env")
    for line in p.read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


@pytest.fixture(scope="module")
def admin(BASE_URL):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
    if r.status_code != 200:
        pytest.skip(f"Login failed {r.status_code}: {r.text}")
    return s


def _tag():
    return f"TESTCAT_{uuid.uuid4().hex[:6]}"


# --------- 1. CATEGORIES CRUD ---------

def test_categories_list_all(admin, BASE_URL):
    r = admin.get(f"{BASE_URL}/api/categories")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_categories_list_filter_type(admin, BASE_URL):
    r = admin.get(f"{BASE_URL}/api/categories", params={"type": "material"})
    assert r.status_code == 200
    for it in r.json():
        assert it.get("type") == "material"


def test_categories_list_invalid_type(admin, BASE_URL):
    r = admin.get(f"{BASE_URL}/api/categories", params={"type": "invalid_xyz"})
    assert r.status_code == 400


def test_categories_list_only_active(admin, BASE_URL):
    r = admin.get(f"{BASE_URL}/api/categories", params={"only_active": "true"})
    assert r.status_code == 200
    for it in r.json():
        assert it.get("active") is not False


def test_create_category_ok(admin, BASE_URL):
    name = f"{_tag()}_MatA"
    r = admin.post(f"{BASE_URL}/api/categories",
                   json={"type": "material", "name": name, "description": "desc",
                         "color": "#002FA7", "active": True})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == name
    assert d["type"] == "material"
    assert d["color"] == "#002FA7"
    assert d.get("auto_created") is False
    # verify persisted via list
    lst = admin.get(f"{BASE_URL}/api/categories", params={"type": "material"}).json()
    assert any(x["id"] == d["id"] for x in lst)
    # cleanup
    admin.delete(f"{BASE_URL}/api/categories/{d['id']}")


def test_create_category_invalid_type(admin, BASE_URL):
    r = admin.post(f"{BASE_URL}/api/categories",
                   json={"type": "invalid_type", "name": "X"})
    assert r.status_code == 400


def test_create_category_empty_name(admin, BASE_URL):
    r = admin.post(f"{BASE_URL}/api/categories",
                   json={"type": "material", "name": "   "})
    assert r.status_code == 400


def test_create_category_duplicate_case_insensitive(admin, BASE_URL):
    name = f"{_tag()}_Dup"
    r1 = admin.post(f"{BASE_URL}/api/categories",
                    json={"type": "material", "name": name})
    assert r1.status_code == 200
    cid = r1.json()["id"]
    r2 = admin.post(f"{BASE_URL}/api/categories",
                    json={"type": "material", "name": name.upper()})
    assert r2.status_code == 400
    admin.delete(f"{BASE_URL}/api/categories/{cid}")


def test_update_category_rename_cascade(admin, BASE_URL):
    """
    Buat kategori material 'CascadeOldNN', buat material dgn category itu,
    lalu rename kategori -> cek db.materials.category ter-update via GET.
    """
    old_name = f"{_tag()}_CascOld"
    new_name = f"{_tag()}_CascNew"
    # create category
    rc = admin.post(f"{BASE_URL}/api/categories",
                    json={"type": "material", "name": old_name})
    assert rc.status_code == 200
    cid = rc.json()["id"]
    # create material dgn category=old_name
    rm = admin.post(f"{BASE_URL}/api/inventory/materials",
                    json={"name": f"{_tag()}_Mat", "category": old_name,
                          "unit": "pcs", "stock": 0, "unit_price": 100, "min_stock": 0})
    assert rm.status_code == 200, rm.text
    mid = rm.json()["id"]
    try:
        # rename category
        ru = admin.put(f"{BASE_URL}/api/categories/{cid}",
                       json={"type": "material", "name": new_name, "active": True})
        assert ru.status_code == 200, ru.text
        assert ru.json()["name"] == new_name
        # verify cascade
        gm = admin.get(f"{BASE_URL}/api/inventory/materials")
        found = next((x for x in gm.json() if x["id"] == mid), None)
        assert found is not None
        assert found["category"] == new_name, f"Cascade rename failed: {found['category']}"
    finally:
        admin.delete(f"{BASE_URL}/api/inventory/materials/{mid}")
        admin.delete(f"{BASE_URL}/api/categories/{cid}")


def test_delete_category_blocked_when_used(admin, BASE_URL):
    cat_name = f"{_tag()}_UsedCat"
    rc = admin.post(f"{BASE_URL}/api/categories",
                    json={"type": "material", "name": cat_name})
    cid = rc.json()["id"]
    rm = admin.post(f"{BASE_URL}/api/inventory/materials",
                    json={"name": f"{_tag()}_MatU", "category": cat_name,
                          "unit": "pcs", "stock": 0, "unit_price": 10, "min_stock": 0})
    mid = rm.json()["id"]
    try:
        rd = admin.delete(f"{BASE_URL}/api/categories/{cid}")
        assert rd.status_code == 400
        assert "dipakai" in rd.text.lower()
    finally:
        admin.delete(f"{BASE_URL}/api/inventory/materials/{mid}")
        admin.delete(f"{BASE_URL}/api/categories/{cid}")


def test_delete_category_ok_when_unused(admin, BASE_URL):
    name = f"{_tag()}_Unused"
    rc = admin.post(f"{BASE_URL}/api/categories",
                    json={"type": "supplier", "name": name})
    cid = rc.json()["id"]
    rd = admin.delete(f"{BASE_URL}/api/categories/{cid}")
    assert rd.status_code == 200
    # verify gone
    lst = admin.get(f"{BASE_URL}/api/categories", params={"type": "supplier"}).json()
    assert not any(x["id"] == cid for x in lst)


# --------- 2. BACKFILL & STATS ---------

def test_backfill_categories(admin, BASE_URL):
    r = admin.post(f"{BASE_URL}/api/categories/backfill")
    assert r.status_code == 200
    d = r.json()
    assert "added" in d and "total" in d
    assert isinstance(d["added"], int)
    assert isinstance(d["total"], int)
    assert d["total"] >= 0


def test_categories_stats(admin, BASE_URL):
    r = admin.get(f"{BASE_URL}/api/categories/stats")
    assert r.status_code == 200, r.text
    d = r.json()
    for t in ("material", "product", "supplier", "customer"):
        assert t in d
        assert "total" in d[t] and "active" in d[t]
        assert isinstance(d[t]["total"], int)


# --------- 3. AUTO-UPSERT HOOKS ---------

def _get_cat_by_name(admin, BASE_URL, cat_type, name):
    r = admin.get(f"{BASE_URL}/api/categories", params={"type": cat_type})
    return next((x for x in r.json() if (x.get("name") or "").lower() == name.lower()), None)


def test_autoupsert_material_category(admin, BASE_URL):
    cat_new = f"{_tag()}_MetallicFoil"
    rm = admin.post(f"{BASE_URL}/api/inventory/materials",
                    json={"name": f"{_tag()}_MA", "category": cat_new,
                          "unit": "pcs", "stock": 0, "unit_price": 1, "min_stock": 0})
    assert rm.status_code == 200, rm.text
    mid = rm.json()["id"]
    try:
        cat = _get_cat_by_name(admin, BASE_URL, "material", cat_new)
        assert cat is not None, "Auto-upsert did not persist category"
        assert cat.get("auto_created") is True
        assert cat["type"] == "material"
    finally:
        admin.delete(f"{BASE_URL}/api/inventory/materials/{mid}")
        c = _get_cat_by_name(admin, BASE_URL, "material", cat_new)
        if c:
            admin.delete(f"{BASE_URL}/api/categories/{c['id']}")


def test_autoupsert_customer_category(admin, BASE_URL):
    cat_new = f"{_tag()}_CorporateVIP"
    rc = admin.post(f"{BASE_URL}/api/inventory/customers",
                    json={"name": f"{_tag()}_Cust", "category": cat_new})
    assert rc.status_code == 200, rc.text
    cid = rc.json()["id"]
    try:
        cat = _get_cat_by_name(admin, BASE_URL, "customer", cat_new)
        assert cat is not None
        assert cat.get("auto_created") is True
    finally:
        admin.delete(f"{BASE_URL}/api/inventory/customers/{cid}")
        c = _get_cat_by_name(admin, BASE_URL, "customer", cat_new)
        if c:
            admin.delete(f"{BASE_URL}/api/categories/{c['id']}")


def test_autoupsert_supplier_category(admin, BASE_URL):
    cat_new = f"{_tag()}_ImportChina"
    rs = admin.post(f"{BASE_URL}/api/purchasing/suppliers",
                    json={"name": f"{_tag()}_Sup", "category": cat_new})
    assert rs.status_code == 200, rs.text
    sid = rs.json()["id"]
    try:
        cat = _get_cat_by_name(admin, BASE_URL, "supplier", cat_new)
        assert cat is not None
        assert cat.get("auto_created") is True
    finally:
        admin.delete(f"{BASE_URL}/api/purchasing/suppliers/{sid}")
        c = _get_cat_by_name(admin, BASE_URL, "supplier", cat_new)
        if c:
            admin.delete(f"{BASE_URL}/api/categories/{c['id']}")


def test_autoupsert_product_category(admin, BASE_URL):
    # Need at least 1 material for product component
    mats = admin.get(f"{BASE_URL}/api/inventory/materials").json()
    if not mats:
        pytest.skip("No materials to build product component")
    mid = mats[0]["id"]
    cat_new = f"{_tag()}_SablonKaos"
    rp = admin.post(f"{BASE_URL}/api/products",
                    json={"name": f"{_tag()}_Prod", "category": cat_new,
                          "pricing_mode": "fixed", "unit_price": 1000,
                          "components": [{"material_id": mid, "formula": "per_qty", "quantity": 1}]})
    assert rp.status_code == 200, rp.text
    pid = rp.json()["id"]
    try:
        cat = _get_cat_by_name(admin, BASE_URL, "product", cat_new)
        assert cat is not None
        assert cat.get("auto_created") is True
    finally:
        admin.delete(f"{BASE_URL}/api/products/{pid}")
        c = _get_cat_by_name(admin, BASE_URL, "product", cat_new)
        if c:
            admin.delete(f"{BASE_URL}/api/categories/{c['id']}")


def test_autoupsert_via_material_update(admin, BASE_URL):
    """PUT hook — update material w/ new category should upsert."""
    rm = admin.post(f"{BASE_URL}/api/inventory/materials",
                    json={"name": f"{_tag()}_MU", "category": "flexy",
                          "unit": "pcs", "stock": 0, "unit_price": 1, "min_stock": 0})
    mid = rm.json()["id"]
    new_cat = f"{_tag()}_HoloFilm"
    try:
        ru = admin.put(f"{BASE_URL}/api/inventory/materials/{mid}",
                       json={"name": f"{_tag()}_MU", "category": new_cat,
                             "unit": "pcs", "stock": 0, "unit_price": 1, "min_stock": 0})
        assert ru.status_code == 200, ru.text
        cat = _get_cat_by_name(admin, BASE_URL, "material", new_cat)
        assert cat is not None
        assert cat.get("auto_created") is True
    finally:
        admin.delete(f"{BASE_URL}/api/inventory/materials/{mid}")
        c = _get_cat_by_name(admin, BASE_URL, "material", new_cat)
        if c:
            admin.delete(f"{BASE_URL}/api/categories/{c['id']}")


# --------- 4. VALIDATION & REGRESSION ---------

def test_material_category_empty_rejected(admin, BASE_URL):
    r = admin.post(f"{BASE_URL}/api/inventory/materials",
                   json={"name": f"{_tag()}_M", "category": "  ",
                         "unit": "pcs", "stock": 0, "unit_price": 1, "min_stock": 0})
    assert r.status_code == 400
    assert "Kategori" in r.text or "kategori" in r.text


def test_material_arbitrary_category_allowed(admin, BASE_URL):
    """MATERIAL_CATEGORIES enum tidak di-enforce lagi."""
    arbitrary = f"{_tag()}_XYZBrandNewCat"
    rm = admin.post(f"{BASE_URL}/api/inventory/materials",
                    json={"name": f"{_tag()}_MAny", "category": arbitrary,
                          "unit": "pcs", "stock": 0, "unit_price": 1, "min_stock": 0})
    assert rm.status_code == 200, f"Arbitrary category should be allowed, got: {rm.text}"
    mid = rm.json()["id"]
    admin.delete(f"{BASE_URL}/api/inventory/materials/{mid}")
    c = _get_cat_by_name(admin, BASE_URL, "material", arbitrary)
    if c:
        admin.delete(f"{BASE_URL}/api/categories/{c['id']}")


def test_material_legacy_flexy_still_works(admin, BASE_URL):
    """Regression: create material with category='flexy' (pre-existing) still works."""
    rm = admin.post(f"{BASE_URL}/api/inventory/materials",
                    json={"name": f"{_tag()}_MFlexy", "category": "flexy",
                          "unit": "pcs", "stock": 0, "unit_price": 1, "min_stock": 0})
    assert rm.status_code == 200, rm.text
    mid = rm.json()["id"]
    admin.delete(f"{BASE_URL}/api/inventory/materials/{mid}")


def test_customer_without_category_ok(admin, BASE_URL):
    rc = admin.post(f"{BASE_URL}/api/inventory/customers",
                    json={"name": f"{_tag()}_CustNoCat"})
    assert rc.status_code == 200, rc.text
    admin.delete(f"{BASE_URL}/api/inventory/customers/{rc.json()['id']}")


def test_supplier_without_category_ok(admin, BASE_URL):
    rs = admin.post(f"{BASE_URL}/api/purchasing/suppliers",
                    json={"name": f"{_tag()}_SupNoCat"})
    assert rs.status_code == 200, rs.text
    admin.delete(f"{BASE_URL}/api/purchasing/suppliers/{rs.json()['id']}")


def test_product_without_category_ok(admin, BASE_URL):
    mats = admin.get(f"{BASE_URL}/api/inventory/materials").json()
    if not mats:
        pytest.skip("No materials")
    mid = mats[0]["id"]
    rp = admin.post(f"{BASE_URL}/api/products",
                    json={"name": f"{_tag()}_ProdNoCat", "pricing_mode": "fixed",
                          "unit_price": 500,
                          "components": [{"material_id": mid, "formula": "per_qty", "quantity": 1}]})
    assert rp.status_code == 200, rp.text
    admin.delete(f"{BASE_URL}/api/products/{rp.json()['id']}")


# --------- 5. UPDATE CATEGORY invalid/duplicate ---------

def test_update_category_duplicate_rejected(admin, BASE_URL):
    n1 = f"{_tag()}_UpDup1"
    n2 = f"{_tag()}_UpDup2"
    a = admin.post(f"{BASE_URL}/api/categories", json={"type": "product", "name": n1}).json()
    b = admin.post(f"{BASE_URL}/api/categories", json={"type": "product", "name": n2}).json()
    try:
        r = admin.put(f"{BASE_URL}/api/categories/{b['id']}",
                      json={"type": "product", "name": n1, "active": True})
        assert r.status_code == 400
    finally:
        admin.delete(f"{BASE_URL}/api/categories/{a['id']}")
        admin.delete(f"{BASE_URL}/api/categories/{b['id']}")


def test_update_category_not_found(admin, BASE_URL):
    r = admin.put(f"{BASE_URL}/api/categories/nonexistent-id-xxx",
                  json={"type": "product", "name": "X", "active": True})
    assert r.status_code == 404
