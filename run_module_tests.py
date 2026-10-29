#!/usr/bin/env python3
"""Run M1, M3, and M4 tests and save dated console and JUnit logs."""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TESTS = {
    "1": Path("src/Module1/Test/test_module1.py"),
    "3": Path("src/Module3/test_warehouse_inventory.py"),
    "4": Path("src/Module4/Test/test_module4.py"),
}
SMOKE_CHECKS = {
    "1": """
from module1_service import Module1Service
service = Module1Service()
result = service.login("staff01@wrhm.vn", "StaffPass123!")
assert result["user"]["is_active"]
assert service.check_permission("CATALOG_VIEW")
print("PASS | TC-101 smoke | seeded staff login and catalog permission")
""",
    "3": """
import importlib.util
from pathlib import Path
path = Path("src/Module3/test_warehouse_inventory.py")
spec = importlib.util.spec_from_file_location("module3_inventory", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
service = module.WarehouseInventorySystem()
service.seed_stock("SMOKE-SKU", "SMOKE-BIN", 20, 0, 0)
assert service.get_stock("SMOKE-SKU", "SMOKE-BIN")["atp"] == 20
result = service.adjust_inventory("SMOKE-KEY", "SMOKE-SKU", "SMOKE-BIN", -2, "SMOKE")
assert result["on_hand"] == 18 and result["atp"] == 18
print("PASS | stock query and adjustment | on_hand=18, atp=18")
""",
    "4": """
from module4_service import Module4Service
service = Module4Service()
service.login("controller@wrhm.vn", "ControllerPass123!")
cycle = service.run_replenishment_cycle()
assert cycle["evaluated"] == len(service.skus)
assert len(service.suggestions) == cycle["created"]
print(f"PASS | replenishment cycle | evaluated={cycle['evaluated']}, suggestions={cycle['created']}")
""",
}


def run_module(module: str, run_date: str) -> int:
    test_path = TESTS[module]
    log_dir = ROOT / "output" / f"Module_0{module}_Test_Logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"unit_tests_{run_date}.txt"
    junit_path = log_dir / f"test_run_{run_date}.xml"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-v",
        "-s",
        str(test_path),
        f"--junitxml={junit_path}",
    ]

    header = (
        f"MODULE {module} TEST RUN\n"
        f"Started: {datetime.now().astimezone().isoformat(timespec='seconds')}\n"
        f"Command: {' '.join(command)}\n"
        f"Working directory: {ROOT}\n"
        f"{'-' * 72}\n"
    )
    print(header, end="", flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(header)
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
        return_code = process.wait()
        footer = f"\nExit code: {return_code}\nLog: {log_path}\nJUnit: {junit_path}\n"
        print(footer, end="", flush=True)
        log.write(footer)
    return return_code


def write_log(path: Path, title: str, command: str, body: str) -> None:
    content = (
        f"{title}\n"
        f"Date: {datetime.now().astimezone().isoformat(timespec='seconds')}\n"
        f"Command: {command}\n"
        f"{'-' * 72}\n"
        f"{body.rstrip()}\n"
    )
    path.write_text(content, encoding="utf-8")
    print(content, end="")


def run_smoke(module: str, run_date: str, log_dir: Path) -> int:
    module_dir = ROOT / "src" / f"Module{module}"
    command = [sys.executable, "-c", SMOKE_CHECKS[module]]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(module_dir) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    body = result.stdout
    if result.stderr:
        body += result.stderr
    if result.returncode:
        body += f"\nSmoke check failed with exit code {result.returncode}.\n"
    write_log(
        log_dir / f"smoke_tests_{run_date}.txt",
        f"MODULE {module} - SERVICE SMOKE CHECK",
        "Python service-level check (no web server or interactive CLI required)",
        body or "No output was produced.",
    )
    return result.returncode


def write_traceability_inventory(module: str, run_date: str, log_dir: Path) -> None:
    test_path = ROOT / TESTS[module]
    tree = ast.parse(test_path.read_text(encoding="utf-8"), filename=str(test_path))
    test_functions = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]
    case_ids: set[str] = set()
    requirement_ids: set[str] = set()
    for function in test_functions:
        text = ast.get_docstring(function) or ""
        case_ids.update(re.findall(r"\bTC-\d+\b", text))
        requirement_ids.update(re.findall(r"\b(?:FR|NFR)-\d+\b", text))

    body = (
        f"Test functions found in source: {len(test_functions)}\n"
        f"Distinct test-case IDs in test docstrings: {len(case_ids)}"
        f"{': ' + ', '.join(sorted(case_ids)) if case_ids else ''}\n"
        f"Distinct FR/NFR IDs in test docstrings: {len(requirement_ids)}"
        f"{': ' + ', '.join(sorted(requirement_ids)) if requirement_ids else ''}\n"
        "Note: This is a source-annotation inventory, not an authoritative RTM "
        "coverage calculation. Compare it with the module workbook."
    )
    write_log(
        log_dir / f"requirements_toolkit_{run_date}.txt",
        f"MODULE {module} - TEST/REQUIREMENT ANNOTATION INVENTORY",
        f"AST scan of {test_path.relative_to(ROOT)}",
        body,
    )


def write_cli_status(module: str, run_date: str, log_dir: Path) -> None:
    body = (
        "NOT APPLICABLE: this module has no dedicated CLI or web entry point "
        "in the submission package.\n"
        "The module's programmatic service smoke check is recorded in "
        f"smoke_tests_{run_date}.txt."
    )
    write_log(
        log_dir / f"cli_quick_run_{run_date}.txt",
        f"MODULE {module} - CLI/WEB QUICK RUN",
        "Availability check",
        body,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--modules",
        nargs="+",
        choices=sorted(TESTS),
        default=sorted(TESTS),
        help="Modules to run (default: 1 3 4).",
    )
    args = parser.parse_args()
    run_date = datetime.now().astimezone().date().isoformat()

    results = []
    for module in args.modules:
        log_dir = ROOT / "output" / f"Module_0{module}_Test_Logs"
        test_code = run_module(module, run_date)
        smoke_code = run_smoke(module, run_date, log_dir)
        write_traceability_inventory(module, run_date, log_dir)
        write_cli_status(module, run_date, log_dir)
        results.append((module, test_code or smoke_code))
    failed = [module for module, code in results if code != 0]
    if failed:
        print(f"Failed module test runs: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"All selected module test runs passed: {', '.join(args.modules)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
