# 🚀 TRADE BOT DASHBOARD - COMPLETE SETUP GUIDE

## 📁 What You Have Now

```
trading-control-python/
├── trade-dashboard/           ← NEW REAL-TIME DASHBOARD
│   ├── app.py                ← Main Streamlit app
│   ├── orchestrator.py       ← Claude API pipeline
│   ├── state.py              ← Trade log & portfolio state
│   ├── assets/
│   │   └── trade-log.json    ← Trade history
│   └── README.md             ← Documentation
├── multi_agent_orchestrator.py  ← Core system
├── test_multi_agent.py       ← Tests
├── demo_trade_bot.py         ← Demo examples
└── [other project files...]
```

## ⚡ HOW TO RUN - STEP BY STEP

### Step 1: Install Dependencies
```bash
# Make sure you're in the main project folder
cd /Users/matthew/Desktop/trading-control-python

# Install required packages
pip install streamlit anthropic
```

### Step 2: Set Up API Key
```bash
# Create the secrets folder
mkdir -p .streamlit

# Create the secrets file
cat > .streamlit/secrets.toml << EOF
ANTHROPIC_API_KEY = "your-anthropic-api-key-here"
EOF
```

**IMPORTANT**: Replace `"your-anthropic-api-key-here"` with your actual Anthropic API key.

### Step 3: Run the Dashboard
```bash
# Navigate to the dashboard folder
cd trade-dashboard

# Start the dashboard
streamlit run app.py
```

## 🎯 WHAT YOU'LL SEE

### 1. **Browser Opens Automatically**
- Go to: `http://localhost:8501`
- You'll see the "Trade Bot Brain" dashboard

### 2. **Dashboard Layout**
```
🧠 Trade Bot Brain
├── Controls: Asset | Timeframe | Analyze Button
├── Sidebar: Portfolio Value | Drawdown
├── 🤖 Agent Brain (4 Columns)
│   ├── 📡 Signal Agent
│   ├── 🤝 Consensus Agent  
│   ├── ⚠️ Risk Agent
│   └── 📏 Sizing Agent
├── 🔄 Pipeline Flow (SIGNAL → CONSENSUS → RISK → SIZING)
├── 🎯 Final Decision Card
├── 💼 Portfolio State
└── 📋 Trade Log
```

### 3. **Real-time Action**
When you click "Analyze":
- **Agents start thinking** - You'll see their text appear in real-time
- **Pipeline lights up** - Each step turns green as it completes
- **Final decision appears** - Complete trade recommendation
- **Trade gets saved** - Added to the trade log

## 🔥 LIVE DEMO - WHAT HAPPENS

### Input Example:
- **Asset**: AAPL
- **Timeframe**: 1D
- **Portfolio**: $100,000, -2% drawdown

### What You See:
1. **Signal Agent** starts thinking (yellow pulse)
2. **Text streams**: "I'm analyzing AAPL signals..."
3. **Signal Agent** turns green (done)
4. **Consensus Agent** starts thinking
5. **All 4 agents** complete in sequence
6. **Pipeline** turns all green
7. **Final Decision Card** appears:
   ```
   🟢 DECISION: LONG
   Asset: AAPL
   Size: 150 units (1.5%)
   Entry: $150.25
   Stop: $145.00
   Target: $160.00
   R/R Ratio: 2.0:1
   Confidence: HIGH
   ```

## 🎮 INTERACTIVE FEATURES

### Agent Panels (4 Columns)
- **Status Indicators**: ⚪ Idle → 🟡 Thinking → 🟢 Done / 🔴 Vetoed
- **Thinking Process**: Expand to see Claude's real-time thinking
- **JSON Results**: Expand to see parsed data

### Pipeline Flow
- **Visual Steps**: SIGNAL → CONSENSUS → RISK → SIZING
- **Key Metrics**: Signal count, agreement %, risk score, position size
- **Color Coding**: Green = complete, Red = vetoed

### Trade Log
- **Complete History**: All trades with dates and details
- **Win Rate**: Automatic calculation
- **Color Coding**: Green rows = wins, Red = losses
- **Export**: Download as CSV

## 🛠️ TROUBLESHOOTING

### If Dashboard Won't Start:
```bash
# Check Python version (needs 3.8+)
python --version

# Reinstall packages
pip install --upgrade streamlit anthropic

# Check API key
echo $ANTHROPIC_API_KEY
```

### If API Key Error:
```bash
# Edit secrets file
nano .streamlit/secrets.toml

# Make sure it looks like this:
ANTHROPIC_API_KEY = "sk-ant-api03-..."
```

### If Port Already in Use:
```bash
# Run on different port
streamlit run app.py --server.port 8502
```

## 📱 MOBILE & TABLET

The dashboard works on:
- ✅ **Desktop browsers** (Chrome, Firefox, Safari)
- ✅ **Tablets** (iPad, Android tablets)
- ✅ **Mobile phones** (responsive design)

## 🎯 QUICK TEST

1. **Run the dashboard**: `streamlit run app.py`
2. **Enter**: Asset = "AAPL", Timeframe = "1D"
3. **Set Portfolio**: $50,000, -1% drawdown
4. **Click "🔍 Analyze"**
5. **Watch** the agents think in real-time
6. **See** the final decision appear

## 🚀 NEXT STEPS

1. **Get your Anthropic API key** from https://console.anthropic.com
2. **Set up the secrets file** as shown above
3. **Run the dashboard** and watch it work
4. **Try different assets** (AAPL, MSFT, GOOGL, TSLA)
5. **Check the trade log** for history
6. **Export trades** as CSV for analysis

**The dashboard is now ready to run and you'll see Claude's multi-agent trading brain working in real-time!** 🎉
