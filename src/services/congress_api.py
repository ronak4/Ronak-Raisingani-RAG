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
from datetime import timedelta
import datetime
import httpx
import re
from xml.etree import ElementTree as ET
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
        self.api_key_param = self.api_key or None
        
        # Persistent HTTP client with connection pooling
        self._http_client = None

    FACTS_DIR = os.getenv("FACTS_CACHE_DIR","/tmp/legis_facts")
    FACTS_TTL = 21600

    async def get_committee_details(self, chamber: str, code: str) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30) as c:
            params = {}
            if self.api_key:
                params["api_key"] = self.api_key
            r = await c.get(f"{self.base_url}/committee/{(chamber or '').lower()}/{(code or '').lower()}",
                            params=params, headers=self.headers)
            if r.status_code != 200:
                return None
            data = r.json() or {}
            name = (data.get("committee", {}) or {}).get("name") or data.get("name")
            return {"code": (code or "").lower(), "name": name, "chamber": chamber}

    async def _get_committee_members(self, chamber: str, code: str) -> set:
        async with httpx.AsyncClient(timeout=20) as c:
            params = {}
            if self.api_key:
                params["api_key"] = self.api_key
            r = await c.get(
                f"{self.base_url}/committee/details/{chamber}/{code.lower()}",
                params=params,
                headers=self.headers,
            )
            if r.status_code != 200:
                return set()
            data = r.json()
            members = data.get("members", [])
            return {m.get("bioguideId") for m in members if m.get("bioguideId")}

    async def _fetch_xml(self, url):
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(url, headers=self.headers)
            r.raise_for_status()
            try:
                return ET.fromstring(r.text)
            except ET.ParseError:
                return None

    def _house_vote_xml(self, year, roll): 
        return f"https://clerk.house.gov/evs/{year}/roll{int(roll):03d}.xml"

    def _senate_vote_xml(self, congress, session, roll):
        return f"https://www.senate.gov/legislative/LIS/roll_call_votes/vote{int(congress)}{int(session)}/vote_{int(congress)}_{int(session)}_{int(roll):05d}.xml"

    def _senate_vote_html(self, congress, session, roll):
        return self._senate_vote_xml(congress, session, roll).replace(".xml",".htm")

    def _derive_roll_hints(self, bill):
        hints = []
        for a in bill.actions or []:
            t = (a.get("text") or a.get("action") or "").upper()
            d = (a.get("action_date") or a.get("date") or "")[:10]
            y = int(d[:4]) if d[:4].isdigit() else None
            m = re.search(r"(?:ROLL(?:\s|-)?CALL(?:\s|-)?VOTE\s*NO?\.?\s*(\d+)|ROLL\s*NO\.?\s*(\d+))", t)
            if m and y:
                chamber = "house" if "HOUSE" in t else ("senate" if "SENATE" in t else None)
                roll_no = int(m.group(1) or m.group(2))
                if chamber:
                     hints.append({"chamber": chamber, "year": y, "roll": roll_no})
        return hints

    def _parse_house_xml(self, root):
        if root is None:
            return None
        def gi(p):
            x = root.findtext(p) or "0"
            try:
                return int(x)
            except:
                return 0
        party_totals = {
            "democratic": {
                "yea": gi(".//democratic-yeas"),
                "nay": gi(".//democratic-nays"),
                "present": gi(".//democratic-present"),
                "not_voting": gi(".//democratic-not-voting"),
            },
            "republican": {
                "yea": gi(".//republican-yeas"),
                "nay": gi(".//republican-nays"),
                "present": gi(".//republican-present"),
                "not_voting": gi(".//republican-not-voting"),
            },
            "independent": {
                "yea": gi(".//independent-yeas"),
                "nay": gi(".//independent-nays"),
                "present": gi(".//independent-present"),
                "not_voting": gi(".//independent-not-voting"),
            },
        }
        out = {
            "question": root.findtext(".//question") or root.findtext(".//question-text"),
            "result": root.findtext(".//result") or root.findtext(".//vote-result"),
            "date": root.findtext(".//vote-date") or root.findtext(".//action-date"),
            "totals": {
                "yea": gi(".//yea-total"),
                "nay": gi(".//nay-total"),
                "present": gi(".//present-total"),
                "not_voting": gi(".//not-voting-total"),
            },
            "party_totals": party_totals,
            "legis": root.findtext(".//legis-num") or root.findtext(".//bill-number"),
        }
        out["party_line"] = self._classify_party_line(out.get("party_totals"))
        return out

    def _parse_senate_xml(self, root):
        if root is None:
            return None
        def gi(p):
            x = root.findtext(p)
            return int(x) if x and x.isdigit() else 0
        party_totals = {
            "democratic": {
                "yea": gi(".//DEMOCRAT/YEAS"),
                "nay": gi(".//DEMOCRAT/NAYS"),
                "present": gi(".//DEMOCRAT/PRESENT"),
                "not_voting": gi(".//DEMOCRAT/NOT_VOTING"),
            },
            "republican": {
                "yea": gi(".//REPUBLICAN/YEAS"),
                "nay": gi(".//REPUBLICAN/NAYS"),
                "present": gi(".//REPUBLICAN/PRESENT"),
                "not_voting": gi(".//REPUBLICAN/NOT_VOTING"),
            },
            "independent": {
                "yea": gi(".//INDEPENDENT/YEAS"),
                "nay": gi(".//INDEPENDENT/NAYS"),
                "present": gi(".//INDEPENDENT/PRESENT"),
                "not_voting": gi(".//INDEPENDENT/NOT_VOTING"),
            },
        }
        out = {
            "question": root.findtext(".//QUESTION"),
            "result": root.findtext(".//RESULT"),
            "date": root.findtext(".//VOTE_DATE"),
            "totals": {
                "yea": gi(".//YEAS"),
                "nay": gi(".//NAYS"),
                "present": gi(".//PRESENT"),
                "not_voting": gi(".//NOT_VOTING"),
            },
            "party_totals": party_totals,
        }
        out["party_line"] = self._classify_party_line(out.get("party_totals"))
        return out

    def _classify_party_line(self, party_totals: dict) -> str:
        if not party_totals:
            return ""
        dy = party_totals.get("democratic", {}).get("yea", 0)
        ry = party_totals.get("republican", {}).get("yea", 0)
        dn = party_totals.get("democratic", {}).get("nay", 0)
        rn = party_totals.get("republican", {}).get("nay", 0)
        if dy > 0 and ry > 0:
            return "bipartisan"
        if (dy > 0 and ry == 0 and rn > 0) or (ry > 0 and dy == 0 and dn > 0):
            return "party-line"
        return ""

    async def get_votes_for_bill(self, bill):
        out: Dict[str, Any] = {}
        recorded: List[Dict[str, Any]] = []
        for a in (bill.actions or []):
            if not isinstance(a, dict):
                continue
            for rv in (a.get("recordedVotes") or []):
                chamber = (rv.get("chamber") or a.get("chamber") or "").lower()
                try:
                    roll = int(rv.get("rollNumber"))
                except Exception:
                    continue
                date = rv.get("date") or a.get("action_date") or a.get("actionDate") or ""
                year = int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else None
                session = rv.get("sessionNumber")
                if chamber in ("house", "senate") and roll and year:
                    recorded.append({"chamber": chamber, "roll": roll, "year": year, "session": session})
        seen = set()
        hints: List[Dict[str, Any]] = []
        for r in recorded:
            key = (r["chamber"], r["year"], r["roll"]) 
            if key in seen:
                continue
            seen.add(key)
            hints.append(r)
        if not hints:
            hints = self._derive_roll_hints(bill)
        
        house_votes = []
        senate_votes = []
        
        for h in hints:
            if h["chamber"] == "house":
                v = await self._get_house_vote_via_congress_api(int(bill.congress), int(h["year"]), int(h["roll"]))
                if not v:
                    xml = await self._fetch_xml(self._house_vote_xml(h["year"], h["roll"]))
                    v = self._parse_house_xml(xml)
                    if v:
                        v["public_url"] = f"https://clerk.house.gov/Votes/rollcallvote.aspx?VoteNum={h['roll']:03d}&Year={h['year']}"
                        v["roll"] = h["roll"]
                if v:
                    house_votes.append(v)
            else:
                session = h.get("session") or (1 if int(h["year"]) % 2 == 1 else 2)
                xml = await self._fetch_xml(self._senate_vote_xml(int(bill.congress), session, int(h["roll"])) )
                v = self._parse_senate_xml(xml)
                if v:
                    v["public_url"] = self._senate_vote_html(int(bill.congress), session, int(h["roll"]))
                    v["roll"] = int(h["roll"])
                    senate_votes.append(v)
        
        # Return the most recent vote (last in list) for compatibility, or all votes
        if house_votes:
            out["house"] = house_votes[-1]  # Most recent
            out["house_votes"] = house_votes  # All votes for future use
        if senate_votes:
            out["senate"] = senate_votes[-1]
            out["senate_votes"] = senate_votes
        if out.get("house"):
            hv = out["house"]
        return out

    async def _get_house_vote_via_congress_api(self, congress: int, year: int, roll: int) -> Optional[Dict[str, Any]]:
        try:
            session = 1 if year % 2 == 1 else 2
            endpoint = f"/vote/house/{int(congress)}/{int(session)}/{int(roll)}"
            data = await self._get_cached_or_fetch(endpoint)
            v = data.get("vote") or data.get("houseVote") or data
            if not isinstance(v, dict):
                return None
            totals = v.get("totals") or {}
            def gi(*keys):
                for k in keys:
                    x = totals.get(k)
                    if x is None:
                        continue
                    try:
                        return int(x)
                    except Exception:
                        try:
                            return int((x or {}).get("total"))
                        except Exception:
                            pass
                return 0
            out = {
                "question": v.get("question") or v.get("questionText"),
                "result": v.get("result") or v.get("voteResult"),
                "date": v.get("date") or v.get("voteDate"),
                "totals": {
                    "yea": gi("yea", "yeas", "yeaTotal"),
                    "nay": gi("nay", "nays", "nayTotal"),
                    "present": gi("present", "presentTotal"),
                    "not_voting": gi("notVoting", "not_voting", "notVotingTotal"),
                },
                "public_url": v.get("url"),
                "roll": int(roll),
            }
            if not out.get("public_url"):
                out["public_url"] = f"https://clerk.house.gov/Votes/rollcallvote.aspx?VoteNum={int(roll):03d}&Year={int(year)}"
            return out
        except Exception:
            return None

    async def _list_with_pagination(self, endpoint):
        items = []
        offset = 0
        limit = 250
        async with httpx.AsyncClient(timeout=20) as c:
            while True:
                params = {"offset": offset, "limit": limit}
                if self.api_key:
                    params["api_key"] = self.api_key
                r = await c.get(f"{self.base_url}{endpoint}", params=params, headers=self.headers)
                if r.status_code != 200:
                    break
                data = r.json()
                key = next((k for k, v in data.items() if isinstance(v, list)), None)
                batch = data.get(key, [])
                if not batch:
                    break
                items.extend(batch)
                if len(batch) < limit:
                    break
                offset += len(batch)
        return items

    def _extract_bill_numbers(items):
        out = []
        for s in items or []:
            if isinstance(s, str):
                out.append(s)
        return out

    async def get_committee_meetings_for_bill(self, bill, window_days: int = 21):
        def _norm_str(s: str) -> str:
            return " ".join(((s or "").upper()).split()).strip()
        def _format_measure_display(bt: str, bn: int) -> str:
            bt = (bt or "").upper()
            if bt == "HR": return f"H.R. {bn}"
            if bt == "S": return f"S. {bn}"
            if bt == "HRES": return f"H.RES. {bn}"
            if bt == "SRES": return f"S.RES. {bn}"
            if bt == "HJRES": return f"H.J.RES. {bn}"
            if bt == "SJRES": return f"S.J.RES. {bn}"
            if bt == "HCONRES": return f"H.CON.RES. {bn}"
            if bt == "SCONRES": return f"S.CON.RES. {bn}"
            return f"{bt} {bn}"
        async def _get_hearing_detail(congress: int, chamber: str, jacket: Any) -> Dict[str, Any]:
            try:
                d = await self._get_cached_or_fetch(f"/hearing/{int(congress)}/{chamber}/{jacket}")
                return d.get("hearing") or d
            except Exception:
                return {}
        def _extract_related_bills(detail: Dict[str, Any]) -> List[str]:
            out = []
            for k in ("relatedBills", "related-bills", "bills"):
                arr = detail.get(k) or []
                for b in arr:
                    if isinstance(b, dict):
                        bid = b.get("displayNumber") or b.get("identifier") or b.get("billId")
                        if bid:
                            out.append(str(bid))
                    elif b:
                        out.append(str(b))
            return out
        codes = {(c.get("code") or c.get("committee_code") or c.get("system_code") or "").upper() for c in (getattr(bill, "committees", []) or []) if c}
        if not codes:
            return []
        recent = [(a.get("action_date") or a.get("actionDate") or a.get("date") or "")[:10] for a in (bill.actions or [])][-10:]
        def in_window(ds: str) -> bool:
            if not recent:
                return True
            try:
                dt = datetime.date.fromisoformat(ds[:10])
            except Exception:
                return False
            return any(len(d) == 10 and abs((dt - datetime.date.fromisoformat(d)).days) <= window_days for d in recent)
        merged: List[Dict[str, Any]] = []
        bid_disp = _format_measure_display(bill.bill_type, bill.bill_number)
        bid_norm = _norm_str(bid_disp)
        for chamber in ["house", "senate"]:
            hs = await self._list_with_pagination(f"/hearing/{bill.congress}/{chamber}")
            ms = await self._list_with_pagination(f"/committee-meeting/{bill.congress}/{chamber}")

            for x in hs:
                ic = {(c.get("systemCode") or c.get("code") or c.get("system_code") or "").upper() for c in (x.get("committees") or []) if c}
                if not (ic & codes):
                    continue

                title = ((x.get("title") or "") + " " + (x.get("description") or "")).strip()
                date = x.get("date") or ""
                match_basis = None
                detail = None
                related_bills_detail = []

                jacket = x.get("jacketNumber")
                if jacket:
                    detail = await self._get_hearing_detail(int(bill.congress), chamber, jacket)
                    related_bills_detail = _extract_related_bills(detail) or []
                    rel_norm = {_norm_str(rb) for rb in related_bills_detail}
                    if bid_norm in rel_norm:
                        match_basis = "related_bills"

                if not match_basis and title and bid_norm in _norm_str(title):
                    match_basis = "title_match"
                if not match_basis and date and in_window(date):
                    match_basis = "date_window"

                if match_basis:
                    related_bills_inline = [
                        rb.get("billNumber")
                        for rb in (x.get("relatedBills") or x.get("related_bills") or [])
                        if rb and rb.get("billNumber")
                    ]
                    related_bills = sorted({*_extract_bill_numbers(related_bills_detail), *related_bills_inline})

                    summary = (x.get("summary") or x.get("description") or "").strip()
                    if not summary and detail is None and jacket:
                        detail = await self._get_hearing_detail(int(bill.congress), chamber, jacket)
                    if not summary and detail:
                        summary = (detail.get("summary") or detail.get("description") or "").strip()

                    merged.append({
                        "title": x.get("title"),
                        "date": date,
                        "chamber": chamber,
                        "committees": sorted(ic & codes),
                        "url": x.get("url") or x.get("sourceLink") or x.get("source_link"),
                        "related_bills": related_bills,
                        "match_basis": match_basis,
                        "source": "hearing",
                        "findings": summary[:600] if summary else "",
                    })

            for x in ms:
                ic = {(c.get("systemCode") or c.get("code") or c.get("committeeCode") or "").upper() for c in (x.get("committees") or []) if c}
                if not (ic & codes):
                    continue

                title = ((x.get("title") or "") + " " + (x.get("description") or "")).strip()
                date = x.get("date") or x.get("meetingDate") or ""
                match_basis = None
                detail = None
                related_bills_detail = []

                jacket = x.get("jacketNumber")
                if jacket:
                    detail = await self._get_hearing_detail(int(bill.congress), chamber, jacket)
                    related_bills_detail = _extract_related_bills(detail) or []
                    rel_norm = {_norm_str(rb) for rb in related_bills_detail}
                    if bid_norm in rel_norm:
                        match_basis = "related_bills"

                if not match_basis and title and bid_norm in _norm_str(title):
                    match_basis = "title_match"
                if not match_basis and date and in_window(date):
                    match_basis = "date_window"

                if match_basis:
                    related_bills_inline = [
                        rb.get("billNumber")
                        for rb in (x.get("relatedBills") or x.get("related_bills") or [])
                        if rb and rb.get("billNumber")
                    ]
                    related_bills = sorted({*_extract_bill_numbers(related_bills_detail), *related_bills_inline})

                    summary = (x.get("summary") or x.get("description") or "").strip()
                    if not summary and detail is None and jacket:
                        detail = await self._get_hearing_detail(int(bill.congress), chamber, jacket)
                    if not summary and detail:
                        summary = (detail.get("summary") or detail.get("description") or "").strip()

                    merged.append({
                        "title": x.get("title"),
                        "date": date,
                        "chamber": chamber,
                        "committees": sorted(ic & codes),
                        "url": x.get("url") or x.get("sourceLink") or x.get("source_link"),
                        "related_bills": related_bills,
                        "match_basis": match_basis,
                        "source": "committee-meeting",
                        "findings": summary[:600] if summary else "",
                    })

        merged.sort(key=lambda z: z.get("date") or "", reverse=True)
        return merged[:10]

    def _canonical_urls(self, bill):
        bt = (bill.bill_type or "").lower()
        slug = {
            "hr": "house-bill",
            "hres": "house-resolution",
            "hjres": "house-joint-resolution",
            "hconres": "house-concurrent-resolution",
            "s": "senate-bill",
            "sres": "senate-resolution",
            "sjres": "senate-joint-resolution",
            "sconres": "senate-concurrent-resolution",
        }.get(bt, bt)
        base = f"https://www.congress.gov/bill/{int(bill.congress)}th-congress/{slug}/{int(bill.bill_number)}"
        u = {
            "bill": base,
            "actions": f"{base}/all-actions",
            "cosponsors": f"{base}/cosponsors",
            "all_info": f"{base}/all-info#summaries",
        }
        sp = getattr(bill, "sponsor", None) or {}
        name = (sp.get("name") or "").strip().lower()
        bid = (sp.get("bioguide_id") or "").strip()
        if name and bid:
            slug_name = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
            u["sponsor"] = f"https://www.congress.gov/member/{slug_name}/{bid}"
        return u

    async def _hydrate_amendment(self, congress, chamber, amd_no):
         async with httpx.AsyncClient(timeout=20) as c:
             params = {}
             if self.api_key:
                 params["api_key"] = self.api_key
             seg = "house-amendment" if (str(chamber or "").lower() == "house") else ("senate-amendment" if (str(chamber or "").lower() == "senate") else None)
             urls = []
             if seg:
                 urls.append(f"{self.base_url}/amendment/{congress}/{seg}/{int(amd_no)}")
             else:
                 urls.append(f"{self.base_url}/amendment/{congress}/house-amendment/{int(amd_no)}")
                 urls.append(f"{self.base_url}/amendment/{congress}/senate-amendment/{int(amd_no)}")
             for u in urls:
                 r = await c.get(u, params=params, headers=self.headers)
                 if r.status_code == 200:
                     return r.json()
             return {}

    async def _enrich_amendments(self, bill):
        amds = getattr(bill, "amendments", []) or []
        out = []
        for a in amds:
            no = a.get("number") or a.get("amendmentNumber") or a.get("seq") or a.get("amendmentNum")
            if no is None:
                continue
            try:
                d = await self._hydrate_amendment(int(bill.congress), (a.get("chamber") or "").lower(), int(no))
            except Exception:
                d = {}
            spon = d.get("sponsor") or a.get("sponsor") or {}
            sponsor_bioguide = spon.get("bioguideId") or spon.get("bioguide_id")
            sponsor_name = spon.get("fullName") or spon.get("name")
            purpose = d.get("purpose") or d.get("description") or a.get("purpose") or a.get("description")
            chamber = ((a.get("chamber") or (d.get("chamber") if d else None) or "") or "").lower() or ("house" if str(bill.bill_type).lower().startswith("h") else "senate")
            url = self._cg_amendment_url(int(bill.congress), chamber, int(no))
            result = a.get("result") or d.get("status") or d.get("result")
            out.append({
                "number": int(no),
                "chamber": chamber,
                "sponsor_bioguide": sponsor_bioguide,
                "sponsor_name": sponsor_name,
                "purpose": purpose,
                "result": result,
                "url": url,
            })
        return out

    async def get_committee_details(self, chamber: str, code: str):
        async with httpx.AsyncClient(timeout=30) as c:
            params = {}
            if getattr(self, "api_key", None):
                params["api_key"] = self.api_key
            r = await c.get(f"{self.base_url}/committee/details/{(chamber or '').lower()}/{(code or '').lower()}",
                            params=params, headers=getattr(self, "headers", {}))
            if r.status_code != 200:
                return {}
            data = r.json() or {}
            name = (data.get("committee", {}) or {}).get("name") or data.get("name")
            ch = (data.get("committee", {}) or {}).get("chamber") or data.get("chamber") or chamber
            return {"code": (code or "").lower(), "name": name, "chamber": ch}

    async def get_committee_members_bioguide_ids(self, chamber: str, code: str) -> set:
        roster = await self._get_committee_members((chamber or "").lower(), (code or "").lower())
        return roster or set()

    async def cosponsors_on_committees(self, committees, cosponsors):
        out = {}
        for c in committees:
            members = await self.get_committee_members_bioguide_ids(c.get("chamber",""), c.get("code",""))
            hits = []
            for cs in cosponsors or []:
                bid = (cs.get("bioguide_id") or cs.get("bioguideId") or "").strip()
                if bid and bid in members:
                    hits.append(cs.get("name") or bid)
            out[c.get("name") or c.get("code")] = hits
        return out

    async def build_trusted_facts(self, bill):
        if not os.path.isdir(self.FACTS_DIR):
            os.makedirs(self.FACTS_DIR, exist_ok=True)
        key = f"{bill.congress}-{bill.bill_type}-{bill.bill_number}.json"
        path = os.path.join(self.FACTS_DIR, key)
        if os.path.exists(path) and (datetime.datetime.utcnow().timestamp() - os.path.getmtime(path)) < self.FACTS_TTL:
            with open(path, "r") as f:
                return json.load(f)

        votes = await self.get_votes_for_bill(bill)
        if isinstance(votes, dict):
            if votes.get("house"):
                hv = votes.get("house")
        hearings = await self.get_committee_meetings_for_bill(bill)

        raw = (
            getattr(bill, "committees", None)
            or getattr(bill, "committee_refs", None)
            or getattr(bill, "referrals", None)
            or []
        )

        committees_out = []
        for ref in raw:
            if isinstance(ref, str):
                ch = ""
                cd = ref
                nm = None
            else:
                ch = (ref.get("chamber") or ref.get("chamberCode") or "").strip()
                cd = (ref.get("code") or ref.get("committeeCode") or ref.get("committee") or "").strip()
                nm = (ref.get("name") or "").strip() or None

            det = None
            if cd and (not nm or not ch):
                det = await self.get_committee_details(ch, cd)

            committees_out.append({
                "code": (cd or "").lower(),
                "name": nm or ((det or {}).get("name") or cd),
                "chamber": ch or ((det or {}).get("chamber") or ""),
            })

        bill.committees = committees_out

        amds = await self._enrich_amendments(bill)
        urls = self._canonical_urls(bill)

        cos = getattr(bill, "cosponsors", []) or []
        overlap = await self.cosponsors_on_committees(committees_out, cos)

        latest_text = getattr(bill, "latest_action_text", None) or (bill.actions[-1]["text"] if bill.actions else "")
        latest_code = getattr(bill, "latest_action_code", None) or (bill.actions[-1].get("action_code") if bill.actions else "")
        has_votes = bool((votes or {}).get("house") or (votes or {}).get("senate"))
        had_floor_activity = has_votes or any(("ROLL" in (a.get("text","").upper()) or "ON PASSAGE" in (a.get("text","").upper()) or "PASSED" in (a.get("text","").upper())) for a in (bill.actions or []))
        introduced_date = getattr(bill, "introduced_date", None)
        first_action_date = (bill.actions[0].get("action_date") if (getattr(bill,"actions",None) and bill.actions and bill.actions[0].get("action_date")) else None)
        def _derive_stage():
             house = bool((votes or {}).get("house"))
             senate = bool((votes or {}).get("senate"))
             txt = " ".join([(a.get("text") or "") for a in (bill.actions or [])]).upper()
             if "BECAME PUBLIC LAW" in txt or "SIGNED BY PRESIDENT" in txt:
                 return "enacted"
             if "PRESENTED TO PRESIDENT" in txt:
                 return "to-president"
             if house and senate:
                 return "senate-passed"
             if house:
                 return "house-passed"
             return "introduced"
        stage = _derive_stage()
        summaries_all = getattr(bill, "summaries", []) or []
        summary_latest = None
        if summaries_all:
            try:
                summary_latest = max((s for s in summaries_all if s.get("update_date")), key=lambda s: s.get("update_date"))
            except Exception:
                summary_latest = summaries_all[-1] if summaries_all else None

        facts = {
            "bill_id": f"{str(bill.bill_type).upper()} {int(bill.bill_number)}",
            "title": bill.title or getattr(bill, "short_title", "") or "",
            "congress": int(bill.congress),
            "sponsor": getattr(bill, "sponsor", {}) or {},
            "committees": committees_out,
            "cosponsors_who_serve_on_committees": overlap,
            "cosponsors_count": len(cos),
            "latest_action": latest_text,
            "status_code": latest_code or "",
            "votes": votes,  # DEBUG: votes dict stored here - check if all fields preserved
            "hearings": hearings,
            "amendments": amds,
            "urls": urls,
            "had_floor_activity": had_floor_activity,
             "stage": stage,
             "introduced_date": introduced_date,
             "first_action_date": first_action_date,
             "summary_latest": summary_latest,
        }

        if isinstance(facts.get("votes"), dict) and facts["votes"].get("house"):
            hv = facts["votes"]["house"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(facts, f, ensure_ascii=False)
        return facts
    
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
        
        # Parse actions (build before deriving votes/hearings)
        actions = []
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
        
        # Keep BillData.votes empty; canonical votes come from build_trusted_facts()
        votes = []
        
        # Use merged hearings/meetings filtered by committees and date window
        from types import SimpleNamespace
        bill_like = SimpleNamespace(
            congress=int(congress),
            bill_type=bill_type,
            bill_number=int(bill_number),
            actions=actions,
            committees=committees,
            sponsor=sponsor,
        )
        hearings = await self.get_committee_meetings_for_bill(bill_like)

        
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
            sponsor_info = amendment.get("sponsor")
            sponsor_name = None
            if isinstance(sponsor_info, dict):
                sponsor_name = sponsor_info.get("fullName") or " ".join(filter(None, [sponsor_info.get("firstName"), sponsor_info.get("lastName")]))
            elif sponsor_info:
                sponsor_name = str(sponsor_info)
            latest_action = amendment.get("latestAction") or {}

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

