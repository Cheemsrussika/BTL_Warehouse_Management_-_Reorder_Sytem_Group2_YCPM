# Warehouse Inventory and Reorder System — Module 2 Demo

**Course:** CSE703095 Software Requirements  
**Module:** Warehouse Operations & Movements  
**Tech:** Python 3.10+, Flask, SQLite (automatically created).  
**Scope:** Standalone **student demonstration**, not the full four-module system.

## Easiest way (Windows, no additional packages)

Double-click `run_windows.bat`, or open PowerShell in this folder and run:

```powershell
py demo_cli.py
```

You can immediately use all 8 core functions in the command-line menu.

## Web version (Windows PowerShell, Flask required)

```powershell
# Open PowerShell in the SourceCode folder first
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000**. If PowerShell blocks activation, use:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

To stop press **Ctrl+C**. On macOS/Linux: `python3 -m venv .venv`, `source .venv/bin/activate`, `pip install -r requirements.txt`, `python app.py`.

## Use the demo

1. **Dashboard**: view SKU, lot, bin, quantity, expiry and movement history.
2. **Goods Receiving**: create a draft for `PO-1001 / SKU001 / LOT-TEST / A-01 / 5 / 2027-12-31`, then click **Confirm**. Inventory increases by 5.
3. **Goods Issuing**: create a draft for `SKU001 / 10 / FIFO`, then confirm. Stock is decreased.
4. **QR/Barcode**: scan `SKU001`, `8930000000001` or `LOT-OLD` and optionally enter an expected SKU and count task.
5. **Goods Returns**: create a return for `SKU001 / LOT-OLD / A-01 / 2`, then confirm **Accepted** or **Quarantine**.
6. **Bin Transfers**: move `SKU001 / LOT-OLD / A-01 → B-01 / 3`, then confirm. The system checks source balance and destination capacity.
7. **FIFO/FEFO**: use Preview to see the proposed lot order. FIFO uses the earliest receiving date; FEFO prioritizes the earliest expiry date.

Database file `warehouse.db` is created on the first run. To **reset demo data**, stop the server and delete only `warehouse.db`, then restart.

## Tests and requirement artifacts

```powershell
python -m unittest discover -s tests -v
python requirements_toolkit.py
python verify_demo.py
```

The scripts generate `artifacts/requirements.json`, `artifacts/srs_skeleton.md`, and `artifacts/coverage_report.txt`.
The 24 TC-aligned tests and 3 supplementary defect-regression tests run against disposable SQLite databases. **They do not certify that the group's integrated project has been tested**; integrated Test Case execution stays `Not Run` until the team runs it.

## Technical scope and limitations

- Flask + SQLite, deliberately simple architecture and no external inventory service.
- Each confirmation is a single SQLite transaction. A previously confirmed record cannot be confirmed twice.
- The available/QUARANTINE stock distinction is implemented. Product and bin catalog are seeded to simulate Module 1. The local movement ledger simulates the event handoff to Module 3.
- Only a typed/scanner-keyboard QR/barcode payload is supported. **No phone-camera scanner.**
- No login, access control, procurement recommendation, distributed synchronization or production-grade audit/security is implemented.
- Uses demo assumptions: whole-unit quantities, expiry-controlled products need expiry date, expired lots cannot be issued, FIFO/FEFO issue quantities are selected automatically, FEFO ties use oldest receiving date.

## File layout

- `app.py`: SQLite schema, business rules, Flask endpoints (optional Flask import).
- `demo_cli.py`, `run_windows.bat`: zero-dependency menu demo.
- `verify_demo.py`: eight workflow checks against a disposable SQLite database.
- `templates/`, `static/`: web interface.
- `tests/`: test scripts.
- `requirements_toolkit.py`: traceability artifacts from FR/UC/TC ids.
- The SRS (Word) and Test Cases/RTM (Excel) are provided alongside SourceCode in the ZIP.

## Review update (draft v0.4)

- **27/27** local Python tests pass: 24 original TC-aligned tests and 3 extra checks for ambiguous lot labels.
- **8/8** smoke workflows pass on fresh temporary data (`python verify_demo.py`).
- A lot code shared by multiple SKUs is reported as `AMBIGUOUS` instead of silently choosing a wrong SKU.
- Requirements, use cases, Test Cases and RTM are delivered in the accompanying Word/Excel files.
- No group-wide end-to-end, secure-role, scanner-camera, or Flask-browser verification is claimed.
