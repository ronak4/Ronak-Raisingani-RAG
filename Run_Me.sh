
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
    echo "Starting Ollama service..."
    ollama serve &
    
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
echo "📥 Checking for required model (qwen2.5:7b)..."

# Check if qwen2.5:7b model is available
if ! ollama list | grep -q "qwen2.5:7b"; then
    echo "Model qwen2.5:7b not found!"
    echo "Downloading qwen2.5:7b model (this may take several minutes)..."
    echo ""
    
    # Download the model
    if ollama pull qwen2.5:7b; then
        echo "Model qwen2.5:7b downloaded successfully"
    else
        echo "Failed to download model qwen2.5:7b"
        echo "Please check your internet connection and try again."
        exit 1
    fi
else
    echo "✅ Model qwen2.5:7b is available"
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
if ! ollama list | grep -q "qwen2.5:7b"; then
    echo "❌ Model qwen2.5:7b not available!"
    echo "Please ensure the model is downloaded: ollama pull qwen2.5:7b"
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

