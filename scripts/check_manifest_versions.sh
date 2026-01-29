#!/bin/bash
# Quick script to check latest versions from PyPI
# Usage: ./scripts/check_manifest_versions.sh

echo "Checking latest versions on PyPI..."
echo ""

echo "pyatv:"
curl -s https://pypi.org/pypi/pyatv/json | grep -o '"version":"[^"]*"' | head -1
echo ""

echo "samsungtvws:"
curl -s https://pypi.org/pypi/samsungtvws/json | grep -o '"version":"[^"]*"' | head -1
echo ""

echo "wakeonlan:"
curl -s https://pypi.org/pypi/wakeonlan/json | grep -o '"version":"[^"]*"' | head -1
echo ""

echo "Current requirements in manifest.json:"
grep -A 3 '"requirements"' custom_components/frame_artmode_sync/manifest.json
