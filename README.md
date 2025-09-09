# Claude-DeepSeek Proxy

A high-performance proxy service that adapts Claude API calls to work with DeepSeek-V3.1 via OpenAI-compatible gateways, providing seamless integration between Claude Code and DeepSeek models.

## Features

- **Full Claude API Compatibility**: Complete message format conversion between Claude and OpenAI APIs
- **Tool Calling Support**: Seamless adaptation of Claude tool calls to OpenAI function calling
- **Streaming Responses**: Real-time streaming with proper SSE format conversion
- **DeepSeek Optimization**: Automatic thinking mode detection and parameter optimization
- **Production Ready**: Authentication, rate limiting, error handling, and health checks

## Architecture

```
┌─────────────┐    ┌─────────────────┐    ┌──────────────┐    ┌─────────────┐
│ Claude Code │───▶│ Claude-DeepSeek │───▶│ OpenAI       │───▶│ DeepSeek-V3 │
│             │    │     Proxy       │    │ Gateway      │    │             │
└─────────────┘    └─────────────────┘    └──────────────┘    └─────────────┘
```

## Quick Start

### 1. Prerequisites

- Docker and Docker Compose
- OpenAI兼容的DeepSeek网关服务
- 网关的API端点和密钥

### 2. Setup

```bash
# Clone and setup
git clone <repository>
cd claude-deepseek-proxy

# Copy and configure environment
cp .env.example .env
# Edit .env with your OpenAI gateway settings

# Start services
./start.sh
```

### 3. Configure Claude Code

```bash
# Set environment variables for Claude Code
export ANTHROPIC_BASE_URL="http://localhost:8080/v1"
export ANTHROPIC_API_KEY="sk-your-api-key"

# Test connection
claude-code "Hello, can you help me write a Python function?"
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_BASE_URL` | OpenAI compatible gateway endpoint | `https://your-gateway.com/v1` |
| `OPENAI_API_KEY` | Gateway API key | Required |
| `ALLOWED_API_KEYS` | Comma-separated Claude API keys | Required |
| `DEEPSEEK_THINKING` | Enable thinking mode | `false` |
| `LOG_LEVEL` | Log level | `INFO` |

### Advanced Configuration

Edit `config/default.yaml` for fine-tuned control:

```yaml
openai:
  base_url: "https://your-gateway.com/v1"
  api_key: "your-gateway-api-key"
  timeout: 300

deepseek:
  model_name: "deepseek-v3.1"
  default_thinking: false
  max_tokens: 8192
  temperature: 0.7

auth:
  require_api_key: true
  rate_limit_requests_per_minute: 60
```

## API Compatibility

### Supported Claude API Endpoints

| Claude Endpoint | Status | Notes |
|----------------|--------|--------|
| `/v1/messages` | ✅ | Full support with streaming |
| `/v1/models` | ✅ | Returns DeepSeek model info |
| `/health` | ✅ | Health check endpoint |

### Supported Features

- ✅ Text generation
- ✅ Tool/Function calling
- ✅ Streaming responses
- ✅ System prompts
- ✅ Message history
- ✅ Temperature control
- ✅ Max tokens control
- ✅ DeepSeek thinking mode
- ❌ Multimodal (text + images) - DeepSeek limitation

## DeepSeek Features

### Automatic Thinking Mode

The proxy automatically enables DeepSeek's thinking mode for:
- Mathematical calculations
- Code generation tasks
- Complex reasoning problems
- Multi-step analysis

### Parameter Optimization

Automatic parameter tuning based on task type:

| Task Type | Temperature | Top-P | Thinking Mode |
|-----------|-------------|-------|---------------|
| Code | 0.1 | 0.9 | ✅ |
| Reasoning | 0.3 | 0.8 | ✅ |
| Creative | 0.8 | 0.95 | ❌ |
| Analysis | 0.2 | 0.85 | ✅ |

## Monitoring

### Metrics Available

- Request/response metrics
- Cache hit rates
- DeepSeek feature usage
- Tool execution statistics
- Error rates and types

### Accessing Dashboards

- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000 (admin/admin)
- **Proxy Metrics**: http://localhost:8080/metrics

## Performance

### Caching Strategy

- **Memory Cache**: Fast access for recent requests
- **Redis Cache**: Persistent cache across restarts
- **Smart TTL**: Different cache times based on content type
- **Cache Keys**: SHA-256 hashed request fingerprints

### Expected Performance

| Metric | Value |
|--------|-------|
| Cache Hit Rate | 30-60% (depends on usage) |
| Response Time | <2s (cached), <10s (uncached) |
| Throughput | 10-50 RPS (depends on hardware) |
| Memory Usage | ~500MB (proxy only) |

## Development

### Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Start Redis
docker run -d -p 6379:6379 redis:7-alpine

# Start vLLM separately (see vLLM docs)

# Run proxy
python -m src.main
```

### Project Structure

```
src/
├── core/           # Core conversion logic
│   ├── converter.py    # Claude ↔ OpenAI format conversion
│   ├── tools.py       # Tool calling adaptation
│   ├── streaming.py   # Streaming response handling
│   └── deepseek.py    # DeepSeek-specific features
├── utils/          # Utilities
│   ├── config.py      # Configuration management
│   ├── auth.py        # Authentication & rate limiting
│   ├── cache.py       # Caching system
│   └── monitoring.py  # Metrics & health checks
└── main.py         # FastAPI application
```

### Testing

```bash
# Run tests
python -m pytest tests/

# Test specific component
python -m pytest tests/test_converter.py

# Integration test
curl -X POST http://localhost:8080/v1/messages \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'
```

## Troubleshooting

### Common Issues

1. **vLLM Connection Failed**
   - Check GPU availability: `nvidia-smi`
   - Verify vLLM is running: `curl http://localhost:8000/health`
   - Check model loading: `docker-compose logs vllm`

2. **Authentication Errors**
   - Verify API key in environment variables
   - Check allowed keys configuration
   - Ensure proper Bearer token format

3. **Cache Issues**
   - Check Redis connection: `redis-cli ping`
   - Verify Redis URL configuration
   - Check Redis logs: `docker-compose logs redis`

4. **Performance Issues**
   - Monitor GPU utilization
   - Check cache hit rates at `/metrics`
   - Adjust batch sizes and concurrent requests

### Debug Mode

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG

# Run with detailed logs
docker-compose up
```

## Production Deployment

### Security Considerations

- Use strong API keys
- Enable TLS/HTTPS in production
- Configure firewall rules
- Regular security updates
- Monitor for unusual patterns

### Scaling

- **Horizontal**: Run multiple proxy instances behind load balancer
- **Vertical**: Increase resources for individual services
- **Caching**: Use Redis Cluster for large-scale caching
- **Monitoring**: Set up alerting for key metrics

### Resource Requirements

| Component | CPU | RAM | Storage | GPU |
|-----------|-----|-----|---------|-----|
| Proxy | 2-4 cores | 2-4 GB | 10 GB | - |
| vLLM | 16+ cores | 32+ GB | 100+ GB | 8x H100 |
| Redis | 1-2 cores | 2-8 GB | 50+ GB | - |
| Monitoring | 1-2 cores | 2-4 GB | 20+ GB | - |

## License

[Your License Here]

## Contributing

1. Fork the repository
2. Create feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit pull request

## Support

- GitHub Issues: Report bugs and feature requests
- Documentation: Check wiki for detailed guides
- Community: Join discussions