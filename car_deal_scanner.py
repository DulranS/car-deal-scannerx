import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Set

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from anthropic import Anthropic, HUMAN_PROMPT, AI_PROMPT
from supabase import create_client


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

    def get_seen_ids(self) -> Set[str]:
        response = self.client.table(self.table).select("listing_id").execute()
        if response.error:
            raise RuntimeError(f"Supabase error loading seen IDs: {response.error}")
        rows = response.data or []
        return {row["listing_id"] for row in rows}

    def add_seen_ids(self, listing_ids: List[str]) -> None:
        if not listing_ids:
            return
        rows = [{"listing_id": lid, "seen_at": datetime.utcnow().isoformat()} for lid in listing_ids]
        response = self.client.table(self.table).upsert(rows, on_conflict="listing_id").execute()
        if response.error:
            raise RuntimeError(f"Supabase error writing seen IDs: {response.error}")


class SearchEngine:
    def __init__(self, serpapi_key: Optional[str] = None):
        self.serpapi_key = serpapi_key
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def search(self, query: str) -> List[str]:
        if self.serpapi_key:
            return self._search_serpapi(query)
        raise RuntimeError("SERPAPI_API_KEY is required for search support.")

    def _search_serpapi(self, query: str) -> List[str]:
        params = {
            "engine": "google",
            "q": query,
            "api_key": self.serpapi_key,
            "num": 10,
            "hl": "en",
            "gl": "lk",
        }
        response = self.session.get("https://serpapi.com/search.json", params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        urls = []
        for result in data.get("organic_results", []):
            url = result.get("link") or result.get("displayed_link")
            if url:
                urls.append(url)
        return urls


class ListingScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch(self, url: str) -> Optional[Listing]:
        listing_id = self._extract_id(url)
        if not listing_id:
            return None
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        html = response.text
        if "ikman.lk" in url:
            return self._parse_ikman(url, listing_id, html)
        if "riyasewana.com" in url:
            return self._parse_riyasewana(url, listing_id, html)
        return None

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
        self.model = "claude-3.1"
        self.temperature = 0.2

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

    def enrich_deal(self, deal: Deal) -> Deal:
        prompt = self._build_prompt(deal.listing, deal.market_value, deal.score)
        response = self.client.completions.create(
            model=self.model,
            prompt=HUMAN_PROMPT + prompt + AI_PROMPT,
            max_tokens_to_sample=400,
            temperature=self.temperature,
        )
        text = response.completion.strip()
        try:
            parsed = self._parse_response(text)
            why_buy = parsed.get("why_buy", deal.why_buy)
            risks = parsed.get("risks", deal.risks)
        except Exception:
            why_buy = deal.why_buy
            risks = deal.risks
        return Deal(
            listing=deal.listing,
            market_value=deal.market_value,
            roi=deal.roi,
            est_profit=deal.est_profit,
            score=deal.score,
            why_buy=why_buy,
            risks=risks,
        )

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


class DiscordPoster:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def post(self, payload: Dict) -> None:
        response = requests.post(self.webhook_url, json=payload, timeout=15)
        response.raise_for_status()


class CarDealScanner:
    def __init__(self, supabase_url: str, supabase_key: str, anthropic_key: str, discord_webhook: str, serpapi_key: Optional[str] = None):
        self.store = SupabaseStore(supabase_url, supabase_key)
        self.search = SearchEngine(serpapi_key)
        self.scraper = ListingScraper()
        self.scorer = DealScorer()
        self.formatter = FormatAgent(anthropic_key)
        self.discord = DiscordPoster(discord_webhook)

    def run(self, dry_run: bool = False) -> None:
        seen_ids = self.store.get_seen_ids()
        urls = self._collect_candidate_urls(seen_ids)
        new_listings = self._load_listings(urls, seen_ids)
        deals = self._score_listings(new_listings)
        top_deals = sorted(deals, key=lambda d: d.score, reverse=True)[:4]
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
            return
        enriched_deals = [self.formatter.enrich_deal(deal) for deal in top_deals]
        formatted = self.formatter.format_payload(enriched_deals)
        print(json.dumps(formatted, indent=2))
        if not dry_run:
            self.discord.post(formatted["header"])
            self.discord.post(formatted["deals"])
            self.store.add_seen_ids([deal.listing.listing_id for deal in enriched_deals])

    def _collect_candidate_urls(self, seen_ids: Set[str]) -> List[str]:
        urls = []
        for query in SEARCH_QUERIES:
            urls.extend(self.search.search(query))
            time.sleep(1)
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
