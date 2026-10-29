import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class PermissionError(Exception):
    pass


class AppendOnlyAuditLog(list):
    """Audit trail view (FR-103 / NFR-104): readable, never mutable.

    Any attempt to change or remove an entry is rejected, so the trail stays
    immutable once written.  The service itself appends through the base
    ``list`` implementation, which bypasses this guard.
    """

    def _immutable(self, *args, **kwargs):
        raise PermissionError(
            "Audit log entries are append-only and cannot be modified or deleted"
        )

    append = extend = insert = remove = pop = clear = sort = reverse = _immutable

    def __setitem__(self, index, value):
        self._immutable()

    def __delitem__(self, index):
        self._immutable()


class Module1Service:
    def __init__(self, seed_path: str = None):
        if seed_path is None:
            seed_path = Path(__file__).resolve().parents[2] / "datasets" / "seed_master_data.json"
        with open(seed_path, "r") as f:
            data = json.load(f)
        self.users = {u["email"]: dict(u) for u in data.get("users", [])}
        self.skus = {s["sku_code"]: dict(s) for s in data.get("skus", [])}
        self.sku_by_barcode = {s["barcode"]: s["sku_code"] for s in data.get("skus", [])}
        self.storage_bins = {b["bin_code"]: dict(b) for b in data.get("storage_bins", [])}
        self.audit_logs: AppendOnlyAuditLog = AppendOnlyAuditLog()
        self.current_user = None
        self.role_permissions = {
            "IT_ADMIN": ["USER_MANAGE", "AUDIT_VIEW", "CATALOG_MANAGE", "BIN_MANAGE"],
            "WAREHOUSE_MANAGER": ["AUDIT_VIEW", "CATALOG_MANAGE", "BIN_MANAGE"],
            "INVENTORY_CONTROLLER": ["CATALOG_MANAGE"],
            "WAREHOUSE_STAFF": ["CATALOG_VIEW"],
        }

    def _log(self, action: str, user: str = None, details: Dict = None):
        entry = {
            "timestamp": time.time(),
            "action": action,
            "user": user or (self.current_user["email"] if self.current_user else None),
            "details": details or {}
        }
        list.append(self.audit_logs, entry)
        return entry

    def login(self, email: str, password: str):
        start = time.time()
        if email not in self.users:
            self._log("LOGIN_FAILED", user=email, details={"reason": "unknown_user"})
            raise ValueError("Invalid credentials")
        user = self.users[email]
        if not user.get("is_active", True):
            self._log("LOGIN_FAILED", user=email, details={"reason": "inactive"})
            raise PermissionError("Account suspended")
        if user.get("password") != password:
            self._log("LOGIN_FAILED", user=email, details={"reason": "bad_password"})
            raise ValueError("Invalid credentials")
        self.current_user = dict(user)
        self._log("LOGIN_SUCCESS", user=email)
        latency = time.time() - start
        return {"user": self.current_user, "latency": latency}

    def check_permission(self, required_perm: str):
        if not self.current_user:
            raise PermissionError("Not authenticated")
        role = self.current_user.get("role")
        perms = self.role_permissions.get(role, [])
        if required_perm not in perms:
            self._log("UNAUTHORIZED_ACCESS", details={"required": required_perm})
            raise PermissionError("403 Forbidden / PermissionError")
        return True

    def provision_user(self, email: str, role: str, password: str, requester_email: str):
        self.check_permission("USER_MANAGE")
        if email in self.users:
            raise ValueError("Duplicate username/email")
        self.users[email] = {"user_id": f"U-{len(self.users)+100}", "email": email, "role": role, "is_active": True, "password": password}
        self._log("PROVISION_USER", user=requester_email, details={"email": email, "role": role})
        return self.users[email]

    def deactivate_user(self, target_email: str, requester_email: str):
        """Soft delete an account: it stays for audit purposes but cannot log in."""
        self.check_permission("USER_MANAGE")
        if target_email not in self.users:
            raise ValueError("User not found")
        self.users[target_email]["is_active"] = False
        self.users[target_email]["deleted_at"] = time.time()
        self._log("DEACTIVATE_USER", user=requester_email, details={"email": target_email})
        return self.users[target_email]

    def add_sku(self, sku_code: str, barcode: str, name: str, uom: str = "EA", **kwargs):
        self.check_permission("CATALOG_MANAGE")
        if sku_code in self.skus:
            raise ValueError("Duplicate SKU code")
        if barcode in self.sku_by_barcode:
            raise ValueError("Duplicate barcode")
        sku = {"sku_code": sku_code, "barcode": barcode, "name": name, "uom": uom, "status": "ACTIVE", **kwargs}
        self.skus[sku_code] = sku
        self.sku_by_barcode[barcode] = sku_code
        self._log("ADD_SKU", details={"sku_code": sku_code})
        return sku

    def archive_sku(self, sku_code: str) -> bool:
        """Soft delete a SKU.  Blocked while on-hand stock is greater than 0."""
        self.check_permission("CATALOG_MANAGE")
        if sku_code not in self.skus:
            raise ValueError("SKU not found")
        sku = self.skus[sku_code]
        stock = sku.get("stock_on_hand", 0)
        if stock > 0:
            raise ValueError(
                f"Cannot archive SKU with stock > 0 (on hand: {stock}). "
                "Deplete or write off the balance first."
            )
        sku["status"] = "ARCHIVED"
        self._log("ARCHIVE_SKU", details={"sku_code": sku_code})
        return True

    def update_sku_parameters(self, sku_code: str, rop: int = None, moq: int = None, default_bin: str = None):
        self.check_permission("CATALOG_MANAGE")
        if sku_code not in self.skus:
            raise ValueError("SKU not found")
        sku = self.skus[sku_code]
        if rop is not None and rop < 0:
            raise ValueError("ROP must be >= 0")
        if moq is not None and moq <= 0:
            raise ValueError("MOQ must be >= 0")
        if rop is not None:
            sku["rop"] = rop
        if moq is not None:
            sku["moq"] = moq
        if default_bin is not None:
            if default_bin not in self.storage_bins:
                raise ValueError("Bin location is invalid")
            sku["default_bin"] = default_bin
        self._log("UPDATE_SKU_PARAMS", details={"sku_code": sku_code})
        return sku

    def create_bin(self, bin_code: str, capacity: int = 50) -> bool:
        """Create a storage bin.  Capacity must be a positive integer."""
        self.check_permission("BIN_MANAGE")
        parts = bin_code.split('-')
        if len(parts) != 5:
            raise ValueError("Invalid bin coordinate format")
        if bin_code in self.storage_bins:
            raise ValueError("Duplicate coordinate")
        if not isinstance(capacity, int) or capacity <= 0:
            raise ValueError("Capacity must be a positive integer")
        bin_obj = {"bin_code": bin_code, "capacity": capacity, "on_hand": 0, "active": True}
        self.storage_bins[bin_code] = bin_obj
        self._log("CREATE_BIN", details={"bin_code": bin_code})
        return True

    def get_sku_display(self, sku_code: str):
        if sku_code not in self.skus:
            raise ValueError("SKU not found")
        sku = dict(self.skus[sku_code])
        if not sku.get("image_url"):
            sku["image_url"] = "placeholder-thumbnail.svg"
        return sku

    def get_audit_logs(self):
        self.check_permission("AUDIT_VIEW")
        return list(self.audit_logs)
