"""
Monitoring and metrics collection utilities
"""
import asyncio
import time
from typing import Dict, Any, List, Optional
from collections import defaultdict, deque
from dataclasses import dataclass, field
import structlog
import aiohttp

logger = structlog.get_logger(__name__)


@dataclass
class RequestMetrics:
    """Request metrics data"""
    endpoint: str
    method: str
    status_code: int
    duration: float
    timestamp: float
    error_type: Optional[str] = None


@dataclass 
class ServiceMetrics:
    """Service-level metrics"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_response_time: float = 0.0
    request_times: deque = field(default_factory=lambda: deque(maxlen=1000))
    error_counts: Dict[str, int] = field(default_factory=dict)
    endpoint_stats: Dict[str, Dict] = field(default_factory=dict)


class MetricsCollector:
    """Collect and aggregate service metrics"""
    
    def __init__(self, max_history: int = 1000):
        self.metrics = ServiceMetrics()
        self.max_history = max_history
        self.start_time = time.time()
        
    def record_request(self, endpoint: str, method: str):
        """Record a new request"""
        self.metrics.total_requests += 1
        
        # Update endpoint stats
        key = f"{method} {endpoint}"
        if key not in self.metrics.endpoint_stats:
            self.metrics.endpoint_stats[key] = {
                "count": 0,
                "success": 0,
                "error": 0,
                "total_time": 0.0
            }
        self.metrics.endpoint_stats[key]["count"] += 1
        
    def record_response(self, endpoint: str, method: str, status_code: int, duration: float):
        """Record response metrics"""
        # Update success/failure counts
        if 200 <= status_code < 400:
            self.metrics.successful_requests += 1
            success = True
        else:
            self.metrics.failed_requests += 1
            success = False
            
        # Update response time
        self.metrics.total_response_time += duration
        self.metrics.request_times.append(duration)
        
        # Update endpoint stats
        key = f"{method} {endpoint}"
        if key in self.metrics.endpoint_stats:
            stats = self.metrics.endpoint_stats[key]
            stats["total_time"] += duration
            if success:
                stats["success"] += 1
            else:
                stats["error"] += 1
                
    def record_response_time(self, duration: float):
        """Record response time"""
        self.metrics.request_times.append(duration)
        
    def record_error(self, error_type: str):
        """Record error occurrence"""
        self.metrics.error_counts[error_type] = self.metrics.error_counts.get(error_type, 0) + 1
        
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics"""
        uptime = time.time() - self.start_time
        
        # Calculate percentiles
        request_times = sorted(self.metrics.request_times)
        percentiles = self._calculate_percentiles(request_times)
        
        # Calculate rates
        requests_per_second = self.metrics.total_requests / uptime if uptime > 0 else 0
        
        return {
            "uptime_seconds": uptime,
            "total_requests": self.metrics.total_requests,
            "successful_requests": self.metrics.successful_requests,
            "failed_requests": self.metrics.failed_requests,
            "success_rate": (
                self.metrics.successful_requests / self.metrics.total_requests 
                if self.metrics.total_requests > 0 else 0
            ),
            "requests_per_second": requests_per_second,
            "average_response_time": (
                self.metrics.total_response_time / len(self.metrics.request_times)
                if self.metrics.request_times else 0
            ),
            "response_time_percentiles": percentiles,
            "error_counts": dict(self.metrics.error_counts),
            "endpoint_stats": self._format_endpoint_stats()
        }
        
    def _calculate_percentiles(self, sorted_times: List[float]) -> Dict[str, float]:
        """Calculate response time percentiles"""
        if not sorted_times:
            return {"p50": 0, "p90": 0, "p95": 0, "p99": 0}
            
        length = len(sorted_times)
        return {
            "p50": sorted_times[int(0.50 * length)],
            "p90": sorted_times[int(0.90 * length)],
            "p95": sorted_times[int(0.95 * length)],
            "p99": sorted_times[int(0.99 * length)]
        }
        
    def _format_endpoint_stats(self) -> Dict[str, Any]:
        """Format endpoint statistics"""
        formatted = {}
        for endpoint, stats in self.metrics.endpoint_stats.items():
            count = stats["count"]
            formatted[endpoint] = {
                "requests": count,
                "success": stats["success"],
                "errors": stats["error"],
                "success_rate": stats["success"] / count if count > 0 else 0,
                "average_time": stats["total_time"] / count if count > 0 else 0
            }
        return formatted
        
    def reset_metrics(self):
        """Reset all metrics"""
        self.metrics = ServiceMetrics()
        self.start_time = time.time()


class HealthChecker:
    """Health check utilities for services"""
    
    def __init__(self):
        self.last_vllm_check = None
        self.last_redis_check = None
        self.check_cache = {}
        
    async def check_vllm_health(self, endpoint: str = None, api_key: str = None) -> Dict[str, Any]:
        """Check vLLM service health"""
        if not endpoint:
            from src.utils.config import ConfigManager
            config = ConfigManager().config
            endpoint = config.vllm.endpoint
            api_key = config.vllm.api_key
            
        cache_key = f"vllm_health_{endpoint}"
        now = time.time()
        
        # Use cached result if recent (within 30 seconds)
        if cache_key in self.check_cache:
            cached_time, cached_result = self.check_cache[cache_key]
            if now - cached_time < 30:
                return cached_result
        
        try:
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
                
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                # Try health endpoint first
                health_url = f"{endpoint.rstrip('/v1')}/health"
                try:
                    async with session.get(health_url, headers=headers) as response:
                        if response.status == 200:
                            result = {
                                "status": "healthy",
                                "endpoint": endpoint,
                                "response_time": time.time() - now,
                                "details": "Health endpoint responded successfully"
                            }
                            self.check_cache[cache_key] = (now, result)
                            return result
                except aiohttp.ClientError:
                    pass  # Try models endpoint as fallback
                    
                # Try models endpoint as fallback
                models_url = f"{endpoint}/models"
                async with session.get(models_url, headers=headers) as response:
                    response_time = time.time() - now
                    
                    if response.status == 200:
                        data = await response.json()
                        result = {
                            "status": "healthy",
                            "endpoint": endpoint,
                            "response_time": response_time,
                            "models_available": len(data.get("data", [])),
                            "details": "Models endpoint responded successfully"
                        }
                    else:
                        result = {
                            "status": "unhealthy",
                            "endpoint": endpoint,
                            "response_time": response_time,
                            "error": f"HTTP {response.status}",
                            "details": await response.text()
                        }
                        
        except asyncio.TimeoutError:
            result = {
                "status": "unhealthy", 
                "endpoint": endpoint,
                "error": "timeout",
                "details": "Request timed out after 10 seconds"
            }
        except Exception as e:
            result = {
                "status": "unhealthy",
                "endpoint": endpoint, 
                "error": type(e).__name__,
                "details": str(e)
            }
            
        self.check_cache[cache_key] = (now, result)
        return result
        
    async def check_redis_health(self, redis_url: str = None) -> Dict[str, Any]:
        """Check Redis health"""
        if not redis_url:
            from src.utils.config import ConfigManager
            config = ConfigManager().config
            redis_url = config.cache.redis_url
            
        cache_key = f"redis_health_{redis_url}"
        now = time.time()
        
        # Use cached result if recent (within 30 seconds)
        if cache_key in self.check_cache:
            cached_time, cached_result = self.check_cache[cache_key]
            if now - cached_time < 30:
                return cached_result
                
        try:
            import redis.asyncio as redis
            
            client = redis.from_url(redis_url, decode_responses=True)
            start_time = time.time()
            
            # Test connection with ping
            await client.ping()
            response_time = time.time() - start_time
            
            # Get basic info
            info = await client.info()
            await client.close()
            
            result = {
                "status": "healthy",
                "redis_url": redis_url,
                "response_time": response_time,
                "memory_used": info.get("used_memory_human", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
                "details": "Redis ping successful"
            }
            
        except Exception as e:
            result = {
                "status": "unhealthy",
                "redis_url": redis_url,
                "error": type(e).__name__,
                "details": str(e)
            }
            
        self.check_cache[cache_key] = (now, result)
        return result
        
    async def comprehensive_health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check"""
        from src.utils.config import ConfigManager
        config = ConfigManager().config
        
        results = {}
        
        # Check vLLM
        try:
            results["vllm"] = await self.check_vllm_health()
        except Exception as e:
            results["vllm"] = {
                "status": "error",
                "error": str(e)
            }
            
        # Check Redis if enabled
        if config.cache.enabled:
            try:
                results["redis"] = await self.check_redis_health()
            except Exception as e:
                results["redis"] = {
                    "status": "error", 
                    "error": str(e)
                }
        else:
            results["redis"] = {
                "status": "disabled",
                "details": "Caching is disabled"
            }
            
        # Overall status
        all_healthy = all(
            result.get("status") in ["healthy", "disabled"] 
            for result in results.values()
        )
        
        return {
            "overall_status": "healthy" if all_healthy else "unhealthy",
            "timestamp": time.time(),
            "services": results
        }


class PrometheusExporter:
    """Export metrics in Prometheus format"""
    
    def __init__(self, metrics_collector: MetricsCollector):
        self.metrics_collector = metrics_collector
        
    def export_metrics(self) -> str:
        """Export metrics in Prometheus text format"""
        metrics = self.metrics_collector.get_metrics()
        
        lines = [
            "# HELP claude_proxy_requests_total Total number of requests",
            "# TYPE claude_proxy_requests_total counter",
            f"claude_proxy_requests_total {metrics['total_requests']}",
            "",
            "# HELP claude_proxy_requests_successful_total Total number of successful requests", 
            "# TYPE claude_proxy_requests_successful_total counter",
            f"claude_proxy_requests_successful_total {metrics['successful_requests']}",
            "",
            "# HELP claude_proxy_requests_failed_total Total number of failed requests",
            "# TYPE claude_proxy_requests_failed_total counter", 
            f"claude_proxy_requests_failed_total {metrics['failed_requests']}",
            "",
            "# HELP claude_proxy_response_time_seconds Response time in seconds",
            "# TYPE claude_proxy_response_time_seconds histogram",
        ]
        
        # Add response time percentiles
        percentiles = metrics['response_time_percentiles']
        for percentile, value in percentiles.items():
            quantile = float(percentile[1:]) / 100  # Convert p95 to 0.95
            lines.append(f'claude_proxy_response_time_seconds{{quantile="{quantile}"}} {value}')
            
        lines.extend([
            "",
            "# HELP claude_proxy_uptime_seconds Service uptime in seconds",
            "# TYPE claude_proxy_uptime_seconds gauge",
            f"claude_proxy_uptime_seconds {metrics['uptime_seconds']}",
            ""
        ])
        
        # Add error counts
        for error_type, count in metrics['error_counts'].items():
            lines.extend([
                f"# HELP claude_proxy_errors_total_{error_type} Total {error_type} errors",
                f"# TYPE claude_proxy_errors_total_{error_type} counter",
                f"claude_proxy_errors_total_{error_type} {count}",
                ""
            ])
            
        return "\n".join(lines)