"""
/**
 * @file ai_service.py
 * @summary AI LLM service for generating answers and full articles using a
 *          local LLM endpoint (Ollama on localhost).
 *
 * @details
 * - Provides a thin async wrapper around a local SDK client with retry and
 *   simple backoff.
 * - Formats bill data and prompts for the 7 required questions and the final
 *   article.
 * - Builds canonical Congress.gov URLs for hyperlink insertion.
 *
 * @dependencies
 * - python-dotenv (loads environment variables)
 */
"""

import os
import asyncio
import time
from typing import Dict, Optional, Any
from dotenv import load_dotenv
load_dotenv()
from utils.schemas import BillData, QUESTION_PROMPTS


class LLMServiceError(Exception):
    """Custom exception for LLM service errors."""
    pass


class AIService:
    """
    /**
     * Service for interacting with a local LLM endpoint (Ollama on localhost).
     *
     * @param model: Optional model name; defaults to "qwen2.5:7b".
     * @param timeout: Per-request timeout in seconds.
     */
    """
    
    def __init__(self, model: Optional[str] = None, timeout: float = 60.0):
        """
        /**
         * Initialize the AI service for local inference.
         *
         * @param model: Model identifier understood by the local endpoint.
         * @param timeout: Request timeout in seconds.
         * @remark Uses a local Ollama endpoint by default (no internet usage).
         */
        """
        self.model = model or "qwen2.5:7b"
        self.timeout = timeout
        self._client = OpenAI(api_key="ollama", base_url="http://localhost:11434/v1")
    
    async def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        /**
         * Generate text via the local LLM endpoint with retries and exponential
         * backoff on transient errors.
         *
         * @param prompt: User/content prompt to send to the model.
         * @param system_prompt: Optional system guidance for tone/policy.
         * @return Generated text content (stripped) on success.
         * @raises LLMServiceError if all retries fail.
         */
        """
        def _call_openai() -> str:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            max_retries = 5
            backoff = 2.0
            last_err: Optional[Exception] = None
            for attempt in range(max_retries):
                try:
                    start = time.time()
                    resp = self._client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=0.3,  # Lower for faster sampling
                        max_tokens=4096,  # Increased for full article generation
                        timeout=self.timeout,
                    )
                    duration = time.time() - start
                    try:
                        from utils.performance_monitor import get_monitor
                        asyncio.run(get_monitor().record_llm_call(duration))
                    except Exception:
                        pass
                    return (resp.choices[0].message.content or "").strip()
                except Exception as e:
                    last_err = e
                    if "rate_limit" in str(e).lower() or "429" in str(e):
                        wait_time = backoff * (2 ** attempt)
                        print(f"Rate limit hit (attempt {attempt + 1}/{max_retries}), waiting {wait_time:.1f}s...")
                        time.sleep(wait_time)
                    else:
                        # Exponential backoff on other transient errors
                        time.sleep(backoff)
                        backoff *= 2
            raise LLMServiceError(f"OpenAI generation failed: {last_err}")
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _call_openai)
    
    def _format_bill_data_for_prompt(self, bill_data: BillData) -> str:
        """
        /**
         * Compact bill data for inclusion in prompts (kept minimal for speed).
         *
         * @param bill_data: Structured bill information.
         * @return Minimal multi-line string suitable for prompt context.
         */
        """
        data = [
            f"Bill: {bill_data.bill_id} - {bill_data.title}",
            f"Status: {bill_data.status or 'N/A'}",
        ]
        if bill_data.sponsor:
            data.append(
                f"Sponsor: {bill_data.sponsor.get('full_name', 'N/A')} "
                f"({bill_data.sponsor.get('party', 'N/A')}-{bill_data.sponsor.get('state', 'N/A')})"
            )
        if bill_data.committees:
            names = ", ".join([c.get("name", "N/A") for c in bill_data.committees[:2]])
            data.append(f"Committees: {names}")
        if bill_data.cosponsors:
            data.append(f"Cosponsors: {len(bill_data.cosponsors)} total")
        return "\n".join(data)
    
    def _build_congress_urls(self, bill_data: BillData) -> Dict[str, str]:
        """
        /**
         * Build canonical Congress.gov URLs for the given bill.
         *
         * @param bill_data: Structured bill information.
         * @return Dict of URL strings keyed by page purpose.
         */
        """
        congress = bill_data.congress
        bill_type = bill_data.bill_type.lower()
        bill_num = bill_data.bill_number
        
        urls = {
            "bill_url": f"https://www.congress.gov/bill/{congress}th-congress/{bill_type}/{bill_num}",
            "actions_url": f"https://www.congress.gov/bill/{congress}th-congress/{bill_type}/{bill_num}/actions",
            "cosponsors_url": f"https://www.congress.gov/bill/{congress}th-congress/{bill_type}/{bill_num}/cosponsors",
        }
        
        if bill_data.sponsor and bill_data.sponsor.get('bioguide_id'):
            bioguide = bill_data.sponsor['bioguide_id']
            urls["sponsor_url"] = f"https://www.congress.gov/member/{bioguide}"
        
        return urls
    
    async def answer_question(self, bill_data: BillData, question_id: int) -> str:
        """
        /**
         * Answer one of the seven required questions for a bill using only the
         * local model.
         *
         * @param bill_data: Structured bill information.
         * @param question_id: Question identifier (1-7).
         * @return Markdown-formatted answer text including hyperlinks.
         */
        """
        if question_id not in QUESTION_PROMPTS:
            raise ValueError(f"Invalid question ID: {question_id}")
        prompt = QUESTION_PROMPTS[question_id]
        bill_data_str = self._format_bill_data_for_prompt(bill_data)
        system_prompt = (
            "You are a knowledgeable assistant that answers questions about U.S.\n"
            "congressional bills using only the provided data from Congress.gov.\n"
            "Write answers in a clear, accessible style suitable for news articles.\n"
            "Be factual, concise, and ALWAYS include markdown hyperlinks in format [text](url)\n"
            "for all Congress.gov references. Use actual URLs from the provided data."
        )
        full_prompt = f"""
{bill_data_str}

{prompt}

Answer:
"""
        return await self.generate_text(full_prompt, system_prompt)
    
    async def generate_article(self, bill_data: BillData, question_answers: Dict[int, str], link_check_results: Dict[str, Any] = None) -> str:
        """
        /**
         * Generate a complete news-style article that incorporates the seven
         * required elements and includes verified Congress.gov hyperlinks using
         * the local LLM only.
         *
         * @param bill_data: Structured bill information.
         * @param question_answers: Map of question_id -> answer text.
         * @param link_check_results: Optional validation summary for links.
         * @return Markdown article content.
         */
        """
        titles = {
            1: "What does this bill do?",
            2: "What committees is this bill in?",
            3: "Who is the sponsor?",
            4: "Who cosponsored this bill?",
            5: "Have any hearings happened?",
            6: "Have any amendments been proposed?",
            7: "Have any votes happened?",
        }
        answers_text = ""
        for qid, answer in question_answers.items():
            if qid in titles:
                answers_text += f"**{titles[qid]}**\n{answer}\n\n"
        
        # Add link validation context if available
        link_context = ""
        if link_check_results:
            valid_count = link_check_results.get('valid_count', 0)
            invalid_count = link_check_results.get('invalid_count', 0)
            link_context = f"\nLink Validation Results: {valid_count} valid URLs, {invalid_count} invalid URLs. Only use verified working links."
        
        system_prompt = (
            "You are a professional journalist writing engaging news articles for a general audience.\n"
            "Write in a clear, accessible style that reads like a real news story, not a technical summary.\n"
            "Use an engaging lead paragraph, flowing narrative, and journalistic tone throughout.\n"
            "CRITICAL: Include markdown hyperlinks in format [text](url) for ALL Congress.gov references.\n"
            "Example: [H.R.1](https://www.congress.gov/bill/118th-congress/house-bill/1)\n"
            f"{link_context}"
        )
        # Build URLs for context
        urls = self._build_congress_urls(bill_data)
        url_context = f"""
Available Congress.gov URLs:
- Bill: {urls.get('bill_url', 'N/A')}
- Actions: {urls.get('actions_url', 'N/A')}
- Cosponsors: {urls.get('cosponsors_url', 'N/A')}
- Sponsor: {urls.get('sponsor_url', 'N/A')}
"""
        
        prompt = f"""
Bill Data:
{self._format_bill_data_for_prompt(bill_data)}

Question Answers:
{answers_text}

{url_context}

Write a complete, compelling news article (aim for 400-500 words) that tells the story of this bill in an engaging way. Make sure to write the FULL article without stopping early:

**Structure your article like a real news story:**
- Start with an engaging lead paragraph that captures attention
- Use flowing narrative paragraphs, not bullet points or technical lists
- Write in journalistic style for general readers, not technical summaries
- Include all 7 key elements naturally within the story:
  1. What does this bill do? Where is it in the process?
  2. What committees is this bill in?
  3. Who is the sponsor?
  4. Who cosponsored this bill? Are any of the cosponsors on the committee that the bill is in?
  5. Have any hearings happened on the bill? If so, what were the findings?
  6. Have any amendments been proposed on the bill? If so, who proposed them and what do they do?
  7. Have any votes happened on the bill? If so, was it a party-line vote or a bipartisan one?

**Writing Style:**
- Use active voice and engaging language
- Avoid technical jargon - write for general audience
- Create smooth transitions between topics
- End with a strong conclusion
- Make sure to answer each question completely and accurately
- Write a complete article with introduction, body paragraphs, and conclusion
- Do not stop writing until you have a full, complete article

Include proper markdown hyperlinks for all Congress.gov references.
"""
        return await self.generate_text(prompt, system_prompt)


