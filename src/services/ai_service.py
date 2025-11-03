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
import re
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
     * @param model: Optional model name; defaults to "qwen2.5:7b-32k" (with 32768 token context window).
     * @param timeout: Per-request timeout in seconds.
     */
    """

    BILL_TYPE_SLUG = {
        "hr":"house-bill","s":"senate-bill",
        "hjres":"house-joint-resolution","sjres":"senate-joint-resolution",
        "hconres":"house-concurrent-resolution","sconres":"senate-concurrent-resolution",
        "hres":"house-resolution","sres":"senate-resolution",
    }
    def _bill_slug(self, bt: str) -> str:
        return self.BILL_TYPE_SLUG.get((bt or "").lower(), (bt or "").lower())
    
    def _cg_bill_url(self, congress: int, bill_type: str, number: int) -> str:
        slug = {
            "hr": "house-bill",
            "hres": "house-resolution",
            "hjres": "house-joint-resolution",
            "hconres": "house-concurrent-resolution",
            "s": "senate-bill",
            "sres": "senate-resolution",
            "sjres": "senate-joint-resolution",
            "sconres": "senate-concurrent-resolution",
        }[(bill_type or "").lower()]
        return f"https://www.congress.gov/bill/{int(congress)}th-congress/{slug}/{int(number)}"

    def _cg_member_url(self, name: str, bioguide_id: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
        return f"https://www.congress.gov/member/{slug}/{bioguide_id}"
    
    def _cg_committee_url(self, chamber: str, code: str, name: str) -> str:
        base = "house" if (chamber or "").lower().startswith("h") else "senate"
        name_slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower().replace("committee", "").strip()).strip("-")
        return f"https://www.congress.gov/committee/{base}-{name_slug}/{(code or '').lower()}"

    def _prefer_public_url(self, obj: dict, *, fallback: str = "") -> str:
        for k in ("congressdotgov_url","website_url","url"):
            u = (obj or {}).get(k)
            if u:
                return self._convert_api_url_to_user_url(u)
        return fallback or "https://www.congress.gov"

    def _cg_amendment_url(self, congress: int, chamber: str, amd_number: int) -> str:
        typ = "house-amendment" if (chamber or "").lower().startswith("h") else "senate-amendment"
        return f"https://www.congress.gov/amendment/{int(congress)}th-congress/{typ}/{int(amd_number)}"

    def _senate_roll_url(self, congress: int, session: int, roll: int) -> str:
        r5 = f"{int(roll):05d}"
        return (
            f"https://www.senate.gov/legislative/LIS/roll_call_votes/"
            f"vote{int(congress)}{int(session)}/vote_{int(congress)}_{int(session)}_{r5}.htm"
        )

    def _vote_public_url(self, vote: dict, bill: BillData) -> str:
        try:
            roll = vote.get("roll_number") or vote.get("roll") or vote.get("roll_call")
            chamber = (vote.get("chamber") or "").lower()
            date = vote.get("vote_date") or vote.get("date") or ""
            year = int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else None
            if not roll:
                return self._cg_bill_url(bill.congress, bill.bill_type, bill.bill_number)
            if chamber.startswith("house"):
                if year:
                    return f"https://clerk.house.gov/Votes/rollcallvote.aspx?VoteNum={int(roll):03d}&Year={year}"
                return self._cg_bill_url(bill.congress, bill.bill_type, bill.bill_number)
            if chamber.startswith("senate"):
                if year is None:
                    session = 1 if (int(bill.congress) % 2 == 1) else 2
                else:
                    session = 1 if (year % 2 == 1) else 2
                return self._senate_roll_url(int(bill.congress), int(session), int(roll))
        except Exception:
            pass
        return self._cg_bill_url(bill.congress, bill.bill_type, bill.bill_number)
    
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
        self.model = model or "qwen2.5:7b-32k"  # Custom model with 32768 token context window
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
                                "num_ctx": 32768,
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
        
        m = re.search(r"/bill/(\d+)/(hr|s|hjres|sjres|hconres|sconres|hres|sres)/(\d+)", api_url, re.I)
        if m:
            return self._cg_bill_url(int(m[1]), m[2], int(m[3]))
        m = re.search(r"/member/([a-z0-9]+)", api_url, re.I)
        if m:
            return self._cg_member_url(m[1])
        m = re.search(r"/committee/(house|senate)/([a-z0-9]+)", api_url, re.I)
        if m:
            chamber = m[1]
            code = m[2]
            return self._cg_committee_url(chamber, code, code)  # Use code as name fallback
        m = re.search(r"/amendment/(\d+)/(hr|s|hjres|sjres|hconres|sconres|hres|sres)/(\d+)", api_url, re.I)
        if m:
            congress, btype, bill_no = int(m[1]), m[2], int(m[3])
            if bill_data:
                for amd in (bill_data.amendments or []):
                    amd_no = amd.get("amendment_number")
                    if amd_no and str(bill_no) == str(bill_data.bill_number):
                        try:
                            chamber = "house" if btype.lower().startswith("h") else "senate"
                            return self._cg_amendment_url(congress, chamber, int(amd_no))
                        except Exception:
                            break
            return self._cg_bill_url(congress, btype, bill_no) + "/amendments"
        return "https://www.congress.gov"
    
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
        bill_type = bill_data.bill_type
        bill_num = bill_data.bill_number
        
        base = self._cg_bill_url(congress, bill_type, bill_num)
        urls = {
            "bill_url": base,
            "actions_url": f"{base}/actions",
            "cosponsors_url": f"{base}/cosponsors",
            "amendments_url": f"{base}/amendments",
            "text_url": f"{base}/text",
            "summary_url": f"{base}/all-info#summaries",
        }
        if bill_data.sponsor and bill_data.sponsor.get("bioguide_id") and bill_data.sponsor.get("name"):
            urls["sponsor_url"] = self._cg_member_url(
                bill_data.sponsor["name"],
                bill_data.sponsor["bioguide_id"],
            )
        return urls

    def _extract_votes(self, bill_data: BillData, facts: Optional[dict]) -> list:      
        if facts and isinstance(facts.get("votes"), dict):
            out = []
            hv = facts["votes"].get("house") if facts.get("votes") else None
            if hv:
                vote_entry = {
                    "roll_number": hv.get("roll"),
                    "vote_date": hv.get("date"),
                    "chamber": "House",
                    "result": hv.get("result"),
                    "description": hv.get("question"),
                    "url": hv.get("public_url"),
                }      
                out.append(vote_entry)        
            sv = facts["votes"].get("senate") if facts.get("votes") else None
            if sv:
                vote_entry = {
                    "roll_number": sv.get("roll"),
                    "vote_date": sv.get("date"),
                    "chamber": "Senate",
                    "result": sv.get("result"),
                    "description": sv.get("question"),
                    "url": sv.get("public_url"),
                }
                out.append(vote_entry)
            if out:
                return out
        return bill_data.votes or []

    def _get_committees(self, bill_data: BillData, facts: Optional[dict]) -> list:
        src = (facts.get("committees") if facts else None) or (bill_data.committees or [])
        out = []
        for c in src:
            name = c.get("name") or c.get("committee_name") or c.get("title") or "Committee"
            code = (c.get("code") or c.get("committee_code") or c.get("system_code") or "").lower()
            chamber = (c.get("chamber") or "").lower()
            if not chamber and code:
                chamber = "house" if code.startswith("h") else "senate"
            if not chamber:
                chamber = ""  # Fallback
            url = c.get("url") or self._cg_committee_url(chamber, code, name)
            out.append({"name": name, "code": code.upper() if code else None, "chamber": chamber, "url": url})
        return out

    def _get_hearings(self, bill_data: BillData, facts: Optional[dict]) -> list:
        return (facts.get("hearings") if facts else None) or (bill_data.hearings or [])
    
    async def answer_question(self, bill_data: BillData, question_id: int, facts: Optional[dict] = None) -> str:
        if question_id not in QUESTION_PROMPTS:
            raise ValueError(f"Invalid question ID: {question_id}")
        prompt = QUESTION_PROMPTS[question_id]
        bill_data_str = self._format_bill_data_for_prompt(bill_data)

        votes_list = self._extract_votes(bill_data, facts)
        hearings_list = self._get_hearings(bill_data, facts)
        committees_list = self._get_committees(bill_data, facts)
        overlap = (facts.get("cosponsors_who_serve_on_committees") if facts else None) or {}

        question_specific_data = ""
        from utils.schemas import QuestionType

        if question_id == QuestionType.ANY_AMENDMENTS:
            if bill_data.amendments:
                amendments_text = f"\n\nAmendments ({len(bill_data.amendments)} total):\n"
                for i, amendment in enumerate(bill_data.amendments, 1):
                    amendment_num = amendment.get("amendment_number", "N/A")
                    purpose = amendment.get("purpose", "")
                    description = amendment.get("description", "")
                    sponsor_name = amendment.get("sponsor", "Unknown")
                    introduced_date = amendment.get("introduced_date", "N/A")
                    amendments_text += f"\n{i}. Amendment {amendment_num}"
                    if introduced_date and introduced_date != "N/A":
                        amendments_text += f" (Introduced: {introduced_date})"
                    amendments_text += "\n"
                    amendments_text += f"   Sponsor: {sponsor_name}\n"
                    if purpose:
                        amendments_text += f"   Purpose: {purpose}\n"
                    elif description:
                        amendments_text += f"   Description: {description[:300]}\n"
                question_specific_data = amendments_text
            else:
                question_specific_data = "\n\nAmendments: None found.\n"

        if question_id == QuestionType.ANY_HEARINGS:
            if hearings_list:
                hearings_text = f"\n\nHearings ({len(hearings_list)} total):\n"
                for i, hearing in enumerate(hearings_list, 1):
                    title = hearing.get("title", "N/A")
                    date = hearing.get("date") or (hearing.get("dates", [])[:1] or ["N/A"])[0]
                    citation = hearing.get("citation", "")
                    hearings_text += f"\n{i}. {title}\n"
                    if date and date != "N/A":
                        hearings_text += f"   Date: {date}\n"
                    if citation:
                        hearings_text += f"   Citation: {citation}\n"
                    hc = hearing.get("committees") or []
                    if hc:
                        names = [c.get("name", "") for c in hc if c.get("name")]
                        if names:
                            hearings_text += f"   Committees: {', '.join(names[:3])}\n"
                question_specific_data = hearings_text
            else:
                 if facts and facts.get("had_floor_activity"):
                     question_specific_data = "\n\nHearings: None found in committee records; the bill advanced under a House/Senate rule or direct floor consideration.\n"
                 else:
                     question_specific_data = "\n\nHearings: None found.\n"

        if question_id == QuestionType.WHAT_DOES_BILL_DO:
            latest_actions = []
            for action in (bill_data.actions or []):
                text = action.get("text")
                date = action.get("action_date")
                if text and date:
                    latest_actions.append(f"- {date}: {text}")
            status_line = f"\n\nProcess: Status={bill_data.status or 'N/A'}; Votes recorded={len(votes_list)}."
            if latest_actions:
                status_line += "\nRecent actions:\n" + "\n".join(latest_actions)
            question_specific_data = status_line

        if question_id == QuestionType.WHAT_COMMITTEES:
            if committees_list:
                lines = ["\n\nCommittees:"]
                for c in committees_list:
                    name = c.get("name", "N/A")
                    code = c.get("code") or c.get("system_code") or "N/A"
                    lines.append(f"- {name} ({code})")
                question_specific_data = "\n".join(lines)
            else:
                question_specific_data = "\n\nCommittees: None listed."

        if question_id == QuestionType.WHO_IS_SPONSOR:
            sponsor = bill_data.sponsor or {}
            full_name = sponsor.get("full_name", "N/A")
            party = sponsor.get("party", "N/A")
            state = sponsor.get("state", "N/A")
            bioguide = sponsor.get("bioguide_id")
            sponsor_url = f"https://www.congress.gov/member/{bioguide}" if bioguide else ""
            question_specific_data = (f"\n\nSponsor details:\n- {full_name} ({party}-{state})" + (f" — {sponsor_url}" if sponsor_url else ""))

        if question_id == QuestionType.WHO_COSPONSORED:
            count = len(bill_data.cosponsors or [])
            lines = [f"\n\nCosponsors: {count} total"]
            for c in (bill_data.cosponsors or []):
                name = c.get("full_name", "N/A")
                party = c.get("party", "N/A")
                state = c.get("state", "N/A")
                lines.append(f"- {name} ({party}-{state})")
            if overlap:
                hits = []
                for code, members in overlap.items():
                    if members:
                        names = [m.get("full_name") or m.get("name") for m in members if (m.get("full_name") or m.get("name"))]
                        if names:
                            hits.append(f"{len(names)} cosponsor(s) sit on {code}: {', '.join(names[:5])}")
                if hits:
                    lines.append("\nCommittee overlap: " + "; ".join(hits))
            question_specific_data = "\n".join(lines)

        if question_id == QuestionType.ANY_VOTES:
            votes = votes_list
            lines = [f"\n\nVotes: {len(votes)} roll call(s) recorded"]
            for v in votes:
                roll = v.get("roll_number") or v.get("roll_call") or "N/A"
                result = v.get("result") or "N/A"
                date = v.get("vote_date") or "N/A"
                chamber = v.get("chamber") or "N/A"
                desc = (v.get("description") or "").strip()
                line = f"- {date} [{chamber}] Roll {roll}: {result}"
                if desc:
                    line += f" — {desc[:160]}"
                url = v.get("url") or self._vote_public_url(v, bill_data)
                if url:
                    line += f" — {url}"
                lines.append(line)
            question_specific_data = "\n".join(lines)

        system_prompt = (
            "You are an extraction-first political journalist. Use ONLY the provided Congress.gov data.\n"
            "Do not add outside facts, conjecture, or summaries from memory. If a detail is missing, write: "
            "\"Not specified in the provided data.\"\n"
            "Each answer must be 3–5 paragraphs, each paragraph 3–5 sentences, plain narrative (no lists, no headings).\n"
            "Be precise and neutral. Quote numbers, dates, titles, and vote counts exactly as provided. If conflicting\n"
            "values appear, prefer the most recent by date; if still ambiguous, state the discrepancy in one sentence.\n"
            "Linking: When a URL is provided in the input, you MUST hyperlink it in markdown format [text](url).\n"
            "Do NOT invent or guess URLs; if none is provided for a reference, leave it unlinked.\n"
            "BANNED language: 'likely', 'appears', 'reportedly', 'it seems', hedging about facts.\n"
            "Examples (format only):\n"
            "- Bill: [H.R.1](https://www.congress.gov/bill/118th-congress/house-bill/1)\n"
            "- Sponsor: [Rep. Smith](https://www.congress.gov/member/S000001)\n"
            "- Amendment: [House Amendment 133](https://www.congress.gov/amendment/118th-congress/house-amendment/133)\n"
            "- Committee: [Committee Name](https://www.congress.gov/committee/...)\n"
            "If a URL is provided, you MUST use markdown linking; do not print raw URLs."
        )
        full_prompt = f"""
{bill_data_str}{question_specific_data}

{prompt}

Answer:
"""
        return await self.generate_text(full_prompt, system_prompt, max_tokens=500)

    async def generate_article(self, bill_data: BillData, question_answers: Dict[int, str], link_check_results: Dict[str, Any] = None, facts: Optional[dict] = None) -> str:
        answers_text = ""
        for qid in range(1, 8):
            answer = question_answers.get(qid)
            if answer:
                answers_text += f"{answer}\n\n"

        link_context = ""
        valid_urls_list = []
        if link_check_results:
            valid_count = link_check_results.get("valid_count", 0)
            invalid_count = link_check_results.get("invalid_count", 0)
            results = link_check_results.get("results", [])
            valid_urls_list = [r.get("url") for r in results if r.get("is_valid", False)]
            link_context = f"\nLink Validation Results: {valid_count} valid URLs, {invalid_count} invalid URLs."
            if valid_urls_list:
                link_context += f"\n\nVERIFIED VALID URLs (ONLY use these):\n"
                for valid_url in valid_urls_list[:20]:
                    link_context += f"- {valid_url}\n"
                link_context += "\nCRITICAL: Only use URLs from the verified valid URLs list above. Do NOT invent or modify URLs."

        system_prompt = (
            "You are a professional journalist writing engaging news articles for a general audience.\n"
            "Write in a clear, accessible style that reads like a real news story, not a technical summary.\n"
            "Use an engaging lead paragraph, flowing narrative, and journalistic tone throughout.\n"
            "CRITICAL: Include markdown hyperlinks in format [text](url) for ALL Congress.gov references.\n"
            "Example: [H.R.1](https://www.congress.gov/bill/118th-congress/house-bill/1)\n"
            f"{link_context}\n"
            "CRITICAL: The article MUST be 600 to 900 words. This is a hard requirement, not a suggestion.\n"
            "CRITICAL: Include ALL vote information from the Question Answers section, especially from Question 7 about votes.\n"
        )

        urls = self._build_congress_urls(bill_data)
        all_urls_list = []
        if urls.get("bill_url"):
            all_urls_list.append(f"- Bill: {urls.get('bill_url')}")
        if urls.get("actions_url"):
            all_urls_list.append(f"- Actions: {urls.get('actions_url')}")
        if urls.get("cosponsors_url"):
            all_urls_list.append(f"- Cosponsors: {urls.get('cosponsors_url')}")
        if urls.get("sponsor_url"):
            all_urls_list.append(f"- Sponsor: {urls.get('sponsor_url')}")

        committees = self._get_committees(bill_data, facts)
        for committee in committees:
            name = committee.get("name", "N/A")
            code = (committee.get("code") or "").lower()
            chamber = (committee.get("chamber") or "").lower()
            # Infer chamber from code if not explicitly provided
            if not chamber and code:
                chamber = "house" if code.startswith("h") else "senate"
            if not chamber:
                chamber = ""  # Fallback
            url = self._prefer_public_url(committee, fallback=self._cg_committee_url(chamber, code, name))
            all_urls_list.append(f"- Committee ({name}): {url}")

        have_specific = 0
        for amd in (bill_data.amendments or [])[:5]:
            amd_no = amd.get("amendment_number")
            if amd_no:
                chamber = "house" if bill_data.bill_type.lower().startswith("h") else "senate"
                all_urls_list.append(
                    f"- Amendment {amd_no}: " + self._cg_amendment_url(bill_data.congress, chamber, int(amd_no))
                )
                have_specific += 1
        all_urls_list.append(f"- Amendments (all): {urls['amendments_url']}")

        votes = self._extract_votes(bill_data, facts)
        if votes:
            for vote in votes[:3]:
                roll = vote.get("roll_number") or vote.get("roll_call") or "N/A"
                vurl = vote.get("url") or self._vote_public_url(vote, bill_data)
                all_urls_list.append(f"- Vote Roll {roll}: {vurl}")

        hearings = self._get_hearings(bill_data, facts)
        if hearings:
            for hearing in hearings[:2]:
                title = (hearing.get("title") or "Hearing")[:50]
                hurl = self._prefer_public_url(hearing)
                if hurl.startswith("https://api.congress.gov"):
                    committees = hearing.get("committees") or []
                    if committees:
                        c0 = committees[0]
                        hurl = self._cg_committee_url(
                            c0.get("chamber") or c0.get("chamber_code") or "",
                            c0.get("code") or c0.get("committee_code") or "",
                            c0.get("name") or c0.get("committee_name") or "",
                        )
                    else:
                        hurl = urls["bill_url"]
                all_urls_list.append(f"- Hearing ({title}): {hurl}")

        urls_unique = sorted(set(all_urls_list or []))
        url_context = f"""
REQUIRED: Use these URLs as markdown hyperlinks throughout your article:
{chr(10).join(urls_unique) if urls_unique else "No URLs available"}

CRITICAL: You MUST include markdown links [text](url) for:
- The bill itself: [bill name](bill_url)
- The sponsor: [sponsor name](sponsor_url) when mentioning the sponsor
- Committees mentioned: [committee name](committee_url) when referencing committees
- Amendments mentioned: [Amendment X](amendment_url) when discussing amendments
- Votes mentioned: [Roll Call X](vote_url) when referencing votes
- Any hearings: [hearing title](hearing_url) when mentioning hearings

Example: "The bill was introduced by [Rep. John Smith](https://www.congress.gov/member/S000001) and referred to the [House Committee on Natural Resources](https://www.congress.gov/committee/...)."
"""
         # Canonical facts extracted from normalized 'facts' payload
        stage_raw = ((facts or {}).get('stage') or (bill_data.status or 'N/A'))
        stage_map = {
            "introduced": "Introduced in the House/Senate",
            "house-passed": "Passed the House",
            "senate-passed": "Passed the Senate",
            "to-president": "Presented to the President",
            "enacted": "Became law",
            "failed": "Failed passage",
        }
        stage = stage_map.get(str(stage_raw).lower(), stage_raw)
        introduced_on = ((facts or {}).get('introduced_date') or 'N/A')
        _votes = (facts or {}).get('votes') or {}
        hv = _votes.get('house') if isinstance(_votes, dict) else None
        sv = _votes.get('senate') if isinstance(_votes, dict) else None
        house_vote_desc = (f"{hv.get('result')} (Roll {hv.get('roll')}, {hv.get('date')})" if hv else "Not specified in the provided data.")
        senate_vote_desc = (f"{sv.get('result')} (Roll {sv.get('roll')}, {sv.get('date')})" if sv else "Not specified in the provided data.")
        sl = ((facts or {}).get('summary_latest') or {})
        summary_text = (sl.get('text') or sl.get('summary') or sl.get('description') or '')
        summary_excerpt = (summary_text.replace('\n',' ').strip()[:400] + ('…' if len(summary_text) > 400 else '')) if summary_text else "Not specified in the provided data."
        facts_context = f"""
        
 Canonical Facts:
 - Introduced: {introduced_on}
 - Stage: {stage}
 - House vote: {house_vote_desc}
 - Senate vote: {senate_vote_desc}
 - CRS latest summary (excerpt): {summary_excerpt}
 """
        prompt = f"""
Bill Data:
{self._format_bill_data_for_prompt(bill_data)}

Question Answers:
{answers_text}
{facts_context}
{url_context}

Write a complete, factual political news article. 

**CRITICAL WORD COUNT REQUIREMENT:** The article MUST be between 600 and 900 words. Count your words as you write. Do not stop early. This is a hard requirement. Aim for 750 words as a target.

Use **only** the provided Question Answers and verified Congress.gov URLs.  
Do **not** add outside facts, speculation, or commentary beyond the data.  
If a required detail is missing, write exactly: *"Not specified in the provided data."*  

**CRITICAL: Vote Information** - You MUST include comprehensive information about all votes from Question 7 (the votes question). Include roll call numbers, dates, results, margins, and URLs. Do not skip or minimize vote information.

**Structure (guidance for you—do not include section headings in the article):**
- Lead: one engaging paragraph (4-6 sentences) introducing the bill and its current stage.  
- Body: cohesive narrative paragraphs (no lists, bullets, or subheads) that seamlessly incorporate:
  1) What the bill does and where it is in the process (expand on this)
  2) Committees involved (expand on their roles)
  3) The sponsor and their background/role
  4) Cosponsors and any overlap with committees (expand if there are many)
  5) Hearings and findings (if any, expand on them)
  6) Amendments, their authors, and purposes (if any, expand on them)
  7) Votes taken - EXPAND on this. Include detailed vote information: roll call numbers, dates, results, margins, whether party-line or bipartisan, and include markdown links to vote URLs
- Conclusion: summarize the bill's next steps or significance in neutral tone (3-5 sentences).

**Writing and factual rules:**
- Follow AP-style clarity, neutral political tone, and active voice.  
- Avoid jargon, speculation, or filler phrases.  
- Quote all numbers, titles, and dates exactly as provided.  
- If conflicting data appear, state the discrepancy concisely.  
- Use 8 to 12 narrative paragraphs, each 4 to 8 sentences.  
- Maintain smooth transitions between subjects—no abrupt jumps.  
- Every Congress.gov entity mentioned must use a markdown link `[text](url)` when a verified URL is available.  
- Do **not** invent or guess URLs, and do **not** print them raw.  

**Output requirements:**  
- MUST be 600-900 words. Count as you write. Do not stop at 300-400 words.
- Include ALL vote information prominently - this is critical.
- Completeness and factual accuracy take priority.
"""
        return await self.generate_text(prompt, system_prompt, max_tokens=2400)  # Increased from 1536 to allow for longer articles

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


