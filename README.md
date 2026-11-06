# TSA Wait Times for Home Assistant

<img src="https://raw.githubusercontent.com/ColeMundus/ha-tsa-wait-times/main/custom_components/tsa_wait_times/brand/icon.png" alt="TSA seal; unofficial integration" width="96" height="96">

[![CI: workflow](docs/badges/ci.svg)](https://github.com/ColeMundus/ha-tsa-wait-times/actions/workflows/ci.yml)
[![HA tested: 2026.10.0](docs/badges/compatibility.svg)](https://github.com/ColeMundus/ha-tsa-wait-times/actions/workflows/ci.yml)
[![License: MIT](docs/badges/license.svg)](LICENSE)
[![Distribution: custom repository](docs/badges/distribution.svg)](#installation)

Airport security wait estimates and checkpoint status from
[TSAWaitTimes.com](https://www.tsawaittimes.com/), with no account or API key.
Choose from the site's live [airport directory](https://www.tsawaittimes.com/airports)
and monitor multiple airports. This integration is independent of TSA and TayTech.

## Installation

Requires **Home Assistant 2026.10.0+**. Available as a HACS custom repository;
not yet included in HACS's default catalog. [Preview release: 0.2.2b0](https://github.com/ColeMundus/ha-tsa-wait-times/releases/tag/v0.2.2b0).

1. In HACS, open **Custom repositories** and add
   `https://github.com/ColeMundus/ha-tsa-wait-times` with category **Integration**.
2. Download **TSA Wait Times** (enable prereleases to select the preview), then restart Home Assistant.
3. Continue with setup below.

For manual installation, download the ZIP from the release and extract it into your
HA configuration directory before restarting. The installed path must be
`custom_components/tsa_wait_times/manifest.json`.

## Setup

1. Open **Settings → Devices & services → Add integration → TSA Wait Times**.
2. Confirm the suggested nearby airport or choose another from the searchable list.
3. Set the polling interval (**5–1440 minutes**, default **5**) and submit.

The default is calculated locally from HA's location; your coordinates are never
sent to the website or a geocoding service. Missing coordinates leave manual selection
available. Add another entry for another airport; **Configure** changes polling.

## Entities

Each airport gets a device containing:

| Entity | Information |
| --- | --- |
| Estimated wait | Airport-wide estimate in minutes, including seconds; hourly estimates in attributes |
| TSA PreCheck available | Whether the website reports PreCheck availability; checkpoint list in attributes |
| Checkpoint open | One binary sensor per terminal/checkpoint: **on = Open**, **off = Closed** |

New checkpoints appear automatically. Missing or unknown values become **unavailable**,
not zero or closed. Checkpoint identities use exact source labels; custom names and
IDs survive reload. All entities share one airport refresh.

## Data and privacy

- Waits are **modeled estimates**, not guaranteed live queue measurements. The source
  does not provide checkpoint-specific wait durations or an observation timestamp.
  `fetched_at` means retrieval time, not measurement time.
- Only selected airports are polled. The directory is cached, requests are paced,
  and rate-limit responses trigger backoff. Website markup and coverage can change.
- HA stores the selected airport and interval, not your home coordinates. The local
  airport-coordinate reference comes from public-domain [OurAirports data](https://ourairports.com/data/).
- The website's [terms](https://www.tsawaittimes.com/terms) permit personal,
  noncommercial and educational use; this project does not grant commercial data rights.
  Code is MIT licensed; website data and the TSA seal are not relicensed by this project.
  See [notices](custom_components/tsa_wait_times/NOTICE) for artwork provenance and insignia restrictions. No endorsement is implied.

If setup or updates fail, check the airport page and retry after the polling/backoff
interval. Persistent failures may indicate changed site markup; report sanitized logs.

[Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Security](SECURITY.md)
