# Contributing

Use Python 3.14 and uv. The lock pairs Core 2026.10.0 with
pytest-homeassistant-custom-component 0.13.371; update those together.

```sh
uv sync --locked
env -u PYTHONPATH -u PYTHONHOME uv run --locked ruff check .
env -u PYTHONPATH -u PYTHONHOME uv run --locked ruff format --check .
env -u PYTHONPATH -u PYTHONHOME uv run --locked mypy
env -u PYTHONPATH -u PYTHONHOME uv run --locked pytest --cov=custom_components/tsa_wait_times --cov-report=term-missing
env -u PYTHONPATH -u PYTHONHOME uv run --locked python scripts/package.py
git diff --check
```

Tests use actual HA flows, registries and the HA-owned aiohttp session against a
loopback server. External sockets remain blocked. Keep fixtures synthetic; do not
check in live captures, secrets or local agent instructions. Airport choices come
from TSAWaitTimes.com's linked directory. Parser changes need verified displayed
units, selected-airport identity checks and missing-value regressions; do not add
unverified API or autocomplete locations as working airport coverage.

CI runs lint, typing, tests, packaging, hassfest and (only for public repositories)
HACS validation. A private HACS skip is not validation success. The archive script
validates runtime syntax/JSON, required files, safe inputs and the finished ZIP.
It creates a manual-install archive and SHA256 sidecar; it does not publish anything.

Before a release: review changes independently, run all checks, resolve branding
rights, validate HACS without exclusions, and test an authorized fresh installation
and upgrade separately. Match manifest/project version and tag. Public visibility,
release publication and production installation each require explicit authorization.
No workflow automatically creates a release.

Report reproducible failures with Core version and sanitized logs. Do not include
personal travel plans; follow SECURITY.md for security reports.
