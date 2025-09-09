#!/usr/bin/env python3
"""
Test streaming implementation specifically
"""
import asyncio
import time
import json
import aiohttp

PROXY_URL = "http://localhost:8080"
API_KEY = "sk-hongfu001"

async def test_streaming_detailed():
    """Detailed streaming test"""
    payload = {
        "messages": [{"role": "user", "content": "Count from 1 to 5, one number per line"}],
        "max_tokens": 50,
        "stream": True
    }
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        start_time = time.time()
        chunks = []
        chunk_times = []
        
        print("📡 Starting streaming request...")
        
        async with session.post(f"{PROXY_URL}/v1/messages", json=payload, headers=headers) as resp:
            print(f"📊 Response status: {resp.status}")
            print(f"📊 Content-Type: {resp.headers.get('content-type', 'unknown')}")
            
            chunk_count = 0
            async for line in resp.content:
                current_time = time.time() - start_time
                chunk_times.append(current_time)
                
                line_str = line.decode('utf-8').strip()
                if line_str:
                    chunk_count += 1
                    print(f"📦 Chunk {chunk_count} at {current_time:.3f}s: {line_str[:80]}")
                    
                    if line_str.startswith('data: '):
                        try:
                            data = json.loads(line_str[6:])
                            chunks.append(data)
                            
                            # Show meaningful content
                            if data.get("type") == "content_block_delta":
                                text = data.get("delta", {}).get("text", "")
                                if text:
                                    print(f"     📝 Text: {repr(text)}")
                            
                        except json.JSONDecodeError as e:
                            print(f"     ❌ JSON error: {e}")
            
            total_time = time.time() - start_time
            
        print(f"\n📊 Streaming Summary:")
        print(f"   Total time: {total_time:.3f}s")
        print(f"   Raw chunks: {chunk_count}")
        print(f"   Parsed chunks: {len(chunks)}")
        print(f"   First chunk at: {chunk_times[0]:.3f}s" if chunk_times else "No chunks received")
        
        # Analyze chunk types
        chunk_types = {}
        for chunk in chunks:
            chunk_type = chunk.get("type", "unknown")
            chunk_types[chunk_type] = chunk_types.get(chunk_type, 0) + 1
        
        print(f"   Chunk types: {chunk_types}")

async def compare_simple_requests():
    """Compare very simple requests"""
    
    tests = [
        ("Non-streaming simple", {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 5, "stream": False}),
        ("Streaming simple", {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 5, "stream": True})
    ]
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        for name, payload in tests:
            print(f"\n🔍 Testing: {name}")
            start = time.time()
            
            async with session.post(f"{PROXY_URL}/v1/messages", json=payload, headers=headers) as resp:
                if payload["stream"]:
                    chunk_count = 0
                    first_chunk = None
                    
                    async for line in resp.content:
                        if first_chunk is None:
                            first_chunk = time.time() - start
                        chunk_count += 1
                    
                    total = time.time() - start
                    print(f"   ⏱️  Total: {total:.3f}s, First chunk: {first_chunk:.3f}s, Chunks: {chunk_count}")
                else:
                    data = await resp.json()
                    total = time.time() - start
                    usage = data.get("usage", {})
                    print(f"   ⏱️  Total: {total:.3f}s, Tokens: {usage.get('total_tokens', 'unknown')}")

async def main():
    print("🧪 Streaming Implementation Test\n")
    
    await compare_simple_requests()
    
    print("\n" + "="*50)
    print("🔬 Detailed Streaming Analysis")
    print("="*50)
    
    await test_streaming_detailed()

if __name__ == "__main__":
    asyncio.run(main())