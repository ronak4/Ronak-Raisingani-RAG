"""
/**
 * @file kafka_client_simple.py
 * @summary Simplified Kafka-like utilities implemented over Redis lists to
 *          emulate producer/consumer/admin behaviors for local development.
 *
 * @details
 * - Producer publishes messages by LPUSH-ing JSON entries into a topic queue.
 * - Consumer polls with BRPOP, deserializes, and invokes a handler coroutine.
 * - Admin initializes topic queues by creating empty lists.
 * - Avoids external Kafka dependencies while preserving a similar interface.
 *
 * @limitations
 * - At-least-once semantics only; no partitions or offsets.
 * - Single Redis instance, not fault-tolerant.
 */
"""

import asyncio
import json
import time
import uuid
import redis
from typing import Dict, List, Optional, Any, Callable
from utils.schemas import KafkaMessage, TaskType


class KafkaClientError(Exception):
    """Custom exception for Kafka client errors."""
    pass


class KafkaProducer:
    """
    /**
     * Simplified producer that publishes messages into Redis-backed queues.
     *
     * @param bootstrap_servers: Retained for API compatibility (unused).
     */
    """
    
    def __init__(self, bootstrap_servers: str = "localhost:19092"):
        self.bootstrap_servers = bootstrap_servers
        self.redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    
    async def publish_message(self, topic: str, message: KafkaMessage, key: Optional[str] = None) -> bool:
        """
        /**
         * Publish a message to a logical topic queue.
         *
         * @param topic: Logical topic name.
         * @param message: KafkaMessage payload to serialize.
         * @param key: Optional key (stored for debugging/traceability).
         */
        """
        try:
            message_id = str(uuid.uuid4())
            message_data = {
                'id': message_id,
                'topic': topic,
                'key': key,
                'message': message.dict(),
                'timestamp': time.time()
            }
            
            await asyncio.to_thread(self.redis_client.lpush, f"queue:{topic}", json.dumps(message_data))
            return True
        except Exception as e:
            raise KafkaClientError(f"Failed to publish message: {e}")
    
    def close(self):
        """
        /**
         * Close the underlying Redis client.
         */
        """
        if self.redis_client:
            self.redis_client.close()


class KafkaConsumer:
    """
    /**
     * Simplified consumer that blocks on Redis BRPOP for each configured topic
     * and dispatches messages to an async handler.
     */
    """
    
    def __init__(self, bootstrap_servers: str = "localhost:19092", group_id: str = "default"):
        self.topics = []
        self.group_id = group_id
        self.bootstrap_servers = bootstrap_servers
        self.redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        self.running = False
    
    async def start_consuming(self, message_handler: Callable[[KafkaMessage], None], topics: List[str] = None):
        """
        /**
         * Start consuming messages from the provided topics using BRPOP.
         *
         * @param message_handler: Async function that handles a KafkaMessage.
         * @param topics: List of logical topic names to consume.
         */
        """
        if topics:
            self.topics = topics
        
        self.running = True
        
        while self.running:
            try:
                for topic in self.topics:
                    # Get message from Redis list (blocking with timeout)
                    message_data = await asyncio.to_thread(self.redis_client.brpop, f"queue:{topic}", 0.5)
                    
                    if message_data:
                        _, message_json = message_data
                        message_dict = json.loads(message_json)
                        
                        # Convert back to KafkaMessage
                        message = KafkaMessage(**message_dict['message'])
                        await message_handler(message)
                
                # Small delay to prevent busy waiting
                await asyncio.sleep(0.01)
                
            except Exception as e:
                print(f"Error consuming messages: {e}")
                await asyncio.sleep(1)
    
    def stop(self):
        """
        /**
         * Signal the consumer loop to stop gracefully.
         */
        """
        self.running = False
    
    def close(self):
        """
        /**
         * Stop consuming and close the Redis client.
         */
        """
        self.stop()
        if self.redis_client:
            self.redis_client.close()


class KafkaAdmin:
    """
    /**
     * Simplified admin client for topic initialization.
     */
    """
    
    def __init__(self, bootstrap_servers: str = "localhost:19092"):
        self.bootstrap_servers = bootstrap_servers
        self.redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    
    async def create_topics(self, topics: List[str]):
        """
        /**
         * Create logical topics by initializing Redis lists.
         */
        """
        try:
            for topic in topics:
                # Initialize empty list for topic
                self.redis_client.lpush(f"queue:{topic}", "init")
                self.redis_client.lpop(f"queue:{topic}")  # Remove the init message
            return True
        except Exception as e:
            raise KafkaClientError(f"Failed to create topics: {e}")
    
    def close(self):
        """
        /**
         * Close the underlying Redis client.
         */
        """
        if self.redis_client:
            self.redis_client.close()


# Required topics for the system
REQUIRED_TOPICS = [
    "question-tasks",
    "question-answers", 
    "link-check-tasks",
    "article-tasks",
    "completed-articles"
]
