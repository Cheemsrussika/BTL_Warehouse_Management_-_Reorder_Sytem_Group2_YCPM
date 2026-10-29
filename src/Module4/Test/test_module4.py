"""Acceptance tests for Module 4 - Reorder Engine & Procurement.

Mirrors TC-401..TC-405 of ``Untitled 1.xlsx`` (FR-401..FR-405).
"""

import time
from pathlib import Path
import sys

import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
PACKAGE_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(MODULE_DIR))

from module4_service import Module4Service, ValidationError  # noqa: E402

SEED = PACKAGE_DIR / "datasets" / "seed_master_data.json"
CREDENTIALS = {
    "controller": ("controller@wrhm.vn", "ControllerPass123!"),
    "staff": ("staff01@wrhm.vn", "StaffPass123!"),
}


@pytest.fixture
def service() -> Module4Service:
    return Module4Service(str(SEED))


def login(svc, role):
    svc.login(*CREDENTIALS[role])


def install_catalog(svc, total=200, low=12):
    """Replace the seed catalog with 200 synthetic SKUs (12 at or below ROP)."""
    svc.skus.clear()
    svc.policies.clear()
    svc.suggestions.clear()
    svc.purchase_orders.clear()
    svc.demand_history.clear()
    for index in range(total):
        code, is_low = f"SKU-T{index:04d}", index < low
        svc.skus[code] = {"sku_code": code, "name": f"Synthetic Item {index}", "status": "ACTIVE",
                          "supplier_id": "SUP-A", "rop": 50, "safety_stock": 5 if is_low else 0,
                          "lead_time_days": 3, "moq": 10, "order_multiple": 10, "unit_price": 10.0,
                          "stock_on_hand": 5 if is_low else 500, "reserved_qty": 0}
        svc.policies[code] = {"sku_code": code, "supplier_id": "SUP-A", "rop": 50,
                              "safety_stock": 5 if is_low else 0, "lead_time_days": 3,
                              "moq": 10, "order_multiple": 10}
        svc.demand_history[code] = [{"date": "2026-10-19", "quantity": 2}]


# ---------------------------------------------------------------------------
# TC-401 / TC-402 - FR-401 replenishment policy
# ---------------------------------------------------------------------------
def test_tc401_configure_valid_policy(service):
    """TC-401 | Configure a valid SKU replenishment policy | FR-401"""
    login(service, "controller")

    policy = service.configure_policy("SKU-WIDGET-01", rop=50, safety_stock=30, lead_time_days=7,
                                      moq=25, order_multiple=25, supplier_id="SUP-A")

    assert (policy["rop"], policy["safety_stock"], policy["lead_time_days"],
            policy["moq"], policy["order_multiple"]) == (50, 30, 7, 25, 25)
    assert service.get_policy("SKU-WIDGET-01") == policy
    assert any(entry["action"] == "POLICY_UPDATED" for entry in service.audit_logs)


def test_tc402_reject_invalid_policy_values(service):
    """TC-402 | Reject invalid replenishment policy values | FR-401"""
    login(service, "controller")
    baseline = service.get_policy("SKU-WIDGET-01")
    updates = len([e for e in service.audit_logs if e["action"] == "POLICY_UPDATED"])

    invalid = [
        {"rop": -5, "safety_stock": 30, "lead_time_days": 7, "moq": 25, "order_multiple": 25},
        {"rop": 50, "safety_stock": -10, "lead_time_days": 7, "moq": 25, "order_multiple": 25},
        {"rop": 50, "safety_stock": 30, "lead_time_days": 0, "moq": 25, "order_multiple": 25},
        {"rop": 50, "safety_stock": 30, "lead_time_days": 7, "moq": 0, "order_multiple": 25},
        {"rop": 50, "safety_stock": 30, "lead_time_days": 7, "moq": 30, "order_multiple": 25},
    ]
    for values in invalid:
        with pytest.raises(ValidationError):
            service.configure_policy("SKU-WIDGET-01", supplier_id="SUP-A", **values)

    assert service.get_policy("SKU-WIDGET-01") == baseline
    assert len([e for e in service.audit_logs if e["action"] == "POLICY_UPDATED"]) == updates


# ---------------------------------------------------------------------------
# TC-403 / TC-404 - FR-402 monitoring
# ---------------------------------------------------------------------------
def test_tc403_alert_at_rop_boundary(service):
    """TC-403 | Low-stock alert raised at the ROP boundary | FR-402"""
    login(service, "staff")
    service.post_stock_movement("SKU-WIDGET-01", -5)  # 55 -> 50, ROP = 50

    alert = service.get_low_stock_alerts(["SKU-WIDGET-01"])[0]
    assert (alert["available"], alert["rop"], alert["shortage"], alert["severity"]) == (
        50, 50, 0, "AT_THRESHOLD")


def test_tc404_no_alert_above_rop(service):
    """TC-404 | No alert is raised while stock stays above the ROP | FR-402"""
    login(service, "staff")
    service.post_stock_movement("SKU-WIDGET-01", 25)   # 55 -> 80
    service.post_stock_movement("SKU-WIDGET-01", -20)  # 80 -> 60, still above ROP 50

    assert service.get_low_stock_alerts(["SKU-WIDGET-01"]) == []
    assert service.last_low_stock_evaluation is not None


# ---------------------------------------------------------------------------
# TC-405 - FR-403 automated cycle
# ---------------------------------------------------------------------------
def test_tc405_cycle_creates_one_suggestion_per_uncovered_sku(service):
    """TC-405 | Automated cycle creates one suggestion per uncovered SKU | FR-403"""
    install_catalog(service, total=200, low=12)
    login(service, "controller")

    record = service.run_replenishment_cycle()

    assert (record["evaluated"], record["created"], record["above_rop"]) == (200, 12, 188)
    assert len(service.suggestions) == 12
    assert len({item["sku_code"] for item in service.suggestions.values()}) == 12
    assert all(item["status"] == "OPEN" for item in service.suggestions.values())


def make_suggestion(svc, sku_code="SKU-WIDGET-02"):
    login(svc, "controller")
    svc.run_replenishment_cycle(sku_codes=[sku_code])
    return svc.get_open_suggestions()[0]


# ---------------------------------------------------------------------------
# TC-406 / TC-407 / TC-408 - FR-404 quantity calculation
# ---------------------------------------------------------------------------
def test_tc406_quantity_formula(service):
    """TC-406 | Suggested quantity follows the lead-time, safety-stock and MOQ formula | FR-404"""
    login(service, "controller")
    service.configure_policy("SKU-WIDGET-01", rop=50, safety_stock=30, lead_time_days=7,
                             moq=25, order_multiple=25, supplier_id="SUP-A")
    login(service, "staff")
    service.post_stock_movement("SKU-WIDGET-01", -35)  # 55 -> 20

    calculation = service.calculate_order_quantity("SKU-WIDGET-01")

    assert calculation["quantity"] == 100  # ceil(((10*7)+30-20)/25)*25
    assert calculation["flag"] == "CALCULATED"
    assert calculation["inputs"]["average_daily_demand"] == 10
    assert "100" in calculation["formula"]


def test_tc407_moq_floor(service):
    """TC-407 | MOQ acts as the floor when the net requirement is lower | FR-404"""
    calculation = service.calculate_order_quantity("SKU-WIDGET-02")
    assert calculation["quantity"] == 25
    assert calculation["flag"] == "MOQ_FLOOR"


def test_tc408_fallback_without_demand_history(service):
    """TC-408 | Fallback to ROP minus available when demand history is missing | FR-404"""
    service.demand_history.pop("SKU-WIDGET-02")

    calculation = service.calculate_order_quantity("SKU-WIDGET-02")

    assert calculation["quantity"] == 25
    assert calculation["flag"] == "FALLBACK"
    assert "fallback" in calculation["formula"]


# ---------------------------------------------------------------------------
# TC-409 / TC-410 / TC-411 - FR-405 suggestions and purchase orders
# ---------------------------------------------------------------------------
def test_tc409_reject_invalid_quantities(service):
    """TC-409 | Reject suggestion quantities below MOQ or outside the order multiple | FR-405"""
    suggestion_id = make_suggestion(service)["suggestion_id"]

    with pytest.raises(ValidationError):
        service.adjust_suggestion(suggestion_id, 10)
    with pytest.raises(ValidationError):
        service.adjust_suggestion(suggestion_id, 30)

    adjusted = service.adjust_suggestion(suggestion_id, 50)
    assert adjusted["quantity"] == 50


def test_tc410_one_purchase_order_per_supplier(service):
    """TC-410 | Accepted suggestions become one purchase order per supplier | FR-405"""
    login(service, "controller")
    service.configure_policy("SKU-NO-IMG-01", rop=20, safety_stock=2, lead_time_days=5,
                             moq=1, order_multiple=1, supplier_id="SUP-B")
    login(service, "staff")
    service.post_stock_movement("SKU-WIDGET-01", -5)  # 55 -> 50, at ROP

    login(service, "controller")
    record = service.run_replenishment_cycle(
        sku_codes=["SKU-WIDGET-01", "SKU-WIDGET-02", "SKU-NO-IMG-01"])
    assert record["created"] == 3
    suggestions = service.get_open_suggestions()

    orders = service.create_purchase_orders([s["suggestion_id"] for s in suggestions])

    assert len(orders) == 2
    assert {order["supplier_id"] for order in orders} == {"SUP-A", "SUP-B"}
    for order in orders:
        expected = round(sum(l["quantity"] * l["unit_price"] for l in order["lines"]), 2)
        assert order["status"] == "DRAFT"
        assert order["total_amount"] == expected
    assert service.get_open_suggestions() == []


def test_tc411_dismissal_requires_reason(service):
    """TC-411 | Dismissal of a suggestion requires a written reason | FR-405"""
    suggestion_id = make_suggestion(service)["suggestion_id"]

    with pytest.raises(ValidationError):
        service.dismiss_suggestion(suggestion_id, "  ")

    dismissed = service.dismiss_suggestion(suggestion_id, "Stock already ordered through another channel")
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["dismissal_reason"] == "Stock already ordered through another channel"
    assert service.get_open_suggestions() == []


# ---------------------------------------------------------------------------
# TC-412 .. TC-415 - non-functional requirements
# ---------------------------------------------------------------------------
def test_tc412_cycle_idempotency(service):
    """TC-412 | Replenishment cycle is idempotent | NFR-404"""
    install_catalog(service, total=200, low=12)
    login(service, "controller")
    service.run_replenishment_cycle()
    first_ids = sorted(service.suggestions)

    record = service.run_replenishment_cycle()

    assert record["created"] == 0
    assert record["skipped"] == 12
    assert sorted(service.suggestions) == first_ids


def test_tc413_cycle_throughput(service):
    """TC-413 | Replenishment cycle processes the full catalog within the window | NFR-401"""
    install_catalog(service, total=20_000, low=0)
    login(service, "controller")

    record = service.run_replenishment_cycle()

    assert record["evaluated"] == 20_000
    assert record["duration_seconds"] < 300


def test_tc414_alert_latency(service):
    """TC-414 | Low-stock alert is raised within the latency target | NFR-402"""
    login(service, "staff")
    started = time.perf_counter()
    service.post_stock_movement("SKU-WIDGET-01", -5)
    alerts = service.get_low_stock_alerts(["SKU-WIDGET-01"])
    elapsed = time.perf_counter() - started

    assert elapsed < 60
    assert alerts[0]["severity"] == "AT_THRESHOLD"


def test_tc415_suggestion_workflow_responsiveness(service):
    """TC-415 | Suggestion workflow responds within the interactive target | NFR-405"""
    suggestion = make_suggestion(service)

    started = time.perf_counter()
    queue = service.get_open_suggestions()
    service.adjust_suggestion(queue[0]["suggestion_id"], 50)
    orders = service.create_purchase_orders([suggestion["suggestion_id"]])
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0
    assert service.get_purchase_order(orders[0]["po_id"])["status"] == "DRAFT"
