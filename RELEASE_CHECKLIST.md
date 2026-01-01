# Release Checklist for v0.1.0

## Part 1: Bug Sweep ✅

- [x] PHASE 1: Static showstopper sweep (double-locks, untracked tasks, missing cleanup)
- [x] PHASE 2: Runtime logic bugs (enforcement, time, connectivity, memory)
- [x] PHASE 3: Bug classification and fixes
- [x] PHASE 4: Edge-case matrix verification (A-J)
- [x] **Patches Applied**: Fixed deprecated `get_event_loop()` usage in `frame_client.py`

## Part 2: Release Hardening ✅

### Packaging + CI
- [x] `hacs.json` present and correct
- [x] `manifest.json` correct (domain, name, version 0.1.0, documentation, issue_tracker, codeowners, requirements)
- [x] `strings.json` present
- [x] `translations/en.json` present
- [x] `.github/workflows/hassfest.yml` created
- [x] `.github/workflows/hacs.yml` created
- [x] `LICENSE` present (MIT)
- [x] `ACKNOWLEDGEMENTS.md` present with credits
- [x] `NOTICE` present with dependency licensing info
- [x] Version set to 0.1.0 consistently

### Documentation
- [x] README.md includes:
  - [x] What this solves (2024 Samsung The Frame + Apple TV Art Mode sync)
  - [x] Installation via HACS custom repo
  - [x] Setup steps (TV pairing prompt explanation)
  - [x] Options overview (active hours, presence optional)
  - [x] Observability (status sensor + recent events)
  - [x] Troubleshooting playbook:
    - [x] Breaker open and how to clear
    - [x] Backoff active and what it means
    - [x] Degraded state (TV offline)
    - [x] pyatv reconnect expectations
  - [x] Credits & licensing section with links to ACKNOWLEDGEMENTS.md and NOTICE
  - [x] Disclaimer (not affiliated with Apple or Samsung)

### Versioning + Changelog
- [x] Version set to 0.1.0 in `manifest.json`
- [x] `CHANGELOG.md` created with 0.1.0 highlights
- [x] Release date set to 2024-12-20

### Examples
- [x] `examples/dashboard_frames.yaml`:
  - [x] Uses correct service names under domain `frame_artmode_sync`
  - [x] Uses placeholder entity names with explanations
  - [x] Includes controls for all key settings
  - [x] Includes buttons for all manual services
  - [x] Documents both `device_id` and `entry_id` usage

## Pre-Release Verification

Before tagging v0.1.0, verify:

1. **Code Quality**:
   - [x] No showstopper bugs remaining
   - [x] All tests pass (if applicable)
   - [x] Linter warnings reviewed (missing dependencies are expected in dev environment)

2. **Documentation**:
   - [x] README.md is complete and accurate
   - [x] CHANGELOG.md has correct version and date
   - [x] ACKNOWLEDGEMENTS.md credits all dependencies
   - [x] NOTICE includes dependency licensing

3. **Packaging**:
   - [x] `manifest.json` version is 0.1.0
   - [x] `hacs.json` is correct
   - [x] CI workflows are present and correct

4. **Examples**:
   - [x] Dashboard example uses correct service names
   - [x] Placeholder values are clearly documented

## Known Limitations (Acceptable for v0.1.0)

- [x] Fallback media_player entity support not yet implemented (pyatv is primary)
- [x] Recent events buffer is in-memory only (lost on HA restart)
- [x] Requires network connectivity between HA, Frame TV, and Apple TV
- [x] Frame TV pairing requires manual approval on first setup
- [x] Wake-on-LAN requires Frame TV MAC address configuration

## Release Steps

1. ✅ Complete Part 1 (Bug Sweep) - DONE
2. ✅ Complete Part 2 (Release Hardening) - DONE
3. ⏭️ Create release branch (if using branching strategy)
4. ⏭️ Tag release: `git tag -a v0.1.0 -m "Initial release"`
5. ⏭️ Push tag: `git push origin v0.1.0`
6. ⏭️ Create GitHub release with notes from CHANGELOG.md
7. ⏭️ Verify HACS can discover and install the integration

## Status

**✅ READY FOR RELEASE**

All checklist items completed. Integration is ready for v0.1.0 release.

