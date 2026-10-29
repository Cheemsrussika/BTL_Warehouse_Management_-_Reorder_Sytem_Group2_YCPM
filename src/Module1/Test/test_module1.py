"""Module 1 test suite --- WareHouse Inventory & Reorder System.

Every test case reports its own evidence: the steps it performs, the
assertions it makes and the concrete value it observed.  The console output
follows the pytest "live log" layout, e.g.

    tests/test_module1.py::test_tc101_valid_login
    [INFO] TC-101: Authenticating user staff01@wrhm.vn...
    [INFO] TC-101: Latency measured: 0.0003s (Target <= 2.0s) -> PASSED
    PASSED

The same evidence is written to ``output/test_results.json`` so that the
workbook's ``test_cases`` sheet can be refreshed from the run
(``python3 sync_test_results.py``).
"""

import functools
import json
import logging
import sys
import time
from pathlib import Path

import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
PACKAGE_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(MODULE_DIR))
from module1_service import Module1Service, PermissionError  # noqa: E402

logger = logging.getLogger("module1")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(_handler)

RESULTS_DIR = PACKAGE_DIR / "output" / "Module_01_Test_Logs"
RESULTS_FILE = RESULTS_DIR / "test_results.json"

# --------------------------------------------------------------------------
# case catalogue: the metadata that is mirrored into the workbook
# --------------------------------------------------------------------------
CASES = {
    "TC-101": {
        "title": "Valid User Authentication",
        "targets": "FR-101, NFR-101",
        "preconditions": "An active account exists for staff01@wrhm.vn",
        "expected": "Valid credentials authenticate and an active session is created within 2 s",
        "steps": [
            "Authenticate with the provisioned email and password",
            "Confirm the session is bound to the calling account",
            "Measure the authentication latency against the NFR-101 budget",
        ],
    },
    "TC-102": {
        "title": "Rejection of login attempt with incorrect credentials",
        "targets": "FR-101",
        "preconditions": "An active account exists for staff01@wrhm.vn",
        "expected": "Invalid credentials are rejected and no session is created",
        "steps": [
            "Attempt to authenticate with a wrong password",
            "Confirm the attempt is rejected without disclosing account state",
            "Confirm no session was established",
        ],
    },
    "TC-103": {
        "title": "Unauthorized operational users cannot perform administrative actions",
        "targets": "FR-102, NFR-102",
        "preconditions": "Warehouse Staff is signed in",
        "expected": "A role mismatch is refused with a 403 / PermissionError",
        "steps": [
            "Sign in as Warehouse Staff",
            "Attempt an administrative action (user provisioning)",
            "Confirm the request is refused with a permission error",
        ],
    },
    "TC-104": {
        "title": "User provisioning by an administrator creates an immutable audit record",
        "targets": "FR-101, FR-102, FR-103",
        "preconditions": "The IT Administrator is signed in with administrative privileges",
        "expected": "The account is created and a PROVISION_USER entry is written to the audit trail",
        "steps": [
            "Sign in as IT Administrator",
            "Provision a new account with an email, password and role",
            "Confirm the account exists and carries the assigned role",
            "Confirm an immutable PROVISION_USER entry was recorded",
        ],
    },
    "TC-105": {
        "title": "System prevents registering duplicate barcodes across SKUs",
        "targets": "FR-104, NFR-103",
        "preconditions": "SKU-WIDGET-01 already owns barcode 8931234567890",
        "expected": "A second SKU claiming the same barcode is rejected",
        "steps": [
            "Sign in as Inventory Controller",
            "Attempt to register a new SKU with an existing barcode",
            "Confirm the registration is rejected and no SKU was added",
        ],
    },
    "TC-107": {
        "title": "System rejects negative Reorder Point and non-positive Minimum Order Quantity",
        "targets": "FR-105",
        "preconditions": "SKU-WIDGET-02 exists in the master catalog",
        "expected": "Invalid thresholds are rejected and the stored values are unchanged",
        "steps": [
            "Sign in as Inventory Controller",
            "Attempt to save a negative ROP and a zero MOQ",
            "Confirm the update is rejected",
            "Confirm the stored thresholds are untouched",
        ],
    },
    "TC-108": {
        "title": "Storage hierarchy duplicate coordinate validation",
        "targets": "FR-106",
        "preconditions": "Bin Z1-A01-R01-S1-B01 already exists",
        "expected": "A duplicate composite coordinate is rejected",
        "steps": [
            "Sign in as Warehouse Manager",
            "Attempt to create a bin with an existing coordinate",
            "Confirm the creation is rejected and the bin count is unchanged",
        ],
    },
    "TC-109": {
        "title": "Deactivation of a user account blocks subsequent login",
        "targets": "FR-101, FR-102, FR-103",
        "preconditions": "staff01@wrhm.vn is active and the IT Administrator is signed in",
        "expected": "The account is soft deleted, audited and can no longer authenticate",
        "steps": [
            "Deactivate staff01@wrhm.vn as IT Administrator",
            "Confirm is_active is False (soft delete, not a hard delete)",
            "Confirm a DEACTIVATE_USER entry was recorded",
            "Attempt to sign in again and confirm it is refused",
        ],
    },
    "TC-110": {
        "title": "System prevents archiving a SKU with active on-hand inventory",
        "targets": "FR-104",
        "preconditions": "SKU-WIDGET-01 holds 150 units on hand",
        "expected": "Archiving is rejected while stock > 0 and allowed once stock is zero",
        "steps": [
            "Sign in as Inventory Controller",
            "Attempt to archive a SKU that still holds stock",
            "Confirm the request is rejected and the SKU stays active",
            "Archive a SKU with no stock and confirm it is soft deleted",
        ],
    },
    "TC-111": {
        "title": "Product tracking flags are persisted",
        "targets": "FR-104",
        "preconditions": "The catalog is reachable by the Inventory Controller",
        "expected": "requires_batch and requires_expiry are stored as booleans",
        "steps": [
            "Sign in as Inventory Controller",
            "Register a SKU with both tracking flags enabled",
            "Read the record back and confirm both flags survived the save",
        ],
    },
    "TC-112": {
        "title": "Bin capacity is a positive integer with derived free capacity",
        "targets": "FR-106",
        "preconditions": "Bin Z1-A01-R01-S1-B04 holds 40 of its 50 unit capacity",
        "expected": "Capacity is stored as a positive integer and free capacity is derived from it",
        "steps": [
            "Sign in as Warehouse Manager",
            "Read the seeded bin and derive the free capacity",
            "Create a new bin with capacity 50",
            "Confirm a capacity of 0 is rejected",
        ],
    },
    "TC-113": {
        "title": "Audit log entries are append-only",
        "targets": "FR-103, NFR-104",
        "preconditions": "At least one audit entry exists",
        "expected": "Direct modification and deletion of audit records are blocked",
        "steps": [
            "Sign in as IT Administrator and produce an audit entry",
            "Attempt to append, overwrite, delete and clear the audit trail",
            "Confirm every attempt is refused and the trail is unchanged",
        ],
    },
    "TC-114": {
        "title": "Item image placeholder fallback display",
        "targets": "FR-107, CR-01",
        "preconditions": "SKU-NO-IMG-01 exists without an image URL",
        "expected": "A generic placeholder is rendered when no image is associated",
        "steps": [
            "Read a SKU that has an image URL",
            "Read a SKU that has none",
            "Confirm the placeholder graphic is returned for the missing image",
        ],
    },
}


def tc(tc_id: str):
    """Mark a test as a requirement test case and report its outcome."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            meta = CASES[tc_id]
            started = time.perf_counter()
            sys.stdout.write("\n")
            sys.stdout.flush()
            try:
                summary = func(*args, **kwargs) or "all assertions satisfied"
            except Exception as exc:  # noqa: BLE001 - reported then re-raised
                logger.error("%s: %s -> FAILED", tc_id, exc)
                _record(tc_id, meta, "FAILED", str(exc), time.perf_counter() - started)
                raise
            logger.info("%s: %s -> PASSED", tc_id, summary)
            _record(tc_id, meta, "PASSED", summary, time.perf_counter() - started)

        return wrapper

    return decorator


_RESULTS = []


def _record(tc_id, meta, result, summary, duration):
    _RESULTS.append({
        "id": tc_id,
        "title": meta["title"],
        "related_requirements": meta["targets"],
        "preconditions": meta["preconditions"],
        "steps": meta["steps"],
        "expected_result": meta["expected"],
        "actual_result": summary,
        "status": result,
        "duration_s": round(duration, 4),
    })


@pytest.fixture(scope="session", autouse=True)
def _write_results():
    yield
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(_RESULTS, indent=2))


@pytest.fixture
def service():
    """A fresh service instance seeded from datasets/seed_master_data.json."""
    seed = PACKAGE_DIR / "datasets" / "seed_master_data_1.json"
    return Module1Service(str(seed))


# --------------------------------------------------------------------------
# test cases
# --------------------------------------------------------------------------
@tc("TC-101")
def test_tc101_valid_login(service):
    """TC-101 | Valid User Authentication | FR-101, NFR-101"""
    logger.info("TC-101: Authenticating user staff01@wrhm.vn...")
    result = service.login("staff01@wrhm.vn", "StaffPass123!")
    assert service.current_user is not None, "no session was established"
    assert result["user"]["email"] == "staff01@wrhm.vn", "session bound to the wrong account"
    assert result["user"]["is_active"], "an inactive account was allowed to authenticate"
    assert result["latency"] < 2.0, f"authentication took {result['latency']:.4f}s"
    return "Latency measured: %.4fs (Target <= 2.0s)" % result["latency"]


@tc("TC-102")
def test_tc102_invalid_credentials(service):
    """TC-102 | Rejection of login attempt with incorrect credentials | FR-101"""
    logger.info("TC-102: Attempting invalid login for staff01@wrhm.vn...")
    try:
        service.login("staff01@wrhm.vn", "WrongPass!")
    except ValueError as exc:
        assert "Invalid credentials" in str(exc), f"unexpected error text: {exc}"
        assert service.current_user is None, "a session survived a failed login"
        assert any(e["action"] == "LOGIN_FAILED" for e in service.audit_logs), \
            "the failed attempt was not recorded"
        return "Attempting invalid login; caught ValueError('%s')" % exc
    raise AssertionError("invalid credentials were accepted")


@tc("TC-103")
def test_tc103_rbac_unauthorized_access(service):
    """TC-103 | Unauthorized operational users cannot perform administrative actions | FR-102, NFR-102"""
    logger.info("TC-103: Staff attempting admin user provisioning...")
    service.login("staff01@wrhm.vn", "StaffPass123!")
    try:
        service.provision_user("newuser@wrhm.vn", "WAREHOUSE_STAFF", "pass", "staff01@wrhm.vn")
    except PermissionError as exc:
        assert "403" in str(exc), f"expected a 403, got: {exc}"
        assert "newuser@wrhm.vn" not in service.users, "the account was created anyway"
        assert any(e["action"] == "UNAUTHORIZED_ACCESS" for e in service.audit_logs), \
            "the refused attempt was not recorded"
        return "Staff attempting admin user provisioning; caught PermissionError(%s)" % exc
    raise AssertionError("a warehouse staff account was allowed to provision users")


@tc("TC-104")
def test_tc104_provision_user_creates_audit(service):
    """TC-104 | User provisioning creates an immutable audit record | FR-101, FR-102, FR-103"""
    logger.info("TC-104: Admin provisioning controller01@wrhm.vn...")
    service.login("admin@wrhm.vn", "AdminPass123!")
    created = service.provision_user(
        "controller01@wrhm.vn", "INVENTORY_CONTROLLER", "Controller01!", "admin@wrhm.vn"
    )
    assert created["email"] == "controller01@wrhm.vn", "the wrong account was created"
    assert created["role"] == "INVENTORY_CONTROLLER", "the role was not assigned"
    assert created["is_active"], "the new account is not active"
    entries = [e for e in service.audit_logs if e["action"] == "PROVISION_USER"]
    assert entries, "no PROVISION_USER entry was recorded"
    assert entries[-1]["user"] == "admin@wrhm.vn", "the audit entry has no actor"
    assert entries[-1]["details"]["email"] == "controller01@wrhm.vn", "the audit entry lost the subject"
    return ("Admin provisioned controller01@wrhm.vn; verified immutable PROVISION_USER log entry "
            "by %s" % entries[-1]["user"])


@tc("TC-105")
def test_tc105_duplicate_barcode_rejection(service):
    """TC-105 | Duplicate barcodes are rejected across SKUs | FR-104, NFR-103"""
    logger.info("TC-105: Attempted duplicate barcode '8931234567890'...")
    service.login("controller@wrhm.vn", "ControllerPass123!")
    before = len(service.skus)
    try:
        service.add_sku("SKU-WIDGET-99", "8931234567890", "Duplicate Widget", "EA")
    except ValueError as exc:
        assert "Duplicate barcode" in str(exc), f"unexpected error text: {exc}"
        assert len(service.skus) == before, "the rejected SKU was stored anyway"
        return "Attempted duplicate barcode '8931234567890'; caught ValueError('%s')" % exc
    raise AssertionError("a duplicate barcode was accepted")


@tc("TC-107")
def test_tc107_inventory_parameters_boundary(service):
    """TC-107 | Negative ROP and non-positive MOQ are rejected | FR-105"""
    logger.info("TC-107: Setting ROP=-5, MOQ=0...")
    service.login("controller@wrhm.vn", "ControllerPass123!")
    before = dict(service.skus["SKU-WIDGET-02"])
    try:
        service.update_sku_parameters("SKU-WIDGET-02", rop=-5, moq=0)
    except ValueError as exc:
        assert "ROP" in str(exc) or "MOQ" in str(exc), f"unexpected error text: {exc}"
        assert service.skus["SKU-WIDGET-02"]["rop"] == before["rop"], "the ROP was changed anyway"
        assert service.skus["SKU-WIDGET-02"]["moq"] == before["moq"], "the MOQ was changed anyway"
        return "Setting ROP=-5, MOQ=0; caught ValueError('%s')" % exc
    raise AssertionError("invalid thresholds were accepted")


@tc("TC-108")
def test_tc108_storage_hierarchy_duplicate_coord(service):
    """TC-108 | Duplicate composite bin coordinates are rejected | FR-106"""
    logger.info("TC-108: Attempted duplicate bin coordinate 'Z1-A01-R01-S1-B01'...")
    service.login("manager@wrhm.vn", "ManagerPass123!")
    before = len(service.storage_bins)
    try:
        service.create_bin("Z1-A01-R01-S1-B01", 50)
    except ValueError as exc:
        assert "Duplicate" in str(exc), f"unexpected error text: {exc}"
        assert len(service.storage_bins) == before, "the duplicate bin was stored anyway"
        return "Attempted duplicate bin coordinate 'Z1-A01-R01-S1-B01'; caught ValueError('%s')" % exc
    raise AssertionError("a duplicate bin coordinate was accepted")


@tc("TC-109")
def test_tc109_deactivate_user_blocks_login(service):
    """TC-109 | Deactivating an account blocks subsequent login | FR-101, FR-102, FR-103"""
    logger.info("TC-109: Deactivated user staff01@wrhm.vn...")
    service.login("admin@wrhm.vn", "AdminPass123!")
    service.deactivate_user("staff01@wrhm.vn", "admin@wrhm.vn")
    assert service.users["staff01@wrhm.vn"]["is_active"] is False, "the account is still active"
    assert service.users["staff01@wrhm.vn"].get("deleted_at") is not None, \
        "the account was hard deleted instead of soft deleted"
    entries = [e for e in service.audit_logs if e["action"] == "DEACTIVATE_USER"]
    assert entries, "no DEACTIVATE_USER entry was recorded"
    service.current_user = None
    try:
        service.login("staff01@wrhm.vn", "StaffPass123!")
    except PermissionError as exc:
        assert "suspended" in str(exc).lower(), f"unexpected error text: {exc}"
        return ("Deactivated user; verified is_active=False, DEACTIVATE_USER audit entry, "
                "login rejected")
    raise AssertionError("a deactivated account was allowed to sign in")


@tc("TC-110")
def test_tc110_archive_sku_with_stock_blocked(service):
    """TC-110 | Archiving a SKU with on-hand stock is blocked | FR-104"""
    service.login("controller@wrhm.vn", "ControllerPass123!")
    stock = service.skus["SKU-WIDGET-01"]["stock_on_hand"]
    assert stock > 0, "the fixture SKU has no stock, the test would be meaningless"
    logger.info("TC-110: Attempted archiving SKU with on_hand=%d...", stock)
    try:
        service.archive_sku("SKU-WIDGET-01")
    except ValueError as exc:
        assert "stock > 0" in str(exc), f"unexpected error text: {exc}"
        assert service.skus["SKU-WIDGET-01"]["status"] == "ACTIVE", "the SKU was archived anyway"
        assert service.archive_sku("SKU-WIDGET-02") is True, "a zero-stock SKU was not archived"
        assert service.skus["SKU-WIDGET-02"]["status"] == "ARCHIVED", "the SKU was not soft deleted"
        return ("Attempted archiving SKU with on_hand=%d; caught ValueError('%s')" % (stock, exc))
    raise AssertionError("a SKU with stock on hand was archived")


@tc("TC-111")
def test_tc111_tracking_flags_persisted(service):
    """TC-111 | Product tracking flags are persisted | FR-104"""
    logger.info("TC-111: Registering SKU-BATCH-01 with both tracking flags enabled...")
    service.login("controller@wrhm.vn", "ControllerPass123!")
    sku = service.add_sku("SKU-BATCH-01", "8931234567899", "Sterile Kit", "EA",
                          requires_batch=True, requires_expiry=True)
    stored = service.skus["SKU-BATCH-01"]
    assert stored["requires_batch"] is True, "requires_batch was not persisted"
    assert stored["requires_expiry"] is True, "requires_expiry was not persisted"
    assert sku["requires_batch"] is True and sku["requires_expiry"] is True
    return "Verified requires_batch=True and requires_expiry=True persistence"


@tc("TC-112")
def test_tc112_bin_capacity_positive_and_free_derived(service):
    """TC-112 | Bin capacity is a positive integer with derived free capacity | FR-106"""
    logger.info("TC-112: Reading bin Z1-A01-R01-S1-B04 (capacity 50, on hand 40)...")
    service.login("manager@wrhm.vn", "ManagerPass123!")
    seeded = service.storage_bins["Z1-A01-R01-S1-B04"]
    free = seeded["capacity"] - seeded["on_hand"]
    assert seeded["capacity"] == 50, "unexpected seed capacity"
    assert free == 10, f"free capacity should be 10, got {free}"
    assert service.create_bin("Z1-A01-R01-S1-B05", 50) is True, "the bin was not created"
    created = service.storage_bins["Z1-A01-R01-S1-B05"]
    assert created["capacity"] == 50, "the capacity was not stored"
    try:
        service.create_bin("Z1-A01-R01-S1-B06", 0)
    except ValueError as exc:
        assert "Capacity" in str(exc), f"unexpected error text: {exc}"
        return "Capacity 50 saved (free=%d); capacity 0 rejected" % free
    raise AssertionError("a capacity of 0 was accepted")


@tc("TC-113")
def test_tc113_audit_log_append_only(service):
    """TC-113 | Audit log entries are append-only | FR-103, NFR-104"""
    logger.info("TC-113: Attempting mutation/deletion of audit logs...")
    service.login("admin@wrhm.vn", "AdminPass123!")
    service.provision_user("audit01@wrhm.vn", "WAREHOUSE_STAFF", "Audit01!", "admin@wrhm.vn")
    entries = len(service.audit_logs)
    for label, action in (
        ("append", lambda: service.audit_logs.append({"action": "TAMPER"})),
        ("overwrite", lambda: service.audit_logs.__setitem__(0, {"action": "TAMPER"})),
        ("delete", lambda: service.audit_logs.__delitem__(0)),
        ("clear", lambda: service.audit_logs.clear()),
    ):
        try:
            action()
        except PermissionError as exc:
            assert "append-only" in str(exc), f"unexpected error text for {label}: {exc}"
        else:
            raise AssertionError(f"the audit log accepted a {label} operation")
    assert len(service.audit_logs) == entries, "the audit trail changed size"
    return "Attempted mutation/deletion of audit logs; caught PermissionError"


@tc("TC-114")
def test_tc114_thumbnail_placeholder_fallback(service):
    """TC-114 | Item image placeholder fallback display | FR-107, CR-01"""
    logger.info("TC-114: Querying SKU-NO-IMG-01 (no image URL)...")
    placeholder = service.get_sku_display("SKU-NO-IMG-01")
    assert placeholder["image_url"] == "placeholder-thumbnail.svg", "no placeholder was returned"
    with_image = service.get_sku_display("SKU-WIDGET-01")
    assert with_image["image_url"] == "widget01.png", "the stored image was replaced"
    return "SKU-NO-IMG-01 queried; verified placeholder 'placeholder-thumbnail.svg' fallback"
