"""
/**
 * @file controller.py
 * @summary Orchestrator for the RAG News Generation pipeline. Coordinates
 *          workers, state, messaging, progress monitoring, and outputs.
 *
 * @details
 * - Initializes state and required logical topics.
 * - Publishes question tasks for all target bills.
 * - Monitors progress until all articles are completed.
 * - Saves final results and a summary, then performs cleanup.
 */
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, List
from pathlib import Path
from services.state_manager import StateManager
from utils.kafka_client_simple import KafkaProducer, KafkaAdmin, REQUIRED_TOPICS
from utils.schemas import TARGET_BILLS, QuestionType


class NewsGenerationController:
    """
    /**
     * Main controller for the RAG News Generation system.
     *
     * @param config: Optional configuration dictionary (Redis, Kafka, etc.).
     */
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        
        # Initialize services
        self.state_manager = StateManager(
            redis_host=self.config.get('redis_host', 'localhost'),
            redis_port=self.config.get('redis_port', 6379),
            redis_db=self.config.get('redis_db', 0)
        )
        
        # Kafka clients
        self.producer = KafkaProducer(
            bootstrap_servers=self.config.get('kafka_bootstrap_servers', 'localhost:19092')
        )
        self.admin = KafkaAdmin(
            bootstrap_servers=self.config.get('kafka_bootstrap_servers', 'localhost:19092')
        )
        
        # Controller state
        self.start_time = None
        self.end_time = None
        self.bills_processed = 0
        self.total_tasks = 0
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger("NewsGenerationController")
    
    async def initialize(self):
        """
        /**
         * Initialize the controller and create required logical topics.
         * Establishes state connections and resets any stale state.
         */
        """
        try:
            # Connect to Redis
            await self.state_manager.connect()
            self.logger.info("Connected to Redis")
            
            # Create Kafka topics
            await self.admin.create_topics(REQUIRED_TOPICS)
            self.logger.info(f"Created topics: {REQUIRED_TOPICS}")
            
            # Clear any existing state
            await self._clear_existing_state()
            
            self.logger.info("Controller initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize controller: {e}")
            raise
    
    async def _clear_existing_state(self):
        """
        /**
         * Clear any existing state from previous runs (processing queue,
         * completed bills, and per-bill data) to ensure fresh execution.
         */
        """
        try:
            # Clear processing queue
            processing_queue = await self.state_manager.get_processing_queue()
            for bill_id in processing_queue:
                await self.state_manager.remove_from_processing_queue(bill_id)
            
            # Clear completed bills
            completed_bills = await self.state_manager.get_completed_bills()
            for bill_id in completed_bills:
                await self.state_manager.clear_bill_data(bill_id)
            
            self.logger.info("Cleared existing state")
            
        except Exception as e:
            self.logger.warning(f"Failed to clear existing state: {e}")
    
    async def start_pipeline(self):
        """
        /**
         * Start the news generation pipeline by enqueuing all question tasks
         * and launching progress monitoring.
         */
        """
        try:
            self.start_time = time.time()
            self.logger.info(f"Starting news generation pipeline for {len(TARGET_BILLS)} bills")
            
            # Add all bills to processing queue
            for bill_id in TARGET_BILLS:
                await self.state_manager.add_to_processing_queue(bill_id)
                await self.state_manager.set_bill_status(bill_id, "queued")
            
            # Publish question tasks for all bills
            total_tasks = 0
            for bill_id in TARGET_BILLS:
                for question_id in range(1, 8):  # Questions 1-7
                    from utils.schemas import KafkaMessage, TaskType
                    message = KafkaMessage(
                        bill_id=bill_id,
                        question_id=question_id,
                        task_type=TaskType.ANSWER_QUESTION,
                        payload={"bill_id": bill_id, "question_id": question_id}
                    )
                    await self.producer.publish_message("question-tasks", message, key=bill_id)
                    total_tasks += 1
            
            self.total_tasks = total_tasks
            self.logger.info(f"Published {total_tasks} question tasks")
            
            # Monitor progress
            await self._monitor_progress()
            
        except Exception as e:
            self.logger.error(f"Failed to start pipeline: {e}")
            raise
    
    async def _monitor_progress(self):
        """
        /**
         * Monitor progress, logging periodic statistics and per-bill status
         * until all articles are completed or timeout is reached.
         */
        """
        from utils.performance_monitor import get_monitor
        
        self.logger.info("Starting progress monitoring")
        
        last_stats_time = time.time()
        stats_interval = 5  # Log every 5 seconds for better visibility
        
        while True:
            try:
                # Get processing stats
                stats = await self.state_manager.get_processing_stats()
                completed_bills = await self.state_manager.get_completed_bills()
                
                # Get performance metrics
                perf_stats = await get_monitor().get_stats(total_tasks=self.total_tasks)
                
                # Log progress
                current_time = time.time()
                if current_time - last_stats_time >= stats_interval:
                    elapsed = current_time - self.start_time
                    progress_pct = len(completed_bills) / len(TARGET_BILLS) * 100
                    
                    self.logger.info("="*80)
                    self.logger.info(
                        f"PROGRESS: Articles {len(completed_bills)}/{len(TARGET_BILLS)} ({progress_pct:.1f}%) | "
                        f"Elapsed: {int(elapsed//60)}m {int(elapsed%60)}s"
                    )
                    self.logger.info(
                        f"TASKS: {perf_stats.completed_tasks}/{self.total_tasks} | "
                        f"Speed: {perf_stats.tasks_per_second:.2f} tasks/s"
                    )
                    
                    # Show per-bill progress for first few bills
                    for bill_id in TARGET_BILLS[:3]:
                        answered = 0
                        for q_id in range(1, 8):
                            answer = await self.state_manager.get_question_answer(bill_id, q_id)
                            if answer:
                                answered += 1
                        status = "Complete" if answered == 7 else f"Writing {answered}/7"
                        self.logger.info(f"  {bill_id}: {status}")
                    
                    self.logger.info("="*80)
                    last_stats_time = current_time
                
                # Check if all articles are completed (graceful exit)
                if len(completed_bills) >= len(TARGET_BILLS):
                    self.end_time = time.time()
                    self.bills_processed = len(completed_bills)
                    
                    total_time = self.end_time - self.start_time
                    self.logger.info(
                        f"All articles completed! Processed {self.bills_processed} bills in {total_time:.1f} seconds"
                    )
                    break
                
                # Check for timeout (30 minutes)
                if current_time - self.start_time > 1800:
                    self.logger.warning("Pipeline timeout reached (30 minutes)")
                    break
                
                # Wait before next check (faster polling for immediate exit)
                await asyncio.sleep(2)
                
            except Exception as e:
                self.logger.error(f"Error monitoring progress: {e}")
                await asyncio.sleep(10)
    
    async def get_final_results(self) -> Dict[str, Any]:
        """
        /**
         * Gather final results (articles) and compute summary statistics.
         *
         * @return Dict containing summary stats, article list, and timestamp.
         */
        """
        try:
            # Get all completed articles
            completed_bills = await self.state_manager.get_completed_bills()
            articles = []
            
            for bill_id in completed_bills:
                article = await self.state_manager.get_article(bill_id)
                if article:
                    articles.append({
                        "bill_id": article.bill_id,
                        "bill_title": article.bill_title,
                        "sponsor_bioguide_id": article.sponsor_bioguide_id,
                        "bill_committee_ids": article.bill_committee_ids,
                        "article_content": article.article_content
                    })
            
            # Calculate statistics
            total_time = (self.end_time - self.start_time) if self.end_time and self.start_time else 0
            avg_time_per_bill = total_time / len(completed_bills) if completed_bills else 0
            
            # Count total words and links
            total_words = sum(len(article["article_content"].split()) for article in articles)
            total_links = sum(article["article_content"].count("[") for article in articles)
            
            results = {
                "summary": {
                    "bills_processed": len(completed_bills),
                    "total_bills": len(TARGET_BILLS),
                    "completion_rate": len(completed_bills) / len(TARGET_BILLS) * 100,
                    "total_time_seconds": total_time,
                    "average_time_per_bill": avg_time_per_bill,
                    "total_words": total_words,
                    "total_links": total_links
                },
                "articles": articles,
                "performance_target_met": total_time < 600,  # 10 minutes
                "timestamp": time.time()
            }
            
            return results
            
        except Exception as e:
            self.logger.error(f"Failed to get final results: {e}")
            return {"error": str(e)}
    
    async def save_results(self, results: Dict[str, Any], output_file: str = "output/articles.json"):
        """
        /**
         * Save articles to the primary output JSON and a separate summary file.
         *
         * @param results: Result dict from get_final_results().
         * @param output_file: Path to the articles JSON file.
         */
        """
        try:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w') as f:
                json.dump(results["articles"], f, indent=2)
            
            # Save summary separately
            summary_path = output_path.parent / "summary.json"
            with open(summary_path, 'w') as f:
                json.dump(results["summary"], f, indent=2)
            
            self.logger.info(f"Results saved to {output_path}")
            self.logger.info(f"Summary saved to {summary_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to save results: {e}")
            raise
    
    async def cleanup(self):
        """
        /**
         * Cleanup connections to state and messaging clients.
         */
        """
        try:
            await self.state_manager.disconnect()
            self.producer.close()
            self.admin.close()
            self.logger.info("Controller cleanup completed")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
    
    async def run_full_pipeline(self):
        """
        /**
         * Run initialization, pipeline start, results gathering, saving, and
         * final cleanup. Returns the full results dict.
         */
        """
        try:
            # Initialize
            await self.initialize()
            
            # Start pipeline
            await self.start_pipeline()
            
            # Get results
            results = await self.get_final_results()
            
            # Save results
            await self.save_results(results)
            
            # Log final summary
            summary = results["summary"]
            self.logger.info("=" * 50)
            self.logger.info("PIPELINE COMPLETION SUMMARY")
            self.logger.info("=" * 50)
            self.logger.info(f"Bills processed: {summary['bills_processed']}/{summary['total_bills']}")
            self.logger.info(f"Completion rate: {summary['completion_rate']:.1f}%")
            self.logger.info(f"Total time: {summary['total_time_seconds']:.1f} seconds")
            self.logger.info(f"Average time per bill: {summary['average_time_per_bill']:.1f} seconds")
            self.logger.info(f"Total words generated: {summary['total_words']}")
            self.logger.info(f"Total links generated: {summary['total_links']}")
            self.logger.info(f"Performance target met (<10 min): {results['performance_target_met']}")
            self.logger.info("=" * 50)
            
            return results
            
        except Exception as e:
            self.logger.error(f"Pipeline failed: {e}")
            raise
        finally:
            await self.cleanup()


# Example usage and testing
async def main():
    """
    /**
     * Entry point for running the complete news generation pipeline.
     */
    """
    config = {
        'redis_host': 'localhost',
        'redis_port': 6379,
        'kafka_bootstrap_servers': 'localhost:19092',
        'output_dir': 'output'
    }
    
    controller = NewsGenerationController(config=config)
    
    try:
        results = await controller.run_full_pipeline()
        print("Pipeline completed successfully!")
        print(f"Results: {json.dumps(results['summary'], indent=2)}")
        
    except Exception as e:
        print(f"Pipeline failed: {e}")
    finally:
        await controller.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
