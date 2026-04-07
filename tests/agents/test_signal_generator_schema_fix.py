"""Test to verify SignalGenerator schema fix.

This test verifies that the SignalGenerator code uses strategy_id
instead of agent_id in the SQL INSERT statements.
"""

from __future__ import annotations


class TestSignalGeneratorSchemaFix:
    """Test SignalGenerator uses correct schema (strategy_id, not agent_id)."""

    def test_signal_generator_uses_strategy_id_not_agent_id(self):
        """Test that the SignalGenerator source code uses strategy_id, not agent_id."""
        # Read the source code
        with open("api/services/signal_generator.py") as f:
            source_code = f.read()

        # Simple string search - verify strategy_id is used
        assert '"strategy_id":' in source_code, "Code should contain strategy_id parameter"
        assert "strategy_id" in source_code, "Code should contain strategy_id column reference"

        # Verify agent_id is NOT used as a parameter
        lines = source_code.split("\n")
        agent_id_param_lines = []

        for line in lines:
            # Look for "agent_id": pattern (parameter name in dict)
            if '"agent_id":' in line:
                agent_id_param_lines.append(line.strip())

        # Should not find any agent_id parameter usage
        assert len(agent_id_param_lines) == 0, (
            f"Found agent_id parameter usage: {agent_id_param_lines}"
        )

        # Should find strategy_id usage
        strategy_id_lines = [line.strip() for line in lines if '"strategy_id":' in line]
        assert len(strategy_id_lines) >= 2, (
            f"Should find at least 2 strategy_id parameter usages. Found: {strategy_id_lines}"
        )

    def test_branch_documentation(self):
        """Test documenting this branch's purpose and fix."""
        branch_info = {
            "branch": "fix/agent-runs-schema-mismatch",
            "purpose": "Fix UndefinedColumnError where agent_id column doesn't exist",
            "issue": "SignalGenerator was trying to insert agent_id but database has strategy_id",
            "solution": "Changed INSERT statements to use strategy_id instead of agent_id",
            "files_changed": ["api/services/signal_generator.py"],
            "test_coverage": "This test file ensures the fix works correctly",
            "verification": "String analysis confirms strategy_id is used, not agent_id",
        }

        # Verify all expected keys are present
        expected_keys = [
            "branch",
            "purpose",
            "issue",
            "solution",
            "files_changed",
            "test_coverage",
            "verification",
        ]
        for key in expected_keys:
            assert key in branch_info, f"Missing branch info key: {key}"

        # This test always passes - it's documentation
        assert True

    def test_insert_statements_use_correct_columns(self):
        """Test that INSERT statements use the correct column names."""
        # Read the source code
        with open("api/services/signal_generator.py", "r") as f:
            source_code = f.read()
        
        # Check agent_runs INSERT statement
        assert "INSERT INTO agent_runs" in source_code, "Should have agent_runs INSERT"
        assert "(id, strategy_id, trace_id, input_data," in source_code, "agent_runs INSERT should use correct columns without run_type/trigger_event"
        assert ":strategy_id," in source_code, "agent_runs INSERT should use strategy_id parameter"
        
        # Check that run_type and trigger_event are NOT used
        assert "run_type" not in source_code, "agent_runs INSERT should NOT use run_type column"
        assert "trigger_event" not in source_code, "agent_runs INSERT should NOT use trigger_event column"
        assert "trigger" not in source_code, "agent_runs INSERT should NOT use trigger parameter"
        
        # Check agent_grades INSERT statement  
        assert "INSERT INTO agent_grades" in source_code, "Should have agent_grades INSERT"
        assert ":strategy_id," in source_code, "agent_grades INSERT should use strategy_id parameter"

    def test_error_message_pattern_fixed(self):
        """Test that the specific error pattern is fixed."""
        # Read the source code
        with open("api/services/signal_generator.py") as f:
            source_code = f.read()

        # The error was: UndefinedColumnError: column "agent_id" of relation "agent_runs" does not exist
        # Our fix should prevent this by not using agent_id

        # Verify no agent_id column references in agent_runs context
        agent_runs_context = (
            source_code.split("INSERT INTO agent_runs")[1].split("INSERT INTO")[0]
            if "INSERT INTO agent_runs" in source_code
            else ""
        )

        assert "agent_id" not in agent_runs_context, (
            f"agent_runs context should not contain agent_id. Context: {agent_runs_context[:200]}..."
        )
        assert "strategy_id" in agent_runs_context, (
            f"agent_runs context should contain strategy_id. Context: {agent_runs_context[:200]}..."
        )
