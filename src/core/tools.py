"""
Tool calling adapter for Claude to OpenAI function calling
"""
import json
import uuid
from typing import List, Dict, Any, Optional
import structlog

logger = structlog.get_logger(__name__)


class ToolAdapter:
    """Adapter for Claude tool calling to OpenAI function calling"""
    
    def __init__(self):
        self.supported_tools = set()
        
    def validate_claude_tool(self, tool: Dict[str, Any]) -> bool:
        """Validate Claude tool definition"""
        required_fields = ["name", "description", "input_schema"]
        
        for field in required_fields:
            if field not in tool:
                logger.warning("Missing required field in tool", field=field, tool_name=tool.get("name"))
                return False
                
        # Validate input schema
        schema = tool.get("input_schema", {})
        if not isinstance(schema, dict) or schema.get("type") != "object":
            logger.warning("Invalid input schema", tool_name=tool.get("name"))
            return False
            
        return True
        
    def convert_claude_tools_to_openai(self, claude_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert Claude tools to OpenAI functions"""
        openai_tools = []
        
        for tool in claude_tools:
            if not self.validate_claude_tool(tool):
                continue
                
            openai_tool = {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool["input_schema"]
                }
            }
            
            # Add tool to supported set
            self.supported_tools.add(tool["name"])
            openai_tools.append(openai_tool)
            
        logger.info("Converted Claude tools to OpenAI format", 
                   tool_count=len(openai_tools),
                   tool_names=[t["function"]["name"] for t in openai_tools])
                   
        return openai_tools
        
    def convert_tool_use_to_function_call(self, tool_use: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Claude tool_use to OpenAI function call"""
        function_call = {
            "id": tool_use.get("id", str(uuid.uuid4())),
            "type": "function",
            "function": {
                "name": tool_use.get("name"),
                "arguments": json.dumps(tool_use.get("input", {}))
            }
        }
        
        logger.debug("Converted tool use to function call",
                    tool_name=tool_use.get("name"),
                    tool_id=function_call["id"])
                    
        return function_call
        
    def convert_function_call_to_tool_use(self, function_call: Dict[str, Any]) -> Dict[str, Any]:
        """Convert OpenAI function call to Claude tool_use"""
        function = function_call.get("function", {})
        
        try:
            arguments = json.loads(function.get("arguments", "{}"))
        except json.JSONDecodeError:
            logger.warning("Failed to parse function arguments", 
                          function_name=function.get("name"),
                          arguments=function.get("arguments"))
            arguments = {}
            
        tool_use = {
            "type": "tool_use",
            "id": function_call.get("id", str(uuid.uuid4())),
            "name": function.get("name"),
            "input": arguments
        }
        
        return tool_use
        
    def handle_tool_result(self, tool_result: Any, tool_name: str, tool_id: str) -> Dict[str, Any]:
        """Handle and format tool execution result"""
        if isinstance(tool_result, dict) and "error" in tool_result:
            # Handle tool error
            return {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "is_error": True,
                "content": [{
                    "type": "text",
                    "text": f"Tool execution failed: {tool_result['error']}"
                }]
            }
            
        # Format successful result
        if isinstance(tool_result, str):
            content_text = tool_result
        elif isinstance(tool_result, dict):
            content_text = json.dumps(tool_result, indent=2)
        else:
            content_text = str(tool_result)
            
        return {
            "type": "tool_result", 
            "tool_use_id": tool_id,
            "content": [{
                "type": "text",
                "text": content_text
            }]
        }
        
    def validate_tool_result(self, result: Dict[str, Any]) -> bool:
        """Validate tool result format"""
        if not isinstance(result, dict):
            return False
            
        required_fields = ["type", "tool_use_id"]
        for field in required_fields:
            if field not in result:
                return False
                
        if result["type"] != "tool_result":
            return False
            
        return True


class ToolResultHandler:
    """Handle tool execution results and errors"""
    
    def __init__(self):
        self.execution_history = {}
        
    def format_tool_result(self, result: Any, tool_name: str) -> Dict[str, Any]:
        """Format tool execution result"""
        if result is None:
            return {"content": "Tool executed successfully with no output"}
            
        if isinstance(result, Exception):
            return {
                "error": str(result),
                "type": "execution_error"
            }
            
        if isinstance(result, dict):
            return result
            
        if isinstance(result, (list, tuple)):
            return {"content": json.dumps(result, indent=2)}
            
        return {"content": str(result)}
        
    def handle_tool_error(self, error: Exception, tool_name: str, tool_input: Dict) -> Dict[str, Any]:
        """Handle tool execution errors"""
        error_info = {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "tool_name": tool_name,
            "tool_input": tool_input,
            "timestamp": str(uuid.uuid4())
        }
        
        logger.error("Tool execution error", **error_info)
        
        return {
            "type": "tool_error",
            "error": f"{error_info['error_type']}: {error_info['error_message']}",
            "details": error_info
        }
        
    def validate_tool_schema(self, tool_schema: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate tool JSON schema"""
        try:
            # Basic validation
            if not isinstance(tool_schema, dict):
                return False, "Tool schema must be a dictionary"
                
            if tool_schema.get("type") != "object":
                return False, "Tool schema type must be 'object'"
                
            properties = tool_schema.get("properties", {})
            if not isinstance(properties, dict):
                return False, "Tool schema properties must be a dictionary"
                
            # Validate each property
            for prop_name, prop_schema in properties.items():
                if not isinstance(prop_schema, dict):
                    return False, f"Property '{prop_name}' schema must be a dictionary"
                    
                if "type" not in prop_schema:
                    return False, f"Property '{prop_name}' must have a type"
                    
            return True, None
            
        except Exception as e:
            return False, f"Schema validation error: {str(e)}"
            
    def record_tool_execution(self, tool_name: str, tool_input: Dict, result: Any, duration: float):
        """Record tool execution for monitoring"""
        execution_record = {
            "tool_name": tool_name,
            "input": tool_input,
            "result_type": type(result).__name__,
            "duration_ms": duration * 1000,
            "success": not isinstance(result, Exception),
            "timestamp": str(uuid.uuid4())
        }
        
        self.execution_history[execution_record["timestamp"]] = execution_record
        
        logger.info("Tool execution completed",
                   tool_name=tool_name,
                   duration_ms=execution_record["duration_ms"],
                   success=execution_record["success"])
                   
    def get_execution_stats(self) -> Dict[str, Any]:
        """Get tool execution statistics"""
        if not self.execution_history:
            return {"total_executions": 0}
            
        total = len(self.execution_history)
        successful = sum(1 for record in self.execution_history.values() if record["success"])
        
        tool_counts = {}
        total_duration = 0
        
        for record in self.execution_history.values():
            tool_name = record["tool_name"]
            tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
            total_duration += record["duration_ms"]
            
        return {
            "total_executions": total,
            "successful_executions": successful,
            "failed_executions": total - successful,
            "success_rate": successful / total if total > 0 else 0,
            "average_duration_ms": total_duration / total if total > 0 else 0,
            "tool_usage": tool_counts
        }