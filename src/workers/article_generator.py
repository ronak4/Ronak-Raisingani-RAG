"""
/**
 * @file article_generator.py
 * @summary Worker that assembles final Markdown articles once the seven
 *          required answers are available and links have been validated.
 *
 * @details
 * - Consumes logical "article-tasks" messages and produces completed articles.
 * - Retrieves all question answers and optional link-check results from state.
 * - Calls the LLM service to compose a cohesive, news-style article.
 * - Writes the resulting article to `output/articles.json` and an individual
 *   Markdown file while also caching to Redis.
 */
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Dict, Any, List
from pathlib import Path
from services.congress_api import CongressAPIClient
from services.ai_service import AIService
from services.state_manager import StateManager
from utils.kafka_client_simple import KafkaProducer, KafkaConsumer
from utils.schemas import KafkaMessage, GeneratedArticle, ArticleMetadata, TARGET_BILLS


class ArticleGenerator:
    """
    /**
     * Worker that generates final Markdown articles from question answers.
     *
     * @param worker_id: Optional stable identifier for logs/metrics.
     * @param config: Configuration dict (Redis, Kafka, output directory, etc.).
     */
    """
    
    def __init__(self, worker_id: str = None, config: Dict[str, Any] = None):
        self.worker_id = worker_id or f"article-generator-{uuid.uuid4().hex[:8]}"
        self.config = config or {}
        
        # Initialize services
        self.congress_api = CongressAPIClient(
            api_key=self.config.get('congress_api_key'),
            cache_dir=self.config.get('cache_dir', 'cache')
        )
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
            group_id=self.config.get('kafka_group_id', 'article-generators')
        )
        
        # Worker state
        self.tasks_processed = 0
        self.errors_count = 0
        self.running = False
        
        # Output directory
        self.output_dir = Path(self.config.get('output_dir', 'output'))
        self.output_dir.mkdir(exist_ok=True)
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(f"ArticleGenerator-{self.worker_id}")
    
    async def start(self):
        """
        /**
         * Start the worker, connect to services, and begin consuming tasks.
         */
        """
        try:
            # Connect to services
            await self.state_manager.connect()
            self.logger.info(f"Started article generator: {self.worker_id}")
            
            # Update worker status
            await self.state_manager.update_worker_status(
                self.worker_id, "running", self.tasks_processed, self.errors_count
            )
            
            self.running = True
            
            # Start consuming messages
            await self.consumer.start_consuming(
                topics=["article-tasks"],
                message_handler=self._handle_message
            )
            
        except Exception as e:
            self.logger.error(f"Failed to start article generator: {e}")
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
        self.logger.info(f"Stopped article generator: {self.worker_id}")
    
    async def _handle_message(self, message: KafkaMessage):
        """
        /**
         * Handle a single article generation task.
         *
         * @param message: KafkaMessage containing the target bill_id.
         */
        """
        try:
            self.logger.info(f"Processing article task: {message.bill_id}")
            
            # Check if article already exists
            existing_article = await self.state_manager.get_article(message.bill_id)
            if existing_article:
                self.logger.info(f"Article already exists: {message.bill_id}")
                return
            
            # Verify all questions are answered
            all_answered = await self.state_manager.are_all_questions_answered(message.bill_id)
            if not all_answered:
                self.logger.warning(f"Not all questions answered for {message.bill_id}, skipping article generation")
                return
            
            # Get all question answers
            question_answers = await self.state_manager.get_all_question_answers(message.bill_id)
            
            # Get link check results if available
            link_check_results = await self.state_manager.get_link_check_results(message.bill_id)
            
            # Get fresh bill data for context
            bill_data = await self.congress_api.get_bill_data(message.bill_id)
            
            # Generate article using LLM with link validation context
            article_content = await self.llm_service.generate_article(
                bill_data, 
                question_answers, 
                link_check_results
            )
            
            # Create article metadata
            article_metadata = self._create_article_metadata(bill_data)
            
            # Count words and links
            word_count = len(article_content.split())
            link_count = self._count_links(article_content)
            
            # Create generated article
            generated_article = GeneratedArticle(
                bill_id=message.bill_id,
                bill_title=article_metadata.bill_title,
                sponsor_bioguide_id=article_metadata.sponsor_bioguide_id,
                bill_committee_ids=article_metadata.bill_committee_ids,
                article_content=article_content,
                generated_at=time.time(),
                word_count=word_count,
                link_count=link_count
            )
            
            # Store article in Redis
            await self.state_manager.store_article(generated_article)
            
            # Append to output JSON file
            await self._append_to_output_file(generated_article)
            
            # Mark bill as completed
            await self.state_manager.mark_bill_completed(message.bill_id)
            
            # Publish completion message
            completion_message = KafkaMessage(
                bill_id=message.bill_id,
                task_type="generate_article",
                payload={
                    "article_generated": True,
                    "word_count": word_count,
                    "link_count": link_count,
                    "worker_id": self.worker_id
                }
            )
            
            await self.producer.publish_message("completed-articles", completion_message, message.bill_id)
            
            # Update stats
            self.tasks_processed += 1
            await self.state_manager.update_worker_status(
                self.worker_id, "running", self.tasks_processed, self.errors_count
            )
            
            self.logger.info(f"Completed article generation: {message.bill_id} ({word_count} words, {link_count} links)")
            
        except Exception as e:
            self.errors_count += 1
            self.logger.error(f"Error processing article task {message.bill_id}: {e}")
            
            await self.state_manager.update_worker_status(
                self.worker_id, "error", self.tasks_processed, self.errors_count
            )
    
    def _create_article_metadata(self, bill_data) -> ArticleMetadata:
        """
        /**
         * Extract article metadata (title, sponsor, committees, etc.) from the
         * normalized bill data.
         */
        """
        return ArticleMetadata(
            bill_id=bill_data.bill_id,
            bill_title=bill_data.title,
            sponsor_bioguide_id=bill_data.sponsor.get('bioguide_id') if bill_data.sponsor else None,
            bill_committee_ids=[c.get('system_code') for c in bill_data.committees if c.get('system_code')],
            congress=bill_data.congress,
            bill_type=bill_data.bill_type,
            bill_number=bill_data.bill_number
        )
    
    def _count_links(self, content: str) -> int:
        """
        /**
         * Count the number of Markdown-formatted hyperlinks in the content.
         */
        """
        import re
        # Count markdown links [text](url)
        markdown_links = len(re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content))
        return markdown_links
    
    async def _save_markdown_file(self, article: GeneratedArticle):
        """
        /**
         * Save the generated article as an individual Markdown file for
         * convenient per-bill inspection.
         */
        """
        md_dir = self.output_dir / "articles"
        md_dir.mkdir(exist_ok=True)
        
        # Sanitize filename
        safe_bill_id = article.bill_id.replace('.', '_').replace(' ', '_')
        md_file = md_dir / f"{safe_bill_id}.md"
        
        # Write markdown content
        with open(md_file, 'w') as f:
            f.write(f"# {article.bill_title}\n\n")
            f.write(f"**Bill ID**: {article.bill_id}\n\n")
            f.write(f"**Sponsor**: {article.sponsor_bioguide_id}\n\n")
            f.write(f"**Committees**: {', '.join(article.bill_committee_ids)}\n\n")
            f.write("---\n\n")
            f.write(article.article_content)
        
        self.logger.info(f"Saved markdown file: {md_file}")
    
    async def _append_to_output_file(self, article: GeneratedArticle):
        """
        /**
         * Append or upsert the generated article into `output/articles.json`.
         */
        """
        output_file = self.output_dir / "articles.json"
        
        try:
            # Load existing articles
            if output_file.exists():
                with open(output_file, 'r') as f:
                    articles = json.load(f)
            else:
                articles = []
            
            # Add new article with ONLY required fields (matching required schema)
            article_dict = {
                "bill_id": article.bill_id,
                "bill_title": article.bill_title,
                "sponsor_bioguide_id": article.sponsor_bioguide_id,
                "bill_committee_ids": article.bill_committee_ids,
                "article_content": article.article_content
            }
            
            # Check if article already exists (avoid duplicates)
            existing_indices = [i for i, a in enumerate(articles) if a.get('bill_id') == article.bill_id]
            if existing_indices:
                # Replace existing article
                articles[existing_indices[0]] = article_dict
            else:
                # Add new article
                articles.append(article_dict)
            
            # Write back to file
            with open(output_file, 'w') as f:
                json.dump(articles, f, indent=2)
            
            print(f"\033[92mSaved article: {article.bill_id} ({article.word_count} words)\033[0m")
            self.logger.info(f"Appended article to output file: {article.bill_id}")
            
            # Also save as individual markdown file
            await self._save_markdown_file(article)
            
        except Exception as e:
            print(f"\033[91mERROR saving article {article.bill_id}: {e}\033[0m")
            self.logger.error(f"Failed to append article to output file: {e}")
            import traceback
            traceback.print_exc()
            # Don't raise - continue processing
    
    async def generate_all_articles(self):
        """
        /**
         * Generate articles for all target bills when all answers exist.
         */
        """
        self.logger.info("Starting batch article generation for all target bills")
        
        for bill_id in TARGET_BILLS:
            try:
                # Check if all questions are answered
                all_answered = await self.state_manager.are_all_questions_answered(bill_id)
                if not all_answered:
                    self.logger.warning(f"Skipping {bill_id} - not all questions answered")
                    continue
                
                # Check if article already exists
                existing_article = await self.state_manager.get_article(bill_id)
                if existing_article:
                    self.logger.info(f"Skipping {bill_id} - article already exists")
                    continue
                
                # Generate article
                message = KafkaMessage(
                    bill_id=bill_id,
                    task_type="generate_article",
                    payload={}
                )
                await self._handle_message(message)
                
            except Exception as e:
                self.logger.error(f"Error generating article for {bill_id}: {e}")
                continue
        
        self.logger.info("Completed batch article generation")
    
    async def health_check(self) -> Dict[str, Any]:
        """
        /**
         * Perform a lightweight health check of dependencies and outputs.
         */
        """
        try:
            # Check Redis connection
            await self.state_manager.redis_client.ping()
            
            # Check LLM service
            llm_available = await self.llm_service.check_model_availability()
            
            # Check output directory
            output_writable = self.output_dir.is_dir() and self.output_dir.exists()
            
            return {
                "worker_id": self.worker_id,
                "status": "healthy" if (llm_available and output_writable) else "degraded",
                "tasks_processed": self.tasks_processed,
                "errors_count": self.errors_count,
                "llm_available": llm_available,
                "redis_connected": True,
                "output_writable": output_writable
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
    """Test the article generator."""
    config = {
        'congress_api_key': None,  # Use public API
        'cache_dir': 'cache',
        'ollama_base_url': 'http://localhost:11434',
        'ollama_model': 'llama3.2:latest',
        'redis_host': 'localhost',
        'redis_port': 6379,
        'kafka_bootstrap_servers': 'localhost:19092',
        'kafka_group_id': 'article-generators',
        'output_dir': 'output'
    }
    
    generator = ArticleGenerator(config=config)
    
    try:
        # Test health check
        health = await generator.health_check()
        print(f"Health check: {health}")
        
        # Start worker (this will run indefinitely)
        await generator.start()
        
    except KeyboardInterrupt:
        print("Stopping article generator...")
        await generator.stop()
    except Exception as e:
        print(f"Error: {e}")
        await generator.stop()


if __name__ == "__main__":
    asyncio.run(main())
