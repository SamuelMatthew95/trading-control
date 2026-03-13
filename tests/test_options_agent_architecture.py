from api.services.options import OptionsService


def test_options_service_generate_plays_has_full_agent_trace_and_guardrail():
    service = OptionsService(anthropic_api_key=None)
    flow = service._mock_flow()
    screener = service._mock_screener()

    result = service.generate_plays(flow, screener, learning_context=[])

    assert "items" in result
    assert "agent_trace" in result
    assert "guardrail" in result
    assert "task_plan" in result
    assert result["task_plan"] == [
        "observe_market_state",
        "orient_signals",
        "decide_strategy_candidates",
        "act_with_guardrails",
        "validate_output_quality",
    ]

    agent_names = {step["agent"] for step in result["agent_trace"]}
    assert {
        "OPTIONS_ANALYST",
        "OPTIONS_STRATEGIST",
        "OPTIONS_EXECUTOR",
        "OPTIONS_GUARDRAIL",
        "OPTIONS_VALIDATOR",
    }.issubset(agent_names)


def test_options_learning_summary_is_stable():
    service = OptionsService(anthropic_api_key=None)
    summary = service.learning_summary([
        {"pnl": 1.2, "signalTag": "Sweep"},
        {"pnl": -0.2, "signalTag": "Block"},
    ])
    assert summary["win_rate"] == 50.0
    assert "summary" in summary
    assert "best_signal" in summary


def test_generate_plays_guardrail_returns_human_review_flag():
    service = OptionsService(anthropic_api_key=None)
    result = service.generate_plays([], [], learning_context=[])
    assert "requires_human_review" in result["guardrail"]


def test_get_flow_falls_back_to_mock_when_mcp_fails(mocker):
    service = OptionsService(anthropic_api_key=None)
    mocker.patch.object(service, "_call_mcp_tool", side_effect=RuntimeError("boom"))
    flow = service.get_flow()
    assert isinstance(flow, list)
    assert flow


def test_options_service_exposes_uniform_metrics_endpoints_shape():
    service = OptionsService(anthropic_api_key=None, anthropic_model="test-model")
    _ = service.generate_plays(service._mock_flow(), service._mock_screener(), learning_context=[])

    health = service.get_health()
    performance = service.get_performance()
    stats = service.get_statistics()

    assert health["service"] == "options"
    assert health["model"] == "test-model"
    assert "OPTIONS_GUARDRAIL" in performance
    assert "approval_rate" in stats


def test_build_run_record_uses_options_prefix():
    service = OptionsService(anthropic_api_key=None)
    output = service.generate_plays(service._mock_flow(), service._mock_screener(), learning_context=[])
    record = service.build_run_record(output)
    assert record["task_id"].startswith("options-")
    assert "trace" in record
