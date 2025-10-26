
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
 * Run the pipeline
 */
'
echo "================================================================================"
echo "Starting the RAG News Generation Pipeline..."
echo "================================================================================"
echo ""

python run_integrated_pipeline.py

: '
/**
 * Handle pipeline exit status
 */
'
if [ $? -eq 0 ]; then
    echo ""
    echo "================================================================================"
    echo "Pipeline completed successfully!"
    echo "Check output/articles.json for generated articles"
    echo "================================================================================"
else
    echo ""
    echo "================================================================================"
    echo "Pipeline failed. Check the logs above for errors."
    echo "================================================================================"
    exit 1
fi

