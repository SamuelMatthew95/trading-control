from multi_agent_orchestrator import (DeterministicReasoningModel,
                                      DocumentRetriever,
                                      MultiAgentOrchestrator, Planner,
                                      TaskStateMemory, ToolError, TradeTools)


def test_planner_is_deterministic():
    plan = Planner().build_plan("AAPL", "1D")
    assert [step.name for step in plan.steps] == [
        "signal",
        "consensus",
        "risk",
        "sizing",
        "decision",
    ]


def test_tool_guardrails_reject_unknown_assets():
    tools = TradeTools()
    try:
        tools.get_current_price("BTC")
        assert False, "Expected ToolError"
    except ToolError:
        assert True


def test_task_state_memory_round_trip():
    mem = TaskStateMemory()
    mem.put("task-1", {"status": "running"})
    assert mem.get("task-1") == {"status": "running"}


def test_orchestrator_returns_trade_decision():
    orchestrator = MultiAgentOrchestrator(api_key=None)
    result = orchestrator.analyze_trade(
        "AAPL", "1D", {"total_value": 100000, "drawdown": -0.02}
    )
    assert result["DECISION"] in {"LONG", "SHORT", "FLAT"}
    assert "RISK FLAGS" in result


def test_retriever_returns_grounding_snippets():
    retriever = DocumentRetriever()
    snippets = retriever.retrieve("risk drawdown")
    assert isinstance(snippets, list)
