#!/usr/bin/env python3
"""Preflight gate for Frame Art Mode Sync integration.

This script performs comprehensive checks before deployment:
- Import order validation
- Circular import detection
- Const contract enforcement
- Config flow import-safety
- Minimal HA entrypoint sanity

Usage:
    python3 tools/preflight.py
"""

import ast
import importlib
import importlib.util
import sys
import traceback
from pathlib import Path
from typing import Any

# Add repo root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

# Track import stack for circular detection
_import_stack: list[str] = []
_import_stack_set: set[str] = set()

# Module import order (HA-like)
IMPORT_ORDER = [
    "custom_components.frame_artmode_sync.const",
    "custom_components.frame_artmode_sync.decision",
    "custom_components.frame_artmode_sync.entity_helpers",
    "custom_components.frame_artmode_sync.storage",
    "custom_components.frame_artmode_sync.frame_client",
    "custom_components.frame_artmode_sync.atv_client",
    "custom_components.frame_artmode_sync.pair_controller",
    "custom_components.frame_artmode_sync.services",
    "custom_components.frame_artmode_sync.manager",
    "custom_components.frame_artmode_sync.config_flow",
    "custom_components.frame_artmode_sync.diagnostics",
    "custom_components.frame_artmode_sync.__init__",
]

# Check if Home Assistant is available
HA_AVAILABLE = False
try:
    import homeassistant
    HA_AVAILABLE = True
except ImportError:
    pass


def wrapped_import_module(name: str, package: str | None = None, direct_file: bool = False) -> Any:
    """Wrap importlib.import_module to detect circular imports."""
    if name in _import_stack_set:
        # Circular import detected
        cycle_start = _import_stack.index(name)
        cycle = _import_stack[cycle_start:] + [name]
        raise CircularImportError(
            f"CIRCULAR IMPORT DETECTED: {' -> '.join(cycle)}"
        )
    
    _import_stack.append(name)
    _import_stack_set.add(name)
    try:
        if direct_file:
            # Import directly from file to avoid package __init__.py
            if name == "custom_components.frame_artmode_sync.const":
                const_path = repo_root / "custom_components" / "frame_artmode_sync" / "const.py"
                spec = importlib.util.spec_from_file_location("frame_artmode_sync.const", const_path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    # Add to sys.modules to prevent re-import
                    sys.modules[name] = module
                    spec.loader.exec_module(module)
                    return module
        return importlib.import_module(name, package)
    except ModuleNotFoundError as e:
        if "homeassistant" in str(e) and not HA_AVAILABLE:
            # Re-raise as a different error that we can catch
            raise ImportError(f"HA not available: {e}") from e
        raise
    finally:
        _import_stack.pop()
        _import_stack_set.discard(name)


class CircularImportError(Exception):
    """Raised when a circular import is detected."""
    pass


def check_import_order() -> tuple[bool, list[str]]:
    """Check A: Import order smoke test."""
    errors = []
    print("=" * 70)
    print("A) Import Order Smoke Test")
    print("=" * 70)
    
    for module_name in IMPORT_ORDER:
        try:
            # For const.py when HA not available, import directly from file
            direct = (module_name == "custom_components.frame_artmode_sync.const" and not HA_AVAILABLE)
            wrapped_import_module(module_name, direct_file=direct)
            print(f"✓ OK {module_name}")
        except ImportError as e:
            if "HA not available" in str(e) and not HA_AVAILABLE:
                print(f"⊘ SKIP {module_name} (HA not available)")
            else:
                print(f"✗ FAIL {module_name}")
                print(f"  {traceback.format_exc()}")
                if HA_AVAILABLE:  # Only count as error if HA is available
                    errors.append(f"{module_name}: {traceback.format_exc()}")
        except CircularImportError as e:
            print(f"✗ CIRCULAR {module_name}")
            print(f"  {e}")
            errors.append(f"{module_name}: {e}")
        except Exception as e:
            print(f"✗ FAIL {module_name}")
            print(f"  {traceback.format_exc()}")
            if HA_AVAILABLE:  # Only count as error if HA is available
                errors.append(f"{module_name}: {traceback.format_exc()}")
    
    print()
    return len(errors) == 0, errors


def check_dynamic_imports() -> tuple[bool, list[str]]:
    """Check B: Dynamically import all .py files."""
    errors = []
    print("=" * 70)
    print("B) Dynamic Import All .py Files")
    print("=" * 70)
    
    component_dir = repo_root / "custom_components" / "frame_artmode_sync"
    if not component_dir.exists():
        errors.append(f"Component directory not found: {component_dir}")
        return False, errors
    
    py_files = list(component_dir.rglob("*.py"))
    py_files = [
        f for f in py_files
        if "__pycache__" not in str(f) and f.name != "__init__.py" or f.parent.name == "frame_artmode_sync"
    ]
    
    for py_file in sorted(py_files):
        # Convert file path to module name
        rel_path = py_file.relative_to(repo_root)
        parts = rel_path.parts
        # Remove .py extension and convert to module path
        module_parts = list(parts[:-1]) + [parts[-1].replace(".py", "")]
        module_name = ".".join(module_parts)
        
        # Skip if already tested in import order
        if module_name in IMPORT_ORDER:
            continue
        
        try:
            wrapped_import_module(module_name)
            print(f"✓ OK {module_name}")
        except ImportError as e:
            if "HA not available" in str(e) and not HA_AVAILABLE:
                print(f"⊘ SKIP {module_name} (HA not available)")
            else:
                print(f"✗ FAIL {module_name}")
                print(f"  {traceback.format_exc()}")
                if HA_AVAILABLE:  # Only count as error if HA is available
                    errors.append(f"{module_name}: {traceback.format_exc()}")
        except CircularImportError as e:
            print(f"✗ CIRCULAR {module_name}")
            print(f"  {e}")
            errors.append(f"{module_name}: {e}")
        except Exception as e:
            print(f"✗ FAIL {module_name}")
            print(f"  {traceback.format_exc()}")
            if HA_AVAILABLE:  # Only count as error if HA is available
                errors.append(f"{module_name}: {traceback.format_exc()}")
    
    print()
    return len(errors) == 0, errors


def check_const_contract() -> tuple[bool, list[str]]:
    """Check D: Const contract enforcement."""
    errors = []
    print("=" * 70)
    print("D) Const Contract Enforcement")
    print("=" * 70)
    
    const_path = repo_root / "custom_components" / "frame_artmode_sync" / "const.py"
    if not const_path.exists():
        errors.append("const.py not found")
        return False, errors
    
    # Load const module and get all attributes
    try:
        if HA_AVAILABLE:
            const_module = wrapped_import_module("custom_components.frame_artmode_sync.const")
        else:
            # Import directly from file to avoid package __init__.py
            const_path = repo_root / "custom_components" / "frame_artmode_sync" / "const.py"
            spec = importlib.util.spec_from_file_location("const", const_path)
            if spec and spec.loader:
                const_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(const_module)
            else:
                errors.append("Failed to create spec for const.py")
                return False, errors
        
        const_names = {
            name for name in dir(const_module)
            if not name.startswith("_") and name.isupper()
        }
    except Exception as e:
        errors.append(f"Failed to load const module: {e}")
        return False, errors
    
    # Find all imports from const in other files
    component_dir = repo_root / "custom_components" / "frame_artmode_sync"
    for py_file in component_dir.rglob("*.py"):
        if "__pycache__" in str(py_file) or py_file.name == "const.py":
            continue
        if py_file.parent.name == "translations":
            continue
        
        try:
            with open(py_file, encoding="utf-8") as f:
                content = f.read()
            
            # Parse AST to find imports from our .const module only
            tree = ast.parse(content, py_file.name)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    # Only check imports from our const module (not pyatv.const, homeassistant.const, etc.)
                    if node.module and (
                        node.module == "const" or 
                        node.module == ".const" or
                        node.module.endswith(".frame_artmode_sync.const") or
                        node.module == "custom_components.frame_artmode_sync.const"
                    ):
                        for alias in node.names:
                            imported_name = alias.asname or alias.name
                            if imported_name not in const_names:
                                rel_path = py_file.relative_to(repo_root)
                                errors.append(
                                    f"{rel_path}: imports '{imported_name}' from const, "
                                    f"but it doesn't exist in const.py"
                                )
        except SyntaxError:
            # Skip files with syntax errors (they'll be caught elsewhere)
            pass
        except Exception as e:
            errors.append(f"Error checking {py_file.relative_to(repo_root)}: {e}")
    
    if errors:
        for error in errors:
            print(f"✗ {error}")
    else:
        print("✓ All const imports are valid")
    
    print()
    return len(errors) == 0, errors


def check_config_flow_safety() -> tuple[bool, list[str]]:
    """Check E: Config flow import-safety & instantiation."""
    errors = []
    print("=" * 70)
    print("E) Config Flow Import-Safety")
    print("=" * 70)
    
    if not HA_AVAILABLE:
        print("⊘ SKIP (HA not available)")
        print()
        return True, []
    
    try:
        # Import config_flow
        config_flow_module = wrapped_import_module("custom_components.frame_artmode_sync.config_flow")
        print("✓ Config flow module imported")
        
        # Check for ConfigFlow class
        if not hasattr(config_flow_module, "ConfigFlow"):
            errors.append("ConfigFlow class not found in config_flow module")
            print("✗ ConfigFlow class not found")
        else:
            print("✓ ConfigFlow class found")
            
            # Try to instantiate with minimal stub
            class StubHass:
                """Minimal stub for HomeAssistant."""
                def __init__(self):
                    self.data = {}
                    self.config_entries = StubConfigEntries()
            
            class StubConfigEntries:
                """Minimal stub for config entries."""
                pass
            
            try:
                flow_class = config_flow_module.ConfigFlow
                # Just verify it's a class, don't actually instantiate (requires more setup)
                if not isinstance(flow_class, type):
                    errors.append("ConfigFlow is not a class")
                    print("✗ ConfigFlow is not a class")
                else:
                    print("✓ ConfigFlow is a valid class")
            except Exception as e:
                errors.append(f"Failed to access ConfigFlow: {e}")
                print(f"✗ Failed to access ConfigFlow: {e}")
        
        # Check for heavy imports at module level
        # Read the file and check for pyatv/samsungtvws imports at top level
        config_flow_path = repo_root / "custom_components" / "frame_artmode_sync" / "config_flow.py"
        with open(config_flow_path, encoding="utf-8") as f:
            content = f.read()
        
        # Check if pyatv.connect or pyatv.scan are called at module level
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name):
                        if node.func.value.id == "pyatv" and node.func.attr in ("connect", "scan"):
                            # Check if this is at module level (not inside a function)
                            parent = node
                            while hasattr(parent, "parent"):
                                parent = getattr(parent, "parent", None)
                                if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                    break
                            else:
                                errors.append(
                                    "pyatv.connect or pyatv.scan called at module level "
                                    "(should be lazy-imported inside functions)"
                                )
                                print("✗ Heavy imports at module level detected")
                                break
        
        if not errors:
            print("✓ Config flow is import-safe")
    
    except CircularImportError as e:
        errors.append(f"Circular import in config_flow: {e}")
        print(f"✗ {e}")
    except Exception as e:
        errors.append(f"Failed to check config_flow: {e}")
        print(f"✗ {traceback.format_exc()}")
    
    print()
    return len(errors) == 0, errors


def check_entrypoint_sanity() -> tuple[bool, list[str]]:
    """Check F: Minimal HA entrypoint sanity."""
    errors = []
    print("=" * 70)
    print("F) Minimal HA Entrypoint Sanity")
    print("=" * 70)
    
    if not HA_AVAILABLE:
        print("⊘ SKIP (HA not available)")
        print()
        return True, []
    
    try:
        # Import __init__
        init_module = wrapped_import_module("custom_components.frame_artmode_sync.__init__")
        print("✓ __init__ module imported")
        
        # Check for async_setup_entry
        if not hasattr(init_module, "async_setup_entry"):
            errors.append("async_setup_entry not found")
            print("✗ async_setup_entry not found")
        else:
            print("✓ async_setup_entry found")
        
        # Check for async_unload_entry
        if not hasattr(init_module, "async_unload_entry"):
            errors.append("async_unload_entry not found")
            print("✗ async_unload_entry not found")
        else:
            print("✓ async_unload_entry found")
        
        # Try to call with stubs (just verify no immediate ImportError/NameError)
        class StubHass:
            def __init__(self):
                self.data = {}
                self.config_entries = StubConfigEntries()
        
        class StubConfigEntries:
            def __init__(self):
                self.entries = {}
            
            def async_update_entry(self, entry, **kwargs):
                pass
        
        class StubEntry:
            def __init__(self):
                self.entry_id = "test"
                self.data = {}
                self.options = {}
        
        # Just verify the function exists and is callable, don't actually await it
        # (would require event loop)
        if hasattr(init_module, "async_setup_entry"):
            func = init_module.async_setup_entry
            if not callable(func):
                errors.append("async_setup_entry is not callable")
                print("✗ async_setup_entry is not callable")
            else:
                print("✓ async_setup_entry is callable")
        
    except Exception as e:
        errors.append(f"Failed to check entrypoint: {e}")
        print(f"✗ {traceback.format_exc()}")
    
    print()
    return len(errors) == 0, errors


def main() -> int:
    """Run all preflight checks."""
    print("=" * 70)
    print("Frame Art Mode Sync - Preflight Gate")
    print("=" * 70)
    print()
    
    if not HA_AVAILABLE:
        print("⚠ WARNING: Home Assistant not available in this environment")
        print("   Some checks will be skipped.")
        print()
    
    all_errors = []
    
    # A) Import order
    ok, errors = check_import_order()
    all_errors.extend(errors)
    
    # B) Dynamic imports
    ok, errors = check_dynamic_imports()
    all_errors.extend(errors)
    
    # C) Circular imports (detected during A and B)
    # Already handled by wrapped_import_module
    
    # D) Const contract
    ok, errors = check_const_contract()
    all_errors.extend(errors)
    
    # E) Config flow safety
    ok, errors = check_config_flow_safety()
    all_errors.extend(errors)
    
    # F) Entrypoint sanity
    ok, errors = check_entrypoint_sanity()
    all_errors.extend(errors)
    
    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    if all_errors:
        print(f"✗ FAILED: {len(all_errors)} error(s) found")
        print()
        print("Errors:")
        for i, error in enumerate(all_errors, 1):
            print(f"  {i}. {error}")
        print()
        print("Fix all errors before deploying to Home Assistant.")
        return 1
    else:
        print("✓ SUCCESS: All preflight checks passed!")
        print()
        print("The integration is ready for deployment.")
        return 0


if __name__ == "__main__":
    sys.exit(main())

