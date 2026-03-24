#!/bin/bash

echo "🚀 Production Deployment..."

# Fix database schema
echo "🔧 Fixing database..."
./fix-production.sh

# Start application
echo "🎯 Starting API..."
exec uvicorn api.main:app --host 0.0.0.0 --port 10000
