#!/usr/bin/env python3

import sys

sys.path.insert(0, ".")

from fastapi import APIRouter

# Create router
api_router = APIRouter(prefix="/api/v1", tags=["API"])


@api_router.get("/", response_model=dict)
async def root_endpoint():
    """Root endpoint with API information"""
    return {"name": "Test API", "version": "1.0.0"}


@api_router.get("/health", response_model=dict)
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": "2024-03-06T14:46:00Z"}


if __name__ == "__main__":
    print("Router routes:", [route.path for route in api_router.routes])
