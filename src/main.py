"""
Main FastAPI server for Claude to DeepSeek proxy
"""
import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

import aiohttp
import structlog
import uvicorn
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware

from src.core.converter import MessageConverter
from src.core.tools import ToolAdapter, ToolResultHandler
from src.core.streaming import StreamingHandler, AsyncStreamProcessor
from src.core.deepseek import DeepSeekFeatures, ModelOptimizer, ResponseProcessor
from src.utils.config import ConfigManager
from src.utils.auth import AuthManager

# Initialize logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


# Global instances
config_manager = ConfigManager()
auth_manager = AuthManager(config_manager.config)

# Core processors
message_converter = MessageConverter()
tool_adapter = ToolAdapter()
tool_result_handler = ToolResultHandler()
deepseek_features = DeepSeekFeatures()
model_optimizer = ModelOptimizer()
response_processor = ResponseProcessor()
stream_processor = AsyncStreamProcessor()

# HTTP client for OpenAI gateway requests
http_client: Optional[aiohttp.ClientSession] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    global http_client
    
    # Startup
    logger.info("Starting Claude-DeepSeek proxy server")
    
    # Initialize HTTP client
    connector = aiohttp.TCPConnector(
        limit=100,
        limit_per_host=20,
        keepalive_timeout=30,
        enable_cleanup_closed=True
    )
    
    timeout = aiohttp.ClientTimeout(total=config_manager.config.openai.timeout)
    http_client = aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers={"Authorization": f"Bearer {config_manager.config.openai.api_key}"}
    )
    
    
    logger.info("Proxy server started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down proxy server")
    
    if http_client:
        await http_client.close()
        
    
    logger.info("Proxy server shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Claude-DeepSeek Proxy",
    description="Proxy server to adapt Claude API calls for DeepSeek-V3.1 via OpenAI gateway",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Validate API key"""
    api_key = credentials.credentials
    logger.info("Validating API key", 
                key_prefix=api_key[:12] + "..." if len(api_key) > 12 else api_key,
                configured_keys=[key[:12] + "..." for key in config_manager.config.auth.allowed_keys])
    
    if not auth_manager.validate_api_key(api_key):
        logger.warning("API key validation failed", 
                      key_prefix=api_key[:12] + "..." if len(api_key) > 12 else api_key)
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    logger.info("API key validated successfully")
    return api_key


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    """Request/response logging middleware"""
    request_id = str(uuid.uuid4())
    
    # Log request
    logger.info("Request received",
               request_id=request_id,
               method=request.method,
               path=request.url.path,
               client_ip=request.client.host)
    
    # Process request
    start_time = asyncio.get_event_loop().time()
    response = await call_next(request)
    duration = asyncio.get_event_loop().time() - start_time
    
    # Log response
    logger.info("Request completed",
               request_id=request_id,
               status_code=response.status_code,
               duration_ms=duration * 1000)
    
    
    return response


@app.post("/v1/messages")
async def create_message(
    request: Request,
    api_key: str = Depends(get_current_user)
):
    """Handle Claude messages API"""
    request_id = str(uuid.uuid4())
    
    try:
        # Parse request
        claude_request = await request.json()
        
        logger.info("Processing Claude messages request",
                   request_id=request_id,
                   stream=claude_request.get("stream", False),
                   has_tools=bool(claude_request.get("tools")))
        
        
        # Convert Claude request to OpenAI format
        openai_request = message_converter.claude_to_openai_request(claude_request)
        
        # Apply DeepSeek optimizations
        openai_request = model_optimizer.optimize_request(openai_request)
        
        # Apply thinking mode if needed
        openai_request = deepseek_features.enable_thinking_mode(openai_request)
        
        # Make request to OpenAI compatible endpoint
        openai_endpoint = f"{config_manager.config.openai.base_url}/chat/completions"
        
        if claude_request.get("stream", False):
            return await handle_streaming_request(openai_request, openai_endpoint, request_id)
        else:
            return await handle_non_streaming_request(
                openai_request, openai_endpoint, request_id
            )
            
    except Exception as e:
        logger.error("Error processing message request",
                    request_id=request_id,
                    error=str(e))
        
        raise HTTPException(
            status_code=500,
            detail={"error": {"type": "api_error", "message": "Internal server error"}}
        )


async def handle_streaming_request(
    openai_request: Dict[str, Any],
    openai_endpoint: str,
    request_id: str
) -> StreamingResponse:
    """Handle streaming request"""
    
    async def stream_generator():
        try:
            async with http_client.post(
                openai_endpoint,
                json=openai_request,
                headers={"Accept": "text/event-stream"}
            ) as response:
                
                if response.status != 200:
                    error_text = await response.text()
                    logger.error("OpenAI gateway request failed",
                               request_id=request_id,
                               status=response.status,
                               error=error_text)
                    yield f"data: {{'error': 'OpenAI gateway request failed'}}\n\n"
                    return
                
                # Process stream
                async for event in stream_processor.process_stream(request_id, response):
                    yield event
                    
        except Exception as e:
            logger.error("Streaming error",
                        request_id=request_id,
                        error=str(e))
            yield f"data: {{'error': 'Streaming error occurred'}}\n\n"
    
    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )


async def handle_non_streaming_request(
    openai_request: Dict[str, Any],
    openai_endpoint: str, 
    request_id: str,
) -> JSONResponse:
    """Handle non-streaming request"""
    
    try:
        async with http_client.post(openai_endpoint, json=openai_request) as response:
            
            if response.status != 200:
                error_text = await response.text()
                logger.error("OpenAI gateway request failed",
                           request_id=request_id,
                           status=response.status,
                           error=error_text)
                raise HTTPException(status_code=response.status, detail=error_text)
            
            # Get response
            openai_response = await response.json()
            
            # Process DeepSeek-specific features
            processed_response = response_processor.process_response(openai_response)
            
            # Convert to Claude format
            claude_response = message_converter.openai_to_claude_response(processed_response)
            
            
            logger.info("Request processed successfully",
                       request_id=request_id,
                       tokens_used=claude_response.get("usage", {}).get("total_tokens", 0))
            
            return JSONResponse(claude_response)
            
    except aiohttp.ClientError as e:
        logger.error("HTTP client error",
                    request_id=request_id,
                    error=str(e))
        raise HTTPException(status_code=502, detail="Upstream service error")
    
    except Exception as e:
        logger.error("Unexpected error",
                    request_id=request_id,
                    error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "service": "Claude-DeepSeek Proxy", 
        "status": "healthy"
    }


@app.get("/status")
async def get_status():
    """Get service status (basic info only)"""
    return {
        "service": "Claude-DeepSeek Proxy",
        "status": "running"
    }


@app.get("/v1/models")
async def list_models(api_key: str = Depends(get_current_user)):
    """List available models (Claude API compatibility)"""
    return {
        "object": "list",
        "data": [
            {
                "id": "deepseek-v3.1",
                "object": "model",
                "created": 1234567890,
                "owned_by": "deepseek-ai",
                "permission": [],
                "root": "deepseek-v3.1",
                "parent": None
            }
        ]
    }


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Claude-DeepSeek Proxy",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "messages": "/v1/messages",
            "models": "/v1/models", 
            "health": "/health",
            "status": "/status"
        }
    }


if __name__ == "__main__":
    # Load configuration
    config = config_manager.config
    
    uvicorn.run(
        "src.main:app",
        host=config.server.host,
        port=config.server.port,
        workers=config.server.workers,
        log_level=config.server.log_level.lower(),
        access_log=True,
        reload=False
    )