import { useState, useEffect } from 'react';
import { Brain, TrendingUp, AlertTriangle, Activity, BarChart3, Database, Target, Shield } from 'lucide-react';
import axios from 'axios';
import TopNav from '@/components/layout/TopNav';

interface AgentStatus {
  name: string;
  status: 'idle' | 'thinking' | 'complete' | 'error';
  lastUpdate: string;
}

interface AgentPerformance {
  agent_name: string;
  total_calls: number;
  successful_calls: number;
  avg_response_time: number;
  accuracy_score: number;
  improvement_areas: string[];
}

interface TradeDecision {
  symbol: string;
  decision: string;
  confidence: number;
  reasoning: string;
  timestamp: string;
  position_size?: number;
  risk_assessment?: any;
}

interface Trade {
  id: number;
  date: string;
  asset: string;
  direction: string;
  size: number;
  entry: number;
  stop: number;
  target: number;
  rr_ratio: number;
  exit_price?: number;
  pnl?: number;
  outcome: string;
}

interface TradingStats {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
}

export default function TradingDashboard() {
  const [agents, setAgents] = useState<AgentStatus[]>([
    { name: 'SIGNAL_AGENT', status: 'idle', lastUpdate: '' },
    { name: 'RISK_AGENT', status: 'idle', lastUpdate: '' },
    { name: 'CONSENSUS_AGENT', status: 'idle', lastUpdate: '' },
    { name: 'SIZING_AGENT', status: 'idle', lastUpdate: '' },
  ]);
  
  const [currentDecision, setCurrentDecision] = useState<TradeDecision | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [performance, setPerformance] = useState<Record<string, AgentPerformance>>({});
  const [stats, setStats] = useState<TradingStats | null>(null);
  const [symbol, setSymbol] = useState('AAPL');
  const [price, setPrice] = useState('150.00');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [activeTab, setActiveTab] = useState<'dashboard' | 'trades' | 'performance' | 'learning'>('dashboard');

  // Load data on component mount
  useEffect(() => {
    loadTrades();
    loadPerformance();
    loadStats();
  }, []);

  const loadTrades = async () => {
    try {
      const response = await axios.get('/api/trades');
      setTrades(response.data.trades || []);
    } catch (error) {
      console.error('Failed to load trades:', error);
    }
  };

  const loadPerformance = async () => {
    try {
      const response = await axios.get('/api/performance');
      setPerformance(response.data);
    } catch (error) {
      console.error('Failed to load performance:', error);
    }
  };

  const loadStats = async () => {
    try {
      const response = await axios.get('/api/statistics');
      setStats(response.data);
    } catch (error) {
      console.error('Failed to load stats:', error);
    }
  };

  const analyzeTrade = async (stream = false) => {
    setIsAnalyzing(true);
    
    try {
      if (stream) {
        const response = await fetch('/api/analyze-stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol, price: parseFloat(price) })
        });

        const reader = response.body?.getReader();
        const decoder = new TextDecoder();

        if (reader) {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');
            
            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  const data = JSON.parse(line.slice(6));
                  
                  if (data.type === 'agent') {
                    setAgents((prev: AgentStatus[]) => prev.map((agent: AgentStatus) => 
                      agent.name === data.name 
                        ? { ...agent, status: data.status, lastUpdate: new Date().toISOString() }
                        : agent
                    ));
                  } else if (data.type === 'result') {
                    setCurrentDecision({
                      symbol,
                      decision: data.decision,
                      confidence: data.confidence,
                      reasoning: data.reasoning,
                      timestamp: new Date().toISOString()
                    });
                  }
                } catch (e) {
                  console.error('Error parsing stream data:', e);
                }
              }
            }
          }
        }
      } else {
        const response = await axios.post('/api/analyze', {
          symbol,
          price: parseFloat(price)
        });
        
        setCurrentDecision(response.data);
        setAgents((prev: AgentStatus[]) => prev.map((agent: AgentStatus) => ({
          ...agent,
          status: 'complete' as const,
          lastUpdate: new Date().toISOString()
        })));
      }
      
      // Reload performance data after analysis
      loadPerformance();
    } catch (error) {
      console.error('Analysis failed:', error);
      setAgents((prev: AgentStatus[]) => prev.map((agent: AgentStatus) => ({
        ...agent,
        status: 'error' as const,
        lastUpdate: new Date().toISOString()
      })));
    } finally {
      setIsAnalyzing(false);
    }
  };

  const getStatusIcon = (status: AgentStatus['status']) => {
    switch (status) {
      case 'thinking': return <Activity className="w-4 h-4 text-yellow-500 animate-pulse" />;
      case 'complete': return <TrendingUp className="w-4 h-4 text-green-500" />;
      case 'error': return <AlertTriangle className="w-4 h-4 text-red-500" />;
      default: return <Brain className="w-4 h-4 text-gray-400" />;
    }
  };

  const getDecisionColor = (decision: string) => {
    switch (decision.toUpperCase()) {
      case 'LONG': return 'text-green-600 bg-green-100';
      case 'SHORT': return 'text-red-600 bg-red-100';
      default: return 'text-gray-600 bg-gray-100';
    }
  };

  const renderDashboard = () => (
    <div className="space-y-6">
      {/* Control Panel */}
      <div className="bg-white rounded-lg shadow-sm p-6">
        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
          <Brain className="w-5 h-5 text-blue-600" />
          Trade Analysis
        </h2>
        <div className="flex gap-4 items-end">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Symbol</label>
            <input
              type="text"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="AAPL"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Price</label>
            <input
              type="number"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="150.00"
              step="0.01"
            />
          </div>
          <button
            onClick={() => analyzeTrade(false)}
            disabled={isAnalyzing}
            className="px-6 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isAnalyzing ? 'Analyzing...' : 'Analyze Trade'}
          </button>
          <button
            onClick={() => analyzeTrade(true)}
            disabled={isAnalyzing}
            className="px-6 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isAnalyzing ? 'Streaming...' : 'Stream Analysis'}
          </button>
        </div>
      </div>

      {/* Agent Status */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {agents.map((agent) => (
          <div key={agent.name} className="bg-white rounded-lg shadow-sm p-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold text-gray-900">{agent.name.replace('_', ' ')}</h3>
              {getStatusIcon(agent.status)}
            </div>
            <div className="text-sm text-gray-600">
              Status: <span className={`font-medium ${
                agent.status === 'thinking' ? 'text-yellow-600' :
                agent.status === 'complete' ? 'text-green-600' :
                agent.status === 'error' ? 'text-red-600' :
                'text-gray-500'
              }`}>{agent.status.toUpperCase()}</span>
            </div>
            {agent.lastUpdate && (
              <div className="text-xs text-gray-500 mt-2">
                Last: {new Date(agent.lastUpdate).toLocaleTimeString()}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Results */}
      {currentDecision && (
        <div className="bg-white rounded-lg shadow-sm p-6">
          <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
            <Target className="w-5 h-5 text-blue-600" />
            Analysis Result
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <div className="flex items-center gap-3 mb-3">
                <span className="text-sm font-medium text-gray-700">Decision:</span>
                <span className={`px-3 py-1 rounded-full text-sm font-medium ${getDecisionColor(currentDecision.decision)}`}>
                  {currentDecision.decision.toUpperCase()}
                </span>
              </div>
              <div className="flex items-center gap-3 mb-3">
                <span className="text-sm font-medium text-gray-700">Confidence:</span>
                <div className="flex-1 bg-gray-200 rounded-full h-2">
                  <div 
                    className="bg-blue-600 h-2 rounded-full" 
                    style={{ width: `${currentDecision.confidence * 100}%` }}
                  />
                </div>
                <span className="text-sm text-gray-600">{(currentDecision.confidence * 100).toFixed(1)}%</span>
              </div>
              {currentDecision.position_size && (
                <div className="text-sm text-gray-700 mb-3">
                  Position Size: <span className="font-medium">{(currentDecision.position_size * 100).toFixed(2)}%</span>
                </div>
              )}
            </div>
            <div>
              <div className="text-sm font-medium text-gray-700 mb-2">Reasoning:</div>
              <p className="text-sm text-gray-600 bg-gray-50 p-3 rounded-md">
                {currentDecision.reasoning}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  const renderTrades = () => (
    <div className="bg-white rounded-lg shadow-sm p-6">
      <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
        <Database className="w-5 h-5 text-blue-600" />
        Trade History
      </h2>
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="text-center">
            <div className="text-2xl font-bold text-gray-900">{stats.total_trades}</div>
            <div className="text-sm text-gray-600">Total Trades</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-green-600">{stats.win_rate}%</div>
            <div className="text-sm text-gray-600">Win Rate</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-gray-900">{stats.wins}/{stats.losses}</div>
            <div className="text-sm text-gray-600">Wins/Losses</div>
          </div>
          <div className="text-center">
            <div className={`text-2xl font-bold ${stats.total_pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
              ${stats.total_pnl.toFixed(2)}
            </div>
            <div className="text-sm text-gray-600">Total P&L</div>
          </div>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Date</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Asset</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Direction</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Entry</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Stop</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Target</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">R:R</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">P&L</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Outcome</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {trades.map((trade) => (
              <tr key={trade.id}>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{trade.date}</td>
                <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{trade.asset}</td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <span className={`px-2 py-1 text-xs rounded-full ${
                    trade.direction === 'LONG' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                  }`}>
                    {trade.direction}
                  </span>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${trade.entry}</td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${trade.stop}</td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${trade.target}</td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{trade.rr_ratio}</td>
                <td className="px-6 py-4 whitespace-nowrap text-sm">
                  {trade.pnl ? (
                    <span className={trade.pnl >= 0 ? 'text-green-600' : 'text-red-600'}>
                      ${trade.pnl.toFixed(2)}
                    </span>
                  ) : '-'}
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <span className={`px-2 py-1 text-xs rounded-full ${
                    trade.outcome === 'WIN' ? 'bg-green-100 text-green-800' :
                    trade.outcome === 'LOSS' ? 'bg-red-100 text-red-800' :
                    'bg-gray-100 text-gray-800'
                  }`}>
                    {trade.outcome}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );

  const renderPerformance = () => (
    <div className="space-y-6">
      <div className="bg-white rounded-lg shadow-sm p-6">
        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-blue-600" />
          Agent Performance
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {Object.entries(performance).map(([agentName, perf]) => (
            <div key={agentName} className="border border-gray-200 rounded-lg p-4">
              <h3 className="font-semibold text-gray-900 mb-3">{agentName.replace('_', ' ')}</h3>
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">Total Calls:</span>
                  <span className="font-medium">{perf.total_calls}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">Success Rate:</span>
                  <span className="font-medium">
                    {perf.total_calls > 0 ? ((perf.successful_calls / perf.total_calls) * 100).toFixed(1) : 0}%
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">Avg Response Time:</span>
                  <span className="font-medium">{perf.avg_response_time.toFixed(2)}s</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">Accuracy Score:</span>
                  <span className="font-medium">{(perf.accuracy_score * 100).toFixed(1)}%</span>
                </div>
                {perf.improvement_areas.length > 0 && (
                  <div className="mt-3">
                    <div className="text-sm font-medium text-gray-700 mb-1">Improvement Areas:</div>
                    <div className="flex flex-wrap gap-1">
                      {perf.improvement_areas.map((area, idx) => (
                        <span key={idx} className="px-2 py-1 bg-yellow-100 text-yellow-800 text-xs rounded">
                          {area}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );

  const renderLearning = () => (
    <div className="bg-white rounded-lg shadow-sm p-6">
      <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
        <Shield className="w-5 h-5 text-blue-600" />
        Learning System
      </h2>
      <div className="text-center py-8">
        <Brain className="w-16 h-16 text-gray-400 mx-auto mb-4" />
        <p className="text-gray-600">Advanced learning analytics and agent improvement tracking coming soon...</p>
        <p className="text-sm text-gray-500 mt-2">The system continuously learns from each trade to improve agent performance.</p>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="bg-white rounded-lg shadow-sm p-6 mb-6">
          <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
            <Brain className="w-8 h-8 text-blue-600" />
            Trading Bot Brain
          </h1>
          <p className="text-gray-600 mt-2">AI-powered multi-agent trading system with learning capabilities</p>
        </div>

        {/* Top-level navigation keeps Stocks/Options route parity */}
        <TopNav />

        {/* Navigation Tabs */}
        <div className="bg-white rounded-lg shadow-sm mb-6">
          <nav className="flex space-x-8 px-6" aria-label="Tabs">
            {[
              { id: 'dashboard', name: 'Dashboard', icon: Brain },
              { id: 'trades', name: 'Trade History', icon: Database },
              { id: 'performance', name: 'Performance', icon: BarChart3 },
              { id: 'learning', name: 'Learning', icon: Shield }
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`py-4 px-1 border-b-2 font-medium text-sm whitespace-nowrap ${
                  activeTab === tab.id
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                <div className="flex items-center gap-2">
                  <tab.icon className="w-4 h-4" />
                  {tab.name}
                </div>
              </button>
            ))}
          </nav>
        </div>

        {/* Tab Content */}
        {activeTab === 'dashboard' && renderDashboard()}
        {activeTab === 'trades' && renderTrades()}
        {activeTab === 'performance' && renderPerformance()}
        {activeTab === 'learning' && renderLearning()}
      </div>
    </div>
  );
}
