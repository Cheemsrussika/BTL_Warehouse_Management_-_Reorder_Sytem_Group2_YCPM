# WrHM submission package

This folder contains the currently assembled four-module submission: reports
and requirement workbooks, source/demo code, datasets, diagrams, tests, and
test-run evidence.

## Git repository

https://github.com/Cheemsrussika/BTL_Warehouse_Management_-_Reorder_Sytem_Group2_YCPM

This URL was verified to resolve to a GitHub repository and is also present in
the SRS introduction.

## Setup

Use Python 3.10 or later. From this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-test.txt
```

`requirements.txt` lists runtime dependencies. `requirements-test.txt` includes
those runtime dependencies and pytest. Module 2's business logic and CLI use
the Python standard library; Flask is needed only for its web interface.

## Run and test

```bash
# Module 1 + Module 4
python -m pytest -v src/Module1/Test/test_module1.py src/Module4/Test/test_module4.py

# Run M1, M3, and M4 and save dated text + JUnit logs
python run_module_tests.py

# Module 4 only
python -m pytest -v src/Module4/Test/test_module4.py

# Module 2 (standalone demonstration, not the integrated system)
cd src/Module2
python -m unittest discover -s tests -v
python verify_demo.py
python requirements_toolkit.py
python demo_cli.py

# Module 3
cd ../Module3
python -m pytest -v test_warehouse_inventory.py
```

Run each command from the `Send` folder except the Module 2 and Module 3
commands, which are run from their respective directories as shown.

## Package contents

| Path | Contents |
| --- | --- |
| `SRS_WrHM_Group2.docx` | Group SRS. Verify group metadata and Git URL before submission. |
| `reports/final/template_final_report.pdf` | Official blank final-report template. This is a guide, not the completed group final report. |
| `reports/M1/` | Existing Module 1 report, test/traceability specification, and use-case specification. |
| `WareHouse_merged.xlsx`, `TestCase.csv`, `Traceability_matrix.csv` | Consolidated requirement, test-case, and traceability data. |
| `workbooks/` | M1–M4 workbooks, including canonical `M2_dataset.xlsx` and `M3_dataset.xlsx`; `Module3_Wrhm.ods` is the original OpenDocument spreadsheet, not an XLSX file. |
| `src/Module1/` | M1 service and automated tests. |
| `src/Module2/` | Standalone Flask/SQLite demo, CLI, local tests, and requirement artifacts. |
| `src/Module3/test_warehouse_inventory.py` | M3 in-memory domain implementation and test suite in one file. |
| `src/Module4/` | M4 replenishment service and automated tests. |
| `datasets/` | Sample CSV/JSON seed data used by M1 and M4; the builder generates `seed_master_data.json` from the expanded product dataset. |
| `diagrams/` | Module diagrams and model files. |
| `output/` | Existing and current test evidence. |

## Current validation snapshot

Validated on 2026-10-29 with Python 3.12.3 and pytest 9.2.0:

- M1 + M4: **28 passed**.
- M4 alone: **15 passed**. Separate log and JUnit report are in
  `output/Module_04_Test_Logs/`.
- M2: **27 unit tests passed**, **8/8 smoke workflows passed**, and the local
  requirements toolkit reports **16/16 functional requirements linked to
  tests**. This verifies the standalone M2 demo only.
- M2 Flask smoke check: **6/6 routes returned HTTP 200** using a temporary
  database.
- M3: **15 passed** after correcting the TC-305 expected ATP from 40 to 45:
  with on-hand 50, allocated 0, locked 0 and a -5 adjustment, ATP is 45.
- Python syntax compilation: passed for `src/` and `datasets/`.
- CSV/JSON data files: parsed successfully; seed generation completed.

Run logs and JUnit results are stored under `output/Module_*_Test_Logs/`;
the seed-data build log is `output/seed_data_build_2026-10-29.txt`.
These tests verify local module code; they do not establish end-to-end testing
of one integrated four-module application.

`run_module_tests.py` runs the M1, M3, and M4 test suites and creates a dated
`unit_tests`, `smoke_tests`, `requirements_toolkit`, and `cli_quick_run` log
for each. The CLI/web log says `NOT APPLICABLE` when that module has no such
interface; a direct service smoke check is run instead. JUnit XML is also
saved. Select modules with `python run_module_tests.py --modules 1 4`. M2
keeps its own unittest, smoke-test, toolkit, CLI, and web-route checks.

## Remaining submission checks

- Complete the group final report using `reports/final/template_final_report.pdf`.
  The current package has the SRS and M1 report material, but no completed
  four-module final report yet. Fill the template sections with the group's
  verified module evidence, diagrams, test results, references, and appendices.
- Confirm the repository is public or grant the instructor access before
  submission.
- Verify the group name/number is consistent across the report and workbooks.
- M2 is explicitly a standalone student demo; M3's domain implementation and
  tests are combined in one file. Confirm these boundaries satisfy the
  instructor's requested deliverable scope.
- M3 has an OpenDocument workbook retained as `workbooks/Module3_Wrhm.ods`;
  use `workbooks/M3_dataset.xlsx` when an Excel workbook is required.
- The M2 report, local demo and merged workbook are separate artifacts; confirm
  their requirement IDs and test results are synchronized before final upload.
- Demo users/passwords are sample credentials. Replace them before publishing
  publicly if they are reused anywhere outside this local demonstration.
