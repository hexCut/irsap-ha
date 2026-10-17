# Contributing to irsap-ha

Thanks for helping. This integration talks to a cloud we don't control and writes to radiators in people's homes, so the bar for changes is mostly about evidence. Code written with AI tools is welcome, as long as it meets the same bar.

## Before you start

- Open an issue first for anything bigger than a small fix, so we can agree on the approach.
- Base your branch on **`dev`** and open the pull request against **`dev`**. `main` only receives releases.
- Keep each pull request to one change. Several small PRs are reviewed and released much faster than one large one. Please keep **at most three PRs open at a time**.
- If your PR depends on another open PR, say so at the top of the description.

## Development setup

```
pip install -r requirements_test.txt
pytest
ruff check custom_components tests
```

The tests use [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component) and need the Python version pinned in `.github/workflows/tests.yml`. CI runs the tests, ruff, hassfest and the HACS validation on every push and pull request; all of them must pass.

## Tests

- Every behaviour change needs a test, and the test should fail without your change. Say so in the PR description.
- Never call the real IRSAP cloud from tests. Use the fixtures in `tests/conftest.py` (`mock_login`, `mock_get_shadow`, `mock_update_shadow`) or Home Assistant's `aioclient_mock`.
- When a test needs a shadow, start from a real one captured on your install (with personal data removed, see below) rather than an invented one, and say which model and firmware it comes from.
- `tests/test_snapshots.py` records every entity the integration creates (state, attributes, unit, category, enabled or not). If your change alters what users see, it fails on purpose: regenerate with `pytest tests/test_snapshots.py --snapshot-update`, commit the updated `tests/snapshots/*.ambr`, and list the difference under *Breaking / visible changes*. A shadow from a model we don't cover yet is a welcome addition there.

## Evidence from a real installation

Mocked tests show the code does what you think. They don't show the IRSAP cloud or the radiator behaves the way you think. So:

**Required** for any change that **writes to the cloud** (a new key, a new value, or a change to what an existing command sends) or changes **how the shadow is read** (new keys, new meaning for an existing key):

- debug logs from your own Home Assistant with the branch installed, enabled with:
  ```yaml
  logger:
    default: warning
    logs:
      custom_components.irsap_ha: debug
  ```
- for each command: the command sent from Home Assistant, the `UpdateShadow` call, and the next refreshes showing what the radiator wrote back (`clientId` `dev-…` means the radiator itself rewrote the shadow);
- what the IRSAP NOW app shows afterwards, if relevant;
- your radiator model, firmware version, number of radiators, and Home Assistant version.

**Recommended** for changes to polling, login or timing: a run of at least 24 hours with counts (refreshes, logins, failures, durations), as in #21.

**Not required** for documentation, tests only, CI, or refactoring with no behaviour change.

If you can't test something on real hardware (for example a feature your model doesn't have), say so plainly in the PR. It can still be merged into a beta, and the release notes will ask users with that hardware to confirm.

## Personal data

Before posting logs, diagnostics or shadows, remove:

- e-mail address, password, access tokens;
- the home's address and coordinates (`E_LOC`), presence data (`E_PRS`);
- MAC addresses (`*_SRL`, `*_CNT`, the `clientId` of the radiator), IP addresses (`*_X_ipAddress`);
- environment and shadow ids.

Keep timestamps: they are what makes a log useful. The *Download diagnostics* file already removes these fields.

## Code style

- Follow the style of the surrounding code. Comments may be in Italian or English; user-facing strings go in `translations/en.json` and `translations/it.json`.
- Don't change entity IDs or unique IDs. If a change is visible to users (units, names, categories, entities enabled or disabled), list it under **Breaking / visible changes** in the PR so it reaches the release notes.

## Releases

Maintainers merge into `dev` and publish betas (e.g. `v1.6b5`) from there; a release goes to `main` after the betas have been used for a while without problems. You don't need to change the version in `manifest.json`.
