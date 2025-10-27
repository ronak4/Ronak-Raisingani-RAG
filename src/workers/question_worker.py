"""
/**
 * @file question_worker.py
 * @summary Worker that answers the seven required questions for each bill
 *          using local LLM inference and Congress.gov data.
 *
 * @details
 * - Consumes logical "question-tasks" messages with bill_id and question_id.
 * - Fetches/uses cached bill data, invokes the LLM to generate answers, and
 *   extracts Congress.gov links from the output.
 * - Stores answers in state, publishes results, and triggers downstream tasks
 *   (link checking and article generation) as milestones are reached.
 */
"""

import asyncio
import logging
import time
import uuid
from typing import Dict, Any, List
from services.congress_api import CongressAPIClient
from services.ai_service import AIService
from services.state_manager import StateManager
from utils.kafka_client_simple import KafkaProducer, KafkaConsumer
from utils.schemas import KafkaMessage, QuestionAnswer, QuestionType


class QuestionWorker:
    """
    /**
     * Worker that processes question tasks and generates answers.
     *
     * @param worker_id: Optional stable identifier for logs/metrics.
     * @param config: Configuration dict (Redis, Kafka, LLM model, etc.).
     */
    """
    
    def __init__(self, worker_id: str = None, config: Dict[str, Any] = None):
        self.worker_id = worker_id or f"question-worker-{uuid.uuid4().hex[:8]}"
        self.config = config or {}
        
        # Initialize services
        self.congress_api = CongressAPIClient(
            api_key=self.config.get('congress_api_key'),
            cache_dir=self.config.get('cache_dir', 'cache')
        )
        # AI service (supports OpenAI-compatible APIs including local Ollama)
        self.llm_service = AIService(
            model=self.config.get('groq_model')
        )
        self.state_manager = StateManager(
            redis_host=self.config.get('redis_host', 'localhost'),
            redis_port=self.config.get('redis_port', 6379),
            redis_db=self.config.get('redis_db', 0)
        )
        
        # Kafka clients
        self.producer = KafkaProducer(
            bootstrap_servers=self.config.get('kafka_bootstrap_servers', 'localhost:19092')
        )
        self.consumer = KafkaConsumer(
            bootstrap_servers=self.config.get('kafka_bootstrap_servers', 'localhost:19092'),
            group_id=self.config.get('kafka_group_id', 'question-workers')
        )
        
        # Worker state
        self.tasks_processed = 0
        self.errors_count = 0
        self.running = False
        
        # Parallel processing control
        # Increase safe concurrency with Qwen2.5:7b
        self.max_concurrent_tasks = self.config.get('max_concurrent_tasks', 12)
        self.semaphore = asyncio.Semaphore(self.max_concurrent_tasks)
        
        # Setup logging - only INFO and ERROR, no DEBUG
        log_level = logging.INFO if self.config.get('verbose', False) else logging.ERROR
        self.logger = logging.getLogger(f"QuestionWorker-{self.worker_id}")
        self.logger.setLevel(log_level)
        
        # Suppress httpx/httpcore debug logs
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    async def start(self):
        """
        /**
         * Start the worker, connect to state, and begin consuming tasks.
         */
        """
        try:
            # Connect to services
            await self.state_manager.connect()
            self.logger.info(f"Started question worker: {self.worker_id}")
            
            # Update worker status
            await self.state_manager.update_worker_status(
                self.worker_id, "running", self.tasks_processed, self.errors_count
            )
            
            self.running = True
            
            self.logger.info(f"Worker started with max {self.max_concurrent_tasks} concurrent tasks")
            
            # Start consuming messages
            await self.consumer.start_consuming(
                message_handler=self._handle_message_wrapper,
                topics=["question-tasks"]
            )
            
        except Exception as e:
            self.logger.error(f"Failed to start worker: {e}")
            await self.state_manager.update_worker_status(
                self.worker_id, "error", self.tasks_processed, self.errors_count
            )
            raise
    
    async def stop(self):
        """
        /**
         * Stop the worker and close underlying clients.
         */
        """
        self.running = False
        try:
            if hasattr(self.consumer, 'stop'):
                self.consumer.stop()
        except:
            pass
        try:
            if hasattr(self.producer, 'close'):
                self.producer.close()
        except:
            pass
        self.logger.info(f"Stopped question worker: {self.worker_id}")
    
    async def _handle_message_wrapper(self, message: KafkaMessage):
        """
        /**
         * Wrapper that limits parallelism using a semaphore.
         */
        """
        async with self.semaphore:
            await self._handle_message(message)
    
    async def _handle_message(self, message: KafkaMessage):
        """
        /**
         * Handle a single question task end-to-end.
         *
         * @param message: KafkaMessage containing bill_id and question_id.
         */
        """
        from utils.performance_monitor import get_monitor
        task_id = f"{message.bill_id}-Q{message.question_id}"
        
        try:
            # Start tracking
            await get_monitor().start_task(task_id, "question")
            self.logger.info(f"[{self.worker_id}] Processing: {message.bill_id} - Q{message.question_id}")
            
            # Check if already answered
            existing_answer = await self.state_manager.get_question_answer(
                message.bill_id, message.question_id
            )
            if existing_answer:
                self.logger.debug(f"Question already answered: {message.bill_id} - Q{message.question_id}")
                await get_monitor().end_task(task_id, success=True)
                return
            
            # Fetch bill data
            self.logger.debug(f"Fetching bill data for {message.bill_id}")
            bill_data = await self.congress_api.get_bill_data(message.bill_id)
            self.logger.debug(f"Bill data fetched for {message.bill_id}")
            
            # Generate answer using LLM
            self.logger.debug(f"Generating answer for {message.bill_id} - Q{message.question_id}")
            answer = await self.llm_service.answer_question(bill_data, message.question_id)
            self.logger.debug(f"Answer generated for {message.bill_id} - Q{message.question_id}")
            
            # Extract sources from the answer (URLs)
            sources = self._extract_sources_from_answer(answer)
            
            # Store answer in Redis
            question_answer = QuestionAnswer(
                bill_id=message.bill_id,
                question_id=message.question_id,
                answer=answer,
                sources=sources,
                confidence=0.9,  # High confidence for LLM-generated answers
                generated_at=time.time()
            )
            
            await self.state_manager.store_question_answer(
                message.bill_id, message.question_id, answer, sources, 0.9
            )
            
            # Publish answer to question-answers topic
            answer_message = KafkaMessage(
                bill_id=message.bill_id,
                question_id=message.question_id,
                task_type="answer_question",
                payload={
                    "answer": answer,
                    "sources": sources,
                    "confidence": 0.9,
                    "worker_id": self.worker_id
                }
            )
            
            await self.producer.publish_message("question-answers", answer_message, message.bill_id)
            
            # Publish URLs for link checking
            if sources:
                from utils.schemas import TaskType
                link_check_message = KafkaMessage(
                    bill_id=message.bill_id,
                    question_id=None,
                    task_type=TaskType.CHECK_LINKS,
                    payload={"urls": sources}
                )
                await self.producer.publish_message("link-check-tasks", link_check_message, message.bill_id)
            
            # Check if all questions are answered for this bill
            all_answered = await self.state_manager.are_all_questions_answered(message.bill_id)
            if all_answered:
                self.logger.info(f"All questions answered for {message.bill_id}, triggering article generation")
                from utils.schemas import TaskType
                article_message = KafkaMessage(
                    bill_id=message.bill_id,
                    question_id=None,
                    task_type=TaskType.GENERATE_ARTICLE,
                    payload={"bill_id": message.bill_id}
                )
                await self.producer.publish_message("article-tasks", article_message, message.bill_id)
            
            # Update stats
            self.tasks_processed += 1
            await self.state_manager.update_worker_status(
                self.worker_id, "running", self.tasks_processed, self.errors_count
            )
            
            # End task tracking
            await get_monitor().end_task(task_id, success=True)
            
            self.logger.info(f"Completed: {message.bill_id} - Q{message.question_id} (Total: {self.tasks_processed})")
            
        except Exception as e:
            self.errors_count += 1
            await get_monitor().end_task(task_id, success=False, error=str(e))
            self.logger.error(f"Error processing: {message.bill_id} - Q{message.question_id}: {e}")
            
            await self.state_manager.update_worker_status(
                self.worker_id, "error", self.tasks_processed, self.errors_count
            )
    
    def _extract_sources_from_answer(self, answer: str) -> List[str]:
        """
        /**
         * Extract markdown and plain URLs from an answer.
         */
        """
        import re
        
        # Look for markdown links [text](url)
        url_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        matches = re.findall(url_pattern, answer)
        
        # Extract URLs from matches
        urls = [url for _, url in matches if url.startswith('http')]
        
        # Also look for plain URLs
        plain_url_pattern = r'https?://[^\s\)]+'
        plain_urls = re.findall(plain_url_pattern, answer)
        
        # Combine and deduplicate
        all_urls = list(set(urls + plain_urls))
        
        return all_urls
    
    async def health_check(self) -> Dict[str, Any]:
        """
        /**
         * Perform a basic health check of dependencies and readiness.
         */
        """
        try:
            # Check Redis connection
            await self.state_manager.redis_client.ping()
            
            # Check LLM service
            llm_available = await self.llm_service.check_model_availability()
            
            return {
                "worker_id": self.worker_id,
                "status": "healthy" if llm_available else "degraded",
                "tasks_processed": self.tasks_processed,
                "errors_count": self.errors_count,
                "llm_available": llm_available,
                "redis_connected": True
            }
        except Exception as e:
            return {
                "worker_id": self.worker_id,
                "status": "unhealthy",
                "error": str(e),
                "tasks_processed": self.tasks_processed,
                "errors_count": self.errors_count
            }


# Example usage and testing
async def main():
    """Test the question worker."""
    config = {
        'congress_api_key': None,  # Use public API
        'cache_dir': 'cache',
        'ollama_base_url': 'http://localhost:11434',
        'ollama_model': 'llama3.2:latest',
        'redis_host': 'localhost',
        'redis_port': 6379,
        'kafka_bootstrap_servers': 'localhost:19092',
        'kafka_group_id': 'question-workers'
    }
    
    worker = QuestionWorker(config=config)
    
    try:
        # Test health check
        health = await worker.health_check()
        print(f"Health check: {health}")
        
        # Start worker (this will run indefinitely)
        await worker.start()
        
    except KeyboardInterrupt:
        print("Stopping worker...")
        await worker.stop()
    except Exception as e:
        print(f"Error: {e}")
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
