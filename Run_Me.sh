
: '
/**
 * RAG News Generation - Integrated Pipeline Runner
 * Usage: ./Run_Me.sh
 * Description: Prepares environment, starts infrastructure, and runs the pipeline.
 */
'

echo "🚀 RAG News Generation - Integrated Pipeline"
echo "================================================================================"
echo ""

: '
/**
 * Check if Docker is running
 */
'
if ! docker info > /dev/null 2>&1; then
    echo "Docker is not running!"
    echo "Please start Docker Desktop and try again."
    echo ""
    exit 1
fi

: '
/**
 * Check if Ollama is installed and running
 */
'
echo "🤖 Checking Ollama installation..."

# Check if Ollama is installed
if ! command -v ollama &> /dev/null; then
    echo "Ollama is not installed!"
    echo ""
    echo "Please install Ollama:"
    echo "  macOS: brew install ollama"
    echo "  Linux: curl -fsSL https://ollama.ai/install.sh | sh"
    echo "  Windows: Download from https://ollama.ai/download"
    echo ""
    echo "After installation, run this script again."
    exit 1
fi

# Check if Ollama service is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "Ollama service is not running!"
    echo "Starting Ollama service with 32768 token context window..."
    # Set context length environment variable as backup (though model parameter should handle it)
    OLLAMA_CONTEXT_LENGTH=32768 ollama serve &
    
    # Wait for Ollama to start
    echo "Waiting for Ollama to start (10 seconds)..."
    sleep 10
    
    # Verify Ollama is now running
    if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "Failed to start Ollama service!"
        echo "Please start Ollama manually: ollama serve"
        echo "Then run this script again."
        exit 1
    fi
fi

echo "Ollama is running"
echo ""

: '
/**
 * Check if required model is available
 */
'
echo "📥 Checking for required model (qwen2.5:7b-32k)..."

# Check if base qwen2.5:7b model is available (needed to create custom model)
if ! ollama list | grep -q "qwen2.5:7b"; then
    echo "Base model qwen2.5:7b not found!"
    echo "Downloading qwen2.5:7b model (this may take several minutes)..."
    echo ""
    
    # Download the base model
    if ollama pull qwen2.5:7b; then
        echo "Base model qwen2.5:7b downloaded successfully"
    else
        echo "Failed to download model qwen2.5:7b"
        echo "Please check your internet connection and try again."
        exit 1
    fi
fi

# Check if custom model with 32k context window exists
if ! ollama list | grep -q "qwen2.5:7b-32k"; then
    echo "Custom model qwen2.5:7b-32k not found!"
    echo "Creating custom model with 32768 token context window..."
    echo ""
    
    # Create the custom model from Modelfile
    if [ -f "qwen2.5-7b-32k.Modelfile" ]; then
        if ollama create qwen2.5:7b-32k -f qwen2.5-7b-32k.Modelfile; then
            echo "✅ Custom model qwen2.5:7b-32k created successfully"
        else
            echo "❌ Failed to create custom model"
            echo "Please ensure Ollama is running and try again."
            exit 1
        fi
    else
        echo "❌ Modelfile qwen2.5-7b-32k.Modelfile not found!"
        echo "Creating it now..."
        cat > qwen2.5-7b-32k.Modelfile << 'EOF'
FROM qwen2.5:7b

# Set context window to 32768 tokens (full support for qwen2.5:7b)
PARAMETER num_ctx 32768
EOF
        if ollama create qwen2.5:7b-32k -f qwen2.5-7b-32k.Modelfile; then
            echo "✅ Custom model qwen2.5:7b-32k created successfully"
        else
            echo "❌ Failed to create custom model"
            exit 1
        fi
    fi
else
    echo "✅ Custom model qwen2.5:7b-32k is available"
fi

echo ""

: '
/**
 * Ensure .env exists (create from example if missing)
 */
'
if [ ! -f .env ]; then
    echo "No .env file found!"
    echo "Creating .env from config.example.env..."
    cp config.example.env .env
    echo ""
    echo "Please edit .env and add your API keys:"
    echo "   - CONGRESS_API_KEY (required for Congress.gov)"
    echo ""
    echo "Then run this script again."
    exit 1
fi

: '
/**
 * Create Python virtual environment if it does not exist
 */
'
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    echo "Virtual environment created"
    echo ""
fi

: '
/**
 * Activate virtual environment and install dependencies
 */
'
echo "🔧 Activating virtual environment..."
source venv/bin/activate

echo "Installing dependencies..."
pip install -q -r requirements.txt
echo "Dependencies installed"
echo ""

: '
/**
 * Start Docker infrastructure (Redpanda + Redis)
 */
'
echo "Starting Docker infrastructure (Redpanda + Redis)..."
docker-compose up -d
echo "Docker services started"
echo ""

: '
/**
 * Wait for services to initialize
 */
'
echo "Waiting for services to initialize (5 seconds)..."
sleep 5
echo ""

: '
/**
 * Flush Redis for a clean start
 */
'
echo "Flushing Redis for fresh start..."
docker exec redis redis-cli FLUSHALL > /dev/null 2>&1
echo "Redis flushed"
echo ""

: '
/**
 * Final health check before starting pipeline
 */
'
echo "🔍 Performing final health check..."

# Check Ollama one more time
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "❌ Ollama health check failed!"
    echo "Please ensure Ollama is running: ollama serve"
    exit 1
fi

# Test model availability
if ! ollama list | grep -q "qwen2.5:7b-32k"; then
    echo "❌ Model qwen2.5:7b-32k not available!"
    echo "Please ensure the custom model is created."
    exit 1
fi

echo "✅ All systems ready!"
echo ""

: '
/**
 * Run the pipeline
 */
'
echo "================================================================================"
echo "Starting the RAG News Generation Pipeline..."
echo "================================================================================"
echo ""

python run_integrated_pipeline.py
PIPELINE_EXIT_CODE=$?

: '
/**
 * Cleanup: Stop Ollama if we started it
 */
'
echo ""
echo "🧹 Cleaning up..."

# Check if we started Ollama in this session
if pgrep -f "ollama serve" > /dev/null; then
    echo "Stopping Ollama service..."
    pkill -f "ollama serve" 2>/dev/null || true
    sleep 2
fi

echo "Cleanup completed"
echo ""

: '
/**
 * Handle pipeline exit status
 */
'
if [ $PIPELINE_EXIT_CODE -eq 0 ]; then
    echo "================================================================================"
    echo "Pipeline completed successfully!"
    echo "Check output/articles.json for generated articles"
    echo "================================================================================"
else
    echo "================================================================================"
    echo "Pipeline failed. Check the logs above for errors."
    echo "================================================================================"
    exit 1
fi

