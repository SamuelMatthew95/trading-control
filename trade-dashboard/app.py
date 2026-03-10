import streamlit as st
import json
import time
from datetime import datetime
from orchestrator import run_pipeline
from state import load_trades, save_trade, Trade, get_win_rate, get_total_pnl, get_trade_statistics

# Page config
st.set_page_config(
    page_title="Trade Bot Brain",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
.agent-panel {
    border: 2px solid #ddd;
    border-radius: 10px;
    padding: 15px;
    margin: 10px;
    background: white;
}
.agent-thinking {
    border-color: #f39c12;
    background: #fff9e6;
    animation: pulse 1.5s infinite;
}
.agent-done {
    border-color: #27ae60;
    background: #e8f8f5;
}
.agent-vetoed {
    border-color: #e74c3c;
    background: #ffe6e6;
}
.pipeline-step {
    padding: 10px;
    margin: 5px;
    border-radius: 5px;
    text-align: center;
    font-weight: bold;
}
.pipeline-idle {
    background: #ecf0f1;
    color: #7f8c8d;
}
.pipeline-thinking {
    background: #f39c12;
    color: white;
}
.pipeline-done {
    background: #27ae60;
    color: white;
}
.pipeline-vetoed {
    background: #e74c3c;
    color: white;
}
.decision-long {
    background: #27ae60;
    color: white;
    padding: 10px;
    border-radius: 5px;
    text-align: center;
    font-size: 18px;
    font-weight: bold;
}
.decision-short {
    background: #e74c3c;
    color: white;
    padding: 10px;
    border-radius: 5px;
    text-align: center;
    font-size: 18px;
    font-weight: bold;
}
.decision-flat {
    background: #95a5a6;
    color: white;
    padding: 10px;
    border-radius: 5px;
    text-align: center;
    font-size: 18px;
    font-weight: bold;
}
.decision-veto {
    background: #c0392b;
    color: white;
    padding: 10px;
    border-radius: 5px;
    text-align: center;
    font-size: 18px;
    font-weight: bold;
}
.thinking-text {
    font-family: 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.4;
    max-height: 200px;
    overflow-y: auto;
    white-space: pre-wrap;
    background: #f8f9fa;
    padding: 10px;
    border-radius: 5px;
    margin: 10px 0;
}
@keyframes pulse {
    0% { opacity: 1; }
    50% { opacity: 0.7; }
    100% { opacity: 1; }
}
.metric-card {
    background: white;
    padding: 15px;
    border-radius: 10px;
    border: 1px solid #ddd;
    text-align: center;
}
.metric-value {
    font-size: 24px;
    font-weight: bold;
    color: #2c3e50;
}
.metric-label {
    font-size: 14px;
    color: #7f8c8d;
    margin-top: 5px;
}
.trade-row-win {
    background: #d5f4e6;
}
.trade-row-loss {
    background: #ffe6e6;
}
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'agent_states' not in st.session_state:
    st.session_state.agent_states = {
        'SIGNAL_AGENT': 'idle',
        'CONSENSUS_AGENT': 'idle', 
        'RISK_AGENT': 'idle',
        'SIZING_AGENT': 'idle'
    }
if 'agent_thinking' not in st.session_state:
    st.session_state.agent_thinking = {
        'SIGNAL_AGENT': '',
        'CONSENSUS_AGENT': '',
        'RISK_AGENT': '',
        'SIZING_AGENT': ''
    }
if 'agent_results' not in st.session_state:
    st.session_state.agent_results = {}
if 'final_decision' not in st.session_state:
    st.session_state.final_decision = None
if 'pipeline_complete' not in st.session_state:
    st.session_state.pipeline_complete = False

# SECTION 1 — Header + Controls
st.title("🧠 Trade Bot Brain")
st.markdown("---")

# Input controls
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    asset = st.text_input("Asset Ticker", value="AAPL", placeholder="e.g., AAPL")
with col2:
    timeframe = st.selectbox("Timeframe", ["1D", "4H", "1H", "15M"])
with col3:
    analyze_button = st.button("🔍 Analyze", type="primary")

# Sidebar portfolio inputs
st.sidebar.header("Portfolio State")
portfolio_value = st.sidebar.number_input("Total Value ($)", value=100000, min_value=0)
drawdown = st.sidebar.number_input("Current Drawdown (%)", value=0.0, min_value=-100.0, max_value=0.0, format="%.2f")

portfolio = {
    "total_value": portfolio_value,
    "drawdown": drawdown / 100.0,
    "cash": portfolio_value * (1 + drawdown / 100.0),  # Simplified
    "positions": {}
}

# SECTION 2 — Agent Brain (4 columns)
st.header("🤖 Agent Brain")
agent_cols = st.columns(4)

agents = [
    ("SIGNAL_AGENT", "📡 Signal Agent"),
    ("CONSENSUS_AGENT", "🤝 Consensus Agent"), 
    ("RISK_AGENT", "⚠️ Risk Agent"),
    ("SIZING_AGENT", "📏 Sizing Agent")
]

for i, (agent_id, agent_name) in enumerate(agents):
    with agent_cols[i]:
        # Determine panel class
        state = st.session_state.agent_states[agent_id]
        panel_class = "agent-panel"
        if state == "thinking":
            panel_class += " agent-thinking"
        elif state == "done":
            panel_class += " agent-done"
        elif state == "vetoed":
            panel_class += " agent-vetoed"
        
        # Status indicator
        status_icon = {
            'idle': '⚪',
            'thinking': '🟡',
            'done': '🟢', 
            'vetoed': '🔴'
        }.get(state, '⚪')
        
        st.markdown(f"""
        <div class="{panel_class}">
            <h4>{status_icon} {agent_name}</h4>
            <p><small>Status: {state.upper()}</small></p>
        </div>
        """, unsafe_allow_html=True)
        
        # Show thinking text
        if st.session_state.agent_thinking[agent_id]:
            with st.expander("🧠 Thinking Process", expanded=True):
                st.markdown(f'<div class="thinking-text">{st.session_state.agent_thinking[agent_id]}</div>', 
                           unsafe_allow_html=True)
        
        # Show results
        if agent_id in st.session_state.agent_results:
            with st.expander("📊 Result", expanded=False):
                st.json(st.session_state.agent_results[agent_id])

# SECTION 3 — Pipeline Flow Visualization
st.header("🔄 Pipeline Flow")
pipeline_cols = st.columns(4)

pipeline_steps = [
    ("SIGNAL_AGENT", "Signal", "signals_count", "direction"),
    ("CONSENSUS_AGENT", "Consensus", "agreement_ratio", "agreement_ratio"),
    ("RISK_AGENT", "Risk", "risk_score", "risk_score"),
    ("SIZING_AGENT", "Sizing", "units", "rr_ratio")
]

for i, (agent_id, step_name, metric_key, display_key) in enumerate(pipeline_steps):
    with pipeline_cols[i]:
        state = st.session_state.agent_states[agent_id]
        
        # Determine step class
        step_class = "pipeline-step"
        if state == "thinking":
            step_class += " pipeline-thinking"
        elif state == "done":
            step_class += " pipeline-done"
        elif state == "vetoed":
            step_class += " pipeline-vetoed"
        else:
            step_class += " pipeline-idle"
        
        # Get metric value
        metric_value = "..."
        if agent_id in st.session_state.agent_results:
            result = st.session_state.agent_results[agent_id]
            if metric_key in result:
                if metric_key == "agreement_ratio":
                    metric_value = f"{result[metric_key]:.0%}"
                elif metric_key == "risk_score":
                    metric_value = f"{result[metric_key]:.1f}"
                elif metric_key == "units":
                    metric_value = str(result[metric_key])
                elif metric_key == "rr_ratio":
                    metric_value = f"{result[metric_key]:.1f}:1"
                elif metric_key == "direction":
                    metric_value = result[metric_key]
                else:
                    metric_value = str(result[metric_key])
        
        st.markdown(f"""
        <div class="{step_class}">
            <div>{step_name}</div>
            <div style="font-size: 18px; margin-top: 5px;">{metric_value}</div>
        </div>
        """, unsafe_allow_html=True)

# SECTION 4 — Final Decision Card
if st.session_state.final_decision:
    st.header("🎯 Final Decision")
    
    decision = st.session_state.final_decision
    
    # Determine decision class
    decision_type = decision.get("DECISION", "FLAT")
    decision_class = f"decision-{decision_type.lower()}"
    
    st.markdown(f"""
    <div class="{decision_class}">
        DECISION: {decision_type}
    </div>
    """, unsafe_allow_html=True)
    
    # Decision details
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Asset", decision.get("ASSET", ""))
    with col2:
        st.metric("Size", decision.get("SIZE", ""))
    with col3:
        st.metric("Entry", decision.get("ENTRY", ""))
    with col4:
        st.metric("Stop", decision.get("STOP", ""))
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Target", decision.get("TARGET", ""))
    with col2:
        st.metric("R/R Ratio", decision.get("R/R RATIO", ""))
    
    # Confidence and rationale
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Confidence", decision.get("CONFIDENCE", ""))
    with col2:
        st.metric("Invalidation", decision.get("INVALIDATION", ""))
    
    if "RATIONALE" in decision:
        st.subheader("💭 Rationale")
        st.write(decision["RATIONALE"])

# SECTION 5 — Portfolio State
st.header("💼 Portfolio State")
portfolio_cols = st.columns(4)

with portfolio_cols[0]:
    st.metric("Total Value", f"${portfolio_value:,.0f}")
with portfolio_cols[1]:
    # Drawdown meter
    drawdown_color = "normal" if drawdown > -5 else "inverse"
    st.metric("Drawdown", f"{drawdown:.1f}%", delta=None, delta_color=drawdown_color)
with portfolio_cols[2]:
    # Open positions (simplified)
    trades = load_trades()
    open_positions = len([t for t in trades if t["outcome"] == "OPEN"])
    st.metric("Open Positions", open_positions)
with portfolio_cols[3]:
    # Today's P&L (simplified)
    total_pnl = get_total_pnl(trades)
    pnl_color = "normal" if total_pnl >= 0 else "inverse"
    st.metric("Today's P&L", f"${total_pnl:,.0f}", delta_color=pnl_color)

# SECTION 6 — Trade Log
st.header("📋 Trade Log")

trades = load_trades()
if trades:
    # Win rate
    win_rate = get_win_rate(trades)
    st.metric("Win Rate", f"{win_rate:.1%}")
    
    # Trade table
    for i, trade in enumerate(trades):
        row_class = "trade-row-win" if trade.get("pnl", 0) > 0 else "trade-row-loss" if trade.get("pnl", 0) < 0 else ""
        
        col1, col2, col3, col4, col5, col6, col7, col8 = st.columns([1, 1, 1, 1, 1, 1, 1, 1])
        
        with col1:
            st.write(trade["date"])
        with col2:
            st.write(trade["asset"])
        with col3:
            st.write(trade["direction"])
        with col4:
            st.write(trade["size"])
        with col5:
            st.write(f"${trade['entry']:.2f}")
        with col6:
            exit_price = trade.get("exit", "OPEN")
            st.write(exit_price)
        with col7:
            pnl = trade.get("pnl", 0)
            st.write(f"${pnl:.0f}" if pnl != 0 else "OPEN")
        with col8:
            rr = trade.get("rr_ratio", 0)
            st.write(f"{rr:.1f}:1" if rr > 0 else "N/A")
else:
    st.info("No trades yet. Run an analysis to see trades here.")

# Export button
if trades:
    if st.button("📥 Export to CSV"):
        # Convert trades to CSV format
        csv_data = "Date,Asset,Direction,Size,Entry,Exit,P&L,R/R,Outcome\n"
        for trade in trades:
            csv_data += f"{trade['date']},{trade['asset']},{trade['direction']},{trade['size']},{trade['entry']},{trade.get('exit', 'OPEN')},{trade.get('pnl', 0)},{trade.get('rr_ratio', 0)},{trade['outcome']}\n"
        
        st.download_button(
            label="Download CSV",
            data=csv_data,
            file_name="trade_log.csv",
            mime="text/csv"
        )

# Main analysis logic
if analyze_button and asset:
    # Reset states
    for agent_id in st.session_state.agent_states:
        st.session_state.agent_states[agent_id] = 'idle'
        st.session_state.agent_thinking[agent_id] = ''
    
    st.session_state.agent_results = {}
    st.session_state.final_decision = None
    st.session_state.pipeline_complete = False
    
    # Create placeholders for real-time updates
    status_placeholder = st.empty()
    
    # Run pipeline with streaming
    try:
        for event in run_pipeline(asset, timeframe, portfolio):
            agent_id = event["agent"]
            event_type = event["type"]
            
            # Update agent states
            if event_type == "start":
                st.session_state.agent_states[agent_id] = 'thinking'
                st.session_state.agent_thinking[agent_id] = ''
            elif event_type == "thinking":
                st.session_state.agent_thinking[agent_id] += event["content"]
            elif event_type == "result":
                st.session_state.agent_states[agent_id] = 'done'
                st.session_state.agent_results[agent_id] = event["content"]
            elif event_type == "veto":
                st.session_state.agent_states[agent_id] = 'vetoed'
                st.session_state.final_decision = {
                    "DECISION": "VETO",
                    "ASSET": asset,
                    "REASON": event["content"]
                }
                st.session_state.pipeline_complete = True
                break
            elif event_type == "complete":
                # Format final decision
                content = event["content"]
                sizing = content["sizing"]
                consensus = content["consensus"]
                
                final_decision = {
                    "DECISION": consensus.get("direction", "FLAT"),
                    "ASSET": asset,
                    "SIZE": f"{sizing.get('units', 0)} units",
                    "ENTRY": f"${sizing.get('entry', 0):.2f}",
                    "STOP": f"${sizing.get('stop', 0):.2f}",
                    "TARGET": f"${sizing.get('target', 0):.2f}",
                    "R/R RATIO": f"{sizing.get('rr_ratio', 0):.1f}:1",
                    "CONFIDENCE": "HIGH" if consensus.get("signal_strength", 0) > 0.8 else "MEDIUM" if consensus.get("signal_strength", 0) > 0.6 else "LOW",
                    "RATIONALE": f"Strong {consensus.get('direction', 'FLAT')} consensus with {consensus.get('agreement_ratio', 0):.0%} agreement.",
                    "INVALIDATION": f"Price below ${sizing.get('stop', 0):.2f} or above ${sizing.get('target', 0):.2f}"
                }
                
                st.session_state.final_decision = final_decision
                st.session_state.pipeline_complete = True
                
                # Save trade to log
                if consensus.get("direction") in ["LONG", "SHORT"]:
                    trade = Trade(
                        date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        asset=asset,
                        direction=consensus.get("direction"),
                        size=sizing.get('units', 0),
                        entry=sizing.get('entry', 0),
                        stop=sizing.get('stop', 0),
                        target=sizing.get('target', 0),
                        rr_ratio=sizing.get('rr_ratio', 0)
                    )
                    save_trade(trade)
                
                break
            
            # Rerun to update UI
            st.rerun()
    
    except Exception as e:
        st.error(f"Error running analysis: {e}")
        st.exception(e)

# Auto-refresh for real-time updates
if st.session_state.pipeline_complete:
    time.sleep(1)
    st.rerun()
