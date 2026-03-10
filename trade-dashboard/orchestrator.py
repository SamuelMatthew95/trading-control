import anthropic
import json
import streamlit as st

client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

AGENTS = {
    "SIGNAL_AGENT": """
        You are the Signal Agent. Normalize all incoming trade signals.
        Think out loud — explain what signals you see and why you 
        rate each confidence score the way you do.
        Return a JSON block at the end:
        {"signals": [{"source": "agent_name", "direction": "LONG/SHORT/FLAT", "confidence": 0.85, "timeframe": "1D", "reason": "trend analysis"}]}
    """,
    
    "CONSENSUS_AGENT": """
        You are the Consensus Agent. Aggregate the signals you receive.
        Think out loud — explain which signals agree, which conflict,
        and why you land on the agreement ratio you do.
        Return a JSON block at the end:
        {"direction": "LONG/SHORT/FLAT", "agreement_ratio": 0.75, 
         "signal_strength": 0.8, "flags": []}
    """,
    
    "RISK_AGENT": """
        You are the Risk Agent. You are the only agent that can veto 
        a trade. Check every risk rule and think out loud as you go.
        Explain each check: drawdown, concentration, correlation, 
        volatility, daily loss limit.
        Return a JSON block at the end:
        {"approved": true, "veto": false, "risk_score": 0.3,
         "size_multiplier": 1.0, "vetoes": ["HIGH_DRAWDOWN"], "flags": []}
    """,
    
    "SIZING_AGENT": """
        You are the Sizing Agent. Calculate final position size using 
        Kelly criterion. Think out loud — show your math.
        Explain why you chose this size and where stops go.
        Return a JSON block at the end:
        {"units": 100, "entry": 150.25, "stop": 145.00, 
         "target": 160.00, "rr_ratio": 2.0, "max_loss_dollars": 525.00}
    """
}

def run_agent(agent_name: str, input_data: dict):
    """
    Run a single agent. Returns (full_thinking_text, parsed_json).
    Streams the thinking text in real time.
    """
    full_text = ""
    
    with client.messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=AGENTS[agent_name],
        messages=[{"role": "user", "content": json.dumps(input_data)}]
    ) as stream:
        for text in stream.text_stream:
            full_text += text
            yield text, None  # Stream thinking in real time
    
    # Parse JSON from the response
    try:
        json_start = full_text.rfind("{")
        json_end = full_text.rfind("}") + 1
        if json_start > -1 and json_end > json_start:
            parsed = json.loads(full_text[json_start:json_end])
        else:
            parsed = {}
    except:
        parsed = {}
    
    yield None, parsed  # Final yield with parsed data


def run_pipeline(asset: str, timeframe: str, portfolio: dict):
    """
    Generator that yields pipeline events for the dashboard to consume.
    Yields: {agent, type, content}
    type = "thinking" | "result" | "veto" | "complete"
    """
    
    # Agent 1 — Signals
    yield {"agent": "SIGNAL_AGENT", "type": "start"}
    signals_text = ""
    signals_data = {}
    for text, parsed in run_agent("SIGNAL_AGENT", 
                                   {"asset": asset, "timeframe": timeframe}):
        if text:
            signals_text += text
            yield {"agent": "SIGNAL_AGENT", "type": "thinking", "content": text}
        if parsed:
            signals_data = parsed
            yield {"agent": "SIGNAL_AGENT", "type": "result", "content": parsed}
    
    # Agent 2 — Consensus
    yield {"agent": "CONSENSUS_AGENT", "type": "start"}
    consensus_text = ""
    consensus_data = {}
    for text, parsed in run_agent("CONSENSUS_AGENT", 
                                   {"signals": signals_data}):
        if text:
            yield {"agent": "CONSENSUS_AGENT", "type": "thinking", "content": text}
        if parsed:
            consensus_data = parsed
            yield {"agent": "CONSENSUS_AGENT", "type": "result", "content": parsed}
    
    # Check agreement before continuing
    agreement = consensus_data.get("agreement_ratio", 0)
    if agreement < 0.50:
        yield {"agent": "CONSENSUS_AGENT", "type": "veto", 
               "content": f"CONFLICTED: Agreement ratio {agreement:.0%} too low"}
        return
    
    # Agent 3 — Risk
    yield {"agent": "RISK_AGENT", "type": "start"}
    risk_data = {}
    for text, parsed in run_agent("RISK_AGENT",
                                   {"consensus": consensus_data, 
                                    "portfolio": portfolio}):
        if text:
            yield {"agent": "RISK_AGENT", "type": "thinking", "content": text}
        if parsed:
            risk_data = parsed
            yield {"agent": "RISK_AGENT", "type": "result", "content": parsed}
    
    # Check veto before continuing
    if risk_data.get("veto"):
        yield {"agent": "RISK_AGENT", "type": "veto",
               "content": f"VETOED: {risk_data.get('vetoes', [])}"}
        return
    
    # Agent 4 — Sizing
    yield {"agent": "SIZING_AGENT", "type": "start"}
    sizing_data = {}
    for text, parsed in run_agent("SIZING_AGENT",
                                   {"consensus": consensus_data,
                                    "risk": risk_data,
                                    "portfolio": portfolio}):
        if text:
            yield {"agent": "SIZING_AGENT", "type": "thinking", "content": text}
        if parsed:
            sizing_data = parsed
            yield {"agent": "SIZING_AGENT", "type": "result", "content": parsed}
    
    yield {
        "agent": "ORCHESTRATOR",
        "type": "complete",
        "content": {
            "signals": signals_data,
            "consensus": consensus_data,
            "risk": risk_data,
            "sizing": sizing_data
        }
    }
