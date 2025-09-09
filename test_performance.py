#!/usr/bin/env python3
"""
Performance test script for Claude-DeepSeek proxy
"""
import asyncio
import time
import json
import aiohttp
import sys
from typing import Dict, Any

# Configuration
PROXY_URL = "http://localhost:8080"
API_KEY = "sk-hongfu001"

class ProxyTester:
    def __init__(self):
        self.session = None
        self.headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "ProxyTester/1.0"
        }
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def test_simple_message(self, stream: bool = False) -> Dict[str, Any]:
        """Test simple message"""
        payload = {
            "messages": [
                {"role": "user", "content": "Hello, just say 'Hi' back"}
            ],
            "max_tokens": 10,
            "stream": stream
        }
        
        start_time = time.time()
        
        try:
            async with self.session.post(
                f"{PROXY_URL}/v1/messages",
                json=payload,
                headers=self.headers
            ) as response:
                
                connection_time = time.time() - start_time
                
                if stream:
                    # Handle streaming response
                    chunks = []
                    first_chunk_time = None
                    
                    async for line in response.content:
                        if first_chunk_time is None:
                            first_chunk_time = time.time() - start_time
                        
                        line = line.decode('utf-8').strip()
                        if line.startswith('data: '):
                            try:
                                chunk_data = json.loads(line[6:])
                                chunks.append(chunk_data)
                            except json.JSONDecodeError:
                                pass
                    
                    total_time = time.time() - start_time
                    
                    return {
                        "success": True,
                        "stream": True,
                        "status": response.status,
                        "connection_time": connection_time,
                        "first_chunk_time": first_chunk_time,
                        "total_time": total_time,
                        "chunks_count": len(chunks)
                    }
                else:
                    # Handle non-streaming response
                    data = await response.json()
                    total_time = time.time() - start_time
                    
                    return {
                        "success": True,
                        "stream": False,
                        "status": response.status,
                        "total_time": total_time,
                        "response_length": len(str(data))
                    }
                    
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "total_time": time.time() - start_time
            }
    
    async def test_medium_message(self, stream: bool = False) -> Dict[str, Any]:
        """Test medium complexity message"""
        payload = {
            "messages": [
                {"role": "user", "content": "Write a short paragraph about Python programming (max 100 words)"}
            ],
            "max_tokens": 150,
            "stream": stream
        }
        
        start_time = time.time()
        
        try:
            async with self.session.post(
                f"{PROXY_URL}/v1/messages",
                json=payload,
                headers=self.headers
            ) as response:
                
                if stream:
                    chunks = []
                    first_chunk_time = None
                    
                    async for line in response.content:
                        if first_chunk_time is None:
                            first_chunk_time = time.time() - start_time
                        
                        line = line.decode('utf-8').strip()
                        if line.startswith('data: '):
                            try:
                                chunk_data = json.loads(line[6:])
                                chunks.append(chunk_data)
                            except json.JSONDecodeError:
                                pass
                    
                    total_time = time.time() - start_time
                    
                    return {
                        "success": True,
                        "stream": True,
                        "status": response.status,
                        "first_chunk_time": first_chunk_time,
                        "total_time": total_time,
                        "chunks_count": len(chunks)
                    }
                else:
                    data = await response.json()
                    total_time = time.time() - start_time
                    
                    return {
                        "success": True,
                        "stream": False,
                        "status": response.status,
                        "total_time": total_time,
                        "tokens_used": data.get("usage", {}).get("total_tokens", 0),
                        "response_length": len(str(data))
                    }
                    
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "total_time": time.time() - start_time
            }
    
    async def test_direct_gateway(self) -> Dict[str, Any]:
        """Test direct gateway performance (bypass proxy)"""
        gateway_url = "https://api.siliconflow.cn/v1/chat/completions"
        gateway_headers = {
            "Authorization": "Bearer sk-hnaqvepsiovesqfkeifhhrzbapjgjerbplmpebuzxdmkirzd",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "Pro/deepseek-ai/DeepSeek-V3.1",
            "messages": [
                {"role": "user", "content": "Hello, just say 'Hi' back"}
            ],
            "max_tokens": 10,
            "stream": False
        }
        
        start_time = time.time()
        
        try:
            async with self.session.post(
                gateway_url,
                json=payload,
                headers=gateway_headers
            ) as response:
                
                data = await response.json()
                total_time = time.time() - start_time
                
                return {
                    "success": True,
                    "direct_gateway": True,
                    "status": response.status,
                    "total_time": total_time,
                    "response_length": len(str(data))
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "total_time": time.time() - start_time
            }

async def run_tests():
    """Run all performance tests"""
    print("🚀 Starting Claude-DeepSeek Proxy Performance Tests\n")
    
    async with ProxyTester() as tester:
        
        tests = [
            ("Simple Non-Streaming", tester.test_simple_message, {"stream": False}),
            ("Simple Streaming", tester.test_simple_message, {"stream": True}),
            ("Medium Non-Streaming", tester.test_medium_message, {"stream": False}),
            ("Medium Streaming", tester.test_medium_message, {"stream": True}),
            ("Direct Gateway", tester.test_direct_gateway, {}),
        ]
        
        results = []
        
        for test_name, test_func, kwargs in tests:
            print(f"📊 Running {test_name}...")
            
            # Run test 3 times for average
            test_results = []
            for i in range(3):
                print(f"   Attempt {i+1}/3...", end="", flush=True)
                result = await test_func(**kwargs)
                test_results.append(result)
                
                if result["success"]:
                    print(f" {result['total_time']:.2f}s")
                else:
                    print(f" FAILED: {result.get('error', 'Unknown error')}")
            
            # Calculate averages
            successful_results = [r for r in test_results if r["success"]]
            if successful_results:
                avg_time = sum(r["total_time"] for r in successful_results) / len(successful_results)
                min_time = min(r["total_time"] for r in successful_results)
                max_time = max(r["total_time"] for r in successful_results)
                
                summary = {
                    "test_name": test_name,
                    "attempts": len(test_results),
                    "successful": len(successful_results),
                    "avg_time": avg_time,
                    "min_time": min_time,
                    "max_time": max_time,
                    "details": successful_results[0] if successful_results else None
                }
                results.append(summary)
                
                print(f"   ✅ Average: {avg_time:.2f}s (min: {min_time:.2f}s, max: {max_time:.2f}s)")
            else:
                print(f"   ❌ All attempts failed")
            
            print()
        
        # Print summary
        print("=" * 60)
        print("📈 PERFORMANCE TEST SUMMARY")
        print("=" * 60)
        
        for result in results:
            print(f"{result['test_name']:20} | Avg: {result['avg_time']:6.2f}s | "
                  f"Range: {result['min_time']:.2f}s - {result['max_time']:.2f}s | "
                  f"Success: {result['successful']}/{result['attempts']}")
        
        print("\n🔍 ANALYSIS:")
        
        # Compare streaming vs non-streaming
        simple_non_stream = next((r for r in results if "Simple Non-Streaming" in r["test_name"]), None)
        simple_stream = next((r for r in results if "Simple Streaming" in r["test_name"]), None)
        
        if simple_non_stream and simple_stream:
            diff = simple_stream["avg_time"] - simple_non_stream["avg_time"]
            if abs(diff) > 0.5:  # More than 500ms difference
                if diff > 0:
                    print(f"⚠️  Streaming is {diff:.2f}s slower than non-streaming")
                else:
                    print(f"✅ Streaming is {abs(diff):.2f}s faster than non-streaming")
            else:
                print(f"✅ Streaming and non-streaming performance is similar (±{abs(diff):.2f}s)")
        
        # Compare proxy vs direct
        direct_gateway = next((r for r in results if "Direct Gateway" in r["test_name"]), None)
        proxy_simple = simple_non_stream
        
        if direct_gateway and proxy_simple:
            proxy_overhead = proxy_simple["avg_time"] - direct_gateway["avg_time"]
            if proxy_overhead > 0.1:  # More than 100ms overhead
                print(f"⚠️  Proxy adds {proxy_overhead:.2f}s overhead")
            else:
                print(f"✅ Proxy overhead is minimal ({proxy_overhead:.2f}s)")
        
        # Check if gateway is the bottleneck
        if direct_gateway and direct_gateway["avg_time"] > 5:
            print(f"⚠️  Direct gateway is slow ({direct_gateway['avg_time']:.2f}s) - this is the main bottleneck")
        
        print("\n💡 RECOMMENDATIONS:")
        print("- If direct gateway is slow: Contact gateway provider or try alternative gateway")
        print("- If proxy overhead is high: Optimize proxy processing")
        print("- If streaming is much slower: Check streaming implementation")

if __name__ == "__main__":
    print("Claude-DeepSeek Proxy Performance Tester")
    print("Make sure your proxy is running on localhost:8080")
    print()
    
    try:
        asyncio.run(run_tests())
    except KeyboardInterrupt:
        print("\n🛑 Tests interrupted by user")
    except Exception as e:
        print(f"❌ Test failed: {e}")