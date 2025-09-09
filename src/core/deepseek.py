"""
DeepSeek-V3.1 specific features and optimizations
"""
import re
from typing import Dict, Any, Optional, Tuple
import structlog
from enum import Enum

logger = structlog.get_logger(__name__)


class TaskType(Enum):
    """Task types for parameter optimization"""
    CODE = "code"
    REASONING = "reasoning" 
    CREATIVE = "creative"
    ANALYSIS = "analysis"
    DEFAULT = "default"


class DeepSeekFeatures:
    """DeepSeek-V3.1 specific feature management"""
    
    def __init__(self):
        self.thinking_patterns = {
            "math": r"(?i)(?:calculate|solve|equation|formula|math)",
            "code": r"(?i)(?:code|program|function|algorithm|debug)",
            "reasoning": r"(?i)(?:analyze|reason|think|logic|deduce)",
            "creative": r"(?i)(?:create|write|story|poem|creative)"
        }
        
    def enable_thinking_mode(
        self, 
        request: Dict[str, Any], 
        thinking: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Enable/disable DeepSeek thinking mode"""
        
        # Auto-detect if thinking should be enabled
        if thinking is None:
            thinking = self._should_enable_thinking(request)
            
        if thinking:
            if "extra_body" not in request:
                request["extra_body"] = {}
            request["extra_body"]["chat_template_kwargs"] = {"thinking": True}
            
            logger.info("Enabled DeepSeek thinking mode", 
                       auto_detected=thinking is None)
        
        return request
        
    def _should_enable_thinking(self, request: Dict[str, Any]) -> bool:
        """Auto-detect if thinking mode should be enabled"""
        messages = request.get("messages", [])
        
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str):
                # Check for patterns that benefit from thinking
                for pattern_type, pattern in self.thinking_patterns.items():
                    if re.search(pattern, content):
                        logger.debug("Auto-detected thinking pattern", 
                                   pattern_type=pattern_type)
                        return True
                        
        # Enable for complex tool use scenarios
        tools = request.get("tools", [])
        if len(tools) > 2:
            return True
            
        return False
        
    def parse_thinking_response(self, content: str) -> Tuple[Optional[str], str]:
        """Parse DeepSeek thinking response to extract reasoning and final answer"""
        
        # DeepSeek thinking format: <think>...</think> followed by final answer
        thinking_pattern = r'<think>(.*?)</think>(.*)'
        match = re.search(thinking_pattern, content, re.DOTALL)
        
        if match:
            thinking_process = match.group(1).strip()
            final_answer = match.group(2).strip()
            
            logger.debug("Extracted thinking process", 
                        thinking_length=len(thinking_process),
                        answer_length=len(final_answer))
                        
            return thinking_process, final_answer
            
        # If no thinking tags found, treat entire content as final answer
        return None, content
        
    def format_thinking_for_claude(
        self, 
        thinking: Optional[str], 
        answer: str
    ) -> List[Dict[str, Any]]:
        """Format thinking process for Claude response"""
        content_blocks = []
        
        if thinking:
            # Add thinking process as separate content block
            content_blocks.append({
                "type": "text",
                "text": f"**Reasoning Process:**\n{thinking}\n\n**Answer:**\n{answer}"
            })
        else:
            content_blocks.append({
                "type": "text", 
                "text": answer
            })
            
        return content_blocks
        
    def optimize_for_code_generation(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Optimize parameters for code generation tasks"""
        
        # Lower temperature for more deterministic code
        request["temperature"] = 0.1
        request["top_p"] = 0.9
        request["frequency_penalty"] = 0.2
        
        # Enable thinking for complex code tasks
        messages = request.get("messages", [])
        for message in messages:
            content = str(message.get("content", ""))
            if any(word in content.lower() for word in ["implement", "algorithm", "function", "class"]):
                request = self.enable_thinking_mode(request, True)
                break
                
        logger.debug("Applied code generation optimizations")
        return request
        
    def optimize_for_reasoning(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Optimize parameters for reasoning tasks"""
        
        # Moderate temperature for balanced reasoning
        request["temperature"] = 0.3
        request["top_p"] = 0.8
        
        # Always enable thinking for reasoning tasks
        request = self.enable_thinking_mode(request, True)
        
        logger.debug("Applied reasoning optimizations")
        return request
        
    def detect_task_type(self, request: Dict[str, Any]) -> TaskType:
        """Detect the type of task from request content"""
        messages = request.get("messages", [])
        content_text = ""
        
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str):
                content_text += " " + content.lower()
                
        # Check for code patterns
        code_patterns = ["code", "function", "class", "implement", "debug", "program"]
        if any(pattern in content_text for pattern in code_patterns):
            return TaskType.CODE
            
        # Check for reasoning patterns  
        reasoning_patterns = ["analyze", "reason", "solve", "calculate", "logic"]
        if any(pattern in content_text for pattern in reasoning_patterns):
            return TaskType.REASONING
            
        # Check for creative patterns
        creative_patterns = ["write", "create", "story", "poem", "creative"]
        if any(pattern in content_text for pattern in creative_patterns):
            return TaskType.CREATIVE
            
        return TaskType.DEFAULT


class ModelOptimizer:
    """DeepSeek model parameter optimization"""
    
    def __init__(self):
        self.task_configs = {
            TaskType.CODE: {
                "temperature": 0.1,
                "top_p": 0.9,
                "frequency_penalty": 0.2,
                "presence_penalty": 0.0,
                "thinking": True
            },
            TaskType.REASONING: {
                "temperature": 0.3,
                "top_p": 0.8, 
                "frequency_penalty": 0.1,
                "presence_penalty": 0.0,
                "thinking": True
            },
            TaskType.CREATIVE: {
                "temperature": 0.8,
                "top_p": 0.95,
                "frequency_penalty": 0.3,
                "presence_penalty": 0.2,
                "thinking": False
            },
            TaskType.ANALYSIS: {
                "temperature": 0.2,
                "top_p": 0.85,
                "frequency_penalty": 0.1,
                "presence_penalty": 0.1,
                "thinking": True  
            },
            TaskType.DEFAULT: {
                "temperature": 0.7,
                "top_p": 0.8,
                "frequency_penalty": 0.1,
                "presence_penalty": 0.0,
                "thinking": False
            }
        }
        
    def optimize_request(
        self, 
        request: Dict[str, Any], 
        task_type: Optional[TaskType] = None
    ) -> Dict[str, Any]:
        """Optimize request parameters for DeepSeek"""
        
        if task_type is None:
            deepseek = DeepSeekFeatures()
            task_type = deepseek.detect_task_type(request)
            
        config = self.task_configs[task_type]
        
        # Apply optimized parameters
        for param, value in config.items():
            if param == "thinking":
                if value:
                    deepseek = DeepSeekFeatures()
                    request = deepseek.enable_thinking_mode(request, True)
            else:
                request[param] = value
                
        logger.info("Applied DeepSeek optimizations", 
                   task_type=task_type.value,
                   temperature=config["temperature"],
                   thinking_enabled=config["thinking"])
                   
        return request
        
    def get_recommended_max_tokens(self, task_type: TaskType) -> int:
        """Get recommended max tokens for task type"""
        recommendations = {
            TaskType.CODE: 8192,      # Code can be lengthy
            TaskType.REASONING: 4096,  # Reasoning needs space
            TaskType.CREATIVE: 6144,   # Creative content varies
            TaskType.ANALYSIS: 4096,   # Analysis is typically focused
            TaskType.DEFAULT: 4096
        }
        return recommendations[task_type]


        
        
class ResponseProcessor:
    """Process DeepSeek responses for Claude compatibility"""
    
    def __init__(self):
        pass
        
    def process_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Process DeepSeek response"""
        
        # Extract content
        choices = response.get("choices", [])
        if not choices:
            return response
            
        choice = choices[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        
        # Check if response contains thinking
        deepseek = DeepSeekFeatures()
        thinking, answer = deepseek.parse_thinking_response(content)
        
        if thinking:
            
            # Format for Claude
            formatted_content = deepseek.format_thinking_for_claude(thinking, answer)
            message["content"] = formatted_content[0]["text"]
            
        return response