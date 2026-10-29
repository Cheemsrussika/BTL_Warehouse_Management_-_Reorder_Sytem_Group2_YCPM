"""Build ``seed_master_data.json`` from the canonical CSV datasets.

The CSV files are the single source of truth for the prototype data.  Run this
script after editing any CSV so that the JSON seed consumed by the services
(``src/module1_service.py`` and ``src/module4_service.py``) stays in sync with
the workbook/datasets::

    python3 datasets/build_seed_master_data.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "seed_master_data.json"


def read_csv(name: str) -> list[dict]:
    with open(BASE / name, "r", encoding="utf-8-sig", newline="") as fh:
        return [row for row in csv.DictReader(fh)]


def as_bool(value: str, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y"}


def as_int(value: str, default: int = 0) -> int:
    if value is None or value.strip() == "":
        return default
    return int(float(value))


def as_float(value: str, default: float = 0.0) -> float:
    if value is None or value.strip() == "":
        return default
    return float(value)


def as_text(value: str):
    if value is None or value.strip() == "":
        return None
    return value.strip()


def build() -> dict:
    users = [
        {
            "user_id": row["user_id"],
            "email": row["email"],
            "role": row["role"],
            "is_active": as_bool(row["is_active"], True),
            "password": row["password"],
        }
        for row in read_csv("users.csv")
    ]

    skus = []
    for row in read_csv("products 4.csv"):
        skus.append(
            {
                "sku_code": row["sku_code"],
                "barcode": row["barcode"],
                "name": row["name"],
                "uom": row["uom"],
                "category": row["category"],
                "supplier_id": as_text(row.get("supplier_id")),
                "rop": as_int(row["rop"]),
                "safety_stock": as_int(row["safety_stock"]),
                "lead_time_days": as_int(row["lead_time_days"]),
                "moq": as_int(row["moq"]),
                "order_multiple": as_int(row["order_multiple"]),
                "unit_price": as_float(row["unit_price"]),
                "stock_on_hand": as_int(row["stock_on_hand"]),
                "reserved_qty": as_int(row.get("reserved_qty")),
                "default_bin": as_text(row.get("default_bin")),
                "image_url": as_text(row.get("image_url")),
                "is_perishable": as_bool(row.get("is_perishable", "")),
                "shelf_life_days": as_int(row.get("shelf_life_days", 0)),
                "status": row["status"],
            }
        )

    storage_bins = [
        {
            "bin_code": row["bin_code"],
            "zone": row["zone"],
            "aisle": row["aisle"],
            "rack": row["rack"],
            "shelf": row["shelf"],
            "bin": row["bin"],
            "capacity": as_int(row["capacity"]),
            "on_hand": as_int(row["on_hand"]),
            "active": as_bool(row["active"], True),
        }
        for row in read_csv("warehouse_layout.csv")
    ]

    suppliers = [
        {
            "supplier_id": row["supplier_id"],
            "name": row["name"],
            "contact_name": row["contact_name"],
            "email": row["email"],
            "phone": row["phone"],
            "lead_time_days": as_int(row["lead_time_days"]),
            "active": as_bool(row["active"], True),
        }
        for row in read_csv("suppliers.csv")
    ]

    demand_history: dict[str, list[dict]] = {}
    for row in read_csv("demand_history.csv"):
        demand_history.setdefault(row["sku_code"], []).append(
            {"date": row["date"], "quantity": as_int(row["quantity"])}
        )
    for entries in demand_history.values():
        entries.sort(key=lambda item: item["date"])

    lines_by_po: dict[str, list[dict]] = {}
    for row in read_csv("purchase_order_lines.csv"):
        lines_by_po.setdefault(row["po_id"], []).append(
            {
                "line_id": row["line_id"],
                "sku_code": row["sku_code"],
                "quantity": as_int(row["quantity"]),
                "unit_price": as_float(row["unit_price"]),
            }
        )

    supplier_email = {s["supplier_id"]: s["email"] for s in suppliers}

    purchase_orders = []
    for row in read_csv("purchase_orders.csv"):
        lines = lines_by_po.get(row["po_id"], [])
        total = round(sum(line["quantity"] * line["unit_price"] for line in lines), 2)
        history = []
        for status, stamp in (
            ("DRAFT", row["created_at"]),
            ("PENDING_APPROVAL", row.get("submitted_at")),
            ("APPROVED", row.get("approved_at")),
        ):
            if stamp:
                history.append({"status": status, "at": stamp, "actor": row["created_by"]})
        final = row["status"]
        final_stamp = row.get("received_at") or row.get("approved_at") or row.get("created_at")
        if final not in {entry["status"] for entry in history}:
            history.append({"status": final, "at": final_stamp, "actor": row.get("approved_by") or row["created_by"]})

        transmissions = []
        if final in {"SENT", "ACKNOWLEDGED", "PARTIALLY_RECEIVED", "RECEIVED", "CLOSED"}:
            transmissions.append(
                {
                    "at": row.get("approved_at") or row["created_at"],
                    "recipient": supplier_email.get(row["supplier_id"]),
                    "status": "SENT",
                    "attempts": 1,
                    "error": None,
                }
            )

        purchase_orders.append(
            {
                "po_id": row["po_id"],
                "supplier_id": row["supplier_id"],
                "status": final,
                "created_by": row["created_by"],
                "created_at": row["created_at"],
                "submitted_at": as_text(row.get("submitted_at")),
                "approved_by": as_text(row.get("approved_by")),
                "approved_at": as_text(row.get("approved_at")),
                "expected_delivery_date": as_text(row.get("expected_delivery_date")),
                "received_at": as_text(row.get("received_at")),
                "rejection_reason": None,
                "total_amount": total,
                "lines": lines,
                "transmissions": transmissions,
                "transmission_status": "SENT" if transmissions else None,
                "flags": [],
                "status_history": history,
            }
        )

    return {
        "users": users,
        "skus": skus,
        "storage_bins": storage_bins,
        "suppliers": suppliers,
        "demand_history": demand_history,
        "purchase_orders": purchase_orders,
    }


def main() -> None:
    data = build()
    with open(OUTPUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(
        f"wrote {OUTPUT.name}: {len(data['skus'])} SKUs, "
        f"{len(data['suppliers'])} suppliers, {len(data['purchase_orders'])} purchase orders"
    )


if __name__ == "__main__":
    main()
