# Changelog

## 0.2.2b0 — Unreleased

- Suggest the nearest unconfigured live-directory airport using HA’s location locally.
- Keep the full editable airport selector and manual fallback; setup still requires submission.
- Bundle a compact public-domain OurAirports coordinate reference; no home-coordinate transmission or storage.
- Preserve manual overrides on provider errors and existing airport identities.

## 0.2.1b0 — Unreleased

- Add native terminal/checkpoint-open binary sensors, including later discoveries.
- Preserve airport wait/PreCheck identities and checkpoint attributes; share polling.
- Keep missing/unknown checkpoints unavailable and preserve registry customizations.
- Cover checkpoint identity, reload/unload, discovery and recovery with native HA tests.

## 0.2.0b0 — Unreleased

- Replace the PDX-only provider with anonymous TSAWaitTimes.com HTML.
- Select airports from the live linked directory; independent entries per airport.
- Airport-wide modeled duration, hourly estimate attributes, PreCheck availability
  and terminal/checkpoint status attributes; no invented checkpoint wait sensors.
- Shared directory caching, aggregate five-second pacing, five-minute minimum per
  airport, retained reload/manual-refresh floors and bounded HTTP 429 cooldowns.
- Version-2 migration preserves legacy PDX entry identity and preferences without
  repurposing or automatically deleting old checkpoint entities.
- Native HA lifecycle, registry, exact-timer and loopback HTTP regression coverage.

## 0.1.0b0 — Unreleased, superseded

- Initial PDX-only airport-feed preview; replaced because it used the wrong source.

No public release has been published.
