"""Run portable local checks for the molecule plugin; never imports C4D."""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS = ROOT / "测试"
OUTPUT = TESTS / "输出"
RESULT = OUTPUT / "本地验证.json"
MINIMUM_TESTS = 23


def mib(size: int) -> float:
    return round(size / (1024 * 1024), 3)


def tree_size(path: Path, *, skip_output_scenes: bool = False, exclude_runtime: bool = True, exclude_cache: bool = True) -> int:
    total = 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(ROOT)
        if (exclude_runtime and ".runtime" in rel.parts) or (exclude_cache and "__pycache__" in rel.parts):
            continue
        if skip_output_scenes and "输出" in rel.parts and item.suffix.lower() == ".c4d":
            continue
        total += item.stat().st_size
    return total


def count_tests(suite: unittest.TestSuite) -> int:
    return sum(count_tests(item) if isinstance(item, unittest.TestSuite) else 1 for item in suite)


def main() -> int:
    started = datetime.now(timezone.utc)
    checks: dict[str, dict] = {}
    failures: list[str] = []

    # unittest discovery
    loader = unittest.TestLoader()
    # Treat tests/ as the import root because it is intentionally not a package.
    suite = loader.discover(str(TESTS), pattern="test_*.py", top_level_dir=str(TESTS))
    test_count = count_tests(suite)
    class QuietResult(unittest.TextTestResult):
        def printErrors(self):
            super().printErrors()

    runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=1, resultclass=QuietResult)
    test_result = runner.run(suite)
    checks["unittest_discover"] = {
        "command": f'"{sys.executable}" -m unittest discover -s "{TESTS}" -p "test_*.py"',
        "exit_code": 0 if test_result.wasSuccessful() else 1,
        "tests": test_count,
        "failures": len(test_result.failures),
        "errors": len(test_result.errors),
    }
    if not test_result.wasSuccessful():
        failures.append("unittest discover failed")
    if test_count < MINIMUM_TESTS:
        failures.append(f"expected at least {MINIMUM_TESTS} unittest cases, discovered {test_count}")

    # pip check, via the project's bundled interpreter
    pip = subprocess.run(
        [sys.executable, "-m", "pip", "check"], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    checks["pip_check"] = {
        "command": f'"{sys.executable}" -m pip check',
        "exit_code": pip.returncode,
        "output": (pip.stdout + pip.stderr).strip()[-4000:],
    }
    if pip.returncode:
        failures.append("pip check failed")

    # Parse project Python sources using Python 3.11 grammar, never importing them.
    py_files = [p for p in ROOT.rglob("*.py") if ".runtime" not in p.relative_to(ROOT).parts
                and "__pycache__" not in p.relative_to(ROOT).parts]
    syntax_errors = []
    for path in py_files:
        try:
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path), feature_version=(3, 11))
        except (SyntaxError, UnicodeError) as exc:
            syntax_errors.append({"file": str(path.relative_to(ROOT)), "error": str(exc)})
    checks["ast_python_3_11"] = {
        "command": "ast.parse(feature_version=(3, 11)) over all project *.py excluding .runtime and __pycache__",
        "exit_code": 0 if not syntax_errors else 1,
        "files": len(py_files),
        "errors": syntax_errors,
    }
    if syntax_errors:
        failures.append("Python 3.11 AST parsing failed")

    # Manifest, required plugin files and icon dimensions.
    manifest_path = ROOT / "脚本信息.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = [manifest["entry"], manifest["icon"], "图标.png", "requirements.txt"]
    required += [f"scimol_c4d/{name}.py" for name in
                 ("__init__", "backend", "c4d_builder", "chemistry_worker", "library", "records", "ui",
                  "display_geometry", "atom_selector", "native_ui", "panel_layout", "usage",
                  "browser_ui", "browser_layout", "resource_browser", "search_index", "resolve_cache", "floating_windows")]
    missing = [name for name in required if not (ROOT / Path(name)).is_file()]
    icon_specs = {}
    for name, wanted in ((manifest["icon"], (48, 48)), ("图标.png", (256, 256))):
        path = ROOT / name
        dimensions = None
        try:
            from PIL import Image
            with Image.open(path) as image:
                dimensions = list(image.size)
        except Exception as exc:
            icon_specs[name] = {"expected": list(wanted), "dimensions": None, "error": str(exc)}
            continue
        icon_specs[name] = {"expected": list(wanted), "dimensions": dimensions}
    icon_ok = all(item.get("dimensions") == item["expected"] for item in icon_specs.values())
    manifest_ok = bool(manifest.get("entry") and manifest.get("icon") and not missing and icon_ok)
    checks["manifest_files_icons"] = {
        "command": "read 脚本信息.json; check entry/required files and PNG dimensions",
        "exit_code": 0 if manifest_ok else 1,
        "entry": manifest.get("entry"),
        "icon": manifest.get("icon"),
        "missing_files": missing,
        "icons": icon_specs,
    }
    if not manifest_ok:
        failures.append("manifest, required files, or icon dimensions invalid")

    # Validate the prepared, 3D-ready fixture using the pure records module.
    fixture_path = TESTS / "fixtures" / "苄醇三维.json"
    if not fixture_path.is_file():
        fixture_path = OUTPUT / "苄醇三维.json"
    fixture_ok = False
    fixture_info = {"path": str(fixture_path.relative_to(ROOT)), "exists": fixture_path.is_file()}
    if fixture_path.is_file():
        spec = importlib.util.spec_from_file_location("local_validation_records", ROOT / "scimol_c4d" / "records.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        record = json.loads(fixture_path.read_text(encoding="utf-8"))
        validated = module.validate_record(record, require_3d=True)
        fixture_ok = bool(validated.get("coordinates_ready"))
        fixture_info.update({
            "coordinates_ready": bool(validated.get("coordinates_ready")),
            "has_3d": bool(validated.get("has_3d")),
            "atoms": len(validated.get("atoms", [])),
            "smiles": validated.get("smiles"),
        })
    checks["fixture_record"] = {
        "command": "scimol_c4d.records.validate_record(fixture, require_3d=True)",
        "exit_code": 0 if fixture_ok else 1,
        **fixture_info,
    }
    if not fixture_ok:
        failures.append("prepared fixture validation failed or coordinates_ready is false")

    runtime_dir = ROOT / ".runtime"
    runtime_bytes = tree_size(runtime_dir, exclude_runtime=False, exclude_cache=False) if runtime_dir.exists() else 0
    source_bytes = tree_size(ROOT, skip_output_scenes=True)
    finished = datetime.now(timezone.utc)
    report = {
        "status": "PASS" if not failures else "FAIL",
        "started_at_utc": started.isoformat(),
        "finished_at_utc": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 3),
        "python": sys.version,
        "python_executable": sys.executable,
        "checks": checks,
        "failures": failures,
        "sizes_mib": {
            "runtime": mib(runtime_bytes),
            "source_and_resources": mib(source_bytes),
            "source_size_exclusions": [".runtime", "__pycache__", "测试/输出/*.c4d"],
            "note": "Source/resource size is not standalone installation size.",
        },
        "scope_note": "Portable local checks only; no c4d/maxon import and no Cinema 4D host validation.",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
