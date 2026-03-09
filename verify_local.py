#!/usr/bin/env python3

print("=== COMPREHENSIVE LOCAL VERIFICATION ===")

# Test1: Check orchestrator
try:
    from orchestrator import OpenClawOrchestrator

    orch = OpenClawOrchestrator()
    required_attrs = ["current_cycle_id", "get_queue_status", "is_running"]
    missing_attrs = []
    for attr in required_attrs:
        if not hasattr(orch, attr):
            missing_attrs.append(attr)
    print(
        "✅ Orchestrator attributes: "
        + str(len(required_attrs) - len(missing_attrs))
        + " present"
    )
    if missing_attrs:
        print("❌ Missing: " + str(missing_attrs))
    else:
        print("✅ All required attributes present")
except Exception as e:
    print("❌ Orchestrator check failed: " + str(e))

# Test2: Check memory
try:
    from memory import PerformanceMemory

    mem = PerformanceMemory()
    required_methods = ["update_agent_performance"]
    missing_methods = []
    for method in required_methods:
        if not hasattr(mem, method):
            missing_methods.append(method)
    print(
        "✅ Memory methods: "
        + str(len(required_methods) - len(missing_methods))
        + " present"
    )
    if missing_methods:
        print("❌ Missing: " + str(missing_methods))
    else:
        print("✅ All required methods present")
except Exception as e:
    print("❌ Memory check failed: " + str(e))

# Test3: Check imports
try:
    from api.routes import get_platform

    print("✅ API routes import working")
except Exception as e:
    print("❌ API routes import failed: " + str(e))

print("=== VERIFICATION COMPLETE ===")
