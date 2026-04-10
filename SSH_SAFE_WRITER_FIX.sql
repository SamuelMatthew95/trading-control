-- SSH commands to fix safe_writer validation issues directly on host
-- Run these commands after SSH into the server

# Navigate to code directory
cd /opt/render/project/src

# Backup the original file
cp api/core/writer/safe_writer.py api/core/writer/safe_writer.py.backup

# Fix 1: Remove agent_id from validation (line ~340)
sed -i 's/\["agent_id", "level", "message"\]/["level", "message"]/' api/core/writer/safe_writer.py

# Fix 2: Change data["agent_id"] to data.get("agent_id") (line ~361)
sed -i 's/data\["agent_id"\]/data.get("agent_id")/' api/core/writer/safe_writer.py

# Fix 3: Skip trace_id validation for notifications (line ~68-70)
# This is more complex, use sed to replace the validation block
sed -i '/# Trace ID validation for v3/,/raise ValueError/c\
        # Trace ID validation for v3 (optional for notifications)\
        if model_name != "Notification":\
            if "trace_id" not in data or not data["trace_id"]:\
                raise ValueError(f"{model_name}: trace_id field is required for v3 events")' api/core/writer/safe_writer.py

# Fix 4: Update entity_id fallback in write_notification (line ~859)
sed -i 's/"entity_id": data.get("notification_id")/"entity_id": data.get("notification_id") or data.get("trace_id") or msg_id/' api/core/writer/safe_writer.py

# Verify the changes
grep -n "level.*message" api/core/writer/safe_writer.py
grep -n "data.get.*agent_id" api/core/writer/safe_writer.py
grep -n "model_name.*Notification" api/core/writer/safe_writer.py
grep -n "entity_id.*notification_id" api/core/writer/safe_writer.py

# Restart the application (Render should auto-restart on file changes)
# Or manually restart if needed
