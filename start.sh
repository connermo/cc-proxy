#!/bin/bash

# Claude-DeepSeek Proxy Startup Script (Remote vLLM)

set -e

echo "🚀 Starting Claude-DeepSeek Proxy with Remote vLLM..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Creating from template..."
    cp .env.example .env
    echo "✅ Please edit .env file with your remote vLLM configuration and run again."
    echo ""
    echo "🔧 Required configuration:"
    echo "   VLLM_ENDPOINT=https://your-vllm-server.com/v1"
    echo "   VLLM_API_KEY=your-remote-vllm-api-key"
    echo "   ALLOWED_API_KEYS=sk-your-claude-api-key"
    exit 1
fi

# Load environment variables
source .env

# Validate required variables for remote vLLM
required_vars=("VLLM_ENDPOINT" "VLLM_API_KEY" "ALLOWED_API_KEYS")
for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo "❌ Required environment variable $var is not set"
        echo "   Please configure your remote vLLM endpoint in .env file"
        exit 1
    fi
done

echo "✅ Environment variables validated"

# Test remote vLLM connection
echo "🔗 Testing connection to remote vLLM server..."
vllm_health_url="${VLLM_ENDPOINT%/v1}/health"

if ! curl -s -f -H "Authorization: Bearer $VLLM_API_KEY" "$vllm_health_url" > /dev/null; then
    echo "❌ Cannot connect to remote vLLM server at $VLLM_ENDPOINT"
    echo "   Please check:"
    echo "   1. VLLM_ENDPOINT is correct"
    echo "   2. VLLM_API_KEY is valid"
    echo "   3. Remote vLLM server is running and accessible"
    echo ""
    echo "   Testing with: curl -H 'Authorization: Bearer $VLLM_API_KEY' '$vllm_health_url'"
    exit 1
fi

echo "✅ Remote vLLM server is accessible"

# Create necessary directories
mkdir -p logs

echo "✅ Directories created"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

echo "✅ Docker is running"

# Build and start services (without local vLLM)
echo "🔧 Building Docker images..."
docker-compose build --no-cache

echo "🚀 Starting services..."
docker-compose up -d

# Wait for services to be ready
echo "⏳ Waiting for services to start..."

# Wait for Redis
echo "Waiting for Redis..."
timeout=60
counter=0
while ! docker-compose exec redis redis-cli ping > /dev/null 2>&1; do
    if [ $counter -ge $timeout ]; then
        echo "❌ Timeout waiting for Redis"
        docker-compose logs redis
        exit 1
    fi
    sleep 2
    counter=$((counter + 2))
    echo -n "."
done
echo " ✅"

# Wait for proxy
echo "Waiting for Claude-DeepSeek proxy..."
timeout=60
counter=0
while ! curl -s http://localhost:8080/health > /dev/null; do
    if [ $counter -ge $timeout ]; then
        echo "❌ Timeout waiting for proxy server"
        docker-compose logs claude-proxy
        exit 1
    fi
    sleep 2
    counter=$((counter + 2))
    echo -n "."
done
echo " ✅"

# Test the complete setup
echo "🧪 Testing end-to-end connection..."
api_key=$(echo $ALLOWED_API_KEYS | cut -d',' -f1)

response=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST http://localhost:8080/v1/messages \
    -H "Authorization: Bearer $api_key" \
    -H "Content-Type: application/json" \
    -d '{"messages": [{"role": "user", "content": "Hello, this is a test"}], "max_tokens": 10}')

if [ "$response" = "200" ]; then
    echo "✅ End-to-end test successful!"
    echo "   Proxy ↔ Remote vLLM ↔ DeepSeek-V3.1 connection working"
else
    echo "❌ End-to-end test failed (HTTP $response)"
    echo "   Check logs: docker-compose logs claude-proxy"
    echo "   Verify remote vLLM server is responding correctly"
    exit 1
fi

echo ""
echo "🎉 Claude-DeepSeek Proxy is running successfully with remote vLLM!"
echo ""
echo "📋 Service URLs:"
echo "   Proxy API:     http://localhost:8080"
echo "   Remote vLLM:   $VLLM_ENDPOINT"
echo "   Prometheus:    http://localhost:9090"
echo "   Grafana:       http://localhost:3000 (admin/admin)"
echo ""
echo "🔧 Configure Claude Code:"
echo "   export ANTHROPIC_BASE_URL='http://localhost:8080/v1'"
echo "   export ANTHROPIC_API_KEY='$api_key'"
echo ""
echo "💡 Test Claude Code integration:"
echo "   claude-code 'Hello, can you help me write a Python function?'"
echo ""
echo "📊 Check status:  curl http://localhost:8080/health"
echo "📈 View metrics:  curl http://localhost:8080/metrics" 
echo "📋 View logs:     docker-compose logs -f"
echo ""
echo "🛑 To stop:       docker-compose down"
echo ""