# System Architecture

## High-Level Architecture Diagram

```mermaid
graph TB
    subgraph "Data Sources"
        API[Congress.gov API]
    end
    
    subgraph "Message Queue Layer"
        KAFKA[Redpanda/Kafka<br/>Message Bus]
        REDIS[Redis<br/>State Manager]
    end
    
    subgraph "Processing Workers"
        QW[Question Workers<br/>Answer 7 Questions]
        LC[Link Checkers<br/>Validate URLs]
        AG[Article Generator<br/>Assemble Articles]
    end
    
    subgraph "Output"
        JSON[articles.json<br/>10 Generated Articles]
    end
    
    API --> KAFKA
    KAFKA --> QW
    KAFKA --> LC
    KAFKA --> AG
    QW --> KAFKA
    LC --> KAFKA
    AG --> KAFKA
    AG --> JSON
    REDIS --> QW
    REDIS --> LC
    REDIS --> AG
```

## Detailed Component Architecture

```mermaid
graph LR
    subgraph "Controller Layer"
        CTRL[NewsGenerationController]
        STATE[StateManager]
    end
    
    subgraph "Data Layer"
        CONG[CongressAPIClient]
        CACHE[Response Cache]
    end
    
    subgraph "LLM Layer"
        OLLAMA[Local Ollama Service<br/>qwen2.5:7b Model]
    end
    
    subgraph "Worker Layer"
        QW1[Question Worker 1]
        QW2[Question Worker 2]
        LC1[Link Checker 1]
        AG1[Article Generator]
    end
    
    subgraph "Infrastructure"
        KAFKA[Redpanda]
        REDIS[Redis]
        DOCKER[Docker Containers]
    end
    
    CTRL --> CONG
    CTRL --> KAFKA
    CTRL --> STATE
    CONG --> CACHE
    CONG --> API[Congress.gov API]
    QW1 --> OLLAMA
    QW2 --> OLLAMA
    LC1 --> HTTP[HTTP Client]
    AG1 --> OLLAMA
    STATE --> REDIS
    KAFKA --> QW1
    KAFKA --> QW2
    KAFKA --> LC1
    KAFKA --> AG1
```

## Data Flow Architecture

```mermaid
sequenceDiagram
    participant C as Controller
    participant API as Congress.gov API
    participant K as Kafka/Redpanda
    participant QW as Question Workers
    participant LC as Link Checkers
    participant AG as Article Generator
    participant OLLAMA as Local Ollama
    participant R as Redis
    participant O as Output JSON
    
    C->>API: Fetch bill data
    API-->>C: Bill information
    C->>K: Publish question tasks
    K->>QW: Consume question tasks
    QW->>API: Get additional data
    QW->>OLLAMA: Generate answers
    OLLAMA-->>QW: AI responses
    QW->>K: Publish answers
    K->>LC: Consume link check tasks
    LC->>HTTP: Validate URLs
    LC->>K: Publish link results
    K->>AG: Consume article tasks
    AG->>R: Check completion status
    AG->>OLLAMA: Generate article
    OLLAMA-->>AG: Complete article
    AG->>O: Generate final article
    AG->>K: Publish completion
```

## Message Flow Architecture

```mermaid
graph TD
    subgraph "Input Topics"
        QI[query.input]
        LI[hyperlink.input]
        DI[draft.input]
    end
    
    subgraph "Output Topics"
        QO[query.output]
        LO[hyperlink.output]
        DO[draft.output]
        EO[error.output]
    end
    
    subgraph "Workers"
        QW[Question Workers]
        LC[Link Checkers]
        AG[Article Generator]
    end
    
    QI --> QW
    QW --> QO
    QO --> LI
    LI --> LC
    LC --> LO
    LO --> DI
    DI --> AG
    AG --> DO
    QW --> EO
    LC --> EO
    AG --> EO
```

## Performance Architecture

```mermaid
graph TB
    subgraph "Performance Monitoring"
        PM[Performance Monitor]
        METRICS[Task Metrics]
        STATS[Completion Stats]
    end
    
    subgraph "Optimization Features"
        CACHE[Response Caching]
        RETRY[Retry Logic]
        RATE[Rate Limiting]
    end
    
    subgraph "Scalability"
        PARALLEL[Parallel Workers]
        LOAD[Load Balancing]
        QUEUE[Task Queuing]
    end
    
    PM --> METRICS
    METRICS --> STATS
    CACHE --> API[Congress.gov API]
    RETRY --> WORKERS[All Workers]
    RATE --> API
    PARALLEL --> WORKERS
    LOAD --> KAFKA[Kafka Topics]
    QUEUE --> KAFKA
```

## Container Architecture

```mermaid
graph TB
    subgraph "Docker Compose Services"
        REDPANDA[Redpanda<br/>Kafka Alternative]
        REDIS[Redis<br/>State Store]
        CONSOLE[Redpanda Console<br/>Monitoring]
    end
    
    subgraph "Application Containers"
        CONTROLLER[Controller Container]
        WORKERS[Worker Containers]
    end
    
    subgraph "External Services"
        CONGRESS[Congress.gov API]
        OLLAMA[Local Ollama<br/>AI Service]
    end
    
    REDPANDA --> CONTROLLER
    REDIS --> CONTROLLER
    CONSOLE --> REDPANDA
    CONTROLLER --> WORKERS
    WORKERS --> CONGRESS
    WORKERS --> OLLAMA
```

## Security Architecture

```mermaid
graph TB
    subgraph "API Security"
        KEY[API Key Management]
        RATE[Rate Limiting]
        CACHE[Response Caching]
    end
    
    subgraph "Network Security"
        DOCKER[Docker Network Isolation]
        LOCAL[Local Development]
        PROD[Production Ready]
    end
    
    subgraph "Data Security"
        ENV[Environment Variables]
        SECRETS[Secret Management]
        LOGS[Audit Logging]
    end
    
    KEY --> ENV
    RATE --> API[External APIs]
    CACHE --> REDIS[Redis Cache]
    DOCKER --> CONTAINERS[Application Containers]
    ENV --> SECRETS
    SECRETS --> LOGS
```

This architecture ensures:
- **Scalability**: Multiple workers can process tasks in parallel
- **Reliability**: Redis state management and retry logic
- **Performance**: Caching and rate limiting optimization
- **Monitoring**: Real-time progress tracking and metrics
- **Security**: API key management and network isolation
