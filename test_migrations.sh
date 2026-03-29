#!/bin/bash
# Simple migration test - bypass SQLAlchemy issues

echo "🧪 Testing migration SQL directly..."

# Test if we can connect to PostgreSQL
DATABASE_URL="postgresql://test" python3 -c "
import asyncio
import asyncpg

async def test_connection():
    try:
        conn = await asyncpg.connect('postgresql://test')
        await conn.close()
        print('✅ PostgreSQL connection successful')
    except Exception as e:
        print(f'❌ PostgreSQL connection failed: {e}')
        exit(1)

asyncio.run(test_connection())
"

if [ $? -eq 0 ]; then
    echo "✅ Database connectivity verified"
else
    echo "❌ Database connectivity failed"
    exit 1
fi

# Test if pgvector extension exists
DATABASE_URL="postgresql://test" python3 -c "
import asyncio
import asyncpg

async def test_pgvector():
    try:
        conn = await asyncpg.connect('postgresql://test')
        result = await conn.fetchval('SELECT extversion FROM pg_extension WHERE extname = $1', 'vector')
        if result:
            print(f'✅ pgvector extension exists: {result}')
        else:
            print('❌ pgvector extension not found')
            exit(1)
        await conn.close()
    except Exception as e:
        print(f'❌ pgvector test failed: {e}')
        exit(1)

asyncio.run(test_pgvector())
"
