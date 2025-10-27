#!/usr/bin/env python3
"""
/**
 * @file run_integrated_pipeline.py
 * @summary Integrated pipeline runner that initializes the controller,
 *          launches workers, monitors progress, and writes final outputs.
 *
 * @details
 * - Spawns question, link-check, and article-generation workers.
 * - Uses a simple progress monitor for periodic statistics printing.
 * - Waits until all articles are produced, then performs a graceful shutdown.
 */
"""

import asyncio
import sys
import signal
import logging
import time
import subprocess
from pathlib import Path
from typing import List
from dotenv import load_dotenv
load_dotenv()

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from controller import NewsGenerationController
from workers.question_worker import QuestionWorker
from workers.link_checker import LinkChecker
from workers.article_generator import ArticleGenerator
from utils.performance_monitor import get_monitor, reset_monitor
from utils.schemas import TARGET_BILLS


def flush_redis():
    """
    /**
     * Flush all data from the Redis instance in the Docker container named
     * "redis". Returns True on success, False otherwise.
     */
    """
    try:
        result = subprocess.run(
            ["docker", "exec", "redis", "redis-cli", "FLUSHALL"],
            capture_output=True,
            text=True,
            check=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to flush Redis: {e}")
        return False


class IntegratedPipeline:
    """
    /**
     * Integrated pipeline with auto-worker management.
     *
     * @param num_question_workers: Number of question workers to start.
     * @param num_link_checkers: Number of link-check workers to start.
     * @param verbose: If True, enables more verbose logging.
     */
    """
    
    def __init__(self, num_question_workers: int = 1, num_link_checkers: int = 1, verbose: bool = True):
        self.num_question_workers = num_question_workers
        self.num_link_checkers = num_link_checkers
        self.verbose = verbose
        
        # Components
        self.controller = None
        self.workers = []
        self.worker_tasks = []
        self.running = False
        
        # Setup logging - only errors and progress
        log_level = logging.ERROR if not verbose else logging.INFO
        
        # Custom formatter with colors
        class ColoredFormatter(logging.Formatter):
            RED = '\033[91m'
            GREEN = '\033[92m'
            YELLOW = '\033[93m'
            RESET = '\033[0m'
            
            def format(self, record):
                if record.levelname == 'ERROR':
                    record.levelname = f'{self.RED}ERROR{self.RESET}'
                    record.msg = f'{self.RED}{record.msg}{self.RESET}'
                elif 'PROGRESS' in str(record.msg) or '✓' in str(record.msg):
                    record.msg = f'{self.GREEN}{record.msg}{self.RESET}'
                return super().format(record)
        
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(ColoredFormatter('%(asctime)s - %(message)s'))
        
        logging.basicConfig(
            level=log_level,
            handlers=[handler]
        )
        
        # Suppress noisy loggers
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("h11").setLevel(logging.WARNING)
        
        self.logger = logging.getLogger("Pipeline")
        
        # Reset performance monitor
        reset_monitor()
    
    async def initialize(self):
        """
        /**
         * Initialize the controller and prepare all worker instances.
         */
        """
        print("\033[92mInitializing integrated pipeline...\033[0m")
        
        # Create controller
        self.controller = NewsGenerationController(config={'verbose': self.verbose})
        await self.controller.initialize()
        
        # Create workers with config
        worker_config = {
            'verbose': False,  # Disable verbose to reduce overhead
            'max_concurrent_tasks': 12  # Increased for Qwen2.5:7b performance
        }
        
        # Create question workers
        for i in range(self.num_question_workers):
            worker = QuestionWorker(
                worker_id=f"question-worker-{i+1}",
                config=worker_config
            )
            self.workers.append(('question', worker))
        
        # Create link checkers
        for i in range(self.num_link_checkers):
            worker = LinkChecker(
                worker_id=f"link-checker-{i+1}",
                config=worker_config
            )
            self.workers.append(('link', worker))
        
        # Create article generator
        worker = ArticleGenerator(
            worker_id="article-generator-1",
            config=worker_config
        )
        self.workers.append(('article', worker))
        
        print(f"\033[92mCreated {len(self.workers)} workers")
        print(f"  - {self.num_question_workers} question workers")
        print(f"  - {self.num_link_checkers} link checkers")
        print(f"  - 1 article generator\033[0m")
    
    async def start_workers(self):
        """
        /**
         * Start all configured workers concurrently.
         */
        """
        print("\033[92mStarting all workers...\033[0m")
        
        for worker_type, worker in self.workers:
            task = asyncio.create_task(worker.start())
            self.worker_tasks.append(task)
        
        # Give workers a moment to initialize
        await asyncio.sleep(2)
        print("\033[92mAll workers started successfully\033[0m")
    
    async def run_pipeline(self):
        """
        /**
         * Run the complete pipeline lifecycle until all articles are produced
         * or an unrecoverable error occurs.
         */
        """
        self.running = True
        
        try:
            # Initialize
            await self.initialize()
            
            # Start workers first
            await self.start_workers()
            
            # Start the pipeline controller
            print("\n\033[92m" + "="*80)
            print("Starting news generation pipeline...")
            print("Processing 10 bills with 70 total questions...")
            print("="*80 + "\033[0m\n")
            
            # Run controller with monitoring
            controller_task = asyncio.create_task(self.controller.start_pipeline())
            monitor_task = asyncio.create_task(self._monitor_progress())
            
            # Wait for all articles to be completed instead of controller completion
            from utils.schemas import TARGET_BILLS
            while True:
                completed_bills = await self.controller.state_manager.get_completed_bills()
                if len(completed_bills) >= len(TARGET_BILLS):
                    self.logger.info("All articles completed - stopping pipeline")
                    break
                await asyncio.sleep(2)  # Check every 2 seconds
            
            # Cancel controller task since we're done
            controller_task.cancel()
            try:
                await controller_task
            except asyncio.CancelledError:
                pass
            
            # Signal workers to stop
            print("\033[92mStopping all workers...\033[0m")
            for worker_type, worker in self.workers:
                try:
                    await worker.stop()
                    print(f"\033[92mStopped {worker_type} worker\033[0m")
                except Exception as e:
                    print(f"\033[91mError stopping {worker_type} worker: {e}\033[0m")
            
            # Wait for workers to finish gracefully
            if self.worker_tasks:
                print("\033[92mWaiting for workers to finish...\033[0m")
                await asyncio.gather(*self.worker_tasks, return_exceptions=True)
            
            # ASCII art completion message
            completion_art = """
\033[92m
███████╗ ██████╗ ███╗   ███╗██████╗ ██╗     ███████╗████████╗███████╗██████╗ 
██╔════╝██╔═══██╗████╗ ████║██╔══██╗██║     ██╔════╝╚══██╔══╝██╔════╝██╔══██╗
██║     ██║   ██║██╔████╔██║██████╔╝██║     █████╗     ██║   █████╗  ██║  ██║
██║     ██║   ██║██║╚██╔╝██║██╔═══╝ ██║     ██╔══╝     ██║   ██╔══╝  ██║  ██║
╚██████╗╚██████╔╝██║ ╚═╝ ██║██║     ███████╗███████╗   ██║   ███████╗██████╔╝
 ╚═════╝ ╚═════╝ ╚═╝     ╚═╝╚═╝     ╚══════╝╚══════╝   ╚═╝   ╚══════╝╚═════╝ 
\033[0m
"""
            print(completion_art)
            
            # Get final stats
            monitor = get_monitor()
            final_stats = await monitor.get_stats(total_tasks=len(TARGET_BILLS) * 7)
            elapsed = time.time() - self.controller.start_time
            
            print("\033[92m" + "="*80)
            print(f"Pipeline completed successfully!")
            print(f"Generated {len(TARGET_BILLS)} articles in {int(elapsed//60)}m {int(elapsed%60)}s")
            print(f"Answered {final_stats.completed_tasks} questions")
            print(f"Average speed: {final_stats.tasks_per_second:.2f} tasks/second")
            print(f"Articles per minute: {(len(TARGET_BILLS) / (elapsed / 60)):.2f}")
            print(f"Output saved to: output/articles.json")
            print("="*80 + "\033[0m")
            
            # Stop monitoring
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
            
        except Exception as e:
            self.logger.error(f"Pipeline failed: {e}")
            import traceback
            traceback.print_exc()
            raise
        finally:
            await self.cleanup()
    
    async def _monitor_progress(self):
        """
        /**
         * Periodically print progress, throughput, and time elapsed, along
         * with per-bill status.
         */
        """
        from utils.schemas import TARGET_BILLS
        
        while self.running:
            try:
                await asyncio.sleep(15)  # Update every 15 seconds for faster feedback
                
                # Get performance stats
                monitor = get_monitor()
                stats = await monitor.get_stats(total_tasks=len(TARGET_BILLS) * 7)  # 7 questions per bill
                
                # Get active tasks summary
                active = monitor.get_active_tasks_summary()
                active_str = ", ".join([f"{k}:{v}" for k, v in active.items()]) if active else "none"
                
                # Get controller progress
                try:
                    completed_bills = await self.controller.state_manager.get_completed_bills()
                    progress_pct = len(completed_bills) / len(TARGET_BILLS) * 100
                    
                    # Compact progress display - force print to stdout
                    import sys
                    elapsed_time = time.time() - self.controller.start_time
                    elapsed_min = int(elapsed_time // 60)
                    elapsed_sec = int(elapsed_time % 60)
                    
                    sys.stdout.write(f"\n\033[92m{'='*80}\n")
                    sys.stdout.write(f"PROGRESS: Articles {len(completed_bills)}/{len(TARGET_BILLS)} ({progress_pct:.1f}%) | "
                          f"Tasks: {stats.completed_tasks}/{stats.total_tasks} | "
                          f"Speed: {stats.tasks_per_second:.2f}/s | "
                          f"Time Elapsed: {elapsed_min}m {elapsed_sec}s\n")
                    
                    # Show bill status in one line each
                    for bill_id in TARGET_BILLS:
                        answered = 0
                        article = await self.controller.state_manager.get_article(bill_id)
                        for q_id in range(1, 8):
                            answer = await self.controller.state_manager.get_question_answer(bill_id, q_id)
                            if answer:
                                answered += 1
                        if article:
                            status = "Article"
                        elif answered == 7:
                            status = "Writing"
                        else:
                            status = f"{answered}/7"
                        sys.stdout.write(f"  {bill_id:12} {status:10}\n")
                    
                    sys.stdout.write(f"{'='*80}\033[0m\n")
                    sys.stdout.flush()
                    
                except Exception as e:
                    self.logger.debug(f"Could not get progress: {e}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Monitor error: {e}")
    
    async def cleanup(self):
        """
        /**
         * Stop all workers, cancel outstanding tasks, and close resources.
         */
        """
        self.logger.info("Stopping all workers...")
        self.running = False
        
        # Stop all workers
        for worker_type, worker in self.workers:
            try:
                await worker.stop()
                self.logger.info(f"Stopped {worker_type} worker: {worker.worker_id}")
            except Exception as e:
                self.logger.error(f"Error stopping worker: {e}")
        
        # Cancel worker tasks
        for task in self.worker_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Cleanup controller
        if self.controller:
            try:
                await self.controller.cleanup()
            except Exception as e:
                self.logger.error(f"Error cleaning up controller: {e}")
        
        self.logger.info("Cleanup completed")


async def main():
    """
    /**
     * Main entry point for launching the integrated pipeline from the CLI.
     */
    """
    print("🚀 RAG News Generation - Integrated Pipeline")
    print("="*80)
    
    # Flush Redis for fresh start
    flush_redis()
    await asyncio.sleep(2)

    print("="*80)
    
    pipeline = IntegratedPipeline(
        num_question_workers=8,  # Increased for Qwen2.5:7b speed
        num_link_checkers=1,
        verbose=False  # Only errors and progress
    )
    
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\n\nReceived interrupt signal. Shutting down...")
        asyncio.create_task(pipeline.cleanup())
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        await pipeline.run_pipeline()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await pipeline.cleanup()
    except Exception as e:
        print(f"\nPipeline failed: {e}")
        await pipeline.cleanup()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

