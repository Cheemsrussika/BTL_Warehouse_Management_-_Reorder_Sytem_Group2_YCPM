# Module 2 — SRS Skeleton (draft)

**System:** Warehouse Inventory and Reorder System
**Note:** This is a student-written exporter, not the official course toolkit.

## Functional Requirements

### FR-201 — F-201
The system allows staff to create a receiving note with product, quantity and location; batch and expiry are recorded when relevant.
Related use case: UC-201
Priority: Must

### FR-202 — F-201
The system checks the related purchase order and allows receipt confirmation; the received quantity is recorded once.
Related use case: UC-201
Priority: Must

### FR-203 — F-202
The system allows staff to create an issue note with product, quantity and destination.
Related use case: UC-202
Priority: Must

### FR-204 — F-202
The system checks available stock before confirming an issue and records the outgoing quantity.
Related use case: UC-202
Priority: Must

### FR-205 — F-203
When staff scans a barcode, SKU or lot code, the system shall identify a unique product; if one lot code belongs to multiple SKUs, it shall request more information rather than selecting a random product.
Related use case: UC-203
Priority: Must

### FR-206 — F-203
The system counts scanned items during the current operation and compares them with the related note.
Related use case: UC-203
Priority: Must

### FR-207 — F-204
The system allows staff to create a return note and record the quantity and reason for return.
Related use case: UC-204
Priority: Must

### FR-208 — F-204
The system allows returned goods to be classified as accepted or defective and prevents defective goods from becoming available stock.
Related use case: UC-204
Priority: Must

### FR-209 — F-205
The system allows staff to create a transfer note with source bin, destination bin, and quantity.
Related use case: UC-205
Priority: Must

### FR-210 — F-205
When a transfer is confirmed, the system decreases source-bin stock and increases destination-bin stock once.
Related use case: UC-205
Priority: Must

### FR-211 — F-206
The system checks source stock, destination-bin validity, and remaining capacity before a transfer.
Related use case: UC-206
Priority: Must

### FR-212 — F-206
The system allows only authorized users to confirm transfers in an allowed status.
Related use case: UC-206
Priority: Must

### FR-213 — F-207
Under FIFO, the system recommends the eligible batch with the earliest receiving date.
Related use case: UC-207
Priority: Should

### FR-214 — F-207
If one FIFO batch is insufficient, the system allocates the remaining quantity from the next eligible batch.
Related use case: UC-207
Priority: Should

### FR-215 — F-208
Under FEFO, the system recommends the eligible batch with the nearest expiration date.
Related use case: UC-208
Priority: Should

### FR-216 — F-208
The system allocates stock using FEFO; for batches with the same expiry date, the earlier received batch has priority.
Related use case: UC-208
Priority: Should

## Non-functional Requirements

- NFR-201: On a local demo dataset, a normal inventory search should return within 2 seconds (to be measured during integration).

- NFR-202: A confirmed stock operation must not change stock more than once, even if confirmation is repeated.

## Use Cases

- UC-201: Receive Goods

- UC-202: Issue Goods

- UC-203: Scan and Count Goods

- UC-204: Handle Returned Goods

- UC-205: Transfer Between Bins

- UC-206: Validate a Transfer

- UC-207: Recommend FIFO Batches

- UC-208: Recommend FEFO Batches
