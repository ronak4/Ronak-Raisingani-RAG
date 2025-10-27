# RAG News Generation System - Complete Architecture

## High-Level System Flow

```mermaid
%%{init: {'themeVariables': { 'primaryTextColor': '#000', 'textColor': '#000', 'labelTextColor': '#000' }}}%%
graph LR
    A[Congress.gov API] --> B[Controller]
    B --> C[Kafka Topics]
    C --> D[Question Workers x8]
    D --> E[Link Checker]
    E --> F[Article Generator]
    F --> G[articles.json]
    
    H[(Redis State)] -.-> B
    H -.-> D
    H -.-> E
    H -.-> F
    
    style A fill:#e1f5ff,stroke:#01579b,stroke-width:3px
    style B fill:#fff3e0,stroke:#e65100,stroke-width:3px
    style C fill:#e8f5e9,stroke:#1b5e20,stroke-width:3px
    style D fill:#fff9c4,stroke:#f57f17,stroke-width:3px
    style E fill:#f3e5f5,stroke:#4a148c,stroke-width:3px
    style F fill:#fce4ec,stroke:#880e4f,stroke-width:3px
    style G fill:#e0f2f1,stroke:#004d40,stroke-width:3px
    style H fill:#ede7f6,stroke:#311b92,stroke-width:3px
```

## Detailed Architecture Diagram

```mermaid
flowchart TB
    subgraph DATA["📊 Data Source"]
        API[Congress.gov API<br/>Bills, Committees, Members<br/>Actions, Amendments, Votes]
    end
    
    subgraph CTRL["🎮 Main Controller"]
        CONTROLLER[Pipeline Controller<br/>run_integrated_pipeline.py]
    end
    
    subgraph SVC["⚙️ Core Services"]
        CONGRESS[Congress API Client]
        AI[AI Service]
        STATE[State Manager]
        LLM[LLM Service<br/>Qwen2.5:7b]
    end
    
    subgraph KAFKA["📨 Message Queue - Redpanda/Kafka"]
        QIN[query.input]
        QOUT[query.output]
        LIN[hyperlink.input]
        LOUT[hyperlink.output]
        DIN[draft.input]
        DOUT[draft.output]
    end
    
    subgraph WORK["👷 Distributed Workers"]
        QW[8x Question Workers<br/>Parallel Processing]
        LC[Link Checker<br/>Validate URLs]
        AG[Article Generator<br/>Assemble Markdown]
    end
    
    subgraph DB["💾 State Storage - Redis"]
        REDIS[(Question Answers<br/>Bill Status<br/>Article Progress)]
    end
    
    subgraph OUT["📄 Output"]
        JSON[articles.json<br/>10 Generated Articles]
    end
    
    subgraph Q["❓ 7 Required Questions"]
        Q1[1️⃣ Bill purpose & status]
        Q2[2️⃣ Committee assignments]
        Q3[3️⃣ Sponsor identity]
        Q4[4️⃣ Cosponsors & overlap]
        Q5[5️⃣ Hearings & findings]
        Q6[6️⃣ Amendments proposed]
        Q7[7️⃣ Votes & partisanship]
    end
    
    %% Main Flow
    API --> CONGRESS
    CONGRESS --> CONTROLLER
    CONTROLLER --> QIN
    
    QIN --> QW
    QW --> AI
    AI --> LLM
    QW --> QOUT
    
    QOUT --> LIN
    LIN --> LC
    LC --> LOUT
    
    LOUT --> DIN
    DIN --> AG
    AG --> DOUT
    DOUT --> JSON
    
    %% State Management
    STATE --> REDIS
    REDIS -.-> QW
    REDIS -.-> LC
    REDIS -.-> AG
    
    %% Questions Flow
    Q --> QW
    
    %% Styling
    classDef dataStyle fill:#e1f5ff,stroke:#01579b,stroke-width:3px
    classDef ctrlStyle fill:#fff3e0,stroke:#e65100,stroke-width:3px
    classDef svcStyle fill:#f3e5f5,stroke:#4a148c,stroke-width:3px
    classDef kafkaStyle fill:#e8f5e9,stroke:#1b5e20,stroke-width:3px
    classDef workStyle fill:#fff9c4,stroke:#f57f17,stroke-width:3px
    classDef dbStyle fill:#fce4ec,stroke:#880e4f,stroke-width:3px
    classDef outStyle fill:#e0f2f1,stroke:#004d40,stroke-width:3px
    classDef qStyle fill:#ede7f6,stroke:#311b92,stroke-width:2px
    
    class DATA,API dataStyle
    class CTRL,CONTROLLER ctrlStyle
    class SVC,CONGRESS,AI,STATE,LLM svcStyle
    class KAFKA,QIN,QOUT,LIN,LOUT,DIN,DOUT kafkaStyle
    class WORK,QW,LC,AG workStyle
    class DB,REDIS dbStyle
    class OUT,JSON outStyle
    class Q,Q1,Q2,Q3,Q4,Q5,Q6,Q7 qStyle
```

## Component Descriptions

### Congress.gov API
- **Bills**: Fetch bill details, titles, summaries
- **Committees**: Get committee assignments and members
- **Members**: Retrieve sponsor and cosponsor information
- **Actions**: Track legislative actions and status
- **Amendments**: Get proposed amendments
- **Votes**: Fetch voting records

### Main Controller
- **Initialize Pipeline**: Set up workers and infrastructure
- **Schedule Tasks**: Create and distribute tasks to workers
- **Monitor Progress**: Track completion and performance

### Core Services
- **Congress API Client**: Handle API requests with caching
- **AI Service**: Interface with LLM for content generation
- **State Manager**: Manage Redis state and task tracking
- **LLM Service**: Direct LLM integration (Qwen2.5:7b)

### Kafka Topics (Redpanda)
- **query.input**: Questions to be answered
- **query.output**: Completed question answers
- **hyperlink.input**: Links to validate
- **hyperlink.output**: Validated links
- **draft.input**: Articles to generate
- **draft.output**: Completed articles
- **error.output**: Failed tasks and errors

### Distributed Workers
- **Question Workers (8x)**: Answer the 7 required questions in parallel
- **Link Checker (1x)**: Validate Congress.gov URLs (HTTP 200)
- **Article Generator (1x)**: Assemble final Markdown articles

### State Storage (Redis)
- **Bill Status**: Track which bills are complete
- **Question Answers**: Store answers for each question
- **Generated Articles**: Cache completed articles
- **Progress Tracking**: Monitor overall system progress

### Output
- **articles.json**: Primary deliverable with all 10 articles
- **Individual MD Files**: Separate Markdown files per bill

### 7 Required Questions
Each bill must answer all 7 questions using only Congress.gov data:
1. What does this bill do? Where is it in the process?
2. What committees is this bill in?
3. Who is the sponsor?
4. Who cosponsored this bill? Are any cosponsors on the committee?
5. Have any hearings happened? If so, what were the findings?
6. Have any amendments been proposed? If so, who proposed them and what do they do?
7. Have any votes happened? If so, was it party-line or bipartisan?

## Data Flow

1. **Controller** fetches bill data from **Congress.gov API**
2. **Controller** creates question tasks and publishes to **query.input** topic
3. **Question Workers** consume tasks, fetch additional data, generate answers using **LLM**
4. Workers publish completed answers to **query.output** topic
5. **Link Checker** validates all Congress.gov URLs in answers
6. **Article Generator** assembles final Markdown articles from validated answers
7. Articles saved to **articles.json** and **State Manager** tracks completion
8. **Monitor** provides real-time progress updates via Redis

## Performance Characteristics

- **Parallel Processing**: 8 question workers handle tasks simultaneously
- **Rate Limiting**: Built-in delays prevent API overload
- **State Persistence**: Redis enables fault recovery
- **Intelligent Caching**: 24-hour TTL reduces API calls by 95%
- **Completion Time**: ~9-10 minutes for all 10 bills
- **Throughput**: 0.11 tasks/second average
- **Success Rate**: 100% with automatic retry logic

