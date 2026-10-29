"""
==============================================================================
Test Suite: Warehouse Inventory and Reorder System (WrHM)
Project: Module 3: Sổ cái Tồn kho & Kiểm kê (Inventory Ledger & Stock Control)
Organization: Phenikaa University - School of Information Systems
Authors Group 2: 
  1. Nguyễn Đăng Quang Anh (24100455)
  2. Tô Kim Trung (24100131)
  3. Cao Bá Sơn (24100038)
  4. Nguyễn Dương Hà My (24100192)
Version: 1.0  |  Date: 2026-09-15
Standards Reference: IEEE 830 / ISO/IEC/IEEE 29148 & ISO/IEC 25010

Excel Traceability Coverage (15 Test Cases: TC-301 to TC-315):
  - Functional Requirements (FR-301 to FR-308)
  - Non-Functional Requirements (NFR-301 to NFR-305)
  - Change Requests (CR-301, CR-302)
==============================================================================
"""

import time
import json
import threading
from datetime import datetime, timezone

try:
    import pytest
    fixture = pytest.fixture
except ImportError:
    pytest = None
    def fixture(fn):
        return fn


# ============================================================================
# DOMAIN EXCEPTIONS
# ============================================================================

class InsufficientStockError(Exception):
    """Raised when Available-To-Promise (ATP) or On-Hand is insufficient (FR-302, FR-303)."""
    pass


class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused with a conflicting payload (FR-304)."""
    pass


class ImmutableLedgerError(Exception):
    """Raised when an unauthorized UPDATE or DELETE is attempted on the audit ledger (FR-305, NFR-304)."""
    pass


class ZeroAdjustmentError(Exception):
    """Raised when an adjustment delta is zero (CR-302, FR-303, FR-305)."""
    pass


# ============================================================================
# DOMAIN MODEL ENTITIES
# ============================================================================

class StockBalance:
    """Represents real-time stock balances at a specific Bin Location (FR-301)."""
    def __init__(self, sku: str, bin_loc: str, on_hand: int = 0, allocated: int = 0, locked: int = 0, system_ref=None):
        self.sku = sku
        self.bin_loc = bin_loc
        self.on_hand = on_hand
        self.allocated = allocated
        self.locked = locked
        self.system_ref = system_ref

    @property
    def atp(self) -> int:
        if self.system_ref and not self.system_ref.quarantine_enabled:
            return self.on_hand - self.allocated
        return self.on_hand - self.allocated - self.locked


class LedgerRecord:
    """Append-only immutable transaction log entry (FR-305, NFR-304)."""
    def __init__(self, tx_id: str, sku: str, bin_loc: str, qty_delta: int, reason_code: str,
                 on_hand_before: int, on_hand_after: int, atp_after: int, timestamp: datetime = None):
        self.tx_id = tx_id
        self.sku = sku
        self.bin_loc = bin_loc
        self.qty_delta = qty_delta
        self.reason_code = reason_code
        self.on_hand_before = on_hand_before
        self.on_hand_after = on_hand_after
        self.atp_after = atp_after
        self.timestamp = timestamp or datetime.now(timezone.utc)
        self._sealed = True

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise ImmutableLedgerError(f"Modification prohibited: ledger record '{self.tx_id}' is immutable.")
        super().__setattr__(name, value)


class ImmutableLedgerList(list):
    """Custom append-only list that blocks item deletion and replacement (NFR-304, FR-305)."""
    def __delitem__(self, index):
        raise ImmutableLedgerError("DELETE operation is strictly prohibited on the immutable transaction ledger.")

    def __setitem__(self, index, value):
        raise ImmutableLedgerError("UPDATE operation is strictly prohibited on the immutable transaction ledger.")

    def pop(self, *args, **kwargs):
        raise ImmutableLedgerError("DELETE (pop) operation is strictly prohibited on the immutable transaction ledger.")

    def remove(self, *args, **kwargs):
        raise ImmutableLedgerError("DELETE (remove) operation is strictly prohibited on the immutable transaction ledger.")

    def clear(self):
        raise ImmutableLedgerError("DELETE (clear) operation is strictly prohibited on the immutable transaction ledger.")


class BlindCycleCountSession:
    """Blind Cycle Count session tracking (FR-306, FR-307, FR-308)."""
    def __init__(self, session_id: str, sku: str, bin_loc: str, snapshot_expected_qty: int, threshold: int = 5):
        self.session_id = session_id
        self.sku = sku
        self.bin_loc = bin_loc
        self.snapshot_expected_qty = snapshot_expected_qty
        self.threshold = threshold
        self.counted_qty = None
        self.variance = None
        self.status = "open"  # 'open', 'completed', 'pending_approval', 'rejected'


# ============================================================================
# WAREHOUSE INVENTORY SYSTEM IMPLEMENTATION (WrHM Module 3)
# ============================================================================

class WarehouseInventorySystem:
    def __init__(self):
        self.stocks = {}
        self.ledger = ImmutableLedgerList()
        self.idempotency_store = {}
        self.cycle_counts = {}
        self.quarantine_enabled = True
        self._lock = threading.Lock()

    def seed_stock(self, sku: str, bin_loc: str, on_hand: int, allocated: int, locked: int):
        """FR-301: Initialize stock balance for SKU and Bin."""
        with self._lock:
            self.stocks[(sku, bin_loc)] = StockBalance(sku, bin_loc, on_hand, allocated, locked, system_ref=self)

    def get_stock(self, sku: str, bin_loc: str) -> dict:
        """FR-301: Query real-time On-Hand, Allocated, Locked, and ATP."""
        with self._lock:
            key = (sku, bin_loc)
            if key not in self.stocks:
                return {"sku": sku, "bin": bin_loc, "on_hand": 0, "allocated": 0, "locked": 0, "atp": 0}
            sb = self.stocks[key]
            data = {
                "sku": sb.sku,
                "bin": sb.bin_loc,
                "on_hand": sb.on_hand,
                "allocated": sb.allocated,
                "atp": sb.atp
            }
            if self.quarantine_enabled:
                data["locked"] = sb.locked
            return data

    def allocate_stock(self, sku: str, bin_loc: str, reserve_qty: int) -> dict:
        """FR-302: Reserve available stock upon receiving order request."""
        with self._lock:
            key = (sku, bin_loc)
            if key not in self.stocks:
                raise InsufficientStockError(f"SKU {sku} at bin {bin_loc} not found.")
            sb = self.stocks[key]
            if sb.atp < reserve_qty:
                raise InsufficientStockError(f"Insufficient ATP. Requested: {reserve_qty}, Available: {sb.atp}")
            sb.allocated += reserve_qty
            return {"sku": sb.sku, "bin": sb.bin_loc, "on_hand": sb.on_hand, "allocated": sb.allocated, "atp": sb.atp}

    def adjust_inventory(self, idempotency_key: str, sku: str, bin_loc: str, qty_delta: int,
                         reason_code: str, actor: str = "ACT-301") -> dict:
        """FR-303, FR-304, FR-305, CR-302: Record stock adjustment with idempotency and audit log."""
        if qty_delta == 0:
            raise ZeroAdjustmentError("Adjustment delta cannot be zero (CR-302).")

        with self._lock:
            payload = {"sku": sku, "bin": bin_loc, "qty_delta": qty_delta, "reason_code": reason_code}

            if idempotency_key in self.idempotency_store:
                cached = self.idempotency_store[idempotency_key]
                if cached["payload"] != payload:
                    raise IdempotencyConflictError("Idempotency key replayed with mismatched payload.")
                cached_res = cached["result"].copy()
                cached_res["is_replay"] = True
                return cached_res

            key = (sku, bin_loc)
            if key not in self.stocks:
                self.stocks[key] = StockBalance(sku, bin_loc, 0, 0, 0, system_ref=self)
            sb = self.stocks[key]

            on_hand_before = sb.on_hand
            new_on_hand = on_hand_before + qty_delta
            new_atp = sb.atp + qty_delta

            if new_on_hand < 0 or new_atp < 0:
                raise InsufficientStockError("Adjustment results in negative on-hand or ATP balance.")

            sb.on_hand = new_on_hand

            tx_id = f"TX-{len(self.ledger) + 1:03d}"
            record = LedgerRecord(tx_id, sku, bin_loc, qty_delta, reason_code,
                                  on_hand_before, new_on_hand, sb.atp)
            self.ledger.append(record)

            res = {
                "tx_id": tx_id,
                "sku": sku,
                "bin": bin_loc,
                "on_hand": new_on_hand,
                "allocated": sb.allocated,
                "atp": sb.atp,
                "is_replay": False
            }

            self.idempotency_store[idempotency_key] = {
                "payload": payload,
                "result": res,
                "created_at": datetime.now(timezone.utc),
                "ttl_hours": 72
            }
            return res

    def create_blind_count(self, session_id: str, sku: str, bin_loc: str, threshold: int = 5) -> BlindCycleCountSession:
        """FR-306: Initialize blind cycle count session."""
        with self._lock:
            key = (sku, bin_loc)
            expected = self.stocks[key].on_hand if key in self.stocks else 0
            session = BlindCycleCountSession(session_id, sku, bin_loc, expected, threshold)
            self.cycle_counts[session_id] = session
            return session

    def get_blind_count_sheet(self, session_id: str, actor: str) -> dict:
        """FR-306, NFR-305: Retrieve count sheet with masked expected quantity for Warehouse Clerks."""
        with self._lock:
            session = self.cycle_counts[session_id]
            sheet = {
                "session_id": session.session_id,
                "sku": session.sku,
                "bin": session.bin_loc,
                "status": session.status
            }
            if actor == "ACT-303":
                return sheet
            sheet["snapshot_expected_qty"] = session.snapshot_expected_qty
            return sheet

    def submit_physical_count(self, session_id: str, counted_qty: int, actor: str = "ACT-303") -> dict:
        """FR-307, FR-308: Submit physical count and auto-reconcile or hold."""
        if counted_qty < 0:
            raise ValueError("Counted quantity must be non-negative.")

        with self._lock:
            session = self.cycle_counts[session_id]
            session.counted_qty = counted_qty
            session.variance = counted_qty - session.snapshot_expected_qty

            if abs(session.variance) <= session.threshold:
                key = (session.sku, session.bin_loc)
                if key in self.stocks:
                    self.stocks[key].on_hand = counted_qty
                session.status = "completed"
            else:
                session.status = "pending_approval"

            return {
                "session_id": session.session_id,
                "counted_qty": session.counted_qty,
                "variance": session.variance,
                "status": session.status
            }

    def review_cycle_count(self, session_id: str, approve: bool, actor: str = "ACT-301") -> dict:
        """CR-301, FR-308: Supervisor approves or rejects high-variance count."""
        with self._lock:
            session = self.cycle_counts[session_id]
            if session.status != "pending_approval":
                raise ValueError("Session is not in pending_approval state.")

            if approve:
                session.status = "completed"
                key = (session.sku, session.bin_loc)
                if key in self.stocks:
                    self.stocks[key].on_hand = session.counted_qty
            else:
                session.status = "rejected"

            return {"session_id": session.session_id, "status": session.status}


# ============================================================================
# TEST SUITE: 15 TEST CASES FROM EXCEL (TC-301 TO TC-315)
# ============================================================================

@fixture
def system():
    return WarehouseInventorySystem()


def test_tc_301_verify_initialize_and_query_stock(system):
    """TC-301 | Related: FR-301 | Priority: High | Verify Initialize & Query Real-time Stock Balances"""
    system.seed_stock(sku="SKU-301", bin_loc="BIN-A1", on_hand=100, allocated=20, locked=5)
    res = system.get_stock("SKU-301", "BIN-A1")
    assert res["on_hand"] == 100
    assert res["allocated"] == 20
    assert res["locked"] == 5
    assert res["atp"] == 75


def test_tc_302_verify_allocate_stock_and_deduct_atp(system):
    """TC-302 | Related: FR-302 | Priority: High | Verify Allocate Stock & Deduct ATP"""
    system.seed_stock("SKU-301", "BIN-A1", on_hand=100, allocated=20, locked=5)
    res = system.allocate_stock("SKU-301", "BIN-A1", reserve_qty=25)
    assert res["allocated"] == 45
    assert res["atp"] == 50
    assert res["on_hand"] == 100


def test_tc_303_verify_record_stock_adjustments_with_reason_codes(system):
    """TC-303 | Related: FR-303 | Priority: High | Verify Record Stock Adjustments with Reason Codes"""
    system.seed_stock("SKU-301", "BIN-A1", on_hand=100, allocated=35, locked=0)
    res = system.adjust_inventory(
        idempotency_key="IK-303", sku="SKU-301", bin_loc="BIN-A1", qty_delta=-10, reason_code="DAMAGED", actor="ACT-301"
    )
    assert res["on_hand"] == 90
    assert res["atp"] == 55


def test_tc_304_verify_enforce_transaction_idempotency_on_duplicate_request(system):
    """TC-304 | Related: FR-304 | Priority: High | Verify Enforce Transaction Idempotency on Duplicate Request"""
    system.seed_stock("SKU-301", "BIN-A1", on_hand=90, allocated=0, locked=0)
    res1 = system.adjust_inventory("IK-304", "SKU-301", "BIN-A1", -5, "EXPIRED")
    assert res1["on_hand"] == 85
    assert res1["is_replay"] is False

    res2 = system.adjust_inventory("IK-304", "SKU-301", "BIN-A1", -5, "EXPIRED")
    assert res2["is_replay"] is True
    assert res2["on_hand"] == 85
    assert len(system.ledger) == 1


def test_tc_305_verify_append_only_immutable_transaction_ledger_record(system):
    """TC-305 | Related: FR-305 | Priority: High | Verify Append-Only Immutable Transaction Ledger Record"""
    system.seed_stock("SKU-302", "BIN-B1", on_hand=50, allocated=0, locked=0)
    system.adjust_inventory("IK-305", "SKU-302", "BIN-B1", -5, "LOST")
    assert len(system.ledger) == 1
    rec = system.ledger[0]
    assert rec.sku == "SKU-302"
    assert rec.qty_delta == -5
    assert rec.reason_code == "LOST"
    assert rec.on_hand_before == 50
    assert rec.on_hand_after == 45
    assert rec.atp_after == 45


def test_tc_306_verify_create_blind_count_and_mask_system_quantity(system):
    """TC-306 | Related: FR-306 | Priority: High | Verify Create Blind Cycle Count & Mask System Quantity"""
    system.seed_stock("SKU-303", "BIN-C1", on_hand=200, allocated=0, locked=0)
    system.create_blind_count("CC-301", "SKU-303", "BIN-C1")
    sheet = system.get_blind_count_sheet("CC-301", actor="ACT-303")
    assert "session_id" in sheet
    assert "sku" in sheet
    assert "bin" in sheet
    assert "status" in sheet
    assert "snapshot_expected_qty" not in sheet


def test_tc_307_verify_submit_physical_count_and_calculate_variance(system):
    """TC-307 | Related: FR-307 | Priority: High | Verify Submit Physical Count & Calculate Variance"""
    system.seed_stock("SKU-303", "BIN-C1", on_hand=200, allocated=0, locked=0)
    system.create_blind_count("CC-301", "SKU-303", "BIN-C1")
    res = system.submit_physical_count("CC-301", counted_qty=197, actor="ACT-303")
    assert res["counted_qty"] == 197
    assert res["variance"] == -3


def test_tc_308_verify_auto_reconcile_or_hold_based_on_threshold(system):
    """TC-308 | Related: FR-308 | Priority: High | Verify Auto-Reconcile or Hold Based on Threshold"""
    system.seed_stock("SKU-303", "BIN-C1", on_hand=200, allocated=0, locked=0)
    system.create_blind_count("CC-301", "SKU-303", "BIN-C1", threshold=5)
    res1 = system.submit_physical_count("CC-301", counted_qty=197)
    assert res1["status"] == "completed"
    assert system.stocks[("SKU-303", "BIN-C1")].on_hand == 197

    system.create_blind_count("CC-302", "SKU-303", "BIN-C1", threshold=5)
    res2 = system.submit_physical_count("CC-302", counted_qty=180)
    assert res2["status"] == "pending_approval"
    assert system.stocks[("SKU-303", "BIN-C1")].on_hand == 197


def test_tc_309_verify_real_time_atp_query_and_allocation_latency(system):
    """TC-309 | Related: NFR-301 | Priority: High | Verify Real-Time ATP Query & Allocation Latency (P99 <= 100ms)"""
    system.seed_stock("SKU-PERF", "BIN-P1", on_hand=10000, allocated=0, locked=0)
    latencies = []
    for _ in range(1000):
        t0 = time.perf_counter()
        system.allocate_stock("SKU-PERF", "BIN-P1", reserve_qty=1)
        latencies.append((time.perf_counter() - t0) * 1000)

    latencies.sort()
    p99 = latencies[int(len(latencies) * 0.99)]
    assert p99 <= 100.0


def test_tc_310_verify_concurrency_locking_prevents_negative_atp(system):
    """TC-310 | Related: NFR-302 | Priority: High | Verify Concurrency & Locking Prevents Negative ATP"""
    system.seed_stock("SKU-LOCK", "BIN-L1", on_hand=50, allocated=0, locked=0)
    success_count = [0]
    failure_count = [0]

    def worker():
        try:
            system.allocate_stock("SKU-LOCK", "BIN-L1", reserve_qty=1)
            success_count[0] += 1
        except InsufficientStockError:
            failure_count[0] += 1

    threads = [threading.Thread(target=worker) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert success_count[0] == 50
    assert failure_count[0] == 50
    st = system.get_stock("SKU-LOCK", "BIN-L1")
    assert st["atp"] == 0
    assert st["allocated"] == 50


def test_tc_311_verify_idempotency_key_retention_and_fast_lookup(system):
    """TC-311 | Related: NFR-303 | Priority: High | Verify Idempotency Key Retention (>= 72h) & Fast Lookup (<= 10ms)"""
    system.seed_stock("SKU-314", "BIN-K1", on_hand=100, allocated=0, locked=0)
    system.adjust_inventory("IK-NFR-303", "SKU-314", "BIN-K1", -2, "DAMAGED")

    t0 = time.perf_counter()
    system.adjust_inventory("IK-NFR-303", "SKU-314", "BIN-K1", -2, "DAMAGED")
    lookup_ms = (time.perf_counter() - t0) * 1000

    entry = system.idempotency_store["IK-NFR-303"]
    assert entry["ttl_hours"] >= 72
    assert lookup_ms <= 10.0


def test_tc_312_verify_immutable_audit_ledger_blocks_update_and_delete(system):
    """TC-312 | Related: NFR-304 | Priority: High | Verify Immutable Audit Ledger Blocks UPDATE and DELETE"""
    system.seed_stock("SKU-315", "BIN-M1", on_hand=50, allocated=0, locked=0)
    system.adjust_inventory("IK-315", "SKU-315", "BIN-M1", -5, "LOST")
    rec = system.ledger[0]

    try:
        rec.qty_delta = -999
        assert False, "Expected ImmutableLedgerError on UPDATE was not raised"
    except ImmutableLedgerError:
        pass

    try:
        del system.ledger[0]
        assert False, "Expected ImmutableLedgerError on DELETE was not raised"
    except ImmutableLedgerError:
        pass

    assert len(system.ledger) == 1
    assert system.ledger[0].tx_id == "TX-001"
    assert system.ledger[0].qty_delta == -5


def test_tc_313_verify_backend_blind_count_serializer_strips_expected_qty(system):
    """TC-313 | Related: NFR-305 | Priority: High | Verify Backend Blind Count Serializer Strips snapshot_expected_qty"""
    system.seed_stock("SKU-316", "BIN-C5", on_hand=250, allocated=0, locked=0)
    system.create_blind_count("CC-305", "SKU-316", "BIN-C5")
    sheet_data = system.get_blind_count_sheet("CC-305", actor="ACT-303")
    json_bytes = json.dumps(sheet_data).encode("utf-8")

    assert b"snapshot_expected_qty" not in json_bytes
    assert b"250" not in json_bytes


def test_tc_314_verify_supervisor_review_and_rejection_of_high_variance_session(system):
    """TC-314 | Related: CR-301 | Priority: Medium | Verify Supervisor Review & Rejection of High-Variance Session"""
    system.seed_stock("SKU-317", "BIN-C7", on_hand=200, allocated=0, locked=0)
    system.create_blind_count("CC-314", "SKU-317", "BIN-C7", threshold=5)
    system.submit_physical_count("CC-314", counted_qty=150)
    res = system.review_cycle_count("CC-314", approve=False, actor="ACT-301")
    assert res["status"] == "rejected"
    assert system.stocks[("SKU-317", "BIN-C7")].on_hand == 200


def test_tc_315_verify_rejection_of_zero_quantity_adjustment(system):
    """TC-315 | Related: CR-302 | Priority: High | Verify Rejection of Zero-Quantity Adjustment"""
    system.seed_stock("SKU-315", "BIN-Z1", on_hand=80, allocated=0, locked=0)
    try:
        system.adjust_inventory("IK-315", "SKU-315", "BIN-Z1", qty_delta=0, reason_code="FOUND", actor="ACT-301")
        assert False, "Expected ZeroAdjustmentError was not raised"
    except ZeroAdjustmentError:
        pass

    assert system.stocks[("SKU-315", "BIN-Z1")].on_hand == 80
    assert len(system.ledger) == 0


if __name__ == "__main__":
    print("Executing Warehouse Inventory System Test Suite (WrHM Module 3: TC-301 to TC-315)...")
    tests = [
        test_tc_301_verify_initialize_and_query_stock,
        test_tc_302_verify_allocate_stock_and_deduct_atp,
        test_tc_303_verify_record_stock_adjustments_with_reason_codes,
        test_tc_304_verify_enforce_transaction_idempotency_on_duplicate_request,
        test_tc_305_verify_append_only_immutable_transaction_ledger_record,
        test_tc_306_verify_create_blind_count_and_mask_system_quantity,
        test_tc_307_verify_submit_physical_count_and_calculate_variance,
        test_tc_308_verify_auto_reconcile_or_hold_based_on_threshold,
        test_tc_309_verify_real_time_atp_query_and_allocation_latency,
        test_tc_310_verify_concurrency_locking_prevents_negative_atp,
        test_tc_311_verify_idempotency_key_retention_and_fast_lookup,
        test_tc_312_verify_immutable_audit_ledger_blocks_update_and_delete,
        test_tc_313_verify_backend_blind_count_serializer_strips_expected_qty,
        test_tc_314_verify_supervisor_review_and_rejection_of_high_variance_session,
        test_tc_315_verify_rejection_of_zero_quantity_adjustment,
    ]
    passed = 0
    for t in tests:
        s = WarehouseInventorySystem()
        try:
            t(s)
            print(f"  [PASS] {t.__name__}")
            passed += 1
        except Exception as err:
            print(f"  [FAIL] {t.__name__}: {err}")
    print(f"\nResult: {passed}/{len(tests)} tests passed (100% Traceability Coverage across TC-301 to TC-315)!")
