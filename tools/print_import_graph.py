#!/usr/bin/env python3
"""Print import graph for Frame Art Mode Sync integration.

This script helps debug import relationships and circular dependencies.

Usage:
    python3 tools/print_import_graph.py
"""

import ast
import sys
from collections import defaultdict
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

component_dir = repo_root / "custom_components" / "frame_artmode_sync"


def extract_imports(file_path: Path) -> set[str]:
    """Extract import statements from a Python file."""
    imports = set()
    
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
        
        tree = ast.parse(content, file_path.name)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    # Check if it's a relative import from our package
                    if node.module.startswith(".") or "frame_artmode_sync" in node.module:
                        # Extract the module name
                        parts = node.module.split(".")
                        if parts[0] == "":
                            # Relative import
                            imports.add("frame_artmode_sync")
                        else:
                            imports.add(parts[0])
                    else:
                        # External import
                        imports.add(node.module.split(".")[0])
    except Exception as e:
        print(f"Error parsing {file_path}: {e}", file=sys.stderr)
    
    return imports


def main() -> int:
    """Print import graph."""
    print("=" * 70)
    print("Frame Art Mode Sync - Import Graph")
    print("=" * 70)
    print()
    
    graph = defaultdict(set)
    files = {}
    
    # Find all Python files
    for py_file in component_dir.rglob("*.py"):
        if "__pycache__" in str(py_file) or py_file.parent.name == "translations":
            continue
        
        rel_path = py_file.relative_to(component_dir)
        module_name = str(rel_path).replace("/", ".").replace(".py", "")
        if module_name.endswith(".__init__"):
            module_name = module_name[:-9]
        
        files[module_name] = py_file
        imports = extract_imports(py_file)
        graph[module_name] = imports
    
    # Print graph
    print("Import relationships:")
    print()
    for module in sorted(graph.keys()):
        deps = sorted([d for d in graph[module] if d != "frame_artmode_sync" or module != ""])
        if deps:
            print(f"{module}:")
            for dep in deps:
                print(f"  -> {dep}")
            print()
    
    # Check for potential circular dependencies
    print("=" * 70)
    print("Potential circular dependencies:")
    print("=" * 70)
    print()
    
    # Simple check: if A imports B and B imports A
    found_cycles = False
    modules = list(graph.keys())
    for i, mod1 in enumerate(modules):
        for mod2 in modules[i+1:]:
            if mod1 in graph.get(mod2, set()) and mod2 in graph.get(mod1, set()):
                print(f"⚠ {mod1} <-> {mod2}")
                found_cycles = True
    
    if not found_cycles:
        print("✓ No obvious circular dependencies detected")
    
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

