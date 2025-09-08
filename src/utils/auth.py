"""
Authentication and authorization utilities
"""
import hashlib
import hmac
import time
from typing import Dict, Optional, Set
from collections import defaultdict, deque
import structlog

logger = structlog.get_logger(__name__)


class RateLimiter:
    """Simple rate limiter using sliding window"""
    
    def __init__(self, requests_per_minute: int):
        self.requests_per_minute = requests_per_minute
        self.requests = defaultdict(deque)
        
    def is_allowed(self, identifier: str) -> bool:
        """Check if request is allowed for given identifier"""
        now = time.time()
        window_start = now - 60  # 1 minute window
        
        # Clean old requests
        requests = self.requests[identifier]
        while requests and requests[0] < window_start:
            requests.popleft()
            
        # Check if under limit
        if len(requests) < self.requests_per_minute:
            requests.append(now)
            return True
            
        return False
        
    def get_remaining_requests(self, identifier: str) -> int:
        """Get remaining requests for identifier"""
        now = time.time()
        window_start = now - 60
        
        requests = self.requests[identifier]
        while requests and requests[0] < window_start:
            requests.popleft()
            
        return max(0, self.requests_per_minute - len(requests))
        
    def reset_limits(self, identifier: str):
        """Reset limits for identifier"""
        if identifier in self.requests:
            del self.requests[identifier]


class ApiKeyManager:
    """Manage API keys and their permissions"""
    
    def __init__(self):
        self.keys: Dict[str, Dict] = {}
        self.hashed_keys: Set[str] = set()
        
    def add_key(
        self, 
        api_key: str, 
        description: str = "",
        permissions: Optional[Dict] = None
    ) -> str:
        """Add API key with optional permissions"""
        key_hash = self._hash_key(api_key)
        
        key_info = {
            "hash": key_hash,
            "description": description,
            "permissions": permissions or {},
            "created_at": time.time(),
            "last_used": None,
            "usage_count": 0,
            "active": True
        }
        
        self.keys[api_key] = key_info
        self.hashed_keys.add(key_hash)
        
        logger.info("API key added", 
                   key_hash=key_hash[:8] + "...",
                   description=description)
        
        return key_hash
        
    def validate_key(self, api_key: str) -> bool:
        """Validate API key"""
        if not api_key:
            return False
            
        key_info = self.keys.get(api_key)
        if not key_info or not key_info["active"]:
            return False
            
        # Update usage stats
        key_info["last_used"] = time.time()
        key_info["usage_count"] += 1
        
        return True
        
    def revoke_key(self, api_key: str) -> bool:
        """Revoke API key"""
        key_info = self.keys.get(api_key)
        if key_info:
            key_info["active"] = False
            logger.info("API key revoked", key_hash=key_info["hash"][:8] + "...")
            return True
        return False
        
    def get_key_info(self, api_key: str) -> Optional[Dict]:
        """Get information about API key"""
        return self.keys.get(api_key)
        
    def list_keys(self) -> Dict[str, Dict]:
        """List all API keys (without the actual key values)"""
        return {
            key_info["hash"]: {
                "description": key_info["description"],
                "created_at": key_info["created_at"],
                "last_used": key_info["last_used"],
                "usage_count": key_info["usage_count"],
                "active": key_info["active"]
            }
            for key_info in self.keys.values()
        }
        
    def _hash_key(self, api_key: str) -> str:
        """Hash API key for secure storage"""
        return hashlib.sha256(api_key.encode()).hexdigest()


class AuthManager:
    """Main authentication manager"""
    
    def __init__(self, config):
        self.config = config
        self.api_key_manager = ApiKeyManager()
        self.rate_limiter = RateLimiter(config.auth.rate_limit_requests_per_minute)
        
        # Initialize with configured keys
        for key in config.auth.allowed_keys:
            self.api_key_manager.add_key(key, "Configured key")
            
    def validate_api_key(self, api_key: str) -> bool:
        """Validate API key"""
        if not self.config.auth.require_api_key:
            return True
            
        return self.api_key_manager.validate_key(api_key)
        
    def check_rate_limit(self, identifier: str) -> bool:
        """Check rate limit for identifier"""
        return self.rate_limiter.is_allowed(identifier)
        
    def get_rate_limit_info(self, identifier: str) -> Dict:
        """Get rate limit information"""
        remaining = self.rate_limiter.get_remaining_requests(identifier)
        return {
            "requests_per_minute": self.config.auth.rate_limit_requests_per_minute,
            "remaining_requests": remaining,
            "reset_time": time.time() + 60
        }
        
    def authenticate_request(self, api_key: str, client_ip: str) -> Dict:
        """Authenticate request and check rate limits"""
        result = {
            "authenticated": False,
            "rate_limited": False,
            "key_info": None,
            "rate_limit_info": None
        }
        
        # Check API key
        if self.validate_api_key(api_key):
            result["authenticated"] = True
            result["key_info"] = self.api_key_manager.get_key_info(api_key)
        else:
            logger.warning("Invalid API key", client_ip=client_ip)
            return result
            
        # Check rate limit (use API key as identifier if available, otherwise IP)
        identifier = api_key if api_key else client_ip
        
        if not self.check_rate_limit(identifier):
            result["rate_limited"] = True
            logger.warning("Rate limit exceeded", 
                          identifier=identifier[:8] + "..." if len(identifier) > 8 else identifier,
                          client_ip=client_ip)
            
        result["rate_limit_info"] = self.get_rate_limit_info(identifier)
        
        return result
        
    def create_api_key(self, description: str = "") -> str:
        """Create new API key"""
        import secrets
        api_key = f"sk-{secrets.token_urlsafe(32)}"
        self.api_key_manager.add_key(api_key, description)
        return api_key
        
    def get_auth_stats(self) -> Dict:
        """Get authentication statistics"""
        keys = self.api_key_manager.list_keys()
        
        total_keys = len(keys)
        active_keys = sum(1 for info in keys.values() if info["active"])
        
        return {
            "total_api_keys": total_keys,
            "active_api_keys": active_keys,
            "rate_limit_rpm": self.config.auth.rate_limit_requests_per_minute,
            "require_api_key": self.config.auth.require_api_key
        }


class SecurityUtils:
    """Security utility functions"""
    
    @staticmethod
    def generate_secure_token(length: int = 32) -> str:
        """Generate cryptographically secure token"""
        import secrets
        return secrets.token_urlsafe(length)
        
    @staticmethod
    def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
        """Hash password with salt"""
        if not salt:
            import secrets
            salt = secrets.token_hex(16)
            
        # Use PBKDF2 for password hashing
        import hashlib
        hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return hashed.hex(), salt
        
    @staticmethod
    def verify_password(password: str, hashed_password: str, salt: str) -> bool:
        """Verify password against hash"""
        import hashlib
        computed_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return hmac.compare_digest(hashed_password, computed_hash.hex())
        
    @staticmethod
    def sanitize_input(input_string: str) -> str:
        """Sanitize user input"""
        # Remove potential XSS characters
        import html
        sanitized = html.escape(input_string)
        
        # Remove null bytes
        sanitized = sanitized.replace('\x00', '')
        
        return sanitized
        
    @staticmethod
    def is_safe_redirect_url(url: str, allowed_hosts: Set[str]) -> bool:
        """Check if URL is safe for redirect"""
        from urllib.parse import urlparse
        
        try:
            parsed = urlparse(url)
            return parsed.netloc in allowed_hosts or not parsed.netloc
        except Exception:
            return False