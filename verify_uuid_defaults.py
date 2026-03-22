#!/usr/bin/env python3
"""
Verification script to prove UUID defaults work correctly.
Run this to verify the server_default is properly bound to column metadata.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.core.models import VectorMemory, AgentLog, LLMCostTracking

def main():
    print("🧪 Verifying UUID defaults are properly configured...")
    
    for model_class in [VectorMemory, AgentLog, LLMCostTracking]:
        model = model_class()
        id_column = model.id
        
        print(f"{model_class.__name__}.id:")
        print(f"  has default: {id_column.default is not None}")
        print(f"  has server_default: {id_column.server_default is not None}")
        
        if id_column.server_default is not None:
            # This is the key test - check if text() object has right argument
            default_arg = getattr(id_column.server_default, 'arg', None)
            print(f"  server_default.arg: '{default_arg}'")
            
            if default_arg == "gen_random_uuid()::text":
                print("  ✅ CORRECT: PostgreSQL UUID generation will work")
            else:
                print(f"  ❌ WRONG: server_default.arg is '{default_arg}'")
        else:
            print("  ❌ MISSING: No server_default found")
        print()
    
    print("🎯 Verification complete!")

if __name__ == "__main__":
    main()
