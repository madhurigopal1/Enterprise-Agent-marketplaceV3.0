# Test report - v1.1.0-features

`python -m pytest -q` → **30 passed** (13 original + 9 approval/UI + 8 v1.1 features).

## Browser click-through (headless Chromium, `tests/e2e_browser.py`)
- 7 tabs rendered: Ask, Marketplace, Register Agent, My Runs, Approvals, Governance & Audit, Observability
- Arjun: 2 Finance runs → Approvals shows 2 cards → Select all → "Approve selected (2)" → inbox empty
- My Runs: 2 rows → Open → completed run with human decision and comment → 4-star rating saved
- Download report → `run-xxxx-report.md`
- Sam: Documentation Agent → Kill switch → "suspended" badge, failing Kill switch check with reason
- Governance → Export CSV → `audit-log.csv`
- No JavaScript console errors

Screenshots: `docs/screenshots/`. Providers, SSO and persistence remain simulated.
