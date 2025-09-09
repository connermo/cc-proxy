#!/usr/bin/env python3
"""
Quick test to compare proxy vs direct gateway
"""
import asyncio
import time
import json
import aiohttp

# Configuration
PROXY_URL = "http://localhost:8080"
API_KEY = "sk-hongfu001"
GATEWAY_URL = "https://api.siliconflow.cn/v1/chat/completions"
GATEWAY_API_KEY = "sk-hnaqvepsiovesqfkeifhhrzbapjgjerbplmpebuzxdmkirzd"

async def test_proxy():
    """Test via proxy"""
    payload = {
        "messages": [{"role": "user", "content": "Say hi"}],
        "max_tokens": 5,
        "stream": False
    }
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        start = time.time()
        try:
            async with session.post(f"{PROXY_URL}/v1/messages", json=payload, headers=headers) as resp:
                data = await resp.json()
                total_time = time.time() - start
                return {
                    "success": True,
                    "time": total_time,
                    "status": resp.status,
                    "type": "proxy",
                    "content_length": len(str(data))
                }
        except Exception as e:
            return {"success": False, "error": str(e), "time": time.time() - start, "type": "proxy"}

async def test_direct():
    """Test direct to gateway"""
    payload = {
        "model": "Pro/deepseek-ai/DeepSeek-V3.1",
        "messages": [{"role": "user", "content": "Say hi"}],
        "max_tokens": 5,
        "stream": False
    }
    
    headers = {
        "Authorization": f"Bearer {GATEWAY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        start = time.time()
        try:
            async with session.post(GATEWAY_URL, json=payload, headers=headers) as resp:
                data = await resp.json()
                total_time = time.time() - start
                return {
                    "success": True,
                    "time": total_time,
                    "status": resp.status,
                    "type": "direct",
                    "content_length": len(str(data))
                }
        except Exception as e:
            return {"success": False, "error": str(e), "time": time.time() - start, "type": "direct"}

async def test_streaming():
    """Test streaming via proxy"""
    payload = {
        "messages": [{"role": "user", "content": "Say hi"}],
        "max_tokens": 5,
        "stream": True
    }
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        start = time.time()
        first_chunk_time = None
        chunks = 0
        
        try:
            async with session.post(f"{PROXY_URL}/v1/messages", json=payload, headers=headers) as resp:
                async for line in resp.content:
                    if first_chunk_time is None:
                        first_chunk_time = time.time() - start
                    
                    chunks += 1
                    
                total_time = time.time() - start
                return {
                    "success": True,
                    "time": total_time,
                    "first_chunk_time": first_chunk_time,
                    "chunks": chunks,
                    "status": resp.status,
                    "type": "streaming"
                }
        except Exception as e:
            return {"success": False, "error": str(e), "time": time.time() - start, "type": "streaming"}

async def main():
    print("🔍 Quick Performance Test\n")
    
    # Test each method once
    tests = [
        ("Direct Gateway", test_direct),
        ("Proxy Non-Stream", test_proxy),
        ("Proxy Streaming", test_streaming),
    ]
    
    results = []
    
    for name, test_func in tests:
        print(f"Testing {name}...", end=" ", flush=True)
        result = await test_func()
        results.append((name, result))
        
        if result["success"]:
            print(f"✅ {result['time']:.2f}s")
            if "first_chunk_time" in result:
                print(f"   First chunk: {result['first_chunk_time']:.2f}s")
        else:
            print(f"❌ {result.get('error', 'Failed')}")
    
    print("\n📊 Results Summary:")
    print("-" * 40)
    
    for name, result in results:
        if result["success"]:
            status = f"✅ {result['time']:.2f}s"
            if "first_chunk_time" in result:
                status += f" (first chunk: {result['first_chunk_time']:.2f}s)"
        else:
            status = f"❌ {result.get('error', 'Failed')}"
        
        print(f"{name:18} | {status}")
    
    # Analysis
    successful = [(name, r) for name, r in results if r["success"]]
    
    if len(successful) >= 2:
        print("\n🔍 Analysis:")
        
        direct = next((r for name, r in successful if "Direct" in name), None)
        proxy = next((r for name, r in successful if "Non-Stream" in name), None)
        streaming = next((r for name, r in successful if "Streaming" in name), None)
        
        if direct and proxy:
            overhead = proxy["time"] - direct["time"]
            print(f"Proxy overhead: {overhead:+.2f}s")
        
        if streaming and proxy:
            streaming_diff = streaming["time"] - proxy["time"]
            print(f"Streaming vs Non-streaming: {streaming_diff:+.2f}s")
            
            if streaming_diff > 1:
                print("⚠️  Streaming is significantly slower - may indicate streaming implementation issue")
            elif streaming_diff < -1:
                print("✅ Streaming is faster - working as expected")
            else:
                print("✅ Streaming performance is comparable")

if __name__ == "__main__":
    asyncio.run(main())