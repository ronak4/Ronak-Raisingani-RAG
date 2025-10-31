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
from openai import OpenAI
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
    
    def __init__(self, model: Optional[str] = None, timeout: float = 180.0):
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
    
    async def generate_text(self, prompt: str, system_prompt: Optional[str] = None, max_tokens: Optional[int] = None) -> str:
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
        def _call_local_llm() -> str:
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
                        temperature=0.2,  # Lower for faster sampling
                        max_tokens=max_tokens if max_tokens is not None else 512,
                        timeout=self.timeout,
                        extra_body={
                            "options": {
                            "num_ctx": 8192,
                            "num_keep": 256,
                            "top_k": 30,
                            "top_p": 0.9,
                            "repeat_penalty": 1.05
                            }
                        }
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
                        print(f"Local LLM rate limit hit (attempt {attempt + 1}/{max_retries}), waiting {wait_time:.1f}s...")
                        time.sleep(wait_time)
                    else:
                        # Exponential backoff on other transient errors
                        time.sleep(backoff)
                        backoff *= 2
            raise LLMServiceError(f"Local LLM generation failed: {last_err}")
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _call_local_llm)
    
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
        
        # Include summaries for "what does this bill do" question
        if bill_data.summaries:
            # Use the most recent summary
            summary_text = bill_data.summaries[0].get('text', '')
            # Strip HTML tags for cleaner prompt
            import re
            summary_text = re.sub(r'<[^>]+>', '', summary_text)
            data.append(f"Summary: {summary_text[:500]}")
        
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
    
    def _convert_api_url_to_user_url(self, api_url: str, bill_data: BillData = None) -> str:
        """
        /**
         * Convert API URLs (api.congress.gov/v3/...) to user-facing URLs (www.congress.gov/...).
         *
         * @param api_url: API endpoint URL.
         * @param bill_data: Optional bill data for context.
         * @return User-facing Congress.gov URL.
         */
        """
        if not api_url:
            return api_url
        
        # If already a user-facing URL (clerk.house.gov, senate.gov, www.congress.gov), return as-is
        if not api_url.startswith("https://api.congress.gov"):
            return api_url
        
        import re
        
        match = re.search(r'/amendment/(\d+)/(\w+)/(\d+)', api_url)
        if match:
            congress, am_type, number = match.groups()
            if bill_data:
                bill_type = bill_data.bill_type.lower()
                bill_num = bill_data.bill_number
                return f"https://www.congress.gov/bill/{congress}th-congress/{bill_type}/{bill_num}/amendments"
            # Fallback: construct general amendment URL
            if am_type == "hamdt":
                return f"https://www.congress.gov/bill/{congress}th-congress/house-bill/1/amendments"  # Generic fallback
            elif am_type == "samdt":
                return f"https://www.congress.gov/bill/{congress}th-congress/senate-bill/1/amendments"  # Generic fallback
        
        match = re.search(r'/hearing/(\d+)/(\w+)/(\d+)', api_url)
        if match:
            congress, chamber, jacket = match.groups()
            chamber_name = "house" if chamber == "house" else "senate"
            # Link to hearings/events page for that congress/chamber
            return f"https://www.congress.gov/hearings/{congress}th-congress/{chamber_name}"
        
        return api_url
    
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
        
        # Add question-specific data to the prompt
        question_specific_data = ""
        from utils.schemas import QuestionType
        
        if question_id == QuestionType.ANY_AMENDMENTS:
            # Include amendments data for amendment questions
            if bill_data.amendments:
                amendments_text = f"\n\nAmendments ({len(bill_data.amendments)} total):\n"
                for i, amendment in enumerate(bill_data.amendments, 1):
                    amendment_num = amendment.get('amendment_number', 'N/A')
                    purpose = amendment.get('purpose', '')
                    description = amendment.get('description', '')
                    sponsor_name = amendment.get('sponsor', 'Unknown')
                    if not sponsor_name or sponsor_name == 'None':
                        # Try to get from latest_action if available
                        latest_action = amendment.get('latest_action', {})
                        if isinstance(latest_action, dict):
                            action_text = latest_action.get('text', '')
                            if action_text:
                                import re
                                match = re.search(r'the\s+([A-Z][a-z]+(?:\s+\([A-Z]{2}\))?)\s+amendment', action_text)
                                if match:
                                    sponsor_name = match.group(1)
                    introduced_date = amendment.get('introduced_date', 'N/A')
                    url = amendment.get('url', '')
                    
                    amendments_text += f"\n{i}. Amendment {amendment_num}"
                    if introduced_date and introduced_date != 'N/A':
                        amendments_text += f" (Introduced: {introduced_date})"
                    amendments_text += "\n"
                    amendments_text += f"   Sponsor: {sponsor_name}\n"
                    if purpose:
                        amendments_text += f"   Purpose: {purpose}\n"
                    elif description:
                        amendments_text += f"   Description: {description[:300]}\n"
                    if url:
                        amendments_text += f"   URL: {url}\n"
                
                question_specific_data = amendments_text
            else:
                question_specific_data = "\n\nAmendments: None found.\n"
        
        if question_id == QuestionType.ANY_HEARINGS:
            # Include hearings data for hearing questions
            if bill_data.hearings:
                hearings_text = f"\n\nHearings ({len(bill_data.hearings)} total):\n"
                for i, hearing in enumerate(bill_data.hearings, 1):
                    title = hearing.get('title', 'N/A')
                    jacket_number = hearing.get('jacket_number', 'N/A')
                    dates = hearing.get('dates', [])
                    date_str = dates[0] if dates else 'N/A'
                    citation = hearing.get('citation', '')
                    url = hearing.get('url', '')
                    
                    hearings_text += f"\n{i}. {title}\n"
                    if jacket_number and jacket_number != 'N/A':
                        hearings_text += f"   Hearing Number: {jacket_number}\n"
                    if date_str and date_str != 'N/A':
                        hearings_text += f"   Date: {date_str}\n"
                    if citation:
                        hearings_text += f"   Citation: {citation}\n"
                    if url:
                        hearings_text += f"   URL: {url}\n"
                    
                    # Include committee names
                    hearing_committees = hearing.get('committees', [])
                    if hearing_committees:
                        committee_names = [c.get('name', '') for c in hearing_committees if c.get('name')]
                        if committee_names:
                            hearings_text += f"   Committees: {', '.join(committee_names[:3])}\n"
                
                
                question_specific_data = hearings_text
            else:
                question_specific_data = "\n\nHearings: None found.\n"
        
        # Q1: What does this bill do? Where is it in the process?
        if question_id == QuestionType.WHAT_DOES_BILL_DO:
            latest_actions = []
            for action in (bill_data.actions or []):
                text = action.get('text')
                date = action.get('action_date')
                if text and date:
                    latest_actions.append(f"- {date}: {text}")
            votes_count = len(bill_data.votes or [])
            status_line = f"\n\nProcess: Status={bill_data.status or 'N/A'}; Votes recorded={votes_count}."
            if latest_actions:
                status_line += "\nRecent actions:\n" + "\n".join(latest_actions)
            question_specific_data = status_line
        
        # Q2: What committees is this bill in?
        if question_id == QuestionType.WHAT_COMMITTEES:
            if bill_data.committees:
                lines = ["\n\nCommittees:" ]
                for c in bill_data.committees:
                    name = c.get('name', 'N/A')
                    code = c.get('system_code', 'N/A')
                    url = c.get('url', '')
                    line = f"- {name} ({code})"
                    if url:
                        line += f" — {url}"
                    lines.append(line)
                question_specific_data = "\n".join(lines)
            else:
                question_specific_data = "\n\nCommittees: None listed."
        
        # Q3: Who is the sponsor?
        if question_id == QuestionType.WHO_IS_SPONSOR:
            sponsor = bill_data.sponsor or {}
            full_name = sponsor.get('full_name', 'N/A')
            party = sponsor.get('party', 'N/A')
            state = sponsor.get('state', 'N/A')
            bioguide = sponsor.get('bioguide_id')
            sponsor_url = f"https://www.congress.gov/member/{bioguide}" if bioguide else ''
            question_specific_data = (
                f"\n\nSponsor details:\n- {full_name} ({party}-{state})" +
                (f" — {sponsor_url}" if sponsor_url else "")
            )
        
        # Q4: Who cosponsored?
        if question_id == QuestionType.WHO_COSPONSORED:
            count = len(bill_data.cosponsors or [])
            lines = [f"\n\nCosponsors: {count} total"]
            for c in (bill_data.cosponsors or []):
                name = c.get('full_name', 'N/A')
                party = c.get('party', 'N/A')
                state = c.get('state', 'N/A')
                url = c.get('url', '')
                line = f"- {name} ({party}-{state})"
                if url:
                    line += f" — {url}"
                lines.append(line)
            
            question_specific_data = "\n".join(lines)
        
        # Q7: Have any votes happened?
        if question_id == QuestionType.ANY_VOTES:
            votes = bill_data.votes or []
            lines = [f"\n\nVotes: {len(votes)} roll call(s) recorded"]
            for v in votes:
                roll = v.get('roll_number') or v.get('roll_call')
                result = v.get('result') or 'N/A'
                date = v.get('vote_date') or 'N/A'
                chamber = v.get('chamber') or 'N/A'
                url = v.get('url') or ''
                desc = (v.get('description') or '').strip()
                line = f"- {date} [{chamber}] Roll {roll}: {result}"
                if desc:
                    line += f" — {desc[:160]}"
                if url:
                    line += f" — {url}"
                lines.append(line)
            
            question_specific_data = "\n".join(lines)
        
        system_prompt = (
            "You are a knowledgeable assistant that answers questions about U.S.\n"
            "congressional bills using only the provided data from Congress.gov.\n"
            "Write answers in a clear, accessible style suitable for news articles.\n"
            "CRITICAL: When URLs are provided in the data, you MUST include them as markdown hyperlinks.\n"
            "Format: [text](url) - Examples:\n"
            "- Bill: [H.R.1](https://www.congress.gov/bill/118th-congress/house-bill/1)\n"
            "- Sponsor: [Rep. Smith](https://www.congress.gov/member/S000001)\n"
            "- Amendment: [Amendment 133](https://api.congress.gov/v3/amendment/118/hamdt/133)\n"
            "- Committee: [Committee Name](https://www.congress.gov/committee/...)\n"
            "If a URL is provided in the data, you MUST use it in markdown format. Do not just mention the URL as plain text."
        )
        full_prompt = f"""
{bill_data_str}{question_specific_data}

{prompt}

Answer:
"""
        return await self.generate_text(full_prompt, system_prompt, max_tokens=80)
    
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
        # Build a continuous narrative by concatenating answers (no headings)
        answers_text = ""
        for qid in range(1, 8):
            answer = question_answers.get(qid)
            if answer:
                answers_text += f"{answer}\n\n"
        
        # Add link validation context if available
        link_context = ""
        valid_urls_list = []
        if link_check_results:
            valid_count = link_check_results.get('valid_count', 0)
            invalid_count = link_check_results.get('invalid_count', 0)
            
            # Extract list of valid URLs from results
            results = link_check_results.get('results', [])
            valid_urls_list = [r.get('url') for r in results if r.get('is_valid', False)]
            
            link_context = f"\nLink Validation Results: {valid_count} valid URLs, {invalid_count} invalid URLs."
            if valid_urls_list:
                link_context += f"\n\nVERIFIED VALID URLs (ONLY use these):\n"
                for valid_url in valid_urls_list[:20]:  # Limit to first 20 to avoid prompt bloat
                    link_context += f"- {valid_url}\n"
                link_context += "\nCRITICAL: Only use URLs from the verified valid URLs list above. Do NOT invent or modify URLs."
        
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
        all_urls_list = []
        
        # Main bill URLs
        if urls.get('bill_url'):
            all_urls_list.append(f"- Bill: {urls.get('bill_url')}")
        if urls.get('actions_url'):
            all_urls_list.append(f"- Actions: {urls.get('actions_url')}")
        if urls.get('cosponsors_url'):
            all_urls_list.append(f"- Cosponsors: {urls.get('cosponsors_url')}")
        if urls.get('sponsor_url'):
            all_urls_list.append(f"- Sponsor: {urls.get('sponsor_url')}")
        
        # Extract URLs from committees
        if bill_data.committees:
            for committee in bill_data.committees:
                if committee.get('url'):
                    all_urls_list.append(f"- Committee ({committee.get('name', 'N/A')}): {committee.get('url')}")
        
        # Extract URLs from amendments
        if bill_data.amendments:
            congress = bill_data.congress
            bill_type = bill_data.bill_type.lower()
            bill_num = bill_data.bill_number
            amendments_url = f"https://www.congress.gov/bill/{congress}th-congress/{bill_type}/{bill_num}/amendments"
            all_urls_list.append(f"- Amendments: {amendments_url}")
        
        # Extract URLs from votes 
        if bill_data.votes:
            for vote in bill_data.votes[:20]: 
                if vote.get('url'):
                    roll = vote.get('roll_number') or vote.get('roll_call') or 'N/A'
                    vote_url = vote.get('url')
                    user_url = self._convert_api_url_to_user_url(vote_url, bill_data)
                    all_urls_list.append(f"- Vote Roll {roll}: {user_url}")
        
        # Extract URLs from hearings 
        if bill_data.hearings:
            for hearing in bill_data.hearings[:10]:
                if hearing.get('url'):
                    title = hearing.get('title', 'Hearing')[:50]
                    user_url = self._convert_api_url_to_user_url(hearing.get('url'), bill_data)
                    all_urls_list.append(f"- Hearing ({title}): {user_url}")
        
        url_context = f"""
REQUIRED: Use these URLs as markdown hyperlinks throughout your article:
{chr(10).join(all_urls_list) if all_urls_list else "No URLs available"}

CRITICAL: You MUST include markdown links [text](url) for:
- The bill itself: [bill name](bill_url)
- The sponsor: [sponsor name](sponsor_url) when mentioning the sponsor
- Committees mentioned: [committee name](committee_url) when referencing committees
- Amendments mentioned: [Amendment X](amendment_url) when discussing amendments
- Votes mentioned: [Roll Call X](vote_url) when referencing votes
- Any hearings: [hearing title](hearing_url) when mentioning hearings

Example: "The bill was introduced by [Rep. John Smith](https://www.congress.gov/member/S000001) and referred to the [House Committee on Natural Resources](https://www.congress.gov/committee/...)."
"""
        
        prompt = f"""
Bill Data:
{self._format_bill_data_for_prompt(bill_data)}

Question Answers:
{answers_text}

{url_context}

Write a complete, compelling news article (aim for 600-900 words) that tells the story of this bill in an engaging way. Make sure to write the FULL article without stopping early:

**Structure your article like a real political news story:**
- Start with an engaging lead paragraph that captures attention
- Use flowing narrative paragraphs, not bullet points or technical lists
- Write in political journalistic style for general readers, not technical summaries
- Include all 7 key elements naturally within the story WITHOUT using mini paragraphs to switch topics OR TOPIC HEADLINES:
  1. What does this bill do? Where is it in the process?
  2. What committees is this bill in?
  3. Who is the sponsor?
  4. Who cosponsored this bill? Are any of the cosponsors on the committee that the bill is in?
  5. Have any hearings happened on the bill? If so, what were the findings?
  6. Have any amendments been proposed on the bill? If so, who proposed them and what do they do?
  7. Have any votes happened on the bill? If so, was it a party-line vote or a bipartisan one?

**Writing Style:**
- Write in political journalistic style for general readers, not technical summaries
- Use active voice and engaging language
- Avoid technical jargon - write for general audience
- Create smooth transitions between topics, do not jump around from topic to topic or use mini paragraphs to switch topics.
- End with a strong conclusion that tells the reader if they should be worried about the bill or not.
- Make sure to answer each question completely and accurately
- Write a complete political news article with introduction, body paragraphs, and conclusion
- Do not stop writing until you have a full, complete article

Include proper markdown hyperlinks for all Congress.gov references.
"""
        return await self.generate_text(prompt, system_prompt, max_tokens=1536)

    async def check_model_availability(self) -> bool:
        """
        /**
         * Check if the model is available by making a simple test request.
         *
         * @return True if model is available, False otherwise.
         */
        """
        try:
            # Make a simple test request to check if the model is available
            test_response = await self.generate_text("Test", "You are a helpful assistant.")
            return len(test_response) > 0
        except Exception:
            return False


