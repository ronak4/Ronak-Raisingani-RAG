"""
/**
 * @file state_manager.py
 * @summary Redis-backed state manager for tracking pipeline progress, question
 *          answers, articles, and worker heartbeats.
 *
 * @details
 * - Stores per-question answers and final generated articles with TTLs for
 *   lightweight persistence.
 * - Tracks bill processing status, processing queue, and completed bills.
 * - Maintains worker heartbeats and simple counters for processed/error tasks.
 * - Provides convenience helpers to aggregate processing statistics.
 *
 * @dependencies
 * - redis.asyncio (async Redis client)
 * - utils.schemas (QuestionAnswer, GeneratedArticle models)
 */
"""

import json
import time
from typing import Dict, List, Optional, Any, Set
import redis.asyncio as redis
from utils.schemas import QuestionAnswer, GeneratedArticle, QuestionType


class StateManagerError(Exception):
    """Custom exception for state management errors."""
    pass


class StateManager:
    """
    /**
     * Manage pipeline state in Redis.
     *
     * @param redis_host: Redis host (default localhost)
     * @param redis_port: Redis port (default 6379)
     * @param redis_db: Redis DB index (default 0)
     */
    """
    
    def __init__(self, redis_host: str = "localhost", redis_port: int = 6379, redis_db: int = 0):
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.redis_client = None
        
        # Key patterns
        self.QUESTION_ANSWER_KEY = "bill:{bill_id}:q{question_id}"
        self.ARTICLE_KEY = "bill:{bill_id}:article"
        self.BILL_STATUS_KEY = "bill:{bill_id}:status"
        self.WORKER_STATUS_KEY = "worker:{worker_id}:status"
        self.PROCESSING_QUEUE_KEY = "processing_queue"
        self.COMPLETED_BILLS_KEY = "completed_bills"
        self.LINK_CHECK_KEY = "bill:{bill_id}:link_check"
    
    async def connect(self):
        """
        /**
         * Establish a connection to Redis and validate connectivity.
         */
        """
        try:
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                decode_responses=True
            )
            # Test connection
            await self.redis_client.ping()
        except Exception as e:
            raise StateManagerError(f"Failed to connect to Redis: {e}")
    
    async def disconnect(self):
        """
        /**
         * Close the Redis connection if present.
         */
        """
        if self.redis_client:
            await self.redis_client.close()
    
    async def _get_key(self, pattern: str, **kwargs) -> str:
        """
        /**
         * Format a Redis key using a templated pattern.
         */
        """
        return pattern.format(**kwargs)
    
    async def store_question_answer(self, bill_id: str, question_id: int, answer: str, 
                                  sources: List[str] = None, confidence: float = 1.0) -> bool:
        """
        /**
         * Persist a question answer for a bill with a TTL.
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            question_answer = QuestionAnswer(
                bill_id=bill_id,
                question_id=question_id,
                answer=answer,
                sources=sources or [],
                confidence=confidence,
                generated_at=time.time()
            )
            
            key = await self._get_key(self.QUESTION_ANSWER_KEY, bill_id=bill_id, question_id=question_id)
            await self.redis_client.set(key, question_answer.model_dump_json(), ex=86400)  # 24 hours TTL
            
            return True
        except Exception as e:
            raise StateManagerError(f"Failed to store question answer: {e}")
    
    async def get_question_answer(self, bill_id: str, question_id: int) -> Optional[QuestionAnswer]:
        """
        /**
         * Retrieve a stored question answer for a bill.
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            key = await self._get_key(self.QUESTION_ANSWER_KEY, bill_id=bill_id, question_id=question_id)
            data = await self.redis_client.get(key)
            
            if data:
                return QuestionAnswer.model_validate_json(data)
            return None
        except Exception as e:
            raise StateManagerError(f"Failed to get question answer: {e}")
    
    async def get_all_question_answers(self, bill_id: str) -> Dict[int, QuestionAnswer]:
        """
        /**
         * Retrieve all seven question answers for a bill (if present).
         */
        """
        answers = {}
        
        for question_id in range(1, 8):  # Questions 1-7
            answer = await self.get_question_answer(bill_id, question_id)
            if answer:
                answers[question_id] = answer
        
        return answers
    
    async def are_all_questions_answered(self, bill_id: str) -> bool:
        """
        /**
         * Check whether all seven required answers exist for the bill.
         */
        """
        answers = await self.get_all_question_answers(bill_id)
        return len(answers) == 7
    
    async def store_article(self, article: GeneratedArticle) -> bool:
        """
        /**
         * Persist a generated article with a TTL.
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            key = await self._get_key(self.ARTICLE_KEY, bill_id=article.bill_id)
            await self.redis_client.set(key, article.model_dump_json(), ex=86400)  # 24 hours TTL
            return True
        except Exception as e:
            raise StateManagerError(f"Failed to store article: {e}")
    
    async def get_article(self, bill_id: str) -> Optional[GeneratedArticle]:
        """
        /**
         * Retrieve a generated article for the given bill if present.
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            key = await self._get_key(self.ARTICLE_KEY, bill_id=bill_id)
            data = await self.redis_client.get(key)
            
            if data:
                return GeneratedArticle.model_validate_json(data)
            return None
        except Exception as e:
            raise StateManagerError(f"Failed to get article: {e}")
    
    async def set_bill_status(self, bill_id: str, status: str, metadata: Dict[str, Any] = None) -> bool:
        """
        /**
         * Set the current processing status for a bill.
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            key = await self._get_key(self.BILL_STATUS_KEY, bill_id=bill_id)
            status_data = {
                "status": status,
                "timestamp": time.time(),
                "metadata": metadata or {}
            }
            await self.redis_client.set(key, json.dumps(status_data), ex=86400)
            return True
        except Exception as e:
            raise StateManagerError(f"Failed to set bill status: {e}")
    
    async def get_bill_status(self, bill_id: str) -> Optional[Dict[str, Any]]:
        """
        /**
         * Retrieve the current processing status for a bill.
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            key = await self._get_key(self.BILL_STATUS_KEY, bill_id=bill_id)
            data = await self.redis_client.get(key)
            
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            raise StateManagerError(f"Failed to get bill status: {e}")
    
    async def add_to_processing_queue(self, bill_id: str) -> bool:
        """
        /**
         * Add a bill to the processing queue (set-based).
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            await self.redis_client.sadd(self.PROCESSING_QUEUE_KEY, bill_id)
            return True
        except Exception as e:
            raise StateManagerError(f"Failed to add to processing queue: {e}")
    
    async def remove_from_processing_queue(self, bill_id: str) -> bool:
        """
        /**
         * Remove a bill from the processing queue.
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            await self.redis_client.srem(self.PROCESSING_QUEUE_KEY, bill_id)
            return True
        except Exception as e:
            raise StateManagerError(f"Failed to remove from processing queue: {e}")
    
    async def get_processing_queue(self) -> Set[str]:
        """
        /**
         * Return all bill identifiers currently in the processing queue.
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            return await self.redis_client.smembers(self.PROCESSING_QUEUE_KEY)
        except Exception as e:
            raise StateManagerError(f"Failed to get processing queue: {e}")
    
    async def mark_bill_completed(self, bill_id: str) -> bool:
        """
        /**
         * Mark a bill as completed, move it out of the queue, and set status.
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            await self.redis_client.sadd(self.COMPLETED_BILLS_KEY, bill_id)
            await self.remove_from_processing_queue(bill_id)
            await self.set_bill_status(bill_id, "completed", {"completed_at": time.time()})
            return True
        except Exception as e:
            raise StateManagerError(f"Failed to mark bill completed: {e}")
    
    async def get_completed_bills(self) -> Set[str]:
        """
        /**
         * Return the set of bill identifiers marked as completed.
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            return await self.redis_client.smembers(self.COMPLETED_BILLS_KEY)
        except Exception as e:
            raise StateManagerError(f"Failed to get completed bills: {e}")
    
    async def update_worker_status(self, worker_id: str, status: str, 
                                 tasks_processed: int = 0, errors_count: int = 0) -> bool:
        """
        /**
         * Update a worker heartbeat/status with light counters.
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            key = await self._get_key(self.WORKER_STATUS_KEY, worker_id=worker_id)
            worker_data = {
                "worker_id": worker_id,
                "status": status,
                "last_heartbeat": time.time(),
                "tasks_processed": tasks_processed,
                "errors_count": errors_count
            }
            await self.redis_client.set(key, json.dumps(worker_data), ex=300)  # 5 minutes TTL
            return True
        except Exception as e:
            raise StateManagerError(f"Failed to update worker status: {e}")
    
    async def get_worker_status(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """
        /**
         * Retrieve the most recent status record for a worker.
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            key = await self._get_key(self.WORKER_STATUS_KEY, worker_id=worker_id)
            data = await self.redis_client.get(key)
            
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            raise StateManagerError(f"Failed to get worker status: {e}")
    
    async def clear_bill_data(self, bill_id: str) -> bool:
        """
        /**
         * Remove answers, article, and status for a bill to enable retries.
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            # Clear question answers
            for question_id in range(1, 8):
                key = await self._get_key(self.QUESTION_ANSWER_KEY, bill_id=bill_id, question_id=question_id)
                await self.redis_client.delete(key)
            
            # Clear article
            article_key = await self._get_key(self.ARTICLE_KEY, bill_id=bill_id)
            await self.redis_client.delete(article_key)
            
            # Clear status
            status_key = await self._get_key(self.BILL_STATUS_KEY, bill_id=bill_id)
            await self.redis_client.delete(status_key)
            
            return True
        except Exception as e:
            raise StateManagerError(f"Failed to clear bill data: {e}")
    
    async def get_processing_stats(self) -> Dict[str, Any]:
        """
        /**
         * Compute a simple summary of overall processing progress.
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            processing_queue = await self.get_processing_queue()
            completed_bills = await self.get_completed_bills()
            
            return {
                "bills_in_queue": len(processing_queue),
                "bills_completed": len(completed_bills),
                "total_bills": len(processing_queue) + len(completed_bills),
                "completion_rate": len(completed_bills) / (len(processing_queue) + len(completed_bills)) if (len(processing_queue) + len(completed_bills)) > 0 else 0
            }
        except Exception as e:
            raise StateManagerError(f"Failed to get processing stats: {e}")
    
    async def store_link_check_results(self, bill_id: str, results: Dict[str, Any]) -> bool:
        """
        /**
         * Persist link validation results for a bill with a TTL.
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            key = await self._get_key(self.LINK_CHECK_KEY, bill_id=bill_id)
            await self.redis_client.set(key, json.dumps(results), ex=86400)  # 24 hours TTL
            return True
        except Exception as e:
            raise StateManagerError(f"Failed to store link check results: {e}")
    
    async def get_link_check_results(self, bill_id: str) -> Optional[Dict[str, Any]]:
        """
        /**
         * Retrieve previously stored link validation results for a bill.
         */
        """
        if not self.redis_client:
            raise StateManagerError("Not connected to Redis")
        
        try:
            key = await self._get_key(self.LINK_CHECK_KEY, bill_id=bill_id)
            data = await self.redis_client.get(key)
            
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            raise StateManagerError(f"Failed to get link check results: {e}")


# Example usage and testing
async def main():
    """Test the state manager."""
    state_manager = StateManager()
    
    try:
        await state_manager.connect()
        print("Connected to Redis")
        
        # Test storing and retrieving question answers
        await state_manager.store_question_answer("H.R.1", 1, "This bill does X, Y, Z", ["url1", "url2"])
        answer = await state_manager.get_question_answer("H.R.1", 1)
        print(f"Retrieved answer: {answer}")
        
        # Test bill status
        await state_manager.set_bill_status("H.R.1", "processing", {"started_at": time.time()})
        status = await state_manager.get_bill_status("H.R.1")
        print(f"Bill status: {status}")
        
        # Test processing stats
        stats = await state_manager.get_processing_stats()
        print(f"Processing stats: {stats}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await state_manager.disconnect()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
