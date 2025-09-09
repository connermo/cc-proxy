"""
Claude API to OpenAI API message format converter
"""
import json
import uuid
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
import structlog

logger = structlog.get_logger(__name__)


class MessageConverter:
    """Convert between Claude and OpenAI message formats"""
    
    def __init__(self):
        self.request_mapping = {
            "messages": "messages",
            "max_tokens": "max_tokens", 
            "temperature": "temperature",
            "tools": "tools",
            "system": "system_message",
            "stop_sequences": "stop",
            "stream": "stream"
        }
        
    def _get_model_name(self) -> str:
        """Get model name from config"""
        try:
            from src.utils.config import ConfigManager
            config = ConfigManager().config
            return config.deepseek.model_name
        except Exception:
            return "deepseek-v3.1"  # Fallback
        
    def claude_to_openai_request(self, claude_request: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Claude request format to OpenAI format"""
        request_id = str(uuid.uuid4())
        logger.info("Converting Claude request to OpenAI format", request_id=request_id)
        
        openai_request = {
            "model": self._get_model_name(),
            "messages": [],
            "max_tokens": claude_request.get("max_tokens", 4096),
            "temperature": claude_request.get("temperature", 0.7),
            "stream": claude_request.get("stream", False)
        }
        
        # Convert messages
        messages = self._convert_messages(claude_request.get("messages", []))
        
        # Handle system message
        if "system" in claude_request:
            system_message = {
                "role": "system",
                "content": claude_request["system"]
            }
            messages.insert(0, system_message)
            
        openai_request["messages"] = messages
        
        # Handle tools/functions
        if "tools" in claude_request:
            openai_request["tools"] = self._convert_tools(claude_request["tools"])
            openai_request["tool_choice"] = "auto"
            
        # Handle stop sequences
        if "stop_sequences" in claude_request:
            openai_request["stop"] = claude_request["stop_sequences"]
            
        # Add other parameters
        if "top_p" in claude_request:
            openai_request["top_p"] = claude_request["top_p"]
            
        logger.info("Successfully converted Claude request", 
                   request_id=request_id, 
                   message_count=len(messages))
                   
        return openai_request
        
    def _convert_messages(self, claude_messages: List[Dict]) -> List[Dict]:
        """Convert Claude messages to OpenAI format"""
        openai_messages = []
        
        for msg in claude_messages:
            role = msg.get("role")
            content = msg.get("content")
            
            if role == "user":
                openai_messages.append({
                    "role": "user",
                    "content": self._extract_text_content(content)
                })
            elif role == "assistant":
                assistant_msg = {
                    "role": "assistant",
                    "content": self._extract_text_content(content)
                }
                
                # Handle tool calls in assistant message
                tool_calls = self._extract_tool_calls(content)
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                    
                openai_messages.append(assistant_msg)
                
            elif role == "tool":
                # Tool result message
                openai_messages.append({
                    "role": "tool", 
                    "tool_call_id": msg.get("tool_use_id", str(uuid.uuid4())),
                    "content": self._extract_text_content(content)
                })
                
        return openai_messages
        
    def _extract_text_content(self, content: Union[str, List[Dict]]) -> str:
        """Extract text content from Claude format"""
        if isinstance(content, str):
            return content
            
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            return "".join(text_parts)
            
        return str(content)
        
    def _extract_tool_calls(self, content: Union[str, List[Dict]]) -> List[Dict]:
        """Extract tool calls from Claude assistant message"""
        if isinstance(content, str):
            return []
            
        tool_calls = []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_call = {
                        "id": block.get("id", str(uuid.uuid4())),
                        "type": "function",
                        "function": {
                            "name": block.get("name"),
                            "arguments": json.dumps(block.get("input", {}))
                        }
                    }
                    tool_calls.append(tool_call)
                    
        return tool_calls
        
    def _convert_tools(self, claude_tools: List[Dict]) -> List[Dict]:
        """Convert Claude tools to OpenAI functions format"""
        openai_tools = []
        
        for tool in claude_tools:
            openai_tool = {
                "type": "function",
                "function": {
                    "name": tool.get("name"),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {})
                }
            }
            openai_tools.append(openai_tool)
            
        return openai_tools
        
    def openai_to_claude_response(self, openai_response: Dict[str, Any]) -> Dict[str, Any]:
        """Convert OpenAI response to Claude format"""
        response_id = openai_response.get("id", str(uuid.uuid4()))
        choice = openai_response.get("choices", [{}])[0]
        message = choice.get("message", {})
        
        claude_response = {
            "id": f"msg_{response_id}",
            "type": "message",
            "role": "assistant",
            "model": openai_response.get("model", self._get_model_name()),
            "content": [],
            "stop_reason": self._convert_finish_reason(choice.get("finish_reason")),
            "usage": self._convert_usage(openai_response.get("usage", {}))
        }
        
        # Handle text content
        content = message.get("content")
        if content:
            claude_response["content"].append({
                "type": "text",
                "text": content
            })
            
        # Handle tool calls
        tool_calls = message.get("tool_calls", [])
        for tool_call in tool_calls:
            if tool_call.get("type") == "function":
                function = tool_call.get("function", {})
                claude_response["content"].append({
                    "type": "tool_use",
                    "id": tool_call.get("id"),
                    "name": function.get("name"),
                    "input": json.loads(function.get("arguments", "{}"))
                })
                
        return claude_response
        
    def _convert_finish_reason(self, openai_reason: str) -> str:
        """Convert OpenAI finish reason to Claude format"""
        mapping = {
            "stop": "end_turn",
            "length": "max_tokens", 
            "function_call": "tool_use",
            "tool_calls": "tool_use",
            "content_filter": "stop_sequence",
            None: "end_turn"
        }
        return mapping.get(openai_reason, "end_turn")
        
    def _convert_usage(self, openai_usage: Dict) -> Dict:
        """Convert OpenAI usage to Claude format"""
        return {
            "input_tokens": openai_usage.get("prompt_tokens", 0),
            "output_tokens": openai_usage.get("completion_tokens", 0),
            "total_tokens": openai_usage.get("total_tokens", 0)
        }
        
    def openai_stream_to_claude_chunk(self, openai_chunk: Dict[str, Any]) -> Dict[str, Any]:
        """Convert OpenAI streaming chunk to Claude format"""
        if not openai_chunk.get("choices"):
            return None
            
        choice = openai_chunk["choices"][0]
        delta = choice.get("delta", {})
        
        # Handle content delta
        if "content" in delta and delta["content"]:
            return {
                "type": "content_block_delta", 
                "index": 0,
                "delta": {
                    "type": "text_delta",
                    "text": delta["content"]
                }
            }
            
        # Handle tool call delta
        if "tool_calls" in delta:
            tool_calls = delta["tool_calls"]
            if tool_calls and len(tool_calls) > 0:
                tool_call = tool_calls[0]
                if tool_call.get("function", {}).get("arguments"):
                    return {
                        "type": "content_block_delta",
                        "index": 0, 
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": tool_call["function"]["arguments"]
                        }
                    }
                    
        # Handle completion
        if choice.get("finish_reason"):
            return {
                "type": "message_delta",
                "delta": {
                    "stop_reason": self._convert_finish_reason(choice["finish_reason"])
                }
            }
            
        return None