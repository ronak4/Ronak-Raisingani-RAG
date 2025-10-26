"""
/**
 * @file link_checker.py
 * @summary Worker that validates hyperlinks discovered in generated content
 *          and reports per-bill link health statistics.
 *
 * @details
 * - Consumes logical "link-check-tasks" messages containing URLs to verify.
 * - Performs HTTP GET requests with retries and backoff on timeouts/errors.
 * - Publishes validation results and stores a summary in state for downstream
 *   article generation.
 */
"""

import asyncio
import logging
import time
import uuid
from typing import Dict, Any, List
import httpx
from utils.kafka_client_simple import KafkaProducer, KafkaConsumer
from utils.schemas import KafkaMessage, LinkCheckResult
from services.state_manager import StateManager


class LinkChecker:
    """
    /**
     * Worker that validates URLs and checks they return HTTP 200.
     *
     * @param worker_id: Optional stable identifier for logs/metrics.
     * @param config: Configuration dict (timeouts, retries, Kafka, etc.).
     */
    """
    
    def __init__(self, worker_id: str = None, config: Dict[str, Any] = None):
        self.worker_id = worker_id or f"link-checker-{uuid.uuid4().hex[:8]}"
        self.config = config or {}
        
        # Kafka clients
        self.producer = KafkaProducer(
            bootstrap_servers=self.config.get('kafka_bootstrap_servers', 'localhost:19092')
        )
        self.consumer = KafkaConsumer(
            bootstrap_servers=self.config.get('kafka_bootstrap_servers', 'localhost:19092'),
            group_id=self.config.get('kafka_group_id', 'link-checkers')
        )
        
        # Worker state
        self.tasks_processed = 0
        self.errors_count = 0
        self.running = False
        
        # HTTP client settings
        self.timeout = self.config.get('http_timeout', 10.0)
        self.max_retries = self.config.get('max_retries', 3)
        self.retry_delay = self.config.get('retry_delay', 1.0)
        
        # State manager for storing results
        self.state_manager = StateManager()
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(f"LinkChecker-{self.worker_id}")
    
    async def start(self):
        """
        /**
         * Start the worker, connect to state, and begin consuming tasks.
         */
        """
        try:
            self.logger.info(f"Started link checker: {self.worker_id}")
            self.running = True
            
            # Connect to state manager
            await self.state_manager.connect()
            
            # Start consuming messages
            await self.consumer.start_consuming(
                topics=["link-check-tasks"],
                message_handler=self._handle_message
            )
            
        except Exception as e:
            self.logger.error(f"Failed to start link checker: {e}")
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
        self.logger.info(f"Stopped link checker: {self.worker_id}")
    
    async def _handle_message(self, message: KafkaMessage):
        """
        /**
         * Handle a single link-check task for a bill.
         *
         * @param message: KafkaMessage containing bill_id and list of URLs.
         */
        """
        try:
            self.logger.info(f"Processing link check task: {message.bill_id}")
            
            urls = message.payload.get('urls', [])
            if not urls:
                self.logger.warning(f"No URLs to check for {message.bill_id}")
                return
            
            # Check all URLs
            results = []
            for url in urls:
                result = await self._check_url(url)
                results.append(result)
            
            # Count valid/invalid URLs
            valid_count = sum(1 for r in results if r.is_valid)
            invalid_count = len(results) - valid_count
            
            self.logger.info(f"Link check completed for {message.bill_id}: {valid_count} valid, {invalid_count} invalid")
            
            # Publish results
            result_message = KafkaMessage(
                bill_id=message.bill_id,
                task_type="check_links",
                payload={
                    "results": [r.model_dump() for r in results],
                    "valid_count": valid_count,
                    "invalid_count": invalid_count,
                    "worker_id": self.worker_id
                }
            )
            
            await self.producer.publish_message("link-check-results", result_message, message.bill_id)
            
            # Store results in state manager for article generator to use
            await self.state_manager.store_link_check_results(message.bill_id, {
                "results": [r.model_dump() for r in results],
                "valid_count": valid_count,
                "invalid_count": invalid_count,
                "checked_at": time.time()
            })
            
            # Update stats
            self.tasks_processed += 1
            
        except Exception as e:
            self.errors_count += 1
            self.logger.error(f"Error processing link check task {message.bill_id}: {e}")
    
    async def _check_url(self, url: str) -> LinkCheckResult:
        """
        /**
         * Check whether a URL returns HTTP 200 (with simple retries).
         */
        """
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url, follow_redirects=True)
                    
                    return LinkCheckResult(
                        url=url,
                        is_valid=response.status_code == 200,
                        status_code=response.status_code,
                        checked_at=time.time()
                    )
                    
            except httpx.TimeoutException:
                if attempt == self.max_retries - 1:
                    return LinkCheckResult(
                        url=url,
                        is_valid=False,
                        status_code=None,
                        error_message="Timeout",
                        checked_at=time.time()
                    )
                await asyncio.sleep(self.retry_delay * (2 ** attempt))
                
            except httpx.RequestError as e:
                if attempt == self.max_retries - 1:
                    return LinkCheckResult(
                        url=url,
                        is_valid=False,
                        status_code=None,
                        error_message=str(e),
                        checked_at=time.time()
                    )
                await asyncio.sleep(self.retry_delay * (2 ** attempt))
                
            except Exception as e:
                return LinkCheckResult(
                    url=url,
                    is_valid=False,
                    status_code=None,
                    error_message=f"Unexpected error: {e}",
                    checked_at=time.time()
                )
        
        # This should never be reached, but just in case
        return LinkCheckResult(
            url=url,
            is_valid=False,
            status_code=None,
            error_message="Max retries exceeded",
            checked_at=time.time()
        )
    
    async def check_urls_batch(self, urls: List[str]) -> List[LinkCheckResult]:
        """
        /**
         * Check multiple URLs concurrently and return results in order.
         */
        """
        tasks = [self._check_url(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle any exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(LinkCheckResult(
                    url=urls[i],
                    is_valid=False,
                    status_code=None,
                    error_message=str(result),
                    checked_at=time.time()
                ))
            else:
                processed_results.append(result)
        
        return processed_results
    
    async def health_check(self) -> Dict[str, Any]:
        """
        /**
         * Perform a basic health check using a known-good test URL.
         */
        """
        try:
            # Test with a simple URL
            test_result = await self._check_url("https://httpbin.org/status/200")
            
            return {
                "worker_id": self.worker_id,
                "status": "healthy" if test_result.is_valid else "degraded",
                "tasks_processed": self.tasks_processed,
                "errors_count": self.errors_count,
                "test_url_working": test_result.is_valid
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
    """Test the link checker."""
    config = {
        'kafka_bootstrap_servers': 'localhost:19092',
        'kafka_group_id': 'link-checkers',
        'http_timeout': 10.0,
        'max_retries': 3,
        'retry_delay': 1.0
    }
    
    checker = LinkChecker(config=config)
    
    try:
        # Test health check
        health = await checker.health_check()
        print(f"Health check: {health}")
        
        # Test URL checking
        test_urls = [
            "https://httpbin.org/status/200",
            "https://httpbin.org/status/404",
            "https://nonexistent-domain-12345.com"
        ]
        
        results = await checker.check_urls_batch(test_urls)
        for result in results:
            print(f"URL: {result.url} - Valid: {result.is_valid} - Status: {result.status_code}")
        
        # Start worker (this will run indefinitely)
        await checker.start()
        
    except KeyboardInterrupt:
        print("Stopping link checker...")
        await checker.stop()
    except Exception as e:
        print(f"Error: {e}")
        await checker.stop()


if __name__ == "__main__":
    asyncio.run(main())
