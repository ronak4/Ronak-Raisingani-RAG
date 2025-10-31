"""
/**
 * @file congress_api.py
 * @summary Client for the Congress.gov API providing cached, rate-limited
 *          access to structured legislative data (bills, committees, actions,
 *          amendments, votes).
 *
 * @details
 * - Implements simple on-disk JSON caching with TTL to minimize repeated
 *   network calls.
 * - Applies a light client-side rate limiter to stay within API quotas.
 * - Normalizes API responses into a consistent internal `BillData` model.
 * - Fetches secondary resources (committees, actions, amendments, votes) in
 *   parallel for efficiency.
 *
 * @dependencies
 * - httpx (async client with connection pooling)
 * - aiohttp (import retained for potential fallback/compatibility)
 * - python-dotenv (environment variable loading)
 */
"""

import asyncio
import json
import os
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import aiohttp
import httpx
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from utils.schemas import BillData, TARGET_BILLS


class CongressAPIError(Exception):
    """Custom exception for Congress.gov API errors."""
    pass


class CongressAPIClient:
    """
    /**
     * Client for the Congress.gov API with caching, connection pooling, and
     * basic rate limiting.
     *
     * @param api_key: Optional API key; falls back to CONGRESS_API_KEY env var.
     * @param cache_dir: Directory for JSON cache files.
     */
    """
    
    def __init__(self, api_key: Optional[str] = None, cache_dir: str = "cache"):
        self.api_key = api_key or os.getenv("CONGRESS_API_KEY")
        self.base_url = "https://api.congress.gov/v3"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
        # Rate limiting
        self.rate_limit_delay = 0.1  # Reduced to 0.1s for faster processing (API limit is 20k/hour)
        self.last_request_time = 0
        self.max_retries = 3
        self.retry_delay = 5.0
        
        # Headers
        self.headers = {
            "User-Agent": "RAG-News-Generator/1.0",
            "Accept": "application/json"
        }
        if self.api_key:
            self.headers["X-API-Key"] = self.api_key
            # Also add to params for Congress.gov API
            self.api_key_param = self.api_key
        
        # Persistent HTTP client with connection pooling
        self._http_client = None
    
    async def _rate_limit(self):
        """
        /**
         * Ensure minimum spacing between API requests to respect quotas.
         */
        """
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - time_since_last)
        self.last_request_time = time.time()
    
    def _get_cache_path(self, endpoint: str) -> Path:
        """
        /**
         * Compute a safe filesystem path for a given API endpoint.
         *
         * @param endpoint: Relative API path (e.g., "/bill/118/hr/1").
         * @return Path to JSON cache file.
         */
        """
        # Create a safe filename from the endpoint
        safe_name = endpoint.replace("/", "_").replace("?", "_").replace("&", "_")
        return self.cache_dir / f"{safe_name}.json"
    
    def _is_cache_valid(self, cache_path: Path, ttl_hours: int = 24) -> bool:
        """
        /**
         * Check whether an existing cache file is fresh enough to use.
         *
         * @param cache_path: Path to the JSON cache file.
         * @param ttl_hours: Time-to-live in hours.
         */
        """
        if not cache_path.exists():
            return False
        
        file_age = time.time() - cache_path.stat().st_mtime
        return file_age < (ttl_hours * 3600)
    
    async def _get_http_client(self):
        """
        /**
         * Get or create a persistent httpx.AsyncClient with pooling limits.
         */
        """
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                limits=httpx.Limits(
                    max_connections=50,
                    max_keepalive_connections=20
                )
            )
        return self._http_client
    
    async def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        /**
         * Make an HTTP GET request to the Congress.gov API with retries and
         * backoff on rate limits or transient failures.
         *
         * @param endpoint: Relative API path (e.g., "/bill/118/hr/1").
         * @param params: Optional query string params.
         * @return Parsed JSON response as a dict.
         */
        """
        await self._rate_limit()
        
        url = f"{self.base_url}{endpoint}"
        if params is None:
            params = {}
        
        # Add API key to params for Congress.gov API
        if self.api_key:
            params["api_key"] = self.api_key
        
        for attempt in range(self.max_retries):
            try:
                start_time = time.time()
                
                client = await self._get_http_client()
                response = await client.get(url, headers=self.headers, params=params)
                
                duration = time.time() - start_time
                
                # Record performance metrics
                try:
                    from utils.performance_monitor import get_monitor
                    await get_monitor().record_api_call(duration)
                except:
                    pass
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 404:  # Resource not found (e.g., no votes)
                    return {"error": "Not found", "status": 404}
                elif response.status_code == 429:  # Rate limited
                    wait_time = self.retry_delay * (2 ** attempt)
                    print(f"Rate limited. Waiting {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    raise CongressAPIError(f"API request failed: {response.status_code} - {response.text}")
                    
            except httpx.RequestError as e:
                if attempt == self.max_retries - 1:
                    raise CongressAPIError(f"Request failed after {self.max_retries} attempts: {e}")
                await asyncio.sleep(self.retry_delay * (2 ** attempt))
        
        raise CongressAPIError("Max retries exceeded")
    
    async def _get_cached_or_fetch(self, endpoint: str, params: Dict[str, Any] = None, 
                                 ttl_hours: int = 24, fetch_all_pages: bool = False) -> Dict[str, Any]:
        """
        /**
         * Return data from cache if valid; otherwise fetch from the API and
         * refresh the cache.
         * 
         * @param fetch_all_pages: If True, fetch all paginated results
         */
        """
        cache_path = self._get_cache_path(endpoint)
        
        # Check cache first (only if not fetching all pages, to avoid stale partial data)
        if not fetch_all_pages and self._is_cache_valid(cache_path, ttl_hours):
            try:
                with open(cache_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                # Cache corrupted, fetch fresh data
                pass
        
        if fetch_all_pages:
            data = await self._get_all_paginated_data(endpoint, params)
        else:
            data = await self._make_request(endpoint, params)
        
        # Cache the result
        try:
            with open(cache_path, 'w') as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            print(f"Warning: Could not cache data: {e}")
        
        return data
    
    async def _get_all_paginated_data(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        /**
         * Fetch all pages of paginated data from an endpoint.
         * Combines all items from all pages into a single response structure.
         */
        """
        if params is None:
            params = {}
        
        all_items = []
        offset = 0
        limit = 100 
        max_pages = 100 
        page = 0
        
        item_key = None
        if "/cosponsors" in endpoint:
            item_key = "cosponsors"
        elif "/committees" in endpoint:
            item_key = "committees"
        elif "/actions" in endpoint:
            item_key = "actions"
        elif "/amendments" in endpoint:
            item_key = "amendments"
        else:
            item_key = None
        
        page_params = params.copy()
        page_params["offset"] = offset
        page_params["limit"] = limit
        first_page = await self._make_request(endpoint, page_params)
        
        if item_key is None:
            for key in ["cosponsors", "committees", "actions", "amendments", "hearings"]:
                if key in first_page:
                    item_key = key
                    break
        
        if item_key and item_key in first_page:
            items = first_page.get(item_key, [])
            all_items.extend(items)
        
        pagination = first_page.get("pagination", {})
        total_count = pagination.get("count", 0)
        
        while page < max_pages and len(all_items) < total_count:
            offset += limit
            page += 1
            
            page_params = params.copy()
            page_params["offset"] = offset
            page_params["limit"] = limit
            
            page_data = await self._make_request(endpoint, page_params)
            
            if item_key and item_key in page_data:
                items = page_data.get(item_key, [])
                all_items.extend(items)
                
                if len(items) == 0:
                    break
            else:
                break
        
        if item_key:
            first_page[item_key] = all_items
        
        if "pagination" in first_page:
            first_page["pagination"] = {
                "count": len(all_items),
                "limit": limit,
                "offset": 0
            }
        
        return first_page
    
    def _get_chamber_code(self, bill_type: str) -> str:
        """
        /**
         * Convert bill type to chamber code for hearing endpoint.
         *
         * @param bill_type: e.g., "hr", "s", "hres", "sres"
         * @return Chamber code: "house" or "senate"
         */
        """
        bill_type_lower = bill_type.lower()
        if bill_type_lower.startswith("h"):  # hr, hres
            return "house"
        elif bill_type_lower.startswith("s"):  # s, sres
            return "senate"
        else:
            return "house"  # default
    
    async def _get_hearings_for_bill(self, congress: str, bill_type: str, bill_committees: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        /**
         * Query hearings endpoint and match to bill by committee codes.
         *
         * @param congress: Congress number as string
         * @param bill_type: Bill type (hr, s, etc.)
         * @param bill_committees: List of committee dicts with systemCode
         * @return List of matching hearings
         */
        """
        chamber = self._get_chamber_code(bill_type)
        bill_committee_codes = {c.get("system_code") for c in bill_committees if c.get("system_code")}
        
        if not bill_committee_codes:
            return []
        
        hearings_endpoint = f"/hearing/{congress}/{chamber}"
        
        try:
            # Fetch hearings (with pagination if needed)
            hearings_data = await self._get_cached_or_fetch(hearings_endpoint)
            all_hearings = []
            
            # Process paginated results
            current_data = hearings_data
            max_pages = 10  # Limit to avoid too many requests
            page = 0
            
            while page < max_pages:
                hearings_list = current_data.get("hearings", [])
                if not hearings_list:
                    break
                
                # Check each hearing to see if it matches bill committees
                for hearing_summary in hearings_list:
                    jacket_number = hearing_summary.get("jacketNumber")
                    if not jacket_number:
                        continue
                    
                    # Get detailed hearing info
                    hearing_detail_endpoint = f"/hearing/{congress}/{chamber}/{jacket_number}"
                    try:
                        hearing_detail_data = await self._get_cached_or_fetch(hearing_detail_endpoint)
                        hearing_detail = hearing_detail_data.get("hearing", {})
                        
                        # Check if hearing committees match bill committees
                        hearing_committees = hearing_detail.get("committees", [])
                        hearing_committee_codes = {c.get("systemCode") for c in hearing_committees if c.get("systemCode")}
                        
                        if bill_committee_codes & hearing_committee_codes:  # Intersection
                            all_hearings.append({
                                "jacket_number": jacket_number,
                                "title": hearing_detail.get("title"),
                                "dates": hearing_detail.get("dates", []),
                                "committees": hearing_committees,
                                "citation": hearing_detail.get("citation"),
                                "formats": hearing_detail.get("formats", []),
                                "url": hearing_summary.get("url"),
                                "update_date": hearing_detail.get("updateDate")
                            })
                    except Exception as e:
                        # Skip hearings that fail to fetch details
                        continue
                
                # Check for next page
                pagination = current_data.get("pagination", {})
                next_url = pagination.get("next")
                if next_url and page < max_pages - 1:
                    # Extract offset from next URL or stop if no more pages
                    # For now, limit to first page to avoid excessive API calls
                    # Can be enhanced to fetch more pages if needed
                    break
                
                page += 1
                break  # For now, only check first page (can be enhanced)
            
            return all_hearings
            
        except Exception as e:
            print(f"Warning: Could not fetch hearings: {e}")
            return []
    
    def _parse_bill_id(self, bill_id: str) -> tuple[str, str, int]:
        """
        /**
         * Parse a human-readable bill identifier into its components.
         *
         * @param bill_id: e.g., "H.R.1", "S.2296", "S.RES.412".
         * @return (congress, bill_type, bill_number)
         */
        """
        # Examples: 
        # H.R.1 -> (118, "hr", 1)
        # S.2296 -> (118, "s", 2296)
        # S.RES.412 -> (118, "sres", 412)
        # H.RES.353 -> (118, "hres", 353)
        
        # Assume current Congress (118th)
        congress = 118
        
        # Handle different formats
        bill_id_upper = bill_id.upper()
        
        # Check for resolutions (H.RES, S.RES)
        if ".RES." in bill_id_upper:
            parts = bill_id_upper.split(".RES.")
            if len(parts) != 2:
                raise ValueError(f"Invalid resolution ID format: {bill_id}")
            chamber = parts[0].lower()  # H or S
            number = int(parts[1])
            bill_type = f"{chamber}res"  # hres or sres
            return str(congress), bill_type, number
        
        # Handle regular bills (H.R., S.)
        if ".R." in bill_id_upper:
            # H.R.1 format
            parts = bill_id_upper.split(".R.")
            if len(parts) != 2:
                raise ValueError(f"Invalid bill ID format: {bill_id}")
            chamber = parts[0].lower()  # h
            number = int(parts[1])
            bill_type = f"{chamber}r"  # hr
            return str(congress), bill_type, number
        elif bill_id_upper.startswith("S.") and not ".RES." in bill_id_upper:
            # S.2296 format
            parts = bill_id_upper.split(".")
            if len(parts) != 2:
                raise ValueError(f"Invalid bill ID format: {bill_id}")
            number = int(parts[1])
            return str(congress), "s", number
        else:
            raise ValueError(f"Invalid bill ID format: {bill_id}")
    
    async def get_bill_data(self, bill_id: str) -> BillData:
        """
        /**
         * Fetch and aggregate comprehensive data for a single bill, including
         * committees, actions, amendments, and votes. Uses caching and parallel
         * requests where possible.
         */
        """
        congress, bill_type, bill_number = self._parse_bill_id(bill_id)
        
        # Fetch main bill data
        bill_endpoint = f"/bill/{congress}/{bill_type}/{bill_number}"
        bill_data = await self._get_cached_or_fetch(bill_endpoint)
        
        # Extract basic information
        bill_info = bill_data.get("bill", {})
        
        # Get additional data in parallel
        # Endpoints needed for questions:
        # Q1: What does this bill do? -> /summaries (MISSING), /bill (main), /actions
        # Q2: What committees? -> /committees ✓
        # Q3: Who is sponsor? -> /bill (main) ✓
        # Q4: Who cosponsored? -> /cosponsors ✓, /committee/{chamber}/{code} for members (MISSING)
        # Q5: Hearings? -> /hearing/{congress}/{chamber}/{jacketNumber} ✓
        # Q6: Amendments? -> /amendments ✓
        # Q7: Votes? -> /actions (recordedVotes) ✓
        # Note: fetch_all_pages=True for paginated endpoints to get complete data
        tasks = [
            self._get_cached_or_fetch(f"{bill_endpoint}/cosponsors", fetch_all_pages=True),
            self._get_cached_or_fetch(f"{bill_endpoint}/committees", fetch_all_pages=True),
            self._get_cached_or_fetch(f"{bill_endpoint}/actions", fetch_all_pages=True),
            self._get_cached_or_fetch(f"{bill_endpoint}/amendments", fetch_all_pages=True),
            self._get_cached_or_fetch(f"{bill_endpoint}/summaries"),
        ]
        
        try:
            cosponsors_data, committees_data, actions_data, amendments_data, summaries_data = await asyncio.gather(*tasks)
        except Exception as e:
            print(f"Warning: Could not fetch some bill data for {bill_id}: {e}")
            # Provide empty data for failed requests
            cosponsors_data = {"cosponsors": []}
            committees_data = {"committees": []}
            actions_data = {"actions": []}
            amendments_data = {"amendments": []}
            summaries_data = {"summaries": []}
        
        # Handle 404 responses gracefully
        if cosponsors_data.get("error") == "Not found":
            cosponsors_data = {"cosponsors": []}
        if committees_data.get("error") == "Not found":
            committees_data = {"committees": []}
        if actions_data.get("error") == "Not found":
            actions_data = {"actions": []}
        if amendments_data.get("error") == "Not found":
            amendments_data = {"amendments": []}
        if summaries_data.get("error") == "Not found":
            summaries_data = {"summaries": []}
        
        # Parse sponsor information
        sponsor = None
        if "sponsors" in bill_info and bill_info["sponsors"]:
            sponsor_info = bill_info["sponsors"][0]
            sponsor = {
                "bioguide_id": sponsor_info.get("bioguideId"),
                "full_name": sponsor_info.get("fullName"),
                "first_name": sponsor_info.get("firstName"),
                "last_name": sponsor_info.get("lastName"),
                "party": sponsor_info.get("party"),
                "state": sponsor_info.get("state"),
                "url": sponsor_info.get("url")
            }
        
        # Parse cosponsors
        cosponsors = []
        for cosponsor in cosponsors_data.get("cosponsors", []):
            cosponsors.append({
                "bioguide_id": cosponsor.get("bioguideId"),
                "full_name": cosponsor.get("fullName"),
                "party": cosponsor.get("party"),
                "state": cosponsor.get("state"),
                "url": cosponsor.get("url"),
                "date_signed": cosponsor.get("dateSigned")
            })
        
        # Parse committees
        committees = []
        for committee in committees_data.get("committees", []):
            committees.append({
                "system_code": committee.get("systemCode"),
                "name": committee.get("name"),
                "type": committee.get("type"),
                "url": committee.get("url")
            })
        
        # Parse actions and extract votes from actions
        actions = []
        votes = []
        vote_roll_numbers_seen = set()  # Track votes to avoid duplicates
        
        for action in actions_data.get("actions", []):
            action_code = action.get("actionCode")
            action_text = action.get("text", "").lower()
            action_date = action.get("actionDate")
            
            # Parse action
            actions.append({
                "action_code": action_code,
                "text": action.get("text"),
                "action_date": action_date,
                "chamber": action.get("chamber"),
                "url": action.get("url"),
                "type": action.get("type")
            })
            
            # Extract votes from recordedVotes in actions
            # Note: /votes endpoint doesn't exist - votes come from actions
            if "recordedVotes" in action:
                for recorded_vote in action.get("recordedVotes", []):
                    roll_number = recorded_vote.get("rollNumber")
                    # Avoid duplicate votes
                    vote_key = f"{recorded_vote.get('chamber')}-{recorded_vote.get('congress')}-{roll_number}"
                    if vote_key not in vote_roll_numbers_seen:
                        vote_roll_numbers_seen.add(vote_key)
                        
                        # Try to extract vote result from action text
                        action_full_text = action.get("text", "")
                        result = None
                        if "passed" in action_full_text.lower() or "agreed to" in action_full_text.lower():
                            result = "Passed"
                        elif "failed" in action_full_text.lower() or "rejected" in action_full_text.lower():
                            result = "Failed"
                        elif "adopted" in action_full_text.lower():
                            result = "Adopted"
                        
                        votes.append({
                            "roll_call": roll_number,
                            "roll_number": roll_number,
                            "question": action_full_text,  # Use action text as question description
                            "description": action_full_text,
                            "vote_date": recorded_vote.get("date", action_date),
                            "chamber": recorded_vote.get("chamber"),
                            "session_number": recorded_vote.get("sessionNumber"),
                            "congress": recorded_vote.get("congress"),
                            "url": recorded_vote.get("url"),
                            "result": result
                        })
        
        # Fetch hearings from /hearing endpoint and match by committee codes
        hearings = await self._get_hearings_for_bill(congress, bill_type, committees)
        
        # Parse summaries (for "what does this bill do")
        summaries = []
        for summary in summaries_data.get("summaries", []):
            summaries.append({
                "text": summary.get("text"),
                "version_code": summary.get("versionCode"),
                "update_date": summary.get("updateDate"),
                "action_date": summary.get("actionDate"),
                "action_desc": summary.get("actionDesc")
            })
        
        # Parse amendments
        amendments = []
        for amendment in amendments_data.get("amendments", []):
            sponsor_name = None
            sponsor_info = amendment.get("sponsor")
            if sponsor_info:
                if isinstance(sponsor_info, dict):
                    sponsor_name = sponsor_info.get("fullName") or sponsor_info.get("firstName", "") + " " + sponsor_info.get("lastName", "")
                else:
                    sponsor_name = str(sponsor_info)
            else:
                latest_action = amendment.get("latestAction", {})
                action_text = latest_action.get("text", "") if isinstance(latest_action, dict) else ""
                if action_text:
                    import re
                    match = re.search(r'the\s+([A-Z][a-z]+(?:\s+\([A-Z]{2}\))?)\s+amendment', action_text)
                    if match:
                        sponsor_name = match.group(1)
            
            amendments.append({
                "amendment_number": amendment.get("amendmentNumber") or amendment.get("number"),
                "purpose": amendment.get("purpose"),
                "description": amendment.get("description"),
                "sponsor": sponsor_name,
                "sponsor_full": sponsor_info if sponsor_info else None,
                "introduced_date": amendment.get("introducedDate") or (latest_action.get("actionDate") if isinstance(latest_action, dict) else None),
                "latest_action": latest_action,
                "url": amendment.get("url")
            })
        
        return BillData(
            bill_id=bill_id,
            congress=congress,
            bill_type=bill_type.upper(),
            bill_number=bill_number,
            title=bill_info.get("title", ""),
            short_title=bill_info.get("shortTitle"),
            sponsor=sponsor,
            cosponsors=cosponsors,
            committees=committees,
            actions=actions,
            amendments=amendments,
            votes=votes,
            hearings=hearings,
            summaries=summaries,
            status=bill_info.get("status", {}).get("text") if bill_info.get("status") else None,
            introduced_date=bill_info.get("introducedDate"),
            last_action_date=bill_info.get("lastAction", {}).get("actionDate") if bill_info.get("lastAction") else None
        )
    
    async def get_all_bills_data(self) -> Dict[str, BillData]:
        """
        /**
         * Fetch data for all configured target bills in parallel.
         */
        """
        tasks = [self.get_bill_data(bill_id) for bill_id in TARGET_BILLS]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        bills_data = {}
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"Error fetching data for {TARGET_BILLS[i]}: {result}")
            else:
                bills_data[TARGET_BILLS[i]] = result
        
        return bills_data


# Example usage and testing
async def main():
    """Test the Congress API client."""
    client = CongressAPIClient()
    
    # Test with a single bill
    try:
        bill_data = await client.get_bill_data("H.R.1")
        print(f"Fetched data for {bill_data.bill_id}: {bill_data.title}")
        print(f"Sponsor: {bill_data.sponsor}")
        print(f"Committees: {len(bill_data.committees)}")
        print(f"Cosponsors: {len(bill_data.cosponsors)}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
