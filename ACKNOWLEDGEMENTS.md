# Acknowledgements

This project would not have been possible without the work of others in the Home Assistant and Samsung/Apple TV integration communities.

## Inspiration

- **donkthemagicllama** - A gist demonstrating fallback patterns (verify/retry/power-twice) for 2024 Samsung Frame TVs with Apple TV integration. While this project does not copy code from that gist, it was an important reference for understanding the robustness requirements when controlling Frame TVs.

## Dependencies

### pyatv

This integration uses [pyatv](https://github.com/postlund/pyatv) by **postlund** for Apple TV connectivity and push updates.

- Repository: https://github.com/postlund/pyatv
- Documentation: https://pyatv.dev
- License: MIT

pyatv provides reliable, async-friendly communication with Apple TVs and is the standard library for Apple TV integrations in Home Assistant.

### samsung-tv-ws-api / samsungtvws

This integration uses [samsung-tv-ws-api](https://github.com/xchwarze/samsung-tv-ws-api) (Python package: `samsungtvws`) for Samsung TV WebSocket control.

- Repository: https://github.com/xchwarze/samsung-tv-ws-api
- License: LGPL-3.0

The samsungtvws library provides WebSocket-based control for modern Samsung TVs, including Art Mode management. The ecosystem also includes contributions from **NickWaterton** and others who have maintained and improved Samsung TV integrations in Home Assistant.

## Home Assistant

Built for and with [Home Assistant](https://www.home-assistant.io/), the open-source home automation platform.

## Disclaimer

This project is not affiliated with, endorsed by, or associated with Samsung or Apple. All trademarks are the property of their respective owners.

