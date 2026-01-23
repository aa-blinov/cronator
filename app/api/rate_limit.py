"""Rate limiting middleware and dependencies."""

import time
from collections import defaultdict
from collections.abc import Callable
from functools import wraps

from fastapi import HTTPException, Request, status

# Simple in-memory rate limiter (for production consider Redis)
_rate_limit_store: dict[str, list[float]] = defaultdict(list)


def rate_limit(max_calls: int, period: int):
    """
    Rate limit decorator for FastAPI endpoints.
    
    Args:
        max_calls: Maximum number of calls allowed
        period: Time period in seconds
    
    Usage:
        @router.post("/endpoint")
        @rate_limit(max_calls=5, period=60)
        async def my_endpoint():
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract request from kwargs
            request: Request | None = kwargs.get("request")
            if not request:
                # Try to find in args (for dependency injection)
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            
            if not request:
                # If no request found, skip rate limiting (e.g., in tests)
                return await func(*args, **kwargs)
            
            # Use client IP as key
            client_ip = request.client.host if request.client else "unknown"
            key = f"{func.__name__}:{client_ip}"
            
            now = time.time()
            
            # Clean old entries
            _rate_limit_store[key] = [
                timestamp for timestamp in _rate_limit_store[key]
                if now - timestamp < period
            ]
            
            # Check rate limit
            if len(_rate_limit_store[key]) >= max_calls:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded: max {max_calls} requests per {period} seconds",
                )
            
            # Record this request
            _rate_limit_store[key].append(now)
            
            # Call original function
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def clear_rate_limits():
    """Clear all rate limit data (useful for testing)."""
    _rate_limit_store.clear()
