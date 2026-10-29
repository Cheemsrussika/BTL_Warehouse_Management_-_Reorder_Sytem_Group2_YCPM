"""Module 4 - Reorder Engine & Procurement (prototype service).

Covers the scope of ``Untitled 1.xlsx`` (FR-401..FR-405): replenishment policy,
ROP monitoring, automated cycle, quantity calculation and purchase order
preparation.  Approval routing, supplier transmission, notifications and
reporting (FR-406..FR-410) are outside this package and not implemented.

Seed data: ``datasets/seed_master_data.json`` (built from the CSV datasets).
"""

import copy
import json
import math
import time
from datetime import date, datetime, timedelta
from pathlib import Path

DRAFT = "DRAFT"
#: Orders that already cover a shortage and must not be suggested again.
INCOMING_PO_STATUSES = {"PENDING_APPROVAL", "APPROVED", "SENT", "ACKNOWLEDGED", "PARTIALLY_RECEIVED"}

ROLE_PERMISSIONS = {
    "IT_ADMIN": {"SCHEDULER_MANAGE"},
    "WAREHOUSE_MANAGER": {"SUGGESTION_VIEW"},
    "INVENTORY_CONTROLLER": {"POLICY_MANAGE", "SUGGESTION_MANAGE", "SUGGESTION_VIEW", "PO_CREATE"},
    "WAREHOUSE_STAFF": {"STOCK_POST"},
}


class PermissionError(Exception):
    """Missing role permission (HTTP 403)."""


class ValidationError(ValueError):
    """Business-rule violation (HTTP 400)."""


class StateError(ValidationError):
    """Action not allowed in the current state (HTTP 409)."""


def _int(name, value, minimum):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValidationError(f"{name} must be an integer >= {minimum}")
    return value


class Module4Service:
    def __init__(self, seed_path=None, today=None):
        path = seed_path or Path(__file__).resolve().parents[2] / "datasets" / "seed_master_data.json"
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.users = {u["email"]: dict(u) for u in data.get("users", [])}
        self.skus = {s["sku_code"]: dict(s) for s in data.get("skus", [])}
        self.sku_by_barcode = {s["barcode"]: s["sku_code"] for s in self.skus.values()}
        self.suppliers = {s["supplier_id"]: dict(s) for s in data.get("suppliers", [])}
        self.demand_history = {k: [dict(r) for r in v] for k, v in data.get("demand_history", {}).items()}
        self.purchase_orders = {po["po_id"]: dict(po) for po in data.get("purchase_orders", [])}
        self.policies = {
            code: {
                "sku_code": code,
                "supplier_id": s.get("supplier_id"),
                "rop": int(s.get("rop", 0)),
                "safety_stock": int(s.get("safety_stock", 0)),
                "lead_time_days": int(s.get("lead_time_days", 1)),
                "moq": int(s.get("moq", 1)),
                "order_multiple": int(s.get("order_multiple", 1)),
            }
            for code, s in self.skus.items()
        }
        self.suggestions = {}
        self.executions = []
        self.audit_logs = []
        self.last_low_stock_evaluation = None
        self.current_user = None
        self._today_override = today

    # ------------------------------------------------------------------ utils
    def _now(self):
        return datetime.now().isoformat(timespec="seconds")

    def _today(self):
        return self._today_override or date.today()

    def _log(self, action, actor=None, details=None):
        self.audit_logs.append({
            "at": self._now(),
            "action": action,
            "actor": actor or (self.current_user["email"] if self.current_user else "system"),
            "details": details or {},
        })

    def _has_permission(self, perm):
        return bool(self.current_user) and perm in ROLE_PERMISSIONS.get(self.current_user.get("role"), set())

    def check_permission(self, perm):
        if not self.current_user:
            raise PermissionError("Not authenticated")
        if not self._has_permission(perm):
            self._log("UNAUTHORIZED_ACCESS", details={"required": perm})
            raise PermissionError("403 Forbidden / PermissionError")
        return True

    _require = check_permission

    def _next_id(self, collection, prefix):
        number = len(collection) + 1
        while f"{prefix}-{number:04d}" in collection:
            number += 1
        return f"{prefix}-{number:04d}"

    # ------------------------------------------------------------- auth (M1)
    def login(self, email, password):
        start = time.time()
        user = self.users.get(email)
        if user is None:
            self._log("LOGIN_FAILED", actor=email, details={"reason": "unknown_user"})
            raise ValueError("Invalid credentials")
        if not user.get("is_active", True):
            self._log("LOGIN_FAILED", actor=email, details={"reason": "inactive"})
            raise PermissionError("Account suspended")
        if user.get("password") != password:
            self._log("LOGIN_FAILED", actor=email, details={"reason": "bad_password"})
            raise ValueError("Invalid credentials")
        self.current_user = dict(user)
        self._log("LOGIN_SUCCESS", actor=email)
        return {"user": dict(user), "latency": time.time() - start}

    def logout(self):
        self.current_user = None

    # -------------------------------------------------------------- FR-401
    def configure_policy(self, sku_code, rop, safety_stock, lead_time_days, moq, order_multiple, supplier_id=None):
        self._require("POLICY_MANAGE")
        if sku_code not in self.skus:
            raise ValidationError("SKU not found")
        old = self.policies.get(sku_code) or {}
        supplier = supplier_id if supplier_id is not None else (
            old.get("supplier_id") or self.skus[sku_code].get("supplier_id"))
        if supplier:
            record = self.suppliers.get(supplier)
            if record is None:
                raise ValidationError("Supplier not found")
            if not record.get("active", True):
                raise ValidationError("Supplier is inactive")

        _int("ROP", rop, 0)
        _int("Safety stock", safety_stock, 0)
        _int("Lead time", lead_time_days, 1)
        _int("MOQ", moq, 1)
        _int("Order multiple", order_multiple, 1)
        if moq % order_multiple:
            raise ValidationError("MOQ must be a multiple of the order multiple")

        policy = {
            "sku_code": sku_code, "supplier_id": supplier, "rop": rop,
            "safety_stock": safety_stock, "lead_time_days": lead_time_days,
            "moq": moq, "order_multiple": order_multiple,
        }
        self.policies[sku_code] = policy
        self.skus[sku_code].update({k: policy[k] for k in
                                    ("rop", "safety_stock", "lead_time_days", "moq", "order_multiple", "supplier_id")})
        self._log("POLICY_UPDATED", details={"sku_code": sku_code,
                                             "old": copy.deepcopy(old) or None,
                                             "new": copy.deepcopy(policy)})
        return copy.deepcopy(policy)

    def get_policy(self, sku_code):
        if sku_code not in self.policies:
            raise ValidationError("SKU has no replenishment policy")
        return copy.deepcopy(self.policies[sku_code])

    # -------------------------------------------------------------- FR-402
    def get_available_stock(self, sku_code):
        sku = self.skus.get(sku_code)
        if sku is None:
            raise ValidationError("SKU not found")
        return int(sku.get("stock_on_hand", 0)) - int(sku.get("reserved_qty", 0))

    def post_stock_movement(self, sku_code, quantity, reason=""):
        self._require("STOCK_POST")
        if sku_code not in self.skus:
            raise ValidationError("SKU not found")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not quantity:
            raise ValidationError("Quantity must be a non-zero integer")
        sku = self.skus[sku_code]
        new_stock = int(sku.get("stock_on_hand", 0)) + quantity
        if new_stock < 0:
            raise ValidationError("Insufficient stock for this movement")
        sku["stock_on_hand"] = new_stock
        self._log("STOCK_MOVEMENT", details={"sku_code": sku_code, "quantity": quantity,
                                             "stock_on_hand": new_stock, "reason": reason})
        alerts = self.evaluate_low_stock([sku_code])
        return alerts[0] if alerts else None

    def get_low_stock_alerts(self, sku_codes=None):
        alerts = []
        for code in (sku_codes if sku_codes is not None else self.skus):
            sku, policy = self.skus.get(code), self.policies.get(code)
            if not sku or sku.get("status") != "ACTIVE" or not policy:
                continue
            available, rop = self.get_available_stock(code), int(policy["rop"])
            if available > rop:
                continue
            suggestion = self._open_suggestion_for(code)
            alerts.append({
                "sku_code": code, "name": sku.get("name"), "available": available, "rop": rop,
                "shortage": max(0, rop - available),
                "severity": "AT_THRESHOLD" if available == rop else "BELOW",
                "open_suggestion_id": suggestion["suggestion_id"] if suggestion else None,
                "evaluated_at": self._now(),
            })
        return sorted(alerts, key=lambda a: (-a["shortage"], a["sku_code"]))

    def evaluate_low_stock(self, sku_codes=None):
        self.last_low_stock_evaluation = self._now()
        return self.get_low_stock_alerts(sku_codes)

    # -------------------------------------------------------------- FR-404
    def average_daily_demand(self, sku_code):
        history = self.demand_history.get(sku_code) or []
        return sum(float(r.get("quantity", 0)) for r in history) / len(history) if history else None

    def calculate_order_quantity(self, sku_code, policy=None):
        if sku_code not in self.skus:
            raise ValidationError("SKU not found")
        policy = policy or self.policies.get(sku_code)
        if not policy:
            raise ValidationError("SKU has no replenishment policy")

        available = self.get_available_stock(sku_code)
        average = self.average_daily_demand(sku_code)
        lead, safety, moq, multiple, rop = (policy[k] for k in
                                            ("lead_time_days", "safety_stock", "moq", "order_multiple", "rop"))
        net = rop - available if average is None else average * lead + safety - available
        if net <= 0:
            quantity, base = int(moq), "MOQ_FLOOR"
        else:
            rounded = math.ceil(net / multiple) * multiple
            quantity, base = max(moq, int(rounded)), "MOQ_FLOOR" if rounded < moq else "CALCULATED"
        flag = ("FALLBACK_MOQ_FLOOR" if base == "MOQ_FLOOR" else "FALLBACK") if average is None else base
        formula = (f"max({moq}, ROP {rop} - available {available}) = {quantity} [no demand history, fallback]"
                   if average is None else
                   f"max({moq}, ceil((({average:g} x {lead}) + {safety} - {available}) / {multiple}) x {multiple}) = {quantity}")
        return {
            "quantity": quantity, "flag": flag, "net_requirement": round(net, 2), "formula": formula,
            "inputs": {"average_daily_demand": average, "lead_time_days": lead,
                       "lead_time_demand": round((average or 0) * lead, 2), "safety_stock": safety,
                       "available_stock": available, "rop": rop, "moq": moq, "order_multiple": multiple},
        }

    # -------------------------------------------------------------- FR-403
    def _open_suggestion_for(self, sku_code):
        return next((s for s in self.suggestions.values()
                     if s["sku_code"] == sku_code and s["status"] == "OPEN"), None)

    def _has_incoming_order(self, sku_code):
        return any(po.get("status") in INCOMING_PO_STATUSES and
                   any(l["sku_code"] == sku_code for l in po.get("lines", []))
                   for po in self.purchase_orders.values())

    def _refresh_suggestion(self, suggestion, policy):
        if suggestion.get("adjusted"):
            return
        calc = self.calculate_order_quantity(suggestion["sku_code"], policy)
        suggestion.update(available=calc["inputs"]["available_stock"], suggested_quantity=calc["quantity"],
                          quantity=calc["quantity"], flag=calc["flag"], inputs=calc["inputs"],
                          formula=calc["formula"], refreshed_at=self._now())

    def run_replenishment_cycle(self, sku_codes=None, trigger="MANUAL"):
        if trigger != "SCHEDULED":
            self._require("SUGGESTION_MANAGE")
        execution_id = self._next_id(self.executions, "EXE")
        started_at, clock = self._now(), time.perf_counter()
        targets = list(sku_codes) if sku_codes is not None else [
            code for code, sku in self.skus.items() if sku.get("status") == "ACTIVE"]

        counts = {"evaluated": 0, "created": 0, "skipped": 0, "above_rop": 0}
        errors, created_ids = [], []
        for code in targets:
            sku = self.skus.get(code)
            if not sku or sku.get("status") != "ACTIVE":
                continue
            counts["evaluated"] += 1
            policy = self.policies.get(code)
            if not policy:
                errors.append({"sku_code": code, "reason": "NO_POLICY"})
                continue
            supplier = self.suppliers.get(policy.get("supplier_id") or "")
            if not supplier or not supplier.get("active", True):
                errors.append({"sku_code": code, "reason": "NO_ACTIVE_SUPPLIER"})
                continue
            if self.get_available_stock(code) > int(policy["rop"]):
                counts["above_rop"] += 1
                continue
            existing = self._open_suggestion_for(code)
            if existing:
                self._refresh_suggestion(existing, policy)
                counts["skipped"] += 1
                continue
            if self._has_incoming_order(code):
                counts["skipped"] += 1
                continue

            calc = self.calculate_order_quantity(code, policy)
            suggestion_id = self._next_id(self.suggestions, "SUG")
            self.suggestions[suggestion_id] = {
                "suggestion_id": suggestion_id, "sku_code": code, "supplier_id": policy["supplier_id"],
                "status": "OPEN", "available": calc["inputs"]["available_stock"], "rop": policy["rop"],
                "suggested_quantity": calc["quantity"], "quantity": calc["quantity"],
                "unit_price": float(sku.get("unit_price", 0) or 0), "flag": calc["flag"],
                "inputs": calc["inputs"], "formula": calc["formula"], "execution_id": execution_id,
                "created_at": self._now(), "refreshed_at": None, "adjusted": False, "po_id": None,
            }
            counts["created"] += 1
            created_ids.append(suggestion_id)

        record = {"execution_id": execution_id, "trigger": trigger, "started_at": started_at,
                  "finished_at": self._now(), "duration_seconds": round(time.perf_counter() - clock, 4),
                  **counts, "config_errors": errors, "suggestion_ids": created_ids, "status": "OK"}
        self.executions.append(record)
        self._log("CYCLE_EXECUTED", actor=self.current_user["email"] if self.current_user else "scheduler",
                  details={k: record[k] for k in ("execution_id", "trigger", "evaluated", "created", "skipped")})
        return copy.deepcopy(record)

    # -------------------------------------------------------------- FR-405
    def get_open_suggestions(self):
        self._require("SUGGESTION_VIEW")
        return [copy.deepcopy(s) for s in self.suggestions.values() if s["status"] == "OPEN"]

    def get_suggestion(self, suggestion_id):
        self._require("SUGGESTION_VIEW")
        if suggestion_id not in self.suggestions:
            raise ValidationError("Suggestion not found")
        return copy.deepcopy(self.suggestions[suggestion_id])

    def _suggestion_for_update(self, suggestion_id):
        suggestion = self.suggestions.get(suggestion_id)
        if suggestion is None:
            raise ValidationError("Suggestion not found")
        if suggestion["status"] != "OPEN":
            raise StateError("Suggestion is not open")
        return suggestion

    def adjust_suggestion(self, suggestion_id, quantity):
        self._require("SUGGESTION_MANAGE")
        suggestion = self._suggestion_for_update(suggestion_id)
        _int("Quantity", quantity, 1)
        policy = self.policies[suggestion["sku_code"]]
        if quantity < int(policy["moq"]):
            raise ValidationError("Quantity is below the minimum order quantity")
        if quantity % int(policy["order_multiple"]):
            raise ValidationError("Quantity is not a multiple of the order multiple")
        suggestion.update(quantity=quantity, adjusted=True, adjusted_at=self._now(),
                          adjusted_by=self.current_user["email"])
        return copy.deepcopy(suggestion)

    def dismiss_suggestion(self, suggestion_id, reason):
        self._require("SUGGESTION_MANAGE")
        suggestion = self._suggestion_for_update(suggestion_id)
        if not reason or not reason.strip():
            raise ValidationError("A dismissal reason is required")
        suggestion.update(status="DISMISSED", dismissal_reason=reason.strip(),
                          dismissed_at=self._now(), dismissed_by=self.current_user["email"])
        return copy.deepcopy(suggestion)

    def create_purchase_orders(self, suggestion_ids):
        self._require("PO_CREATE")
        if not suggestion_ids:
            raise ValidationError("Select at least one suggestion")
        selected = [self._suggestion_for_update(sid) for sid in suggestion_ids]
        for suggestion in selected:  # validate everything before creating anything
            supplier = self.suppliers.get(suggestion["supplier_id"] or "")
            if not supplier or not supplier.get("active", True):
                raise ValidationError(f"Supplier {suggestion['supplier_id']} is not active")
            if float(self.skus[suggestion["sku_code"]].get("unit_price", 0) or 0) <= 0:
                raise ValidationError(f"SKU {suggestion['sku_code']} has no unit price on file")

        grouped = {}
        for suggestion in selected:
            grouped.setdefault(suggestion["supplier_id"], []).append(suggestion)

        created = []
        for supplier_id, items in grouped.items():
            po_id = self._next_id(self.purchase_orders, f"PO-{self._today().year}")
            lines = [{
                "line_id": f"{po_id}-L{index:02d}", "sku_code": item["sku_code"],
                "quantity": int(item["quantity"]),
                "unit_price": round(float(self.skus[item["sku_code"]].get("unit_price", 0) or 0), 2),
                "suggestion_id": item["suggestion_id"],
            } for index, item in enumerate(items, start=1)]
            po = {
                "po_id": po_id, "supplier_id": supplier_id, "status": DRAFT,
                "created_by": self.current_user["email"], "created_at": self._now(),
                "expected_delivery_date": (self._today() + timedelta(
                    days=int(self.policies[items[0]["sku_code"]]["lead_time_days"]))).isoformat(),
                "total_amount": round(sum(l["quantity"] * l["unit_price"] for l in lines), 2),
                "lines": lines, "source_suggestions": [i["suggestion_id"] for i in items],
            }
            self.purchase_orders[po_id] = po
            for item in items:
                item.update(status="CONVERTED", po_id=po_id, converted_at=self._now())
            self._log("PO_CREATED", details={"po_id": po_id, "supplier_id": supplier_id,
                                             "lines": len(lines), "total_amount": po["total_amount"]})
            created.append(copy.deepcopy(po))
        return created

    def get_purchase_order(self, po_id):
        po = self.purchase_orders.get(po_id)
        if po is None:
            raise ValidationError("Purchase order not found")
        return copy.deepcopy(po)
