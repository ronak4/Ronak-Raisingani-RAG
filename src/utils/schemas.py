"""
/**
 * @file schemas.py
 * @summary Message schemas and data models used across the RAG News Generation
 *          System.
 *
 * @details
 * - Enum types define task and question identifiers.
 * - Pydantic models capture message payloads, answers, results, and article
 *   metadata.
 * - Static collections include target bill identifiers, question prompts, and
 *   output validation schemas.
 */
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class TaskType(str, Enum):
    """
    /**
     * Types of tasks passed between components.
     */
    """
    ANSWER_QUESTION = "answer_question"
    CHECK_LINKS = "check_links"
    GENERATE_ARTICLE = "generate_article"


class QuestionType(int, Enum):
    """
    /**
     * The seven required question identifiers used for each bill.
     */
    """
    WHAT_DOES_BILL_DO = 1
    WHAT_COMMITTEES = 2
    WHO_IS_SPONSOR = 3
    WHO_COSPONSORED = 4
    ANY_HEARINGS = 5
    ANY_AMENDMENTS = 6
    ANY_VOTES = 7


class KafkaMessage(BaseModel):
    """
    /**
     * Base schema for logical Kafka-style messages.
     */
    """
    bill_id: str = Field(..., description="Congressional bill identifier (e.g., H.R.1)")
    question_id: Optional[int] = Field(None, description="Question ID (1-7) for question tasks")
    task_type: TaskType = Field(..., description="Type of task to perform")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Task-specific data")
    timestamp: Optional[float] = Field(None, description="Message timestamp")
    message_id: Optional[str] = Field(None, description="Unique message identifier")


class QuestionAnswer(BaseModel):
    """
    /**
     * Schema representing a generated answer to a specific question.
     */
    """
    bill_id: str
    question_id: int
    answer: str = Field(..., description="Generated answer to the question")
    sources: List[str] = Field(default_factory=list, description="Congress.gov URLs used")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence score")
    generated_at: Optional[float] = Field(None, description="Answer generation timestamp")


class LinkCheckResult(BaseModel):
    """
    /**
     * Result of validating a hyperlink (HTTP status and any error message).
     */
    """
    url: str = Field(..., description="URL that was checked")
    is_valid: bool = Field(..., description="Whether URL returns HTTP 200")
    status_code: Optional[int] = Field(None, description="HTTP status code")
    error_message: Optional[str] = Field(None, description="Error message if invalid")
    checked_at: Optional[float] = Field(None, description="Check timestamp")


class ArticleMetadata(BaseModel):
    """
    /**
     * Metadata needed for article composition and output.
     */
    """
    bill_id: str = Field(..., description="Congressional bill identifier")
    bill_title: str = Field(..., description="Official bill title")
    sponsor_bioguide_id: Optional[str] = Field(None, description="Sponsor's Bioguide ID")
    bill_committee_ids: List[str] = Field(default_factory=list, description="Committee IDs")
    congress: int = Field(..., description="Congress number (e.g., 118)")
    bill_type: str = Field(..., description="Bill type (H.R., S., etc.)")
    bill_number: int = Field(..., description="Bill number")


class GeneratedArticle(BaseModel):
    """
    /**
     * Final generated article content and optional metrics.
     */
    """
    bill_id: str
    bill_title: str
    sponsor_bioguide_id: Optional[str]
    bill_committee_ids: List[str]
    article_content: str = Field(..., description="Markdown article content")
    generated_at: Optional[float] = Field(None, description="Generation timestamp")
    word_count: Optional[int] = Field(None, description="Article word count")
    link_count: Optional[int] = Field(None, description="Number of hyperlinks")


class BillData(BaseModel):
    """
    /**
     * Normalized bill data aggregated from Congress.gov API responses.
     */
    """
    bill_id: str
    congress: int
    bill_type: str
    bill_number: int
    title: str
    short_title: Optional[str] = None
    sponsor: Optional[Dict[str, Any]] = None
    cosponsors: List[Dict[str, Any]] = Field(default_factory=list)
    committees: List[Dict[str, Any]] = Field(default_factory=list)
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    amendments: List[Dict[str, Any]] = Field(default_factory=list)
    votes: List[Dict[str, Any]] = Field(default_factory=list)
    hearings: List[Dict[str, Any]] = Field(default_factory=list)
    status: Optional[str] = None
    introduced_date: Optional[str] = None
    last_action_date: Optional[str] = None


class WorkerStatus(BaseModel):
    """
    /**
     * Worker heartbeat/status record stored in state management.
     */
    """
    worker_id: str
    worker_type: str
    status: str = Field(..., description="running, idle, error")
    last_heartbeat: float
    tasks_processed: int = 0
    errors_count: int = 0


# Target bills for processing
TARGET_BILLS = [
    "H.R.1",        # House Bill
    "H.R.5371",     # House Bill
    "H.R.5401",     # House Bill
    "S.2296",       # Senate Bill
    "S.24",         # Senate Bill
    "S.2882",       # Senate Bill
    "S.499",        # Senate Bill
    "S.RES.412",    # Senate Resolution
    "H.RES.353",    # House Resolution
    "H.R.1968"      # House Bill
]

# Question prompts for LLM
QUESTION_PROMPTS = {
    QuestionType.WHAT_DOES_BILL_DO: """
    What does this bill do? Where is it in the process?
    """,
    
    QuestionType.WHAT_COMMITTEES: """
    What committees is this bill in?
    """,
    
    QuestionType.WHO_IS_SPONSOR: """
    Who is the sponsor?
    """,
    
    QuestionType.WHO_COSPONSORED: """
    Who cosponsored this bill? Are any of the cosponsors on the committee that the bill is in?
    """,
    
    QuestionType.ANY_HEARINGS: """
    Have any hearings happened on the bill? If so, what were the findings?
    """,
    
    QuestionType.ANY_AMENDMENTS: """
    Have any amendments been proposed on the bill? If so, who proposed them and what do they do?
    """,
    
    QuestionType.ANY_VOTES: """
    Have any votes happened on the bill? If so, was it a party-line vote or a bipartisan one?
    """
}

# Output file schema
ARTICLES_OUTPUT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "bill_id": {"type": "string"},
            "bill_title": {"type": "string"},
            "sponsor_bioguide_id": {"type": ["string", "null"]},
            "bill_committee_ids": {"type": "array", "items": {"type": "string"}},
            "article_content": {"type": "string"}
        },
        "required": ["bill_id", "bill_title", "sponsor_bioguide_id", "bill_committee_ids", "article_content"]
    }
}

