# TSA Wait Times for Home Assistant

Read Portland International Airport (PDX) security wait estimates without an account.
This is an unofficial, read-only custom integration, not a TSA or Port of Portland product.
**PDX is the only supported airport.** No nationwide coverage, AUS support, travel-time
prediction, or TSA account connection is provided.

## Installation

Requires Home Assistant **2026.10.0 or newer**; currently tested against 2026.10.0.
This repository is currently private and no release has been published. It is not
listed in HACS and cannot currently be installed through public HACS distribution.

For an authorized local preview, run `uv run --locked python scripts/package.py` and
extract `dist/tsa-wait-times-0.1.0b0.zip` into your Home Assistant configuration directory.
The resulting path must be `custom_components/tsa_wait_times/manifest.json`.
Restart Home Assistant. Do not copy the development virtual environment or tests.

After public distribution is approved and a release exists, the intended HACS path
is: add `https://github.com/ColeMundus/ha-tsa-wait-times` as a custom **Integration**
repository, download TSA Wait Times, and restart Home Assistant. HACS downloads source;
the manual-install ZIP is not configured as a HACS release asset.

## Setup

In **Settings → Devices & services → Add integration**, select **TSA Wait Times**.
Choose **PDX** and a polling interval in whole minutes (1–1440; default 5).
No credentials, API key, browser extraction, or YAML are needed. Only one PDX entry
is allowed. Use the integration's **Configure** options to change the interval.

## Entities

All entities belong to the **TSA Wait Times PDX** service device. Default IDs:

| Entity | Meaning |
| --- | --- |
| `sensor.tsa_wait_times_pdx_northgeneral` | North general wait, minutes |
| `sensor.tsa_wait_times_pdx_northprecheck` | North TSA PreCheck wait, minutes |
| `sensor.tsa_wait_times_pdx_southgeneral` | South general wait, minutes |
| `sensor.tsa_wait_times_pdx_southprecheck` | South TSA PreCheck wait, minutes |
| `binary_sensor.tsa_wait_times_pdx_north` | North checkpoint closed (on = closed) |
| `binary_sensor.tsa_wait_times_pdx_south` | South checkpoint closed (on = closed) |

Missing/non-numeric waits and waits for closed checkpoints are **unavailable**, not
zero. A genuine numeric zero remains zero. Provider/connection errors make all
entities unavailable until a valid update succeeds. Customized names and IDs survive reload.

## Source and limitations

Data comes directly from the anonymous first-party
[`flypdx.com/TSAWaitTimesRefresh`](https://www.flypdx.com/TSAWaitTimesRefresh)
website feed. This is an **undocumented website endpoint**, not a supported developer
API. It can change or disappear. Public access does not establish permission for
redistribution or a service-level guarantee. Only the airport's displayed `DisplayText`
minutes and explicit checkpoint-closed flags are used; internal dwell/occupancy fields
have unverified units and are ignored. Unknown additional counters are ignored.

The website refreshes its feed every 60 seconds. This integration defaults to five
minutes and enforces at least 60 seconds between attempts, including manual refreshes,
setup validation and reloads. Successful cached data can be reused during that floor.
429 `Retry-After` delta/date values are bounded to 60–3600 seconds; during cooldown
no request is made, even after entry reload. Cooldowns are in memory and reset on
Core restart. After cooldown, the next scheduled/manual update can retry; updates
are not guaranteed to occur exactly when cooldown ends.

The source provides **no observation timestamp**. Home Assistant's update time is
not proof of fresh airport measurement. Waits are estimates, not guarantees; consult
the airport and airline and allow appropriate arrival time. Schedule fields are not
used to infer closure. A stale but syntactically valid source response cannot be detected.

No personal information or credentials are collected. HA stores airport and interval;
public feed values and cooldown state are retained in memory. Diagnostics expose only
airport, interval, update success and absence of a source timestamp. Routine tests use
synthetic data and loopback HTTP, not the live airport.

## Troubleshooting

If setup fails, wait at least one minute before retrying (up to one hour after rate
limiting), then check the airport website. Repeated retries/reloads do not bypass the
in-memory request floor. Unavailable waits may mean the checkpoint is closed or the
source no longer supplies a numeric estimate. Remove the integration through Devices
& services to remove its entry; uninstall its files through your installation method.

## Distribution status

Code is MIT licensed; airport and TSA names/trademarks remain their owners' property.
No official artwork is bundled: branding provenance/redistribution rights are unresolved.
Public release is gated on branding review, independent review, public HACS validation
and installed testing. No endorsement is implied. Local automated checks do not prove
HACS catalog acceptance or operation on a production HA instance.

See [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md) and
[SECURITY.md](SECURITY.md).
