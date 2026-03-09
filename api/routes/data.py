"""
Data API Routes
Simple REST API for live market data and subscriptions
"""

try:
    from typing import Any, Dict, List, Optional

    import structlog
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    logger = structlog.get_logger()
    router = APIRouter()

except ImportError as e:
    print(f"Warning: Missing dependencies for data.py: {e}")

    # Create dummy router for import compatibility
    class DummyRouter:
        def get(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def post(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def delete(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    router = DummyRouter()

    class BaseModel:
        pass

    def HTTPException(*args, **kwargs):
        pass

    logger = None


class DataSubscriptionRequest(BaseModel):
    """Request to subscribe to data updates"""

    agent: str
    symbols: List[str]
    data_types: List[str]
    frequency: str = "1min"


@router.post("/subscribe")
async def subscribe_to_data(subscription_request: DataSubscriptionRequest):
    """Subscribe to live data updates"""
    try:
        from main import app

        data_manager = app.state.orchestrator.data_manager

        subscription_data = {
            "agent": subscription_request.agent,
            "symbols": subscription_request.symbols,
            "data_types": subscription_request.data_types,
            "frequency": subscription_request.frequency,
        }

        subscription_id = await data_manager.subscribe_to_data(subscription_data)

        return {
            "success": True,
            "subscription_id": subscription_id,
            "message": f"Subscribed to {len(subscription_request.symbols)} symbols",
        }

    except Exception as e:
        logger.error(f"Error subscribing to data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/symbol/{symbol}")
async def get_symbol_data(symbol: str):
    """Get data for a specific symbol"""
    try:
        from main import app

        data_manager = app.state.orchestrator.data_manager

        data = await data_manager.get_symbol_data(symbol)

        if not data:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")

        # Convert to dict for JSON serialization
        data_dict = {
            "symbol": data.symbol,
            "price": data.price,
            "volume": data.volume,
            "change": data.change,
            "change_percent": data.change_percent,
            "last_update": data.last_update.isoformat(),
            "technical_indicators": data.technical_indicators,
            "sentiment": data.sentiment,
        }

        return {"success": True, "data": data_dict}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting symbol data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch-data")
async def get_batch_data(symbols: List[str]):
    """Get data for multiple symbols"""
    try:
        from main import app

        data_manager = app.state.orchestrator.data_manager

        batch_data = await data_manager.get_batch_data(symbols)

        # Convert to dict for JSON serialization
        result = {}
        for symbol, data in batch_data.items():
            result[symbol] = {
                "symbol": data.symbol,
                "price": data.price,
                "volume": data.volume,
                "change": data.change,
                "change_percent": data.change_percent,
                "last_update": data.last_update.isoformat(),
                "technical_indicators": data.technical_indicators,
                "sentiment": data.sentiment,
            }

        return {"success": True, "data": result}

    except Exception as e:
        logger.error(f"Error getting batch data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market-overview")
async def get_market_overview():
    """Get market overview with indices and top movers"""
    try:
        from main import app

        data_manager = app.state.orchestrator.data_manager

        overview = await data_manager.get_market_overview()

        return {"success": True, "overview": overview}

    except Exception as e:
        logger.error(f"Error getting market overview: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subscriptions")
async def get_subscriptions():
    """Get all active data subscriptions"""
    try:
        from main import app

        data_manager = app.state.orchestrator.data_manager

        # Convert subscriptions to dict for JSON serialization
        subscriptions = []
        for sub_id, sub in data_manager.subscriptions.items():
            sub_dict = {
                "id": sub.id,
                "agent": sub.agent,
                "symbols": sub.symbols,
                "data_types": sub.data_types,
                "frequency": sub.frequency.value,
                "created_at": sub.created_at.isoformat(),
                "last_sent": sub.last_sent.isoformat(),
            }
            subscriptions.append(sub_dict)

        return {
            "success": True,
            "subscriptions": subscriptions,
            "total": len(subscriptions),
        }

    except Exception as e:
        logger.error(f"Error getting subscriptions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/subscriptions/{subscription_id}")
async def unsubscribe(subscription_id: str):
    """Unsubscribe from data updates"""
    try:
        from main import app

        data_manager = app.state.orchestrator.data_manager

        if subscription_id in data_manager.subscriptions:
            del data_manager.subscriptions[subscription_id]

            return {"success": True, "message": f"Unsubscribed from {subscription_id}"}
        else:
            raise HTTPException(status_code=404, detail="Subscription not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unsubscribing: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def data_health_check():
    """Simple health check for data system"""
    try:
        from main import app

        data_manager = app.state.orchestrator.data_manager

        # Get data freshness
        data_freshness = await data_manager.get_data_freshness()

        # Get number of tracked symbols
        symbols_tracked = len(data_manager.data_cache)

        # Get subscription count
        subscription_count = len(data_manager.subscriptions)

        # Determine health status
        if data_freshness < 60000:  # Less than 1 minute
            status = "healthy"
        elif data_freshness < 300000:  # Less than 5 minutes
            status = "degraded"
        else:
            status = "unhealthy"

        return {
            "status": status,
            "data_freshness_ms": data_freshness,
            "symbols_tracked": symbols_tracked,
            "active_subscriptions": subscription_count,
            "major_indices": len(data_manager.major_indices),
        }

    except Exception as e:
        logger.error(f"Error in data health check: {str(e)}")
        return {"status": "unhealthy", "error": str(e)}
