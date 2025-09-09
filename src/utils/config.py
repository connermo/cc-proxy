"""
Configuration management for the proxy service
"""
import os
import yaml
from typing import Dict, Any, List
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class ServerConfig(BaseModel):
    """Server configuration"""
    host: str = "0.0.0.0"
    port: int = 8080
    workers: int = 4
    log_level: str = "INFO"


class OpenAIConfig(BaseModel):
    """OpenAI compatible service configuration"""
    base_url: str = "https://your-openai-gateway.com/v1"
    api_key: str = "your-gateway-api-key"
    timeout: int = 300
    max_retries: int = 3


class DeepSeekConfig(BaseModel):
    """DeepSeek model configuration"""
    model_name: str = "deepseek-v3.1"
    default_thinking: bool = False
    max_tokens: int = 8192
    temperature: float = 0.7
    top_p: float = 0.8
    frequency_penalty: float = 0.1
    presence_penalty: float = 0.0


class CacheConfig(BaseModel):
    """Cache configuration"""
    enabled: bool = True
    redis_url: str = "redis://localhost:6379"
    default_ttl: int = 3600
    max_memory_cache_size: int = 1000


class AuthConfig(BaseModel):
    """Authentication configuration"""
    require_api_key: bool = True
    allowed_keys: List[str] = Field(default_factory=list)
    rate_limit_requests_per_minute: int = 60


class MonitoringConfig(BaseModel):
    """Monitoring configuration"""
    enable_metrics: bool = True
    enable_health_check: bool = True
    prometheus_port: int = 9090


class LoggingConfig(BaseModel):
    """Logging configuration"""
    level: str = "INFO"
    format: str = "json"
    file: str = "logs/proxy.log"
    max_size: str = "100MB"
    backup_count: int = 5


class Config(BaseSettings):
    """Main configuration"""
    server: ServerConfig = Field(default_factory=ServerConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    deepseek: DeepSeekConfig = Field(default_factory=DeepSeekConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    class Config:
        env_nested_delimiter = "__"
        case_sensitive = False


class ConfigManager:
    """Configuration manager with file and environment variable support"""
    
    def __init__(self, config_path: str = None):
        self.config_path = config_path or self._get_default_config_path()
        self.config = self._load_config()
        
    def _get_default_config_path(self) -> str:
        """Get default configuration file path"""
        # Try different possible locations
        possible_paths = [
            os.environ.get("PROXY_CONFIG_PATH"),
            "config/default.yaml",
            "/app/config/default.yaml",
            os.path.expanduser("~/.claude-deepseek-proxy/config.yaml")
        ]
        
        for path in possible_paths:
            if path and os.path.exists(path):
                return path
                
        # Return default path even if it doesn't exist
        return "config/default.yaml"
        
    def _load_config(self) -> Config:
        """Load configuration from file and environment variables"""
        config_data = {}
        
        # Load from YAML file if exists
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    file_config = yaml.safe_load(f)
                    if file_config:
                        config_data.update(file_config)
            except Exception as e:
                print(f"Warning: Failed to load config file {self.config_path}: {e}")
        
        # Override with environment variables
        env_overrides = self._get_env_overrides()
        self._merge_configs(config_data, env_overrides)
        
        return Config(**config_data)
        
    def _get_env_overrides(self) -> Dict[str, Any]:
        """Get configuration overrides from environment variables"""
        overrides = {}
        
        # Map environment variables to config structure
        env_mappings = {
            "SERVER_HOST": ["server", "host"],
            "SERVER_PORT": ["server", "port"],
            "SERVER_WORKERS": ["server", "workers"],
            "LOG_LEVEL": ["server", "log_level"],
            
            "OPENAI_BASE_URL": ["openai", "base_url"],
            "OPENAI_API_KEY": ["openai", "api_key"],
            "OPENAI_TIMEOUT": ["openai", "timeout"],
            
            "DEEPSEEK_MODEL": ["deepseek", "model_name"],
            "DEEPSEEK_THINKING": ["deepseek", "default_thinking"],
            "DEEPSEEK_MAX_TOKENS": ["deepseek", "max_tokens"],
            "DEEPSEEK_TEMPERATURE": ["deepseek", "temperature"],
            
            "REDIS_URL": ["cache", "redis_url"],
            "CACHE_ENABLED": ["cache", "enabled"],
            "CACHE_TTL": ["cache", "default_ttl"],
            
            "REQUIRE_API_KEY": ["auth", "require_api_key"],
            "RATE_LIMIT": ["auth", "rate_limit_requests_per_minute"],
            
            "ENABLE_METRICS": ["monitoring", "enable_metrics"],
            "PROMETHEUS_PORT": ["monitoring", "prometheus_port"]
        }
        
        for env_var, config_path in env_mappings.items():
            value = os.environ.get(env_var)
            if value is not None:
                # Convert string values to appropriate types
                converted_value = self._convert_env_value(value)
                self._set_nested_value(overrides, config_path, converted_value)
                
        # Handle special cases
        allowed_keys = os.environ.get("ALLOWED_API_KEYS")
        if allowed_keys:
            keys = [key.strip() for key in allowed_keys.split(",")]
            self._set_nested_value(overrides, ["auth", "allowed_keys"], keys)
            
        return overrides
        
    def _convert_env_value(self, value: str) -> Any:
        """Convert environment variable string to appropriate type"""
        # Boolean conversion
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
            
        # Integer conversion
        try:
            if "." not in value:
                return int(value)
        except ValueError:
            pass
            
        # Float conversion
        try:
            return float(value)
        except ValueError:
            pass
            
        # Return as string
        return value
        
    def _set_nested_value(self, config: Dict, path: List[str], value: Any):
        """Set nested configuration value"""
        current = config
        for key in path[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        current[path[-1]] = value
        
    def _merge_configs(self, base: Dict, override: Dict):
        """Merge override configuration into base"""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_configs(base[key], value)
            else:
                base[key] = value
                
    def reload_config(self):
        """Reload configuration from file"""
        self.config = self._load_config()
        
    def get_config_dict(self) -> Dict[str, Any]:
        """Get configuration as dictionary"""
        return self.config.dict()
        
    def save_config(self, path: str = None):
        """Save current configuration to file"""
        save_path = path or self.config_path
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        with open(save_path, 'w') as f:
            yaml.dump(self.get_config_dict(), f, default_flow_style=False, indent=2)
            
    def validate_config(self) -> List[str]:
        """Validate configuration and return any issues"""
        issues = []
        
        # Validate vLLM endpoint
        if not self.config.vllm.endpoint.startswith(("http://", "https://")):
            issues.append("vLLM endpoint must be a valid HTTP/HTTPS URL")
            
        # Validate ports
        if not (1 <= self.config.server.port <= 65535):
            issues.append("Server port must be between 1 and 65535")
            
        if not (1 <= self.config.monitoring.prometheus_port <= 65535):
            issues.append("Prometheus port must be between 1 and 65535")
            
        # Validate model parameters
        if not (0.0 <= self.config.deepseek.temperature <= 2.0):
            issues.append("Temperature must be between 0.0 and 2.0")
            
        if not (0.0 <= self.config.deepseek.top_p <= 1.0):
            issues.append("top_p must be between 0.0 and 1.0")
            
        # Validate cache settings
        if self.config.cache.enabled and not self.config.cache.redis_url:
            issues.append("Redis URL is required when caching is enabled")
            
        return issues