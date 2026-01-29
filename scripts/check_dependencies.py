#!/usr/bin/env python3
"""Check for updates to dependencies.

This script checks the latest versions of pyatv, samsungtvws, and wakeonlan
and compares them with the versions specified in manifest.json.
"""

import json
import sys
from pathlib import Path
from urllib.request import urlopen

try:
    from packaging import version
    HAS_PACKAGING = True
except ImportError:
    HAS_PACKAGING = False
    print("Warning: 'packaging' module not found. Install it for accurate version comparison:")
    print("  pip install packaging")
    print("  Falling back to simple string comparison...\n")

# GitHub API endpoints for releases
DEPENDENCIES = {
    "pyatv": {
        "repo": "postlund/pyatv",
        "pypi": "pyatv",
        "manifest_key": "pyatv",
    },
    "samsungtvws": {
        "repo": "xchwarze/samsung-tv-ws-api",
        "pypi": "samsungtvws",
        "manifest_key": "samsungtvws",
    },
    "wakeonlan": {
        "repo": None,  # Not a GitHub project
        "pypi": "wakeonlan",
        "manifest_key": "wakeonlan",
    },
}


def get_latest_github_release(repo: str) -> str | None:
    """Get the latest release tag from GitHub."""
    try:
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        with urlopen(url, timeout=10) as response:
            data = json.loads(response.read())
            tag = data.get("tag_name", "")
            # Remove 'v' prefix if present
            return tag.lstrip("v") if tag else None
    except Exception as ex:
        print(f"  Warning: Could not fetch GitHub release for {repo}: {ex}")
        return None


def get_latest_pypi_version(package: str) -> str | None:
    """Get the latest version from PyPI."""
    try:
        url = f"https://pypi.org/pypi/{package}/json"
        with urlopen(url, timeout=10) as response:
            data = json.loads(response.read())
            return data.get("info", {}).get("version")
    except Exception as ex:
        print(f"  Warning: Could not fetch PyPI version for {package}: {ex}")
        return None


def parse_version_spec(spec: str) -> tuple[str, str]:
    """Parse version spec like '>=0.14.0' into (operator, version)."""
    if spec.startswith(">="):
        return (">=", spec[2:])
    elif spec.startswith(">"):
        return (">", spec[1:])
    elif spec.startswith("=="):
        return ("==", spec[2:])
    elif spec.startswith("~="):
        return ("~=", spec[2:])
    else:
        # Assume >= if no operator
        return (">=", spec)


def check_dependencies() -> int:
    """Check dependencies and return exit code (0 = all up to date, 1 = updates available)."""
    repo_root = Path(__file__).parent.parent
    manifest_path = repo_root / "custom_components" / "frame_artmode_sync" / "manifest.json"
    
    with open(manifest_path) as f:
        manifest = json.load(f)
    
    requirements = manifest.get("requirements", [])
    current_versions = {}
    
    # Parse current requirements
    for req in requirements:
        for dep_name, dep_info in DEPENDENCIES.items():
            if req.startswith(dep_info["manifest_key"]):
                # Extract version spec
                parts = req.split(">=", 1)
                if len(parts) == 2:
                    current_versions[dep_name] = parts[1]
                else:
                    # Try other operators
                    for op in [">=", ">", "==", "~="]:
                        if op in req:
                            current_versions[dep_name] = req.split(op, 1)[1]
                            break
                break
    
    print("Checking for dependency updates...\n")
    updates_available = False
    
    for dep_name, dep_info in DEPENDENCIES.items():
        print(f"Checking {dep_name}...")
        current = current_versions.get(dep_name, "unknown")
        print(f"  Current: {current}")
        
        # Try GitHub first (for pyatv and samsungtvws)
        latest_github = None
        if dep_info["repo"]:
            latest_github = get_latest_github_release(dep_info["repo"])
            if latest_github:
                print(f"  Latest GitHub release: {latest_github}")
        
        # Always check PyPI (most reliable)
        latest_pypi = get_latest_pypi_version(dep_info["pypi"])
        if latest_pypi:
            print(f"  Latest PyPI version: {latest_pypi}")
        
        # Use PyPI as source of truth, fallback to GitHub
        latest = latest_pypi or latest_github
        
        if latest and current != "unknown":
            try:
                # Compare versions
                if HAS_PACKAGING:
                    if version.parse(latest) > version.parse(current):
                        print(f"  ⚠️  UPDATE AVAILABLE: {current} -> {latest}")
                        updates_available = True
                    elif version.parse(latest) == version.parse(current):
                        print(f"  ✓ Up to date")
                    else:
                        print(f"  ℹ️  Latest is older than current (unusual)")
                else:
                    # Simple string comparison (less accurate)
                    if latest != current:
                        print(f"  ⚠️  Version differs: current={current}, latest={latest}")
                        print(f"     (Install 'packaging' for accurate comparison)")
                        # Heuristic: if latest looks newer, suggest update
                        if latest > current:
                            updates_available = True
                    else:
                        print(f"  ✓ Versions match")
            except Exception as ex:
                print(f"  ⚠️  Could not compare versions: {ex}")
        elif latest:
            print(f"  ⚠️  Could not determine current version, latest is {latest}")
        else:
            print(f"  ⚠️  Could not fetch latest version")
        
        print()
    
    if updates_available:
        print("\n⚠️  Updates are available! Consider updating manifest.json")
        print("\nTo update:")
        print("1. Review the changelogs for breaking changes:")
        print("   - pyatv: https://github.com/postlund/pyatv/releases")
        print("   - samsungtvws: https://github.com/xchwarze/samsung-tv-ws-api/releases")
        print("2. Test the integration with new versions")
        print("3. Update manifest.json with new version requirements")
        return 1
    else:
        print("✓ All dependencies are up to date!")
        return 0


if __name__ == "__main__":
    try:
        exit_code = check_dependencies()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(130)
    except Exception as ex:
        print(f"\n\nError: {ex}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
