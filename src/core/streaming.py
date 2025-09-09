"""
Streaming response handler for Claude API compatibility
"""
import json
import asyncio
from typing import AsyncIterator, Dict, Any, Optional
import structlog
import aiohttp
from dataclasses import dataclass

logger = structlog.get_logger(__name__)


@dataclass
class StreamChunk:
    """Represents a streaming chunk"""
    data: Dict[str, Any]
    event_type: str = "message"
    raw_data: str = ""


class StreamingHandler:
    """Handle streaming responses between OpenAI and Claude formats"""
    
    def __init__(self):
        self.buffer = StreamBuffer()
        
    def _get_model_name(self) -> str:
        """Get model name from config"""
        try:
            from src.utils.config import ConfigManager
            config = ConfigManager().config
            return config.deepseek.model_name
        except Exception:
            return "deepseek-v3.1"  # Fallback
        
    async def stream_openai_to_claude(
        self, 
        openai_stream: AsyncIterator[bytes],
        request_id: str
    ) -> AsyncIterator[str]:
        """Convert OpenAI streaming response to Claude SSE format"""
        logger.info("Starting stream conversion", request_id=request_id)
        
        try:
            # Send initial message start event
            yield self._format_sse_event({
                "type": "message_start",
                "message": {
                    "id": f"msg_{request_id}",
                    "type": "message", 
                    "role": "assistant",
                    "model": self._get_model_name(),
                    "content": [],
                    "usage": {"input_tokens": 0, "output_tokens": 0}
                }
            })
            
            # Send content block start
            yield self._format_sse_event({
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "text",
                    "text": ""
                }
            })
            
            async for chunk in openai_stream:
                try:
                    chunk_data = self._parse_openai_chunk(chunk)
                    if chunk_data:
                        claude_chunk = self._convert_chunk_to_claude(chunk_data)
                        if claude_chunk:
                            yield self._format_sse_event(claude_chunk)
                            
                except Exception as e:
                    logger.warning("Error processing stream chunk", 
                                 error=str(e), request_id=request_id)
                    continue
                    
            # Send content block stop
            yield self._format_sse_event({
                "type": "content_block_stop",
                "index": 0
            })
            
            # Send message stop
            yield self._format_sse_event({
                "type": "message_stop"
            })
            
        except Exception as e:
            logger.error("Stream conversion error", error=str(e), request_id=request_id)
            yield self._format_sse_event({
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": "Streaming error occurred"
                }
            })
            
    def _parse_openai_chunk(self, chunk: bytes) -> Optional[Dict[str, Any]]:
        """Parse OpenAI SSE chunk"""
        try:
            chunk_str = chunk.decode('utf-8').strip()
            if not chunk_str:
                return None
                
            # Handle SSE format: "data: {...}"
            if chunk_str.startswith("data: "):
                data_str = chunk_str[6:]  # Remove "data: " prefix
                
                if data_str == "[DONE]":
                    return {"finish_reason": "stop"}
                    
                return json.loads(data_str)
                
            return None
            
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.warning("Failed to parse chunk", error=str(e))
            return None
            
    def _convert_chunk_to_claude(self, openai_chunk: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert OpenAI chunk to Claude format"""
        if not openai_chunk.get("choices"):
            return None
            
        choice = openai_chunk["choices"][0]
        delta = choice.get("delta", {})
        
        # Handle content delta
        if "content" in delta and delta["content"] is not None:
            return {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "text_delta",
                    "text": delta["content"]
                }
            }
            
        # Handle tool call deltas
        if "tool_calls" in delta:
            tool_calls = delta["tool_calls"]
            if tool_calls and len(tool_calls) > 0:
                tool_call = tool_calls[0]
                
                # Tool call start
                if "function" in tool_call and "name" in tool_call["function"]:
                    return {
                        "type": "content_block_start",
                        "index": 1,
                        "content_block": {
                            "type": "tool_use",
                            "id": tool_call.get("id", ""),
                            "name": tool_call["function"]["name"]
                        }
                    }
                    
                # Tool arguments delta
                if "function" in tool_call and "arguments" in tool_call["function"]:
                    return {
                        "type": "content_block_delta", 
                        "index": 1,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": tool_call["function"]["arguments"]
                        }
                    }
                    
        # Handle completion
        if choice.get("finish_reason"):
            finish_reason = self._convert_finish_reason(choice["finish_reason"])
            return {
                "type": "message_delta",
                "delta": {
                    "stop_reason": finish_reason
                },
                "usage": openai_chunk.get("usage", {})
            }
            
        return None
        
    def _convert_finish_reason(self, openai_reason: str) -> str:
        """Convert OpenAI finish reason to Claude format"""
        mapping = {
            "stop": "end_turn",
            "length": "max_tokens",
            "function_call": "tool_use", 
            "tool_calls": "tool_use",
            "content_filter": "stop_sequence"
        }
        return mapping.get(openai_reason, "end_turn")
        
    def _format_sse_event(self, data: Dict[str, Any], event: str = "message") -> str:
        """Format data as Server-Sent Event"""
        json_data = json.dumps(data, separators=(',', ':'))
        return f"event: {event}\ndata: {json_data}\n\n"


class StreamBuffer:
    """Buffer for streaming data management"""
    
    def __init__(self, buffer_size: int = 1024):
        self.buffer = []
        self.buffer_size = buffer_size
        self.total_size = 0
        
    def add_chunk(self, chunk: str) -> bool:
        """Add chunk to buffer, return True if buffer should be flushed"""
        self.buffer.append(chunk)
        self.total_size += len(chunk)
        
        return self.total_size >= self.buffer_size
        
    def flush_buffer(self) -> str:
        """Flush buffer and return combined data"""
        if not self.buffer:
            return ""
            
        combined = "".join(self.buffer)
        self.buffer.clear()
        self.total_size = 0
        
        return combined
        
    def is_complete_message(self, chunk: str) -> bool:
        """Check if chunk represents a complete message"""
        return chunk.endswith("\n\n") or "[DONE]" in chunk


class AsyncStreamProcessor:
    """Process streaming responses asynchronously"""
    
    def __init__(self, max_concurrent: int = 10):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.active_streams = {}
        
    async def process_stream(
        self,
        stream_id: str,
        openai_response: aiohttp.ClientResponse
    ) -> AsyncIterator[str]:
        """Process a streaming response"""
        async with self.semaphore:
            self.active_streams[stream_id] = {
                "start_time": asyncio.get_event_loop().time(),
                "chunks_processed": 0
            }
            
            try:
                handler = StreamingHandler()
                
                async def chunk_generator():
                    async for chunk in openai_response.content:
                        self.active_streams[stream_id]["chunks_processed"] += 1
                        yield chunk
                        
                async for event in handler.stream_openai_to_claude(
                    chunk_generator(), 
                    stream_id
                ):
                    yield event
                    
            finally:
                if stream_id in self.active_streams:
                    stream_info = self.active_streams.pop(stream_id)
                    duration = asyncio.get_event_loop().time() - stream_info["start_time"]
                    
                    logger.info("Stream processing completed",
                               stream_id=stream_id,
                               duration_seconds=duration,
                               chunks_processed=stream_info["chunks_processed"])
                               
    def get_active_streams(self) -> Dict[str, Dict]:
        """Get information about active streams"""
        current_time = asyncio.get_event_loop().time()
        
        for stream_id, info in self.active_streams.items():
            info["duration"] = current_time - info["start_time"]
            
        return self.active_streams.copy()
        
    async def cleanup_stale_streams(self, max_age_seconds: int = 300):
        """Clean up stale stream records"""
        current_time = asyncio.get_event_loop().time()
        stale_streams = []
        
        for stream_id, info in self.active_streams.items():
            if current_time - info["start_time"] > max_age_seconds:
                stale_streams.append(stream_id)
                
        for stream_id in stale_streams:
            self.active_streams.pop(stream_id, None)
            logger.warning("Cleaned up stale stream", stream_id=stream_id)


