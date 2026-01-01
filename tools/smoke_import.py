#!/usr/bin/env python3
"""Import smoke test for Frame Art Mode Sync integration.

This script verifies that all integration modules can be imported without errors.
It should be run before copying the integration to Home Assistant.

Usage:
    python3 tools/smoke_import.py
"""

import sys
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

# Check if Home Assistant is available
HA_AVAILABLE = False
try:
    import homeassistant
    HA_AVAILABLE = True
except ImportError:
    pass

# Modules to test in order (HA loads them in roughly this order)
MODULES = [
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

# Entity platform modules
ENTITY_MODULES = [
    "custom_components.frame_artmode_sync.switch",
    "custom_components.frame_artmode_sync.time",
    "custom_components.frame_artmode_sync.number",
    "custom_components.frame_artmode_sync.select",
    "custom_components.frame_artmode_sync.sensor",
    "custom_components.frame_artmode_sync.binary_sensor",
    "custom_components.frame_artmode_sync.entities.switch",
    "custom_components.frame_artmode_sync.entities.time",
    "custom_components.frame_artmode_sync.entities.number",
    "custom_components.frame_artmode_sync.entities.select",
    "custom_components.frame_artmode_sync.entities.sensor",
    "custom_components.frame_artmode_sync.entities.binary_sensor",
    "custom_components.frame_artmode_sync.entities.__init__",
]


def test_import(module_name: str) -> tuple[bool, str]:
    """Test importing a module."""
    try:
        # Special handling for const.py - can test even without HA
        if module_name == "custom_components.frame_artmode_sync.const":
            # Test const.py can be parsed
            import ast
            const_path = repo_root / "custom_components" / "frame_artmode_sync" / "const.py"
            with open(const_path) as f:
                ast.parse(f.read(), const_path.name)
            # Import directly using importlib
            from importlib.util import spec_from_file_location, module_from_spec
            spec_obj = spec_from_file_location("const_test", const_path)
            if spec_obj and spec_obj.loader:
                mod = module_from_spec(spec_obj)
                spec_obj.loader.exec_module(mod)
            return True, ""
        elif not HA_AVAILABLE:
            # Skip HA-dependent modules if HA not available
            return None, "SKIP (HA not available)"
        
        __import__(module_name)
        return True, ""
    except ImportError as e:
        return False, f"ImportError: {e}"
    except AttributeError as e:
        return False, f"AttributeError: {e}"
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def verify_const_exports() -> list[str]:
    """Verify all constants imported by other modules exist in const.py."""
    import ast
    import re
    
    errors = []
    const_path = repo_root / "custom_components" / "frame_artmode_sync" / "const.py"
    
    # Read const.py and extract all constant names
    with open(const_path) as f:
        const_content = f.read()
    
    # Extract all NAME = ... patterns
    const_names = set()
    for match in re.finditer(r'^([A-Z_][A-Z0-9_]*) = ', const_content, re.MULTILINE):
        const_names.add(match.group(1))
    
    # Check all .py files for imports from .const
    component_dir = repo_root / "custom_components" / "frame_artmode_sync"
    for py_file in component_dir.rglob("*.py"):
        if py_file.name == "__pycache__" or py_file.parent.name == "__pycache__":
            continue
        if py_file.parent.name == "translations":
            continue
        
        try:
            with open(py_file) as f:
                content = f.read()
            
            # Find imports from .const or ..const
            imports = re.findall(
                r'from\s+(?:\.+|custom_components\.frame_artmode_sync)\.const\s+import\s+([^)]+)',
                content,
                re.MULTILINE | re.DOTALL
            )
            
            for import_line in imports:
                # Parse the import list - handle multiline imports with proper parsing
                # Remove newlines and split by comma
                import_line = re.sub(r'\s+', ' ', import_line.strip())
                # Match actual identifier patterns (not single letters from comments)
                # Match words that start with uppercase letter and contain uppercase/underscores/numbers
                names = re.findall(r'\b([A-Z][A-Z0-9_]{2,})\b', import_line)
                for name in names:
                    if name not in const_names:
                        rel_path = py_file.relative_to(repo_root)
                        errors.append(f"{rel_path}: imports '{name}' which doesn't exist in const.py")
        except Exception as e:
            errors.append(f"Error checking {py_file.relative_to(repo_root)}: {e}")
    
    return errors


def main() -> int:
    """Run smoke test."""
    print("=" * 70)
    print("Frame Art Mode Sync - Import Smoke Test")
    print("=" * 70)
    print()
    
    if not HA_AVAILABLE:
        print("⚠ WARNING: Home Assistant not available in this environment")
        print("   Testing const.py syntax and exports only...")
        print()
    
    # First, verify all const imports are valid
    print("Verifying const.py exports...")
    const_errors = verify_const_exports()
    if const_errors:
        print("✗ FAILED: Found imports of non-existent constants:")
        for error in const_errors:
            print(f"  - {error}")
        print()
        return 1
    else:
        print("✓ All constants imported from const.py exist")
        print()
    
    failed = []
    skipped = []
    
    # Test core modules in order
    print("Testing core modules...")
    for module in MODULES:
        result, msg = test_import(module)
        if result is True:
            print(f"✓ OK import {module}")
        elif result is None:
            print(f"⊘ SKIP {module} ({msg})")
            skipped.append(module)
        else:
            print(f"✗ FAIL import {module}")
            print(f"  {msg}")
            if HA_AVAILABLE:  # Only fail on errors if HA is available
                failed.append(module)
    
    print()
    print("Testing entity platform modules...")
    for module in ENTITY_MODULES:
        result, msg = test_import(module)
        if result is True:
            print(f"✓ OK import {module}")
        elif result is None:
            print(f"⊘ SKIP {module} ({msg})")
            skipped.append(module)
        else:
            print(f"✗ FAIL import {module}")
            print(f"  {msg}")
            if HA_AVAILABLE:  # Only fail on errors if HA is available
                failed.append(module)
    
    print()
    print("=" * 70)
    if failed:
        print(f"FAILED: {len(failed)} module(s) failed to import:")
        for module in failed:
            print(f"  - {module}")
        print()
        print("Fix the import errors above before deploying to Home Assistant.")
        return 1
    elif skipped and not HA_AVAILABLE:
        print("SUCCESS: const.py verified, other modules skipped (HA not available)")
        print()
        print("All constant imports are valid. Test in Home Assistant environment for full validation.")
        return 0
    else:
        print("SUCCESS: All modules imported without errors!")
        print()
        print("You can now copy the integration to Home Assistant.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
