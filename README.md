# RAG News Generation System

A distributed, high-throughput article generation system that produces Markdown-based news stories about U.S. congressional bills using only structured data from the Congress.gov API.

## 🎯 Project Overview

This system implements a Retrieval-Augmented Generation (RAG) pipeline that:
- Fetches data for 10 specific congressional bills from Congress.gov API
- Answers 7 fixed questions for each bill using open-source LLMs
- Generates short, news-style articles in Markdown format with hyperlinks
- Outputs structured JSON files containing all generated articles
- Uses Kafka-like distributed task system for fast, scalable article creation

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Congress.gov  │───▶│   Redpanda/Kafka │───▶│   Redis State   │
│      API        │    │    Message Bus   │    │    Manager      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │
                                ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Question Workers│◀───│   Message Bus   │───▶│ Link Checkers   │
│   (Answer Q&A)  │    │                 │    │ (Validate URLs) │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │Article Generator │
                       │ (Final Article) │
                       └─────────────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │  Output JSON    │
                       │  (10 Articles)  │
                       └─────────────────┘
```

### Core Components

- **Controller**: Main orchestrator that manages the pipeline
- **Question Workers**: Answer the 7 required questions for each bill
- **Link Checkers**: Validate all URLs return HTTP 200
- **Article Generator**: Assembles final Markdown articles
- **State Manager**: Tracks task completion using Redis
- **Congress API Client**: Fetches and caches data from Congress.gov

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose
- 8GB+ RAM recommended
- Congress.gov API key
- Local LLM runtime (Ollama) with model `qwen2.5:7b` pulled and running

### One-command run (recommended)

Use the provided script to set up everything (venv, dependencies, Docker services) and run the pipeline end-to-end:

```bash
./Run_Me.sh
```

Note: If needed, make it executable first with `chmod +x Run_Me.sh`.

### Setup Instructions

1. **Clone and Setup Environment**
   ```bash
   git clone <repository-url>
   cd newsGen
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure Environment**
   ```bash
   cp config.example.env .env
   # Edit .env with your API keys
   ```

3. **Start Infrastructure**
   ```bash
   docker-compose up -d
   ```

4. **Run the Pipeline** (manual alternative to the script above)
   ```bash
   python run_integrated_pipeline.py
   ```

### Expected Output

The system will process all 10 bills and generate articles in approximately 9-10 minutes:

```
RAG News Generation - Integrated Pipeline
================================================================================
================================================================================
Initializing integrated pipeline...
Created 10 workers
  - 8 question workers
  - 1 link checker
  - 1 article generator
Starting all workers...
All workers started successfully

================================================================================
Starting news generation pipeline...
Processing 10 bills with 70 total questions...
================================================================================


================================================================================
PROGRESS: Articles 0/10 (0.0%) | Tasks: 0/70 | Speed: 0.00/s | Time Elapsed: 0m 18s
  H.R.1        0/7       
  H.R.5371     0/7       
  H.R.5401     0/7       
  S.2296       0/7       
  S.24         0/7       
  S.2882       0/7       
  S.499        0/7       
  S.RES.412    0/7       
  H.RES.353    0/7       
  H.R.1968     0/7       
================================================================================
```

## 📊 Performance

- **Target Bills**: 10 congressional bills
- **Questions per Bill**: 7 required questions
- **Total Tasks**: 70 question-answer pairs
- **Expected Completion**: ~9-10 minutes
- **Throughput**: ~0.11 tasks/second
- **Success Rate**: 100% (with retry logic)

## 📁 Project Structure

```
newsGen/
├── src/
│   ├── controller.py              # Main pipeline controller
│   ├── services/
│   │   ├── congress_api.py        # Congress.gov API client
│   │   ├── ai_service.py          # AI LLM service integration
│   │   └── state_manager.py       # Redis state management
│   ├── workers/
│   │   ├── question_worker.py     # Question answering worker
│   │   ├── link_checker.py       # URL validation worker
│   │   └── article_generator.py   # Article assembly worker
│   └── utils/
│       ├── schemas.py             # Data models and schemas
│       ├── kafka_client_simple.py # Kafka client utilities
│       └── performance_monitor.py # Performance tracking
├── output/
│   └── articles.json              # Generated articles output
├── cache/                         # API response cache
├── docker-compose.yml             # Infrastructure setup
├── Dockerfile                     # Container configuration
├── requirements.txt               # Python dependencies
└── run_integrated_pipeline.py    # Main execution script
```

## 🔧 Configuration

### Environment Variables

```bash
# Required
CONGRESS_API_KEY=your_congress_api_key

# Optional
REDIS_HOST=localhost
REDIS_PORT=6379
KAFKA_BOOTSTRAP_SERVERS=localhost:19092
```

### Worker Configuration

The system is optimized for stability and performance:

- **Question Workers**: 8 workers (parallel processing)
- **Link Checkers**: 1 worker
- **Article Generator**: 1 worker
- **Concurrent Tasks per Worker**: up to 12 
- **Timeout**: 180 seconds per LLM call
- **Retry Logic**: 3 attempts with exponential backoff

## 📋 Required Questions

Each bill is analyzed for these 7 questions:

1. **What does this bill do? Where is it in the process?**
2. **What committees is this bill in?**
3. **Who is the sponsor?**
4. **Who cosponsored this bill? Are any of the cosponsors on the committee that the bill is in?**
5. **Have any hearings happened on the bill? If so, what were the findings?**
6. **Have any amendments been proposed on the bill? If so, who proposed them and what do they do?**
7. **Have any votes happened on the bill? If so, was it a party-line vote or a bipartisan one?**

## 📄 Output Format

Articles are saved to `output/articles.json` with this schema:

```json
[
  {
    "bill_id": "H.R.1",
    "bill_title": "Lower Energy Costs Act",
    "sponsor_bioguide_id": "S001176",
    "bill_committee_ids": ["hsii00", "hsif00", "hspw00", "hsbu00", "hsag00"],
    "article_content": "In the ongoing debate over energy costs, Rep. Steve Scalise [R-LA-1] has introduced H.R. 1, the Lower Energy Costs Act, aiming to alleviate financial burdens on American families and businesses..."
  }
]
```

## 🧪 Testing

Run the smoke test to verify system functionality:

```bash
python -m pytest tests/ -v
```

## 🐳 Docker Support

The system includes full Docker containerization:

```bash
# Build and run
docker-compose up --build

# Run in container
docker run -it --rm newsgen python run_integrated_pipeline.py
```

## 📈 Monitoring

The system provides real-time progress monitoring:

- **Progress Updates**: Every 15 seconds
- **Task Tracking**: Redis-based state management
- **Performance Metrics**: Throughput and completion times
- **Error Handling**: Automatic retry with exponential backoff

## 🔍 Troubleshooting

### Common Issues

1. **API Rate Limits**: System includes built-in rate limiting and retry logic
2. **Memory Usage**: Optimized for 8GB+ RAM systems
3. **Network Timeouts**: 180-second timeout with retry logic
4. **Docker Issues**: Ensure Docker Desktop is running

### Debug Mode

Enable verbose logging:

```bash
python run_integrated_pipeline.py --verbose
```

## 📊 Benchmark Results

**Latest Run**: 9m 47s for 10 articles
- **Throughput**: 0.11 tasks/second
- **Success Rate**: 100%
- **Memory Usage**: ~8GB peak
- **API Calls**: 70+ Congress.gov requests (cached)

## 🎯 Optimization Approach

The system is optimized for both speed and accuracy through:

1. **Parallel Processing**: Multiple workers handle different tasks simultaneously
2. **Intelligent Caching**: API responses cached to avoid rate limits
3. **Balanced Concurrency**: Optimized worker count prevents API overload
4. **Robust Error Handling**: Automatic retry with exponential backoff
5. **State Management**: Redis tracks progress for fault tolerance

This approach ensures reliable completion of all 10 articles in under 10 minutes while maintaining high accuracy and proper hyperlink validation.

---

**Author**: Ronak Raisingani  
**Project**: RAG News Generation Challenge  
**Completion**: 10/10 articles generated successfully
