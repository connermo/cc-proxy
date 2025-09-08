"""
Caching utilities for request/response caching
"""
import asyncio
import hashlib
import json
import time
from typing import Dict, Any, Optional, Set
import structlog
import redis.asyncio as redis
from collections import OrderedDict

logger = structlog.get_logger(__name__)


class MemoryCache:
    """In-memory LRU cache"""
    
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.cache = OrderedDict()
        self.access_times = {}
        
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if key in self.cache:
            # Move to end (most recently used)
            value = self.cache.pop(key)
            self.cache[key] = value
            self.access_times[key] = time.time()
            return value
        return None
        
    def set(self, key: str, value: Any, ttl: int = 3600):
        """Set value in cache with TTL"""
        if key in self.cache:
            self.cache.pop(key)
        elif len(self.cache) >= self.max_size:
            # Remove least recently used
            oldest_key = next(iter(self.cache))
            self.cache.pop(oldest_key)
            self.access_times.pop(oldest_key, None)
            
        self.cache[key] = {
            "value": value,
            "expires_at": time.time() + ttl
        }
        self.access_times[key] = time.time()
        
    def delete(self, key: str):
        """Delete key from cache"""
        self.cache.pop(key, None)
        self.access_times.pop(key, None)
        
    def clear(self):
        """Clear all cache entries"""
        self.cache.clear()
        self.access_times.clear()
        
    def cleanup_expired(self):
        """Remove expired entries"""
        now = time.time()
        expired_keys = []
        
        for key, data in self.cache.items():
            if data["expires_at"] < now:
                expired_keys.append(key)
                
        for key in expired_keys:
            self.delete(key)
            
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        now = time.time()
        valid_entries = sum(
            1 for data in self.cache.values() 
            if data["expires_at"] > now
        )
        
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "valid_entries": valid_entries,
            "hit_rate": getattr(self, "_hit_rate", 0.0)
        }


class RedisCache:
    """Redis-based cache"""
    
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.client: Optional[redis.Redis] = None
        self.connected = False
        
    async def connect(self):
        """Connect to Redis"""
        try:
            self.client = redis.from_url(self.redis_url, decode_responses=True)
            # Test connection
            await self.client.ping()
            self.connected = True
            logger.info("Connected to Redis", redis_url=self.redis_url)
        except Exception as e:
            logger.error("Failed to connect to Redis", error=str(e))
            self.connected = False
            
    async def disconnect(self):
        """Disconnect from Redis"""
        if self.client:
            await self.client.close()
            self.connected = False
            
    async def get(self, key: str) -> Optional[Any]:
        """Get value from Redis"""
        if not self.connected:
            return None
            
        try:
            value = await self.client.get(key)
            if value:
                return json.loads(value)
        except Exception as e:
            logger.warning("Redis get error", key=key, error=str(e))
        return None
        
    async def set(self, key: str, value: Any, ttl: int = 3600):
        """Set value in Redis with TTL"""
        if not self.connected:
            return
            
        try:
            serialized = json.dumps(value, separators=(',', ':'))
            await self.client.setex(key, ttl, serialized)
        except Exception as e:
            logger.warning("Redis set error", key=key, error=str(e))
            
    async def delete(self, key: str):
        """Delete key from Redis"""
        if not self.connected:
            return
            
        try:
            await self.client.delete(key)
        except Exception as e:
            logger.warning("Redis delete error", key=key, error=str(e))
            
    async def clear_pattern(self, pattern: str):
        """Clear keys matching pattern"""
        if not self.connected:
            return
            
        try:
            keys = await self.client.keys(pattern)
            if keys:
                await self.client.delete(*keys)
        except Exception as e:
            logger.warning("Redis clear pattern error", pattern=pattern, error=str(e))
            
    async def get_stats(self) -> Dict[str, Any]:
        """Get Redis statistics"""
        if not self.connected:
            return {"connected": False}
            
        try:
            info = await self.client.info()
            return {
                "connected": True,
                "memory_used": info.get("used_memory_human", "unknown"),
                "keys": await self.client.dbsize(),
                "hits": info.get("keyspace_hits", 0),
                "misses": info.get("keyspace_misses", 0)
            }
        except Exception as e:
            logger.warning("Redis stats error", error=str(e))
            return {"connected": False, "error": str(e)}


class CacheManager:
    """Main cache manager combining memory and Redis caches"""
    
    def __init__(self, config):
        self.config = config
        self.memory_cache = MemoryCache(config.max_memory_cache_size)
        self.redis_cache = RedisCache(config.redis_url) if config.enabled else None
        
        # Cache policy settings
        self.cacheable_patterns = {
            "static_info": 86400,     # 24 hours
            "code_generation": 3600,  # 1 hour  
            "reasoning": 1800,        # 30 minutes
            "default": config.default_ttl
        }
        
        # Request tracking
        self.cache_hits = 0
        self.cache_misses = 0
        
        # Start cleanup task
        self._cleanup_task = None
        
    async def initialize(self):
        """Initialize cache connections"""
        if self.redis_cache:
            await self.redis_cache.connect()
            
        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        
    async def close(self):
        """Close cache connections"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            
        if self.redis_cache:
            await self.redis_cache.disconnect()
            
    async def _periodic_cleanup(self):
        """Periodic cleanup of expired entries"""
        while True:
            try:
                await asyncio.sleep(300)  # 5 minutes
                self.memory_cache.cleanup_expired()
                logger.debug("Cache cleanup completed")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Cache cleanup error", error=str(e))
                
    def generate_cache_key(self, request: Dict[str, Any]) -> str:
        """Generate cache key for request"""
        # Create a normalized version of the request for hashing
        normalized = {
            "messages": request.get("messages", []),
            "max_tokens": request.get("max_tokens"),
            "temperature": request.get("temperature"),
            "tools": request.get("tools", []),
            "system": request.get("system")
        }
        
        # Remove None values
        normalized = {k: v for k, v in normalized.items() if v is not None}
        
        # Create hash
        serialized = json.dumps(normalized, sort_keys=True, separators=(',', ':'))
        hash_obj = hashlib.sha256(serialized.encode())
        return f"claude_proxy:{hash_obj.hexdigest()}"
        
    def should_cache_request(self, request: Dict[str, Any]) -> bool:
        """Determine if request should be cached"""
        # Don't cache streaming requests
        if request.get("stream", False):
            return False
            
        # Don't cache requests with tools (they might have side effects)
        if request.get("tools"):
            return False
            
        # Don't cache if explicitly disabled
        if not self.config.enabled:
            return False
            
        return True
        
    def _detect_request_type(self, request: Dict[str, Any]) -> str:
        """Detect request type for cache TTL"""
        messages = request.get("messages", [])
        content_text = ""
        
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str):
                content_text += " " + content.lower()
                
        # Check for patterns
        if any(word in content_text for word in ["function", "class", "code", "implement"]):
            return "code_generation"
        elif any(word in content_text for word in ["analyze", "reason", "solve", "calculate"]):
            return "reasoning"
        elif any(word in content_text for word in ["what is", "define", "explain"]):
            return "static_info"
            
        return "default"
        
    async def get_cached_response(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get cached response"""
        # Try memory cache first
        response = self.memory_cache.get(cache_key)
        if response and response["expires_at"] > time.time():
            self.cache_hits += 1
            logger.debug("Memory cache hit", cache_key=cache_key[:16] + "...")
            return response["value"]
            
        # Try Redis cache
        if self.redis_cache:
            response = await self.redis_cache.get(cache_key)
            if response:
                self.cache_hits += 1
                logger.debug("Redis cache hit", cache_key=cache_key[:16] + "...")
                
                # Store in memory cache for faster access
                self.memory_cache.set(cache_key, response, ttl=300)  # 5 minutes in memory
                return response
                
        self.cache_misses += 1
        logger.debug("Cache miss", cache_key=cache_key[:16] + "...")
        return None
        
    async def cache_response(
        self, 
        cache_key: str, 
        response: Dict[str, Any], 
        request: Optional[Dict[str, Any]] = None
    ):
        """Cache response"""
        if not self.should_cache_request(request or {}):
            return
            
        # Determine TTL
        request_type = self._detect_request_type(request or {})
        ttl = self.cacheable_patterns[request_type]
        
        # Cache in memory
        self.memory_cache.set(cache_key, response, ttl)
        
        # Cache in Redis
        if self.redis_cache:
            await self.redis_cache.set(cache_key, response, ttl)
            
        logger.debug("Cached response",
                    cache_key=cache_key[:16] + "...",
                    request_type=request_type,
                    ttl=ttl)
                    
    async def invalidate_cache(self, pattern: str = None):
        """Invalidate cache entries"""
        if pattern:
            # Clear specific pattern
            if self.redis_cache:
                await self.redis_cache.clear_pattern(pattern)
                
            # For memory cache, we need to check each key
            keys_to_delete = [
                key for key in self.memory_cache.cache.keys() 
                if pattern in key
            ]
            for key in keys_to_delete:
                self.memory_cache.delete(key)
        else:
            # Clear all
            self.memory_cache.clear()
            if self.redis_cache:
                await self.redis_cache.clear_pattern("claude_proxy:*")
                
        logger.info("Cache invalidated", pattern=pattern or "all")
        
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_requests = self.cache_hits + self.cache_misses
        hit_rate = self.cache_hits / total_requests if total_requests > 0 else 0.0
        
        stats = {
            "enabled": self.config.enabled,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "hit_rate": hit_rate,
            "memory_cache": self.memory_cache.get_stats()
        }
        
        return stats
        
    async def get_metrics(self) -> Dict[str, Any]:
        """Get comprehensive cache metrics"""
        stats = self.get_cache_stats()
        
        if self.redis_cache:
            redis_stats = await self.redis_cache.get_stats()
            stats["redis_cache"] = redis_stats
            
        return stats