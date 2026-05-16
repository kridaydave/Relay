#!/usr/bin/env python3
import ast
import os
import sys
from typing import List, Tuple

# Connecting words that indicate a sentence structure (Rule 7.1)
CONNECTING_WORDS = {
    "when", "if", "returns", "raises", "with", "on", "after", "before", "for",
    "contains", "creates", "fails", "succeeds", "validates", "updates", "sets"
}

def check_test_name(name: str) -> bool:
    """
    Check if a test name follows the sentence-style convention (Rule 7.1).
    Heuristic: Must have at least 4 segments and contain at least one connecting word.
    """
    if not name.startswith("test_"):
        return True

    parts = name.split("_")
    # Rule: test_<verb/noun>_<details>_<condition/context>
    if len(parts) < 4:
        return False

    # Check for at least one connecting word
    return any(word in CONNECTING_WORDS for word in parts)

def lint_file(file_path: str) -> List[Tuple[int, str]]:
    """Lint a single file and return a list of (line_no, name) violations."""
    violations = []
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            tree = ast.parse(f.read())
        except SyntaxError:
            return [] # Skip files with syntax errors (CI will catch these elsewhere)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            if not check_test_name(node.name):
                violations.append((node.lineno, node.name))

    return violations

def main():
    test_dir = "tests"
    all_violations = []

    if not os.path.exists(test_dir):
        print(f"Error: {test_dir} directory not found.")
        sys.exit(1)

    for root, _, files in os.walk(test_dir):
        for file in files:
            if file.endswith(".py") and file.startswith("test_"):
                file_path = os.path.join(root, file)
                violations = lint_file(file_path)
                if violations:
                    all_violations.append((file_path, violations))

    if all_violations:
        print("Rule 7.1 Violation: Test names must be full sentences, not noun phrases.")
        print("Example: 'test_success_contains_value' -> 'test_success_contains_value_when_constructed'")
        print("-" * 80)
        for file_path, violations in all_violations:
            for line_no, name in violations:
                print(f"{file_path}:{line_no}: {name}")
        print("-" * 80)
        print(f"Found {sum(len(v) for _, v in all_violations)} violations.")
        sys.exit(1)
    else:
        print("All test names follow Rule 7.1.")
        sys.exit(0)

if __name__ == "__main__":
    main()
