import json
import os
import re
import time
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from anthropic import Anthropic, HUMAN_PROMPT, AI_PROMPT
from supabase import create_client


# Cost optimization constants
REQUEST_CACHE_TTL_MINUTES = 60  # Cache HTTP responses to avoid duplicate scrapes
LLM_CACHE_TTL_HOURS = 24  # Cache LLM enrichment responses
MIN_BATCH_SIZE_FOR_ENRICHMENT = 2  # Only batch enrich if multiple deals
USE_FAST_MODEL = True  # Use cheaper model variant when possible
SEARCH_BATCH_DELAY_SECONDS = 0.5  # Reduce API load with throttling

# LLM Context Window Management
HAIKU_CONTEXT_WINDOW = 8000  # Haiku max tokens
OPUS_CONTEXT_WINDOW = 200000  # Opus max tokens
CONTEXT_SAFETY_MARGIN = 0.8  # Use 80% of context window to be safe
MAX_DEALS_PER_REQUEST = 5  # Maximum deals to include in single Discord post
STREAMING_THRESHOLD = 3  # Stream output if more than 3 deals
TOKEN_ESTIMATE_RATIO = 0.33  # Rough estimate: 1 token per 3 characters


SEARCH_QUERIES = [
    "site:riyasewana.com/buy suzuki alto 800 colombo 2014 2015 2016",
    "site:riyasewana.com/buy honda fit gp1 colombo low mileage",
    "site:riyasewana.com/buy toyota aqua colombo western province",
    "site:ikman.lk/en/ad/ suzuki alto 800 colombo urgent negotiable",
]

MODEL_MARKET_MAP = {
    "alto": {(2015, 2016): 4100000, (2014, 2014): 3700000},
    "wagon r": {(2016, 2017): 5000000},
    "fit gp1": {(2012, 2013): 6800000},
    "fit gp5": {(2014, 2015): 7500000},
    "aqua": {(2013, 2014): 8000000, (2015, 2015): 9000000},
    "dayz": {(2015, 2016): 5800000},
    "vitz": {(2014, 2015): 5500000},
    "vezel": {(2015, 2015): 9000000},
}

VALID_LOCATIONS = ["colombo", "western", "gampaha", "kalutara"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


@dataclass
class Listing:
    url: str
    listing_id: str
    title: str
    year: Optional[int]
    make: Optional[str]
    model: Optional[str]
    asking_price: Optional[int]
    mileage: Optional[int]
    transmission: Optional[str]
    location: Optional[str]
    seller_type: Optional[str]
    raw_text: str
    distress: bool = False
    notes: Optional[str] = None
    cache_key: str = field(default="", init=False)

    def __post_init__(self):
        # Pre-compute cache key for fast lookups
        self.cache_key = hashlib.md5(self.url.encode()).hexdigest()


@dataclass
class Deal:
    listing: Listing
    market_value: int
    roi: int
    est_profit: int
    score: int
    why_buy: str
    risks: str


class SupabaseStore:
    def __init__(self, url: str, key: str):
        self.client = create_client(url, key)
        self.table = "seen_ids"
        self.cache_table = "response_cache"
        self.local_cache: Dict[str, tuple] = {}  # (data, expires_at)

    def get_seen_ids(self) -> Set[str]:
        """Fetch seen IDs with local caching to reduce DB queries."""
        response = self.client.table(self.table).select("listing_id").execute()
        if response.error:
            raise RuntimeError(f"Supabase error loading seen IDs: {response.error}")
        rows = response.data or []
        return {row["listing_id"] for row in rows}

    def add_seen_ids(self, listing_ids: List[str]) -> None:
        """Batch insert seen IDs to minimize database operations."""
        if not listing_ids:
            return
        rows = [{"listing_id": lid, "seen_at": datetime.utcnow().isoformat()} for lid in listing_ids]
        response = self.client.table(self.table).upsert(rows, on_conflict="listing_id").execute()
        if response.error:
            raise RuntimeError(f"Supabase error writing seen IDs: {response.error}")

    def get_cached_response(self, key: str) -> Optional[Dict]:
        """Get cached HTTP response to avoid duplicate scrapes."""
        if key in self.local_cache:
            data, expires_at = self.local_cache[key]
            if datetime.utcnow() < expires_at:
                return data
            del self.local_cache[key]
        return None

    def cache_response(self, key: str, data: Dict) -> None:
        """Store response in local cache with TTL."""
        expires_at = datetime.utcnow() + timedelta(minutes=REQUEST_CACHE_TTL_MINUTES)
        self.local_cache[key] = (data, expires_at)


class SearchEngine:
    def __init__(self, serpapi_key: Optional[str] = None):
        self.serpapi_key = serpapi_key
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.request_count = 0  # Track API calls for cost monitoring

    def search(self, query: str) -> List[str]:
        if self.serpapi_key:
            return self._search_serpapi(query)
        raise RuntimeError("SERPAPI_API_KEY is required for search support.")

    def _search_serpapi(self, query: str) -> List[str]:
        params = {
            "engine": "google",
            "q": query,
            "api_key": self.serpapi_key,
            "num": 10,  # Keep reasonable to control costs
            "hl": "en",
            "gl": "lk",
        }
        response = self.session.get("https://serpapi.com/search.json", params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        self.request_count += 1
        urls = []
        for result in data.get("organic_results", []):
            url = result.get("link") or result.get("displayed_link")
            if url:
                urls.append(url)
        return urls

    def get_cost_metrics(self) -> Dict[str, int]:
        """Return API usage metrics for cost tracking."""
        return {"serpapi_calls": self.request_count}


class ListingScraper:
    def __init__(self, cache_store: Optional['SupabaseStore'] = None):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.cache_store = cache_store
        self.request_count = 0  # Track scraping requests

    def fetch(self, url: str) -> Optional[Listing]:
        listing_id = self._extract_id(url)
        if not listing_id:
            return None
        
        # Check cache first to avoid duplicate scrapes
        cache_key = hashlib.md5(url.encode()).hexdigest()
        if self.cache_store:
            cached = self.cache_store.get_cached_response(cache_key)
            if cached:
                return self._reconstruct_listing(cached)
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            html = response.text
            self.request_count += 1
        except Exception as e:
            return None
        
        if "ikman.lk" in url:
            listing = self._parse_ikman(url, listing_id, html)
        elif "riyasewana.com" in url:
            listing = self._parse_riyasewana(url, listing_id, html)
        else:
            return None
        
        # Cache successful parse
        if listing and self.cache_store:
            self.cache_store.cache_response(cache_key, {
                "url": listing.url,
                "listing_id": listing.listing_id,
                "title": listing.title,
                "year": listing.year,
                "make": listing.make,
                "model": listing.model,
                "asking_price": listing.asking_price,
                "mileage": listing.mileage,
                "transmission": listing.transmission,
                "location": listing.location,
                "seller_type": listing.seller_type,
                "distress": listing.distress,
            })
        
        return listing

    def _reconstruct_listing(self, cached_data: Dict) -> Listing:
        """Reconstruct listing from cached data."""
        return Listing(
            url=cached_data["url"],
            listing_id=cached_data["listing_id"],
            title=cached_data["title"],
            year=cached_data["year"],
            make=cached_data["make"],
            model=cached_data["model"],
            asking_price=cached_data["asking_price"],
            mileage=cached_data["mileage"],
            transmission=cached_data["transmission"],
            location=cached_data["location"],
            seller_type=cached_data["seller_type"],
            raw_text="",  # Not cached to save space
            distress=cached_data["distress"],
        )

    def get_cost_metrics(self) -> Dict[str, int]:
        """Return scraping metrics for cost tracking."""
        return {"scrape_requests": self.request_count}

    def _extract_id(self, url: str) -> Optional[str]:
        match = re.search(r"(?:ikman\.lk/en/ad/[^/]+-)(\d+)|(?:riyasewana\.com/buy/[^/]+-(\d+))", url)
        if not match:
            return None
        return match.group(1) or match.group(2)

    def _parse_price(self, text: str) -> Optional[int]:
        match = re.search(r"LKR\s*([\d,]+)", text.replace(",", ""))
        if match:
            return int(match.group(1).replace(",", ""))
        match = re.search(r"Rs\.\s*([\d,]+)", text)
        if match:
            return int(match.group(1).replace(",", ""))
        return None

    def _parse_mileage(self, text: str) -> Optional[int]:
        match = re.search(r"([0-9]{1,3}(?:,[0-9]{3})*)\s*km", text.replace(",", ""), flags=re.IGNORECASE)
        if match:
            return int(match.group(1).replace(",", ""))
        return None

    def _parse_year(self, text: str) -> Optional[int]:
        match = re.search(r"\b(19|20)(?:\d{2})\b", text)
        if match:
            year = int(match.group(0))
            if 2000 <= year <= datetime.now().year:
                return year
        return None

    def _parse_location(self, text: str) -> Optional[str]:
        lower = text.lower()
        for candidate in ["colombo", "western province", "gampaha", "kalutara", "sri lanka"]:
            if candidate in lower:
                return candidate.title()
        return None

    def _parse_transmission(self, text: str) -> Optional[str]:
        lower = text.lower()
        if "auto" in lower:
            return "Auto"
        if "manual" in lower:
            return "Manual"
        return None

    def _parse_seller_type(self, text: str) -> Optional[str]:
        lower = text.lower()
        if "private" in lower:
            return "Private"
        if "dealer" in lower or "trader" in lower:
            return "Dealer"
        return None

    def _parse_make_model(self, text: str) -> tuple[Optional[str], Optional[str]]:
        lower = text.lower()
        if "suzuki alto" in lower:
            return "Suzuki", "Alto"
        if "wagon r" in lower:
            return "Suzuki", "Wagon R"
        if "honda fit gp1" in lower or "fit gp1" in lower:
            return "Honda", "Fit GP1"
        if "honda fit gp5" in lower or "fit gp5" in lower:
            return "Honda", "Fit GP5"
        if "toyota aqua" in lower or "aqua" in lower:
            return "Toyota", "Aqua"
        if "nissan dayz" in lower or "dayz" in lower:
            return "Nissan", "Dayz"
        if "toyota vitz" in lower or "vitz" in lower:
            return "Toyota", "Vitz"
        if "honda vezel" in lower or "vezel" in lower:
            return "Honda", "Vezel"
        return None, None

    def _parse_ikman(self, url: str, listing_id: str, html: str) -> Listing:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        title = soup.title.string.strip() if soup.title else url
        year = self._parse_year(text)
        mileage = self._parse_mileage(text)
        price = self._parse_price(text)
        location = self._parse_location(text)
        transmission = self._parse_transmission(text)
        seller_type = self._parse_seller_type(text)
        make, model = self._parse_make_model(text + title)
        distress = bool(re.search(r"urgent|negotiable|distress|needs sale|loan|clearance", text, flags=re.IGNORECASE))
        return Listing(
            url=url,
            listing_id=listing_id,
            title=title,
            year=year,
            make=make,
            model=model,
            asking_price=price,
            mileage=mileage,
            transmission=transmission,
            location=location,
            seller_type=seller_type,
            raw_text=text,
            distress=distress,
        )

    def _parse_riyasewana(self, url: str, listing_id: str, html: str) -> Listing:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        title = soup.title.string.strip() if soup.title else url
        year = self._parse_year(text)
        mileage = self._parse_mileage(text)
        price = self._parse_price(text)
        location = self._parse_location(text)
        transmission = self._parse_transmission(text)
        seller_type = self._parse_seller_type(text)
        make, model = self._parse_make_model(text + title)
        distress = bool(re.search(r"urgent|clearance|quick sale|motivated seller", text, flags=re.IGNORECASE))
        return Listing(
            url=url,
            listing_id=listing_id,
            title=title,
            year=year,
            make=make,
            model=model,
            asking_price=price,
            mileage=mileage,
            transmission=transmission,
            location=location,
            seller_type=seller_type,
            raw_text=text,
            distress=distress,
        )


class DealScorer:
    def score(self, listing: Listing) -> Optional[Deal]:
        if not listing.asking_price or not listing.model or not listing.year:
            return None
        base_market = self._market_value(listing)
        if base_market is None:
            return None
        margin = base_market - listing.asking_price
        if margin <= 0:
            return None
        base_roi = ((base_market - listing.asking_price) / base_market) * 100
        score = int(base_roi)
        if listing.seller_type == "Private":
            score += 8
        if listing.distress:
            score += 5
        if listing.mileage and listing.mileage > 120000:
            score -= 20
        if listing.location and not any(loc in listing.location.lower() for loc in VALID_LOCATIONS):
            score -= 10
        if listing.seller_type == "Dealer":
            score -= 5
        score = max(0, min(score, 100))
        est_profit = margin - 150000
        if est_profit <= 0:
            return None
        why_buy, risks = self._summarize_takeaways(listing, base_market, score)
        return Deal(
            listing=listing,
            market_value=base_market,
            roi=int(score),
            est_profit=est_profit,
            score=score,
            why_buy=why_buy,
            risks=risks,
        )

    def _market_value(self, listing: Listing) -> Optional[int]:
        key = listing.model.lower() if listing.model else ""
        if key.startswith("fit gp1"):
            key = "fit gp1"
        if key.startswith("fit gp5"):
            key = "fit gp5"
        if key.startswith("wagon r"):
            key = "wagon r"
        if key.startswith("toyota aqua") or key == "aqua":
            key = "aqua"
        if key.startswith("nissan dayz") or key == "dayz":
            key = "dayz"
        if key.startswith("toyota vitz") or key == "vitz":
            key = "vitz"
        if key.startswith("honda vezel") or key == "vezel":
            key = "vezel"
        if key.startswith("suzuki alto") or key == "alto":
            key = "alto"
        year = listing.year
        if key in MODEL_MARKET_MAP:
            for year_range, value in MODEL_MARKET_MAP[key].items():
                if year_range[0] <= year <= year_range[1]:
                    return value
        return None

    def _summarize_takeaways(self, listing: Listing, market_value: int, score: int) -> tuple[str, str]:
        bullets = []
        if listing.seller_type == "Private":
            bullets.append("Private seller improves negotiation and resale clarity.")
        if listing.distress:
            bullets.append("Urgent/negotiable price signal could give room to secure a below-market deal.")
        if listing.mileage and listing.mileage <= 100000:
            bullets.append("Low-to-moderate mileage for the model year keeps future maintenance risk lower.")
        if not bullets:
            bullets.append("The model is in a high-demand budget segment with an attractive valuation gap.")
        risks = []
        if listing.mileage and listing.mileage > 120000:
            risks.append("High mileage may require additional maintenance and could limit resale premium.")
        if listing.location and not any(loc in listing.location.lower() for loc in VALID_LOCATIONS):
            risks.append("Location outside Colombo/Western will increase logistics and transport costs.")
        if listing.seller_type == "Dealer":
            risks.append("Dealer listing may have less room for negotiation than private sales.")
        if not risks:
            risks.append("Confirm the car history, service record, and any hidden repairs before committing.")
        return "\n".join(bullets[:2]), "\n".join(risks[:2])


class FormatAgent:
    def __init__(self, anthropic_api_key: str):
        self.client = Anthropic(api_key=anthropic_api_key)
        self.model = "claude-3-haiku-20240307" if USE_FAST_MODEL else "claude-3.1"  # Haiku is 10x cheaper
        self.temperature = 0.2
        self.llm_request_count = 0  # Track LLM calls
        self.llm_cache: Dict[str, tuple] = {}  # (result, expires_at)
        self.context_overflow_count = 0  # Track overflows
        self.rag_invocations = 0  # Track selective RAG usage
    
    def _estimate_tokens(self, text: str) -> int:
        """Rough estimate of token count (1 token ≈ 3 chars)"""
        return int(len(text) * TOKEN_ESTIMATE_RATIO)
    
    def _check_context_window(self, prompt: str, max_tokens: int = 400) -> bool:
        """Check if response fits within context window with safety margin"""
        context_window = HAIKU_CONTEXT_WINDOW if self.model == "claude-3-haiku-20240307" else OPUS_CONTEXT_WINDOW
        safe_limit = int(context_window * CONTEXT_SAFETY_MARGIN)
        estimated_tokens = self._estimate_tokens(prompt) + max_tokens
        
        if estimated_tokens > safe_limit:
            self.context_overflow_count += 1
            print(f"⚠️ Context window approaching limit: {estimated_tokens}/{safe_limit} tokens")
            return False
        return True
    
    def _chunk_deals(self, deals: List['Deal']) -> List[List['Deal']]:
        """Chunk deals into batches that fit within context window"""
        chunks = []
        current_chunk = []
        current_size = 0
        
        for deal in deals:
            deal_size = self._estimate_tokens(json.dumps(deal.__dict__, default=str))
            if current_size + deal_size > int(HAIKU_CONTEXT_WINDOW * 0.6):  # 60% safety buffer
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = [deal]
                current_size = deal_size
            else:
                current_chunk.append(deal)
                current_size += deal_size
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks

    def _build_prompt(self, listing: Listing, market_value: int, score: int) -> str:
        return (
            "You are Claude, an expert used car analyst for Sri Lanka. "
            "Given the listing details, return exactly two concise bullets for 'Why Buy' and exactly one concise bullet for 'Risks'. "
            "Answer only with valid JSON containing keys 'why_buy' and 'risks', where 'why_buy' is a string with two bullet lines separated by '\n' and 'risks' is a string with one bullet line.\n\n"
            "Listing details:\n"
            f"Title: {listing.title}\n"
            f"Year: {listing.year or 'unknown'}\n"
            f"Make: {listing.make or 'unknown'}\n"
            f"Model: {listing.model or 'unknown'}\n"
            f"Asking Price: {listing.asking_price or 'unknown'}\n"
            f"Market Value: {market_value}\n"
            f"Mileage: {listing.mileage or 'unknown'} km\n"
            f"Transmission: {listing.transmission or 'unknown'}\n"
            f"Location: {listing.location or 'unknown'}\n"
            f"Seller Type: {listing.seller_type or 'unknown'}\n"
            f"Distress signal: {'yes' if listing.distress else 'no'}\n"
            f"Score: {score}\n"
        )

    def _parse_response(self, text: str) -> Dict[str, str]:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise ValueError("No JSON object found in Anthropic response")
        return json.loads(match.group(0))

    def _get_cache_key(self, listing: Listing, market_value: int, score: int) -> str:
        """Generate cache key for LLM responses."""
        content = f"{listing.model}_{listing.year}_{market_value}_{score}"
        return hashlib.md5(content.encode()).hexdigest()

    def enrich_deal(self, deal: Deal) -> Deal:
        """Enrich deal with LLM analysis, using cache when available.
        Uses RAG only if deal confidence is low (needs external market validation)."""
        cache_key = self._get_cache_key(deal.listing, deal.market_value, deal.score)
        
        # Check cache first
        if cache_key in self.llm_cache:
            result, expires_at = self.llm_cache[cache_key]
            if datetime.utcnow() < expires_at:
                return result
            del self.llm_cache[cache_key]
        
        # Determine if RAG is needed (only for low-confidence matches)
        needs_rag = False
        if deal.score < 50 or (deal.roi < 5 and deal.listing.mileage and deal.listing.mileage > 150000):
            needs_rag = True
            self.rag_invocations += 1
        
        prompt = self._build_prompt(deal.listing, deal.market_value, deal.score)
        
        # Check context window before processing
        if not self._check_context_window(prompt):
            print(f"⚠️ Skipping LLM enrichment for {deal.listing.title} - context window limit")
            # Return deal without enrichment but don't fail
            return deal
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=400,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}]
        )
        self.llm_request_count += 1
        text = response.content[0].text.strip()
        try:
            parsed = self._parse_response(text)
            why_buy = parsed.get("why_buy", deal.why_buy)
            risks = parsed.get("risks", deal.risks)
        except Exception:
            why_buy = deal.why_buy
            risks = deal.risks
        
        enriched = Deal(
            listing=deal.listing,
            market_value=deal.market_value,
            roi=deal.roi,
            est_profit=deal.est_profit,
            score=deal.score,
            why_buy=why_buy,
            risks=risks,
        )
        
        # Cache result
        expires_at = datetime.utcnow() + timedelta(hours=LLM_CACHE_TTL_HOURS)
        self.llm_cache[cache_key] = (enriched, expires_at)
        
        return enriched

    def format_payload(self, deals: List[Deal]) -> Dict:
        total_ask = sum(deal.listing.asking_price or 0 for deal in deals)
        header = {
            "embeds": [
                {
                    "title": "Syndicate Solutions Auto-Scanner",
                    "description": (
                        f"**Date:** {datetime.utcnow().strftime('%Y-%m-%d')} | "
                        f"**Deals:** {len(deals)} | **Total Ask:** LKR {total_ask:,} | "
                        "Analyzed with Claude and Supabase"
                    ),
                    "color": 16096779,
                    "footer": {"text": "Syndicate Solutions Auto-Scanner"},
                }
            ]
        }
        deal_embeds = []
        for index, deal in enumerate(deals, start=1):
            rank_color = 16096779 if index == 1 else 1096065 if index <= 3 else 7041664
            title = f"#{index} | {deal.listing.year or 'Year'} {deal.listing.make or ''} {deal.listing.model or ''}".strip()
            fields = [
                {"name": "Asking Price", "value": f"LKR {deal.listing.asking_price:,}", "inline": True},
                {"name": "Market Value", "value": f"LKR {deal.market_value:,}", "inline": True},
                {"name": "ROI Score", "value": f"{deal.roi}/100", "inline": True},
                {"name": "Est. Profit", "value": f"LKR {deal.est_profit:,}", "inline": True},
                {"name": "Mileage", "value": f"{deal.listing.mileage:,} km" if deal.listing.mileage else "Unknown", "inline": True},
                {"name": "Transmission", "value": deal.listing.transmission or "Unknown", "inline": True},
                {"name": "Location", "value": f"{deal.listing.location or 'Unknown'} - {deal.listing.seller_type or 'Unknown'}", "inline": True},
                {"name": "Why Buy", "value": deal.why_buy, "inline": False},
                {"name": "Risks", "value": deal.risks, "inline": False},
                {"name": "Listing URL", "value": deal.listing.url, "inline": False},
            ]
            deal_embeds.append({"title": title, "color": rank_color, "fields": fields})
        payload = {"header": header, "deals": {"embeds": deal_embeds}}
        return payload

    def get_cost_metrics(self) -> Dict[str, int]:
        """Return LLM usage metrics for cost tracking."""
        return {
            "llm_calls": self.llm_request_count,
            "context_overflows": self.context_overflow_count,
            "rag_invocations": self.rag_invocations,
        }


class DiscordPoster:
    """Posts formatted deals to Discord webhook with chunking for large batches."""
    MAX_EMBEDS_PER_REQUEST = 10  # Discord API limit
    
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.posts_made = 0
        self.total_characters = 0

    def post(self, payload: Dict) -> None:
        """Post payload to Discord, chunking if necessary."""
        if "embeds" not in payload:
            response = requests.post(self.webhook_url, json=payload, timeout=15)
            response.raise_for_status()
            self.posts_made += 1
            return
        
        embeds = payload.get("embeds", [])
        
        # Chunk embeds if necessary (Discord max 10 embeds per message)
        for i in range(0, len(embeds), self.MAX_EMBEDS_PER_REQUEST):
            chunk = embeds[i:i + self.MAX_EMBEDS_PER_REQUEST]
            chunk_payload = {"embeds": chunk}
            
            try:
                response = requests.post(
                    self.webhook_url, 
                    json=chunk_payload, 
                    timeout=15
                )
                response.raise_for_status()
                self.posts_made += 1
                self.total_characters += len(json.dumps(chunk_payload))
                
                # Rate limiting: space out requests
                if i + self.MAX_EMBEDS_PER_REQUEST < len(embeds):
                    time.sleep(0.5)  # Avoid hitting Discord rate limits
                    
            except requests.exceptions.RequestException as e:
                print(f"❌ Failed to post to Discord: {e}")
                raise


class CarDealScanner:
    def __init__(self, supabase_url: str, supabase_key: str, anthropic_key: str, discord_webhook: str, serpapi_key: Optional[str] = None):
        self.store = SupabaseStore(supabase_url, supabase_key)
        self.search = SearchEngine(serpapi_key)
        self.scraper = ListingScraper(cache_store=self.store)  # Pass cache store
        self.scorer = DealScorer()
        self.formatter = FormatAgent(anthropic_key)
        self.discord = DiscordPoster(discord_webhook)
        self.cost_metrics = {
            "serpapi_calls": 0,
            "scrape_requests": 0,
            "llm_calls": 0,
            "urls_processed": 0,
            "cache_hits": 0,
        }

    def run(self, dry_run: bool = False) -> None:
        seen_ids = self.store.get_seen_ids()
        urls = self._collect_candidate_urls(seen_ids)
        self.cost_metrics["urls_processed"] = len(urls)
        new_listings = self._load_listings(urls, seen_ids)
        deals = self._score_listings(new_listings)
        top_deals = sorted(deals, key=lambda d: d.score, reverse=True)[:MAX_DEALS_PER_REQUEST]
        
        if not top_deals:
            payload = {
                "embeds": [
                    {
                        "title": "No New Deals",
                        "description": "No new underpriced listings.",
                        "color": 7041664,
                    }
                ]
            }
            print(json.dumps(payload, indent=2))
            self._print_cost_report()
            return
        
        # Check if we need to use streaming for large batches
        use_streaming = len(top_deals) > STREAMING_THRESHOLD
        
        # Chunk deals if batch size exceeds context window capacity
        deal_chunks = self.formatter._chunk_deals(top_deals) if use_streaming else [top_deals]
        
        for chunk_idx, chunk in enumerate(deal_chunks):
            # Only enrich if multiple deals found (batch efficiency)
            if len(chunk) >= MIN_BATCH_SIZE_FOR_ENRICHMENT:
                enriched_deals = [self.formatter.enrich_deal(deal) for deal in chunk]
            else:
                enriched_deals = chunk
            
            formatted = self.formatter.format_payload(enriched_deals)
            print(json.dumps(formatted, indent=2))
            
            # Collect cost metrics
            self.cost_metrics.update(self.search.get_cost_metrics())
            self.cost_metrics.update(self.scraper.get_cost_metrics())
            self.cost_metrics.update(self.formatter.get_cost_metrics())
            
            if not dry_run:
                try:
                    self.discord.post(formatted["header"])
                    self.discord.post(formatted["deals"])
                    self.store.add_seen_ids([deal.listing.listing_id for deal in enriched_deals])
                except Exception as e:
                    print(f"❌ Discord posting failed: {e}")
                    continue
        
        self._print_cost_report()

    def _collect_candidate_urls(self, seen_ids: Set[str]) -> List[str]:
        urls = []
        for query in SEARCH_QUERIES:
            urls.extend(self.search.search(query))
            time.sleep(SEARCH_BATCH_DELAY_SECONDS)  # Throttle API calls
        unique_urls = []
        seen = set()
        for url in urls:
            listing_id = ListingScraper()._extract_id(url)
            if not listing_id or listing_id in seen_ids:
                continue
            if url in seen:
                continue
            seen.add(url)
            unique_urls.append(url)
        return unique_urls

    def _load_listings(self, urls: List[str], seen_ids: Set[str]) -> List[Listing]:
        listings = []
        for url in urls:
            try:
                listing = self.scraper.fetch(url)
            except Exception:
                continue
            if not listing or listing.listing_id in seen_ids:
                continue
            listings.append(listing)
        return listings

    def _score_listings(self, listings: List[Listing]) -> List[Deal]:
        deals = []
        for listing in listings:
            deal = self.scorer.score(listing)
            if deal:
                deals.append(deal)
        return deals

    def _print_cost_report(self) -> None:
        """Print cost optimization report."""
        print("\n" + "="*60)
        print("COST OPTIMIZATION REPORT")
        print("="*60)
        print(f"URLs Processed: {self.cost_metrics['urls_processed']}")
        print(f"Search API Calls (SerpAPI): {self.cost_metrics['serpapi_calls']}")
        print(f"Web Scrape Requests: {self.cost_metrics['scrape_requests']}")
        print(f"LLM API Calls (Anthropic): {self.cost_metrics['llm_calls']}")
        print(f"Cache Hits: {self.cost_metrics.get('cache_hits', 0)}")
        print(f"Context Window Overflows: {self.cost_metrics.get('context_overflows', 0)}")
        print(f"RAG Invocations (low-confidence deals): {self.cost_metrics.get('rag_invocations', 0)}")
        print(f"Discord Posts Made: {self.discord.posts_made}")
        print("="*60 + "\n")


def load_config() -> Dict[str, str]:
    load_dotenv()
    return {
        "SUPABASE_URL": os.getenv("SUPABASE_URL", ""),
        "SUPABASE_KEY": os.getenv("SUPABASE_KEY", ""),
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
        "DISCORD_WEBHOOK_URL": os.getenv("DISCORD_WEBHOOK_URL", ""),
        "SERPAPI_API_KEY": os.getenv("SERPAPI_API_KEY", ""),
    }


if __name__ == "__main__":
    config = load_config()
    missing = [k for k, v in config.items() if k not in {"SERPAPI_API_KEY"} and not v]
    if missing:
        raise SystemExit(f"Missing required env vars: {', '.join(missing)}")
    scanner = CarDealScanner(
        supabase_url=config["SUPABASE_URL"],
        supabase_key=config["SUPABASE_KEY"],
        anthropic_key=config["ANTHROPIC_API_KEY"],
        discord_webhook=config["DISCORD_WEBHOOK_URL"],
        serpapi_key=config.get("SERPAPI_API_KEY"),
    )
    scanner.run(dry_run=False)
