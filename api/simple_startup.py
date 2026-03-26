#!/usr/bin/env python3
"""
Simple V3 Startup - Easy to understand event flow

This shows exactly how events flow through the system.
"""

import asyncio
import json
from api.v3_production_system import V3ProductionSystem


async def show_event_flow():
    """Show exactly how events flow through the system."""
    print("=" * 80)
    print("🔄 V3 EVENT FLOW EXPLANATION")
    print("=" * 80)
    
    print("\n1️⃣  MARKET TICK (Input Event)")
    print("   ↓")
    print("   redis-cli XADD market_ticks '{")
    print("     \"schema_version\":\"v3\",")
    print("     \"msg_id\":\"tick-001\",")
    print("     \"trace_id\":\"trace-001\",")
    print("     \"symbol\":\"AAPL\",")
    print("     \"price\":150.25,")
    print("     \"source\":\"market\"")
    print("   }'")
    
    print("\n2️⃣  SIGNAL GENERATOR (Agent 1)")
    print("   ↓ Consumes from: market_ticks")
    print("   ↓ Processes: price > 100 ? 'buy' : 'sell'")
    print("   ↓ Publishes to: signals")
    print("   ↓ Writes to: vector_memory")
    
    print("\n3️⃣  REASONING AGENT (Agent 2)")
    print("   ↓ Consumes from: signals")
    print("   ↓ Processes: creates order from signal")
    print("   ↓ Publishes to: orders")
    print("   ↓ Writes to: orders, agent_logs, vector_memory")
    
    print("\n4️⃣  EXECUTION AGENT (Agent 3)")
    print("   ↓ Consumes from: orders")
    print("   ↓ Processes: simulates order fill")
    print("   ↓ Publishes to: executions")
    print("   ↓ Writes to: executions, events")
    
    print("\n5️⃣  TRADE PERFORMANCE (Agent 4)")
    print("   ↓ Consumes from: executions")
    print("   ↓ Processes: calculates PnL and metrics")
    print("   ↓ Publishes to: trade_performance")
    print("   ↓ Writes to: trade_performance")
    
    print("\n6️⃣  GRADE AGENT (Agent 5)")
    print("   ↓ Consumes from: trade_performance")
    print("   ↓ Processes: grades agent performance")
    print("   ↓ Publishes to: agent_grades")
    print("   ↓ Writes to: agent_grades")
    
    print("\n7️⃣  REFLECTION AGENT (Agent 6)")
    print("   ↓ Consumes from: trade_performance")
    print("   ↓ Processes: generates insights")
    print("   ↓ Publishes to: reflections")
    print("   ↓ Writes to: reflection_outputs, vector_memory")
    
    print("\n8️⃣  STRATEGY PROPOSER (Agent 7)")
    print("   ↓ Consumes from: reflections")
    print("   ↓ Processes: proposes strategy changes")
    print("   ↓ Publishes to: proposals")
    print("   ↓ Writes to: strategy_proposals")
    
    print("\n9️⃣  HISTORY AGENT (Agent 8)")
    print("   ↓ Consumes from: trade_performance")
    print("   ↓ Processes: analyzes historical patterns")
    print("   ↓ Publishes to: historical_insights")
    print("   ↓ Writes to: vector_memory")
    
    print("\n🔔 NOTIFICATION AGENT (Agent 9)")
    print("   ↓ Consumes from: ALL streams")
    print("   ↓ Processes: creates notifications")
    print("   ↓ Publishes to: notifications")
    print("   ↓ Writes to: notifications")
    print("   ↓ Sends: WebSocket updates")
    
    print("\n" + "=" * 80)
    print("🎯 RESULT: One market tick → 9 agents → 10+ database writes")
    print("🎯 RESULT: Full traceability with trace_id through entire pipeline")
    print("🎯 RESULT: Dashboard updates in real-time via WebSocket")
    print("=" * 80)


async def simple_startup():
    """Simple startup that shows the event flow clearly."""
    print("🚀 SIMPLE V3 STARTUP")
    
    # Show how events flow
    await show_event_flow()
    
    # Start the system
    print("\n🎬 Starting V3 System...")
    system = V3ProductionSystem()
    
    try:
        await system.start()
        
        print("\n✅ SYSTEM IS LIVE!")
        print("\n📤 SEND EVENTS TO SEE THE FLOW:")
        print("# Market tick (will flow through ALL agents):")
        print('redis-cli XADD market_ticks \'{"schema_version":"v3","msg_id":"test-001","trace_id":"trace-001","symbol":"AAPL","price":150.25,"source":"test"}\'')
        print("\n# V2 event (will go to DLQ):")
        print('redis-cli XADD market_ticks \'{"schema_version":"v2","msg_id":"v2-001","symbol":"GOOGL","price":2500.50,"source":"old"}\'')
        print("\n# Event without trace_id (will go to DLQ):")
        print('redis-cli XADD market_ticks \'{"schema_version":"v3","msg_id":"no-trace-001","symbol":"MSFT","price":300.75,"source":"test"}\'')
        
        print("\n⏳ Waiting for events... (Ctrl+C to stop)")
        await system.shutdown_event.wait()
        
    finally:
        await system.stop()


if __name__ == "__main__":
    asyncio.run(simple_startup())
