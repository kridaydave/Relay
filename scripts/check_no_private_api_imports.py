"""Check that tests don't import private APIs (_xxx) from production code.

Rule: tests should test public API surfaces, not private implementation details.
Private API testing creates tight coupling — refactoring internals breaks tests
even when public behaviour is preserved (TM-01, TM-02, TM-03 in ruthless audit).

Usage:
    python scripts/check_no_private_api_imports.py         # exit 1 on violations
    python scripts/check_no_private_api_imports.py --warn  # print violations, exit 0
"""

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_DIR = REPO_ROOT / "tests"
SOURCE_PACKAGE = "relay"


def _is_private_import(node: ast.AST) -> bool:
    """Check if an AST import node imports a private name from relay."""
    if isinstance(node, ast.ImportFrom):
        if node.module and node.module.startswith(SOURCE_PACKAGE):
            for alias in node.names:
                if alias.name.startswith("_"):
                    return True
    if isinstance(node, ast.Import):
        for alias in node.names:
            parts = alias.name.split(".")
            if parts[0] == SOURCE_PACKAGE and any(p.startswith("_") for p in parts):
                return True
    return False


def _is_dunder(name: str) -> bool:
    """Dunder methods like __enter__, __exit__ are standard Python, not private APIs."""
    return name.startswith("__") and name.endswith("__")


def main() -> int:
    warn_only = "--warn" in sys.argv
    violations: list[str] = []

    for test_file in sorted(TEST_DIR.rglob("test_*.py")):
        try:
            tree = ast.parse(test_file.read_text())
        except SyntaxError:
            violations.append(f"{test_file.relative_to(REPO_ROOT)}: syntax error")
            continue

        for node in ast.walk(tree):
            if _is_private_import(node):
                line = getattr(node, "lineno", 0)
                names = [a.name for a in getattr(node, "names", [])]
                module = getattr(node, "module", "")
                violations.append(
                    f"{test_file.relative_to(REPO_ROOT)}:{line}: "
                    f"private API import: {module or ''} -> {names}"
                )

        # Flag direct _private attribute access (e.g. obj._method())
        # but skip dunder methods (__enter__, __name__, etc.) and __import__
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                if _is_dunder(node.attr):
                    continue
                if node.attr == "__import__":
                    continue
                line = getattr(node, "lineno", 0)
                violations.append(
                    f"{test_file.relative_to(REPO_ROOT)}:{line}: "
                    f"private API access: .{node.attr}"
                )

    if violations:
        prefix = "WARNING" if warn_only else "ERROR"
        print(f"{prefix}: Private API imports/access found in tests:")
        for v in violations:
            print(f"  {v}")
        print()
        if warn_only:
            print("These are pre-existing violations — new ones should be avoided.")
            print("Fix: test public API surfaces instead of private implementation details.")
            return 0
        print("Fix: test public API surfaces instead of private implementation details.")
        print("If testing internals is essential, add a comment explaining why.")
        return 1

    print("OK: no private API imports in tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
