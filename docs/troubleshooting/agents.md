# Agent Lifecycle Troubleshooting

Covers the agent fleet's start/stop/supervision: which agents run, how crashed
tasks are detected and restarted, and the uniform introspection interface
(`name` / `has_crashed`) the supervisor depends on.

## RiskGuardian was started but never supervised

**Symptom:** The stop-loss / take-profit / daily-loss monitor (`RiskGuardian`)
could die and never be restarted — silently disabling position-level risk
enforcement — with no crash alert on the dashboard. `AgentSupervisor` restarted
every stream agent but not RiskGuardian.

**Root cause:** `AgentSupervisor` monitors only the `_build_agents()` list
(`app.state.agents`). `RiskGuardian` is started separately in `startup.py` and
was never added to that list, so it sat outside the supervision loop. It also
lacked the `name` / `has_crashed` properties the supervisor reads, so it could
not have been appended without raising `AttributeError` mid-health-check (which
would have aborted the whole health tick — see the `MultiStreamAgent` entry in
`tests/core/test_base_consumer_crash.py`).

**Fix:**
- Gave `RiskGuardian` and `AgentSupervisor` the same `name` / `has_crashed`
  introspection interface as the stream agents (`MultiStreamAgent`), so the
  background-task agents are uniform with the supervised fleet.
- Wired `RiskGuardian` into the supervised set:
  `AgentSupervisor(event_bus, [*agents, risk_guardian])` (`api/startup.py`).
- RiskGuardian's `_run()` loop already swallows per-cycle exceptions, so the task
  rarely dies; supervision is the backstop for the case where it does. The
  supervisor still cannot restart *itself* — a watchdog can't restart its own
  task — which is why nothing monitors `AgentSupervisor`.

**Regression test:** `tests/core/test_base_consumer_crash.py::test_startup_wires_risk_guardian_into_supervisor`
