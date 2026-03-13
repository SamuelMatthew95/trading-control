"""Demo entry-point for local options-agent orchestration loop.

Run:
    python -m api.services.options_main
"""

from __future__ import annotations

from pprint import pprint

from api.services.options import OptionsService


def main() -> None:
    service = OptionsService(anthropic_api_key=None)
    flow = service.get_flow()
    screener = service.get_screener()
    result = service.generate_plays(flow=flow, screener=screener, learning_context=[])

    print("=== Options Agent Orchestration Demo ===")
    print("Task plan:")
    for step in result.get("task_plan", []):
        print(f"- {step}")

    print("\nAgent trace:")
    for trace in result.get("agent_trace", []):
        print(f"- {trace['agent']}: {trace['summary']}")

    print("\nGuardrail:")
    pprint(result.get("guardrail", {}))

    print("\nApproved plays:")
    pprint(result.get("items", []))


if __name__ == "__main__":
    main()
