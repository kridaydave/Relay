"""Verify that source modules respect the layer dependency order.

The rule: lower layers must NEVER import upper layers.

Layer order (lowest to highest):
  types.py → envelope.py → snapshot.py → snapshot_protocol.py →
  validator.py → context_broker.py → budget/ + slicer/ →
  audit/ → pipeline_state.py → pipeline_rollback.py + parallel/ →
  core_pipeline.py

Usage: python scripts/check_layer_violations.py
"""

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src" / "relay"

# Layer ordering: lower index = lower layer = cannot import higher layers.
# Each entry is a list of module path prefixes.
LAYERS: list[list[str]] = [
    ["relay.types"],                              # layer 0
    ["relay.envelope"],                            # layer 1
    ["relay.snapshot", "relay.snapshot_protocol"],  # layer 2
    ["relay.validator"],                           # layer 3
    ["relay.context_broker"],                      # layer 4
    ["relay.budget", "relay.slicer"],              # layer 5
    ["relay.audit"],                               # layer 6
    ["relay.pipeline_state"],                      # layer 7
    ["relay.pipeline_rollback", "relay.parallel"],  # layer 8
    ["relay.core_pipeline"],                       # layer 9
]


def _layer_for_module(module: str) -> int | None:
    """Return the layer index for a fully-qualified module name."""
    for idx, prefixes in enumerate(LAYERS):
        for prefix in prefixes:
            if module == prefix or module.startswith(prefix + "."):
                return idx
    return None


def _imported_modules(tree: ast.AST) -> set[str]:
    """Extract all relay module names imported by a file.

    Skips TYPE_CHECKING-guarded imports since those are never
    evaluated at runtime and don't create actual dependencies.
    """
    modules: set[str] = set()

    def _is_type_checking_guard(node: ast.AST) -> bool:
        """Check if this import is inside an 'if TYPE_CHECKING:' block."""
        parent = getattr(node, "parent", None)
        if parent is None:
            return False
        if isinstance(parent, ast.If):
            test = parent.test
            if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                return True
        return _is_type_checking_guard(parent)

    # Walk with parent tracking — ast.walk doesn't set parent refs
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                # Mark all imports inside this block with parent refs
                for child in ast.walk(node):
                    if child is not node:
                        # We can't easily set parent refs in stdlib ast,
                        # so let's use a different approach: skip imports
                        # that are children of a TYPE_CHECKING node
                        pass

    # Alternative approach: collect all nodes inside TYPE_CHECKING blocks
    type_checking_nodes: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                for child in ast.walk(node):
                    if child is not node:
                        type_checking_nodes.add(child)

    for node in ast.walk(tree):
        if node in type_checking_nodes:
            continue
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("relay"):
                modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("relay"):
                    parts = alias.name.split(".")
                    if len(parts) >= 2:
                        modules.add(".".join(parts[:2]))
                    modules.add(alias.name)
    return modules


def main() -> int:
    violations: list[str] = []
    seen_files = 0

    for py_file in sorted(SRC_DIR.rglob("*.py")):
        relative = py_file.relative_to(REPO_ROOT)
        module_path = str(relative.with_suffix("")).replace("/", ".").replace("\\", ".")
        # Strip "src." prefix to get "relay.xxx" form
        module_path = module_path.removeprefix("src.")
        if "__pycache__" in module_path or module_path.endswith(".__init__"):
            continue

        module_layer = _layer_for_module(module_path)
        if module_layer is None:
            continue

        seen_files += 1
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            violations.append(f"{relative}: syntax error")
            continue

        for imported in _imported_modules(tree):
            imported_layer = _layer_for_module(imported)
            if imported_layer is None:
                continue
            if imported_layer < module_layer:
                # Lower-layer imports are always fine (types → envelope ✓)
                continue
            if imported_layer > module_layer:
                violations.append(
                    f"{relative}: layer {module_layer} imports "
                    f"'{imported}' (layer {imported_layer}) — "
                    f"upper-layer import violates layering rule"
                )
            # Same layer is allowed — no violation

    if violations:
        print("ERROR: Layer violations found:")
        for v in violations:
            print(f"  {v}")
        print()
        print("Fix: lower layers must not import upper layers.")
        print("See AGENTS.md for the documented layer order.")
        return 1

    print(f"OK: {seen_files} files checked, no layer violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
