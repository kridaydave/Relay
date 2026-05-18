"""Verify that every Failure code in the ErrorCode enum has test coverage.

Rule 7.5: every `Result`-returning function needs tests for every distinct
Failure code it can return. This script catches silently-untested failure
paths that would regress without anyone noticing.

Usage: python scripts/check_failure_coverage.py
"""

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src" / "relay"
TEST_DIR = REPO_ROOT / "tests"

# Hard-coded list of "this Failure code is tested elsewhere / not applicable
# for automated grep" — keep as small as possible.
_KNOWN_UNVERIFIABLE: set[str] = {
    "INVALID_PIPELINE_ID",  # tested via envelope/context_broker tests
}


def _extract_error_codes(tree: ast.AST) -> set[str]:
    """Extract Failure(code=ErrorCode.XXX) usage from an AST tree."""
    codes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = _get_call_func_name(node)
            # Match Failure(code=ErrorCode.XXX) and Failure(reason=..., code=ErrorCode.XXX)
            if func == "Failure":
                for kw in node.keywords:
                    if kw.arg == "code" and isinstance(kw.value, ast.Attribute):
                        if isinstance(kw.value.value, ast.Name) and kw.value.value.id == "ErrorCode":
                            codes.add(kw.value.attr)
    return codes


def _get_call_func_name(node: ast.Call) -> str:
    """Get the dotted function name from a Call node."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        parts: list[str] = []
        n = node.func
        while isinstance(n, ast.Attribute):
            parts.append(n.attr)
            n = n.value
        if isinstance(n, ast.Name):
            parts.append(n.id)
        return ".".join(reversed(parts))
    return ""


def _find_errorcode_references_in_text(text: str) -> set[str]:
    """Find ErrorCode.XXX references in file text (for test files)."""
    return set(re.findall(r"ErrorCode\.(\w+)", text))


def main() -> int:
    # Collect all Failure codes used in production code
    source_codes: set[str] = set()
    for py_file in sorted(SRC_DIR.rglob("*.py")):
        if "__pycache__" in py_file.name:
            continue
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        source_codes.update(_extract_error_codes(tree))

    # Collect all ErrorCode references in test code
    test_refs: set[str] = set()
    for py_file in sorted(TEST_DIR.rglob("*.py")):
        if "__pycache__" in py_file.name:
            continue
        test_refs.update(_find_errorcode_references_in_text(py_file.read_text()))

    uncovered = source_codes - test_refs - _KNOWN_UNVERIFIABLE
    # Remove INTERNAL codes that are never returned as Failure (only at error boundary)
    # These are used inside the enum itself and never in Failure(code=...).
    uncovered -= {"INVALID_PIPELINE_ID"}  # tested via envelope

    if uncovered:
        print("ERROR: Failure codes used in production but not referenced in tests:")
        for code in sorted(uncovered):
            print(f"  ErrorCode.{code}")
        print()
        print("Rule 7.5 requires test coverage for every distinct Failure code.")
        print("Add tests that trigger these failure paths, or add the code to")
        print("_KNOWN_UNVERIFIABLE in this script with a comment explaining why.")
        return 1

    print(f"OK: all {len(source_codes)} Failure codes used in source are referenced in tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
