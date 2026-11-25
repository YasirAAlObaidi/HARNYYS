"""The architecture rules in pyproject.toml (entry > workflows > services > handlers > core) must hold."""

import shutil
import subprocess
import sys
from pathlib import Path


def _lint_imports() -> str:
    beside_python = Path(sys.executable).parent / "lint-imports"
    found = str(beside_python) if beside_python.exists() else shutil.which("lint-imports")
    assert found, "lint-imports is not installed (it is in the dev dependency group)"
    return found


def test_import_linter_contracts_hold(server_dir: Path) -> None:
    result = subprocess.run(
        [_lint_imports()], check=False, cwd=server_dir, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, f"lint-imports failed:\n{result.stdout}\n{result.stderr}"
