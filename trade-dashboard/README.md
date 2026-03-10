# Trade Bot Dashboard

## Real-time Claude Multi-Agent Trading Dashboard

## Setup

### 1. Install Dependencies
```bash
pip install streamlit anthropic
```

### 2. Set API Key
Create `.streamlit/secrets.toml`:
```toml
ANTHROPIC_API_KEY = "your-anthropic-api-key"
```

### 3. Run Dashboard
```bash
cd trade-dashboard
streamlit run app.py
```

## Features

### Real-time Agent Brain
- **4 Agent Panels** showing live thinking process
- **Status Indicators**: Idle (grey) → Thinking (yellow) → Done (green) / Vetoed (red)
- **Streaming Text**: See Claude think in real-time as tokens arrive
- **JSON Results**: Expandable parsed results from each agent

### Pipeline Flow Visualization
- **SIGNAL → CONSENSUS → RISK → SIZING** pipeline
- **Real-time updates** as each agent completes
- **Key metrics** displayed for each step
- **Color-coded status** (green for complete, red for veto)

### Final Decision Card
- **Large decision badge** (LONG=green, SHORT=red, FLAT=grey)
- **Complete trade details**: Size, Entry, Stop, Target, R/R Ratio
- **Confidence level** and rationale
- **Invalidation condition**

### Portfolio State
- **Current metrics**: Value, drawdown, open positions, P&L
- **Drawdown meter** with color coding
- **Real-time updates** from trade log

### Trade Log
- **Complete history** of all trades
- **Win rate calculation**
- **Color-coded rows** (green=win, red=loss)
- **CSV export** functionality

## Architecture

### Agent Pipeline
1. **SIGNAL_AGENT** - Collect and normalize trade signals
2. **CONSENSUS_AGENT** - Build consensus (60% threshold)
3. **RISK_AGENT** - Risk management (can veto)
4. **SIZING_AGENT** - Kelly criterion position sizing

### Real-time Streaming
- **No waiting** for full responses
- **Token-by-token** updates
- **Immediate UI refresh** as thinking arrives
- **Pipeline stops** on veto or low consensus

### State Management
- **Session state** for agent status
- **File persistence** for trade log
- **Portfolio tracking** across sessions

## Usage

1. **Enter Asset** ticker (e.g., AAPL)
2. **Select Timeframe** (1D, 4H, 1H, 15M)
3. **Set Portfolio** value and drawdown
4. **Click Analyze** to start pipeline
5. **Watch agents think** in real-time
6. **Review final decision** and trade details

## File Structure
```
trade-dashboard/
├── app.py                    # Main Streamlit dashboard
├── orchestrator.py           # Claude API pipeline
├── state.py                  # Portfolio + trade log state
└── assets/
    └── trade-log.json        # Persisted trade history
```

## Key Features

- ✅ **Real-time streaming** of Claude thinking
- ✅ **4-agent pipeline** with proper veto logic
- ✅ **Visual pipeline flow** with status indicators
- ✅ **Complete trade logging** with CSV export
- ✅ **Portfolio state** tracking
- ✅ **Responsive design** for all screen sizes
- ✅ **Error handling** and graceful degradation

## Production Ready

- **No hardcoded API keys** (uses st.secrets)
- **Proper error handling** for API failures
- **State persistence** across sessions
- **Export functionality** for trade data
- **Clean separation** of concerns

**Ready for real-time trading with Claude multi-agent coordination!** 🚀
