# Runbook — Alert Handling

How to take any alert from page to closed. Severity contract is defined in
`observability/signoz/alerts.md` (P1 page / P2 channel / P3 digest).

## 1. Acknowledge (always, even solo)
Ack in SigNoz so the alert state reflects reality. Note the time — your
timeline starts now.

## 2. Classify in 2 minutes
Answer three questions, in order:

1. **Is money at risk right now?** (orders flowing on bad data, losses past
   limit, kill switch failing) → engage the kill switch FIRST, investigate
   second: `redis-cli set kill_switch:active 1`.
2. **Is it the app or the telescope?** All metrics dying at the same instant
   → [monitoring-outage.md](monitoring-outage.md). Confirm the app directly
   via `curl /health` before debugging "the outage".
3. **Which runbook?** Every alert in `alerts.md` maps to one. No match =
   novel incident → start from [bot-stopped.md](bot-stopped.md) triage and
   write the missing runbook afterwards.

## 3. Work it
- Follow the runbook's Triage → Mitigate path; prefer rollback over hotfix.
- Keep a raw timeline as you go (commands run, findings, times) — memory
  reconstructs badly.
- One change at a time; verify after each.

## 4. Close
An alert is closed when:
- [ ] the firing condition cleared on its own metric (not silenced),
- [ ] the kill switch state is what you intend it to be (and you checked),
- [ ] impact is written down (duration, trades affected — query
      `trade_lifecycle` / closed trades for the window),
- [ ] follow-ups are filed as issues, not memories.

## 5. Post-incident (within 48h, blameless)
- Update `docs/troubleshooting/<subsystem>.md` (repo rule: Symptom / Root
  cause / Fix / Regression test).
- If the alert was noisy or late, tune the rule in `alerts.md` — alert debt
  is real debt.
- If a runbook step was wrong or missing, fix the runbook in the same PR as
  the fix.

## Silencing policy
Silence only with: an owner, an expiry, and a linked issue. Permanent
silences are deletions — if it never needs action, delete the rule.
