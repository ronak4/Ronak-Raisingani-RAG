"""
/**
 * @file performance_monitor.py
 * @summary Lightweight performance monitoring utilities for tracking task,
 *          API, and LLM timings across the pipeline.
 *
 * @details
 * - Thread-safe (asyncio) collection of task durations and derived stats.
 * - Global monitor instance helpers for easy import and use.
 * - Computes throughput, average times, and ETA.
 */
"""

import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from collections import defaultdict
import asyncio


@dataclass
class TaskMetrics:
    """
    /**
     * Metrics for a single tracked task.
     */
    """
    task_id: str
    task_type: str
    start_time: float
    end_time: Optional[float] = None
    success: bool = True
    error: Optional[str] = None
    
    @property
    def duration(self) -> float:
        """
        /**
         * Get task duration in seconds (uses current time if unfinished).
         */
        """
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time


@dataclass
class PerformanceStats:
    """
    /**
     * Aggregated performance statistics snapshot.
     */
    """
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    api_calls: int = 0
    llm_calls: int = 0
    avg_task_time: float = 0.0
    avg_api_time: float = 0.0
    avg_llm_time: float = 0.0
    tasks_per_second: float = 0.0
    eta_seconds: float = 0.0


class PerformanceMonitor:
    """
    /**
     * Monitor and track performance metrics for the pipeline.
     */
    """
    
    def __init__(self):
        self.start_time = time.time()
        self.active_tasks: Dict[str, TaskMetrics] = {}
        self.completed_tasks: List[TaskMetrics] = []
        self.task_times: Dict[str, List[float]] = defaultdict(list)
        self.api_call_times: List[float] = []
        self.llm_call_times: List[float] = []
        self._lock = asyncio.Lock()
    
    async def start_task(self, task_id: str, task_type: str) -> TaskMetrics:
        """
        /**
         * Start tracking a task by id and type.
         */
        """
        async with self._lock:
            metric = TaskMetrics(
                task_id=task_id,
                task_type=task_type,
                start_time=time.time()
            )
            self.active_tasks[task_id] = metric
            return metric
    
    async def end_task(self, task_id: str, success: bool = True, error: Optional[str] = None):
        """
        /**
         * Finish tracking a task, recording success/error and duration.
         */
        """
        async with self._lock:
            if task_id in self.active_tasks:
                metric = self.active_tasks.pop(task_id)
                metric.end_time = time.time()
                metric.success = success
                metric.error = error
                self.completed_tasks.append(metric)
                self.task_times[metric.task_type].append(metric.duration)
    
    async def record_api_call(self, duration: float):
        """
        /**
         * Record the duration of a single API call.
         */
        """
        async with self._lock:
            self.api_call_times.append(duration)
    
    async def record_llm_call(self, duration: float):
        """
        /**
         * Record the duration of a single LLM call.
         */
        """
        async with self._lock:
            self.llm_call_times.append(duration)
    
    async def get_stats(self, total_tasks: int = 0) -> PerformanceStats:
        """
        /**
         * Compute and return a statistics snapshot.
         */
        """
        async with self._lock:
            completed = len(self.completed_tasks)
            failed = sum(1 for t in self.completed_tasks if not t.success)
            
            # Calculate average times
            all_task_times = [t.duration for t in self.completed_tasks]
            avg_task_time = sum(all_task_times) / len(all_task_times) if all_task_times else 0.0
            avg_api_time = sum(self.api_call_times) / len(self.api_call_times) if self.api_call_times else 0.0
            avg_llm_time = sum(self.llm_call_times) / len(self.llm_call_times) if self.llm_call_times else 0.0
            
            # Calculate throughput
            elapsed = time.time() - self.start_time
            tasks_per_second = completed / elapsed if elapsed > 0 else 0.0
            
            # Calculate ETA
            remaining = total_tasks - completed if total_tasks > 0 else 0
            eta_seconds = remaining / tasks_per_second if tasks_per_second > 0 else 0.0
            
            return PerformanceStats(
                total_tasks=total_tasks,
                completed_tasks=completed,
                failed_tasks=failed,
                api_calls=len(self.api_call_times),
                llm_calls=len(self.llm_call_times),
                avg_task_time=avg_task_time,
                avg_api_time=avg_api_time,
                avg_llm_time=avg_llm_time,
                tasks_per_second=tasks_per_second,
                eta_seconds=eta_seconds
            )
    
    def get_active_tasks_summary(self) -> Dict[str, int]:
        """
        /**
         * Return a mapping of task_type -> active count.
         */
        """
        summary = defaultdict(int)
        for task in self.active_tasks.values():
            summary[task.task_type] += 1
        return dict(summary)
    
    def format_stats(self, stats: PerformanceStats) -> str:
        """
        /**
         * Format a stats snapshot for human-friendly display.
         */
        """
        return (
            f"Tasks: {stats.completed_tasks}/{stats.total_tasks} completed "
            f"({stats.failed_tasks} failed) | "
            f"Speed: {stats.tasks_per_second:.2f} tasks/s | "
            f"Avg times: Task={stats.avg_task_time:.1f}s, "
            f"API={stats.avg_api_time:.1f}s, "
            f"LLM={stats.avg_llm_time:.1f}s | "
            f"ETA: {int(stats.eta_seconds//60)}m {int(stats.eta_seconds%60)}s"
        )


# Global performance monitor instance
_global_monitor: Optional[PerformanceMonitor] = None


def get_monitor() -> PerformanceMonitor:
    """
    /**
     * Get or create the global performance monitor instance.
     */
    """
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = PerformanceMonitor()
    return _global_monitor


def reset_monitor():
    """
    /**
     * Reset the global performance monitor instance.
     */
    """
    global _global_monitor
    _global_monitor = PerformanceMonitor()

