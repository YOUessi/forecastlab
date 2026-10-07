# Browser CI teardown stabilization — 2026-10-08

## Trigger

After merging the Agent 2 exact-quote boundary refinement, the main push CI completed:

- backend tests: success;
- frontend install/build: success;
- Chromium install: success;
- browser assertions: **13 passed**.

The job was nevertheless marked failed during fixture teardown because Playwright raised:

`Page.screenshot: Protocol error (Page.captureScreenshot): Unable to capture screenshot`

The failure occurred after the test assertions had already passed.

## Fix

`frontend/tests/conftest.py` now treats screenshots as best-effort validation artifacts:

- attempt the screenshot only while the page is open;
- catch Playwright screenshot errors;
- always close the browser context in `finally`;
- never suppress an actual browser-test assertion failure.

This changes only artifact collection semantics; product E2E assertions remain strict.
