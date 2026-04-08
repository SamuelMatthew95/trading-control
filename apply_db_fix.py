#!/usr/bin/env python3
"""
Quick script to apply source column fixes directly to PostgreSQL database.
Run this to fix the immediate production issue without waiting for migration.
"""

import asyncio
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

def apply_fixes():
    """Apply the source column fixes directly to PostgreSQL."""
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("ERROR: DATABASE_URL not found in environment")
        return False
    
    print(f"Connecting to database: {database_url.split('@')[1] if '@' in database_url else 'database'}")
    
    # Use synchronous engine for DDL operations
    engine = create_engine(database_url.replace('postgresql+asyncpg://', 'postgresql://'))
    
    with engine.connect() as conn:
        # Read and execute the SQL file
        with open('fix_source_columns.sql', 'r') as f:
            sql_commands = f.read()
        
        print("Applying database fixes...")
        try:
            result = conn.execute(text(sql_commands))
            
            # Show verification results
            print("\n✅ Source columns added successfully!")
            print("\nVerification results:")
            for row in result:
                print(f"  {row.table_name}.{row.column_name}: {row.data_type} (nullable: {row.is_nullable})")
            
            return True
            
        except Exception as e:
            print(f"❌ Error applying fixes: {e}")
            return False

if __name__ == "__main__":
    success = apply_fixes()
    if success:
        print("\n🎉 Database schema updated! Your application should now work without errors.")
        print("   The source column functionality is now restored.")
    else:
        print("\n❌ Failed to apply database fixes. Check your connection and permissions.")
