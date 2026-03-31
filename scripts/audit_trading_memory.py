#!/usr/bin/env python3
"""
Trading Control Memory Audit Script

Verifies codebase compliance with memory-trading.md rules:
- PAPER trading enforcement
- Order idempotency requirements
- Risk management limits
- Redis state management patterns
- Alpaca API usage patterns

Usage: python scripts/audit_trading_memory.py
"""

import re
from pathlib import Path
from typing import Any


class TradingMemoryAuditor:
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.issues = []
        self.warnings = []

    def audit_all(self) -> dict[str, Any]:
        """Run full audit of trading memory compliance."""
        print("🔍 Auditing Trading Control Memory Compliance...")

        # Core compliance checks
        self.check_paper_trading_enforcement()
        self.check_order_idempotency()
        self.check_risk_management()
        self.check_redis_state_management()
        self.check_alpaca_patterns()
        self.check_environment_variables()

        return {
            "issues": self.issues,
            "warnings": self.warnings,
            "compliance_score": self.calculate_compliance_score(),
        }

    def check_paper_trading_enforcement(self):
        """Check for PAPER trading enforcement."""
        print("\n📋 Checking PAPER trading enforcement...")

        # Look for live trading URLs
        api_files = list(self.project_root.glob("**/api/**/*.py"))
        for file_path in api_files:
            content = file_path.read_text()

            # Check for live Alpaca URLs
            if "api.alpaca.markets" in content and "paper-api.alpaca.markets" not in content:
                self.issues.append(
                    {
                        "file": str(file_path),
                        "rule": "PAPER trading enforcement",
                        "message": "Found potential live Alpaca URL without paper trading guard",
                        "line": self.find_line_number(content, "api.alpaca.markets"),
                    }
                )

            # Check for paper trading environment checks
            if "alpaca" in content.lower() and "ALPACA_PAPER" not in content:
                self.warnings.append(
                    {
                        "file": str(file_path),
                        "rule": "PAPER trading enforcement",
                        "message": "Alpaca usage found without ALPACA_PAPER environment check",
                        "line": self.find_line_number(content, "alpaca"),
                    }
                )

    def check_order_idempotency(self):
        """Check for order idempotency patterns."""
        print("\n🔑 Checking order idempotency...")

        api_files = list(self.project_root.glob("**/api/**/*.py"))
        for file_path in api_files:
            content = file_path.read_text()

            # Look for order submission without client_order_id
            if "submit_order" in content and "client_order_id" not in content:
                self.issues.append(
                    {
                        "file": str(file_path),
                        "rule": "Order idempotency",
                        "message": "Order submission found without client_order_id",
                        "line": self.find_line_number(content, "submit_order"),
                    }
                )

            # Check for idempotency_key in database writes
            if "writer.write" in content and "idempotency_key" not in content:
                self.issues.append(
                    {
                        "file": str(file_path),
                        "rule": "Order idempotency",
                        "message": "SafeWriter write found without idempotency_key",
                        "line": self.find_line_number(content, "writer.write"),
                    }
                )

    def check_risk_management(self):
        """Check for risk management patterns."""
        print("\n⚖️ Checking risk management...")

        # Look for position sizing logic
        api_files = list(self.project_root.glob("**/api/**/*.py"))
        for file_path in api_files:
            content = file_path.read_text()

            # Check for hardcoded position sizes
            hardcoded_sizes = re.findall(r"qty\s*=\s*[0-9.]+", content)
            if hardcoded_sizes:
                self.warnings.append(
                    {
                        "file": str(file_path),
                        "rule": "Risk management",
                        "message": f"Found hardcoded position size: {hardcoded_sizes}",
                        "line": self.find_line_number(content, hardcoded_sizes[0]),
                    }
                )

            # Check for 5% risk rule implementation
            if "position" in content.lower() and "0.05" not in content:
                self.warnings.append(
                    {
                        "file": str(file_path),
                        "rule": "Risk management",
                        "message": "Position sizing logic found without 5% risk rule",
                        "line": self.find_line_number(content, "position"),
                    }
                )

    def check_redis_state_management(self):
        """Check Redis state management patterns."""
        print("\n💾 Checking Redis state management...")

        api_files = list(self.project_root.glob("**/api/**/*.py"))
        for file_path in api_files:
            content = file_path.read_text()

            # Check for Redis position tracking
            if "position" in content.lower() and "redis" not in content.lower():
                self.warnings.append(
                    {
                        "file": str(file_path),
                        "rule": "Redis state management",
                        "message": "Position logic found without Redis integration",
                        "line": self.find_line_number(content, "position"),
                    }
                )

            # Check for trace_id in Redis operations
            if "redis" in content.lower() and "trace_id" not in content:
                self.issues.append(
                    {
                        "file": str(file_path),
                        "rule": "Redis state management",
                        "message": "Redis operations found without trace_id",
                        "line": self.find_line_number(content, "redis"),
                    }
                )

    def check_alpaca_patterns(self):
        """Check Alpaca API usage patterns."""
        print("\n🐫 Checking Alpaca API patterns...")

        api_files = list(self.project_root.glob("**/api/**/*.py"))
        for file_path in api_files:
            content = file_path.read_text()

            # Check for error handling
            if "submit_order" in content and "AlpacaAPIError" not in content:
                self.issues.append(
                    {
                        "file": str(file_path),
                        "rule": "Alpaca patterns",
                        "message": "Alpaca order submission without proper error handling",
                        "line": self.find_line_number(content, "submit_order"),
                    }
                )

            # Check for rate limiting
            if "alpaca" in content.lower() and "rate" not in content.lower():
                self.warnings.append(
                    {
                        "file": str(file_path),
                        "rule": "Alpaca patterns",
                        "message": "Alpaca usage found without rate limiting consideration",
                        "line": self.find_line_number(content, "alpaca"),
                    }
                )

    def check_environment_variables(self):
        """Check environment variable usage."""
        print("\n🌍 Checking environment variables...")

        # Check .env files
        env_files = list(self.project_root.glob("**/.env*"))
        for env_file in env_files:
            content = env_file.read_text()

            # Check for required trading variables
            required_vars = [
                "ALPACA_PAPER",
                "ALPACA_BASE_URL",
                "TRADING_MODE",
                "PAPER_PORTFOLIO_VALUE",
            ]

            for var in required_vars:
                if var not in content:
                    self.warnings.append(
                        {
                            "file": str(env_file),
                            "rule": "Environment variables",
                            "message": f"Missing required environment variable: {var}",
                            "line": 1,
                        }
                    )

    def find_line_number(self, content: str, search_term: str) -> int:
        """Find line number of search term in content."""
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            if search_term in line:
                return i
        return 1

    def calculate_compliance_score(self) -> float:
        """Calculate compliance score (0-100)."""
        total_checks = len(self.issues) + len(self.warnings)
        if total_checks == 0:
            return 100.0

        # Issues weigh more than warnings
        weighted_issues = len(self.issues) * 10
        weighted_warnings = len(self.warnings) * 3
        total_weighted = weighted_issues + weighted_warnings

        # Score out of 100 (lower is better)
        max_score = 100
        deduction = min(total_weighted, max_score)

        return max_score - deduction

    def print_report(self, results: dict[str, Any]):
        """Print detailed audit report."""
        print(f"\n{'=' * 60}")
        print("📊 TRADING MEMORY AUDIT REPORT")
        print(f"{'=' * 60}")

        print(f"\n🎯 Compliance Score: {results['compliance_score']:.1f}/100")

        if results["issues"]:
            print(f"\n❌ CRITICAL ISSUES ({len(results['issues'])}):")
            for issue in results["issues"]:
                print(f"   📁 {issue['file']}")
                print(f"   🔸 {issue['rule']}: {issue['message']}")
                print(f"   📍 Line {issue['line']}")
                print()

        if results["warnings"]:
            print(f"\n⚠️ WARNINGS ({len(results['warnings'])}):")
            for warning in results["warnings"]:
                print(f"   📁 {warning['file']}")
                print(f"   🔸 {warning['rule']}: {warning['message']}")
                print(f"   📍 Line {warning['line']}")
                print()

        if not results["issues"] and not results["warnings"]:
            print("\n✅ Perfect compliance! All trading memory rules are followed.")

        print("\n📋 Summary:")
        print(f"   Critical Issues: {len(results['issues'])}")
        print(f"   Warnings: {len(results['warnings'])}")
        print(f"   Compliance Score: {results['compliance_score']:.1f}/100")

        # Recommendations
        self.print_recommendations(results)

    def print_recommendations(self, results: dict[str, Any]):
        """Print specific recommendations based on findings."""
        print("\n💡 RECOMMENDATIONS:")

        if any(issue["rule"] == "PAPER trading enforcement" for issue in results["issues"]):
            print("   🔒 Add ALPACA_PAPER=true checks before any Alpaca API calls")
            print("   🌍 Use environment variables for API URLs with paper/live switching")

        if any(issue["rule"] == "Order idempotency" for issue in results["issues"]):
            print("   🔑 Add client_order_id to all order submissions")
            print("   📝 Include idempotency_key in all SafeWriter calls")

        if any(issue["rule"] == "Risk management" for issue in results["warnings"]):
            print("   ⚖️ Implement 5% max position size rule")
            print("   📊 Add portfolio value-based position sizing")

        if any(issue["rule"] == "Redis state management" for issue in results["issues"]):
            print("   💾 Add trace_id to all Redis operations")
            print("   🔄 Use Redis hashes for position state tracking")


def main():
    """Main audit function."""
    project_root = Path(__file__).parent.parent

    auditor = TradingMemoryAuditor(str(project_root))
    results = auditor.audit_all()
    auditor.print_report(results)

    # Exit with error code if critical issues found
    if results["issues"]:
        exit(1)
    else:
        exit(0)


if __name__ == "__main__":
    main()
