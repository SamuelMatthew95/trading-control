"""
Environment validation script
Validates all required environment variables before starting FastAPI app
"""

import os
import sys


def validate_required_env() -> bool:
    """Validate all required environment variables are present"""
    required_vars = {
        "DATABASE_URL": "PostgreSQL connection string for persistent storage",
        "ANTHROPIC_API_KEY": "Claude API key for AI agents",
    }

    missing_vars = []
    invalid_vars = []

    for var_name, description in required_vars.items():
        value = os.getenv(var_name)
        if not value:
            missing_vars.append(f"[FAIL] {var_name}: {description}")
        elif var_name == "DATABASE_URL" and not value.startswith("postgresql://"):
            invalid_vars.append(f"[FAIL] {var_name}: Must start with 'postgresql://'")

    # Check optional but recommended vars
    optional_vars = {
        "LANGFUSE_PUBLIC_KEY": "Langfuse public key for observability",
        "LANGFUSE_SECRET_KEY": "Langfuse secret key for observability",
        "NEXT_PUBLIC_VERCEL_ANALYTICS_ID": "Vercel Analytics ID",
    }

    present_optional_vars = []
    for var_name, description in optional_vars.items():
        if os.getenv(var_name):
            present_optional_vars.append(f"[OK] {var_name}: {description}")

    # Print validation results
    print(" Environment Variable Validation")
    print("=" * 50)

    if missing_vars or invalid_vars:
        print("[FAIL] CRITICAL ERRORS FOUND:")
        for error in missing_vars + invalid_vars:
            print(f"  {error}")
        print("\nALERT Application cannot start without these variables!")
        return False

    print("[OK] All required variables present:")
    for var_name, description in required_vars.items():
        value = os.getenv(var_name)
        masked_value = value[:10] + "***" if len(value) > 10 else "***"
        print(f"  [OK] {var_name}: {description} ({masked_value})")

    if present_optional_vars:
        print("\n Optional variables found:")
        for var in present_optional_vars:
            print(f"  {var}")

    print("\n Environment validation PASSED!")
    return True


def check_database_url_format() -> bool:
    """Validate DATABASE_URL format"""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return False

    # Check if it's a valid PostgreSQL URL
    if not database_url.startswith("postgresql://"):
        print("[FAIL] DATABASE_URL must start with 'postgresql://'")
        return False

    # Basic format validation
    parts = database_url.replace("postgresql://", "").split("@")
    if len(parts) != 2:
        print("[FAIL] DATABASE_URL format: postgresql://user:password@host:port/database")
        return False

    return True


if __name__ == "__main__":
    if validate_required_env():
        print("[OK] Ready to start application!")
        sys.exit(0)
    else:
        print("[FAIL] Fix environment variables before starting!")
        sys.exit(1)
