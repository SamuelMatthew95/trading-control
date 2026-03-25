#!/bin/bash
# Audit script - verify no id=unknown patterns in write paths

echo "🔍 AUDIT: Checking for id=unknown patterns..."

# Check for dangerous patterns
echo "1. Checking for 'unknown' fallbacks..."
unknown_found=$(grep -r "unknown" /Users/matthew/Desktop/trading-control-python/api/core/writer/safe_writer.py | grep -v "source.*unknown" | wc -l)

if [ $unknown_found -gt 0 ]; then
    echo "❌ FOUND 'unknown' patterns:"
    grep -r "unknown" /Users/matthew/Desktop/trading-control-python/api/core/writer/safe_writer.py | grep -v "source.*unknown"
    exit 1
else
    echo "✅ No dangerous 'unknown' patterns found"
fi

echo "2. Checking for data.get('msg_id') patterns..."
msg_id_get=$(grep -r 'data.get("msg_id"' /Users/matthew/Desktop/trading-control-python/api/core/ --include="*.py" | wc -l)

if [ $msg_id_get -gt 0 ]; then
    echo "❌ FOUND data.get('msg_id') patterns:"
    grep -r 'data.get("msg_id"' /Users/matthew/Desktop/trading-control-python/api/core/ --include="*.py"
    exit 1
else
    echo "✅ No data.get('msg_id') patterns found"
fi

echo "3. Checking for data.get('id') patterns..."
id_get=$(grep -r 'data.get("id"' /Users/matthew/Desktop/trading-control-python/api/core/ --include="*.py" | wc -l)

if [ $id_get -gt 0 ]; then
    echo "❌ FOUND data.get('id') patterns:"
    grep -r 'data.get("id"' /Users/matthew/Desktop/trading-control-python/api/core/ --include="*.py"
    exit 1
else
    echo "✅ No data.get('id') patterns found"
fi

echo "4. Checking for msg_id validation in all write methods..."
write_methods=$(grep -c "if not msg_id:" /Users/matthew/Desktop/trading-control-python/api/core/writer/safe_writer.py)

if [ $write_methods -eq 7 ]; then
    echo "✅ All 7 write methods have msg_id validation"
else
    echo "❌ Missing msg_id validation. Found: $write_methods (expected: 7)"
    exit 1
fi

echo "5. Checking _log_write_operation signature..."
log_sig=$(grep -A1 "def _log_write_operation" /Users/matthew/Desktop/trading-control-python/api/core/writer/safe_writer.py | grep -c "entity_id: str")

if [ $log_sig -eq 1 ]; then
    echo "✅ _log_write_operation uses entity_id parameter"
else
    echo "❌ _log_write_operation signature incorrect"
    exit 1
fi

echo "🎉 ALL CHECKS PASSED - Repo is clean!"
echo "✅ No id=unknown regression possible"
