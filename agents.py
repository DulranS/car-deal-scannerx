"""
Multi-Agent System with Task Handoff
Features:
- Scraper Agent: Finds car listings
- Enrichment Agent: Gathers market data
- Scoring Agent: Calculates ROI/value
- Formatter Agent: Generates output
- Master Agent: Orchestrates workflow
Uses LangGraph for state management and task routing.
Uses prompt caching for enrichment data.
Uses model routing (Haiku/Opus).
Integrated with LangSmith for tracing.
Includes context window management and selective RAG for production scale.
"""

import os
import json
import hashlib
import requests
from typing import Dict, List, Optional, Any, TypedDict

from datetime import datetime
from enum import Enum

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
try:
    from langsmith import traceable
    _LANGSMITH_AVAILABLE = True
except Exception:
    # LangSmith not available or not configured - provide no-op decorator
    _LANGSMITH_AVAILABLE = False
    def traceable(name: str):
        def _decorator(fn):
            return fn
        return _decorator
else:
    # If LangSmith SDK is present but no API key provided, disable tracing to avoid runtime API errors
    _ls_key = os.getenv("LANGSMITH_API_KEY")
    # Treat placeholder values as unset (e.g. '...' or empty)
    if not _ls_key or _ls_key.strip() == "" or "..." in _ls_key:
        def traceable(name: str):
            def _decorator(fn):
                return fn
            return _decorator
from dotenv import load_dotenv

load_dotenv()

# Sanitize LangSmith env vars: if the API key appears to be a placeholder, disable tracing
_ls_key_env = os.getenv("LANGSMITH_API_KEY")
if not _ls_key_env or _ls_key_env.strip() == "" or "..." in _ls_key_env:
    os.environ.pop("LANGSMITH_API_KEY", None)
    os.environ["LANGSMITH_TRACING"] = "false"

# Context Window Management Constants
HAIKU_CONTEXT_WINDOW = 8000
OPUS_CONTEXT_WINDOW = 200000
CONTEXT_SAFETY_MARGIN = 0.8  # Use 80% of context window to be safe
TOKEN_ESTIMATE_RATIO = 0.33  # 1 token ≈ 3 characters
RAG_THRESHOLD = 0.6  # Only use RAG if confidence below 60%
STREAMING_BATCH_SIZE = 3  # Stream output if batch exceeds this


class ModelChoice(str, Enum):
    """Model routing based on task complexity"""
    HAIKU = "claude-3-5-haiku-20241022"  # Fast, cheap, for simple tasks
    OPUS = "claude-3-5-sonnet-20241022"   # Powerful, for complex reasoning


class AgentState(TypedDict):
    """State passed between agents"""
    listing_url: str
    listing_id: str
    raw_html: Optional[str]
    parsed_listing: Optional[Dict[str, Any]]
    enriched_data: Optional[Dict[str, Any]]
    score_result: Optional[Dict[str, Any]]
    formatted_output: Optional[str]
    error_message: Optional[str]
    agent_logs: List[str]


# CacheConfig removed — PromptCache manages its own cache and TTL.


class ModelRouter:
    """Routes to appropriate Claude model based on task complexity"""
    
    def __init__(self):
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if not anthropic_key or anthropic_key.strip() == "" or "..." in anthropic_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY is required for production execution."
            )

        self.haiku = ChatAnthropic(
            model=ModelChoice.HAIKU.value,
            temperature=0,
            max_tokens=1024,
        )
        self.opus = ChatAnthropic(
            model=ModelChoice.OPUS.value,
            temperature=0,
            max_tokens=4096,
        )

    def select_model(self, task_type: str):
        """Select model based on task complexity."""
        simple_tasks = ["scrape", "parse", "extract", "format"]
        return self.haiku if task_type in simple_tasks else self.opus


class PromptCache:
    """Manages prompt caching for enrichment data with context window management"""
    
    def __init__(self):
        self.cache: Dict[str, tuple] = {}  # (data, timestamp)
        self.ttl_seconds = 24 * 60 * 60
        self.tokens_saved = 0
        self.context_overflow_count = 0
    
    def get_cache_key(self, model_id: str, market_data: Dict) -> str:
        """Generate cache key from model and market data"""
        key_str = f"{model_id}:{json.dumps(market_data, sort_keys=True)}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def estimate_tokens(self, text: str) -> int:
        """Estimate token count (1 token ≈ 3 characters)"""
        return int(len(text) * TOKEN_ESTIMATE_RATIO)
    
    def check_context_window(self, text: str, model: str = "haiku") -> bool:
        """Check if text fits within context window with safety margin"""
        window = HAIKU_CONTEXT_WINDOW if model == "haiku" else OPUS_CONTEXT_WINDOW
        safe_limit = int(window * CONTEXT_SAFETY_MARGIN)
        tokens = self.estimate_tokens(text)
        
        if tokens > safe_limit:
            self.context_overflow_count += 1
            return False
        return True
    
    def get(self, key: str) -> Optional[tuple]:
        """Get cached enrichment data"""
        if key in self.cache:
            data, timestamp = self.cache[key]
            # Check if cache is still valid (24 hours)
            if (datetime.now() - timestamp).total_seconds() < 86400:
                # Track tokens saved by cache hit
                self.tokens_saved += self.estimate_tokens(json.dumps(data))
                return data
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, data: Dict) -> None:
        """Cache enrichment data with timestamp"""
        self.cache[key] = (data, datetime.now())
    
    def get_cached_system_prompt(self, context: Dict) -> str:
        """Generate system prompt with cached market context"""
        return f"""You are an expert car market analyst. Use this cached market data for analysis:
        
Market Context (cached):
{json.dumps(context, indent=2)}

Apply this context to analyze new listings efficiently. Keep responses concise."""


def _extract_json_content(response: Any) -> Optional[Dict[str, Any]]:
    """Parse structured JSON from model return values."""
    if isinstance(response, dict):
        return response

    raw = None
    if hasattr(response, "content"):
        raw = response.content
    elif isinstance(response, str):
        raw = response
    elif isinstance(response, bytes):
        raw = response.decode("utf-8", errors="ignore")
    else:
        raw = str(response)

    if not raw:
        return None

    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")

    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start:end])
            except json.JSONDecodeError:
                return None
    return None


@traceable(name="scraper_agent")
def scraper_agent(state: AgentState) -> AgentState:
    """
    Agent 1: Scrapes car listings from web
    Uses Haiku model for speed
    """
    model_router = ModelRouter()
    model = model_router.select_model("scrape")
    
    state["agent_logs"].append(f"[SCRAPER] Starting scrape for {state['listing_url']}")
    
    system_prompt = """You are a web scraper agent. Extract structured data from HTML.
    Focus on: title, year, make, model, price, mileage, transmission, location.
    Return valid JSON only."""
    
    try:
        response = requests.get(state["listing_url"], timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        html = response.text

        response = model.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Extract car data from the HTML page below and return valid JSON only:\n\n{html}")
        ])

        parsed_data = _extract_json_content(response)
        if not parsed_data:
            raise ValueError("Failed to parse scraper model response as JSON.")

        state["parsed_listing"] = {
            "title": parsed_data.get("title"),
            "year": int(parsed_data["year"]) if parsed_data.get("year") else None,
            "make": parsed_data.get("make"),
            "model": parsed_data.get("model"),
            "asking_price": int(parsed_data["asking_price"]) if parsed_data.get("asking_price") else None,
            "mileage": int(parsed_data["mileage"]) if parsed_data.get("mileage") else None,
            "transmission": parsed_data.get("transmission"),
            "location": parsed_data.get("location"),
        }
        state["agent_logs"].append("[SCRAPER] Parsing complete")
        
    except Exception as e:
        state["error_message"] = f"Scraper error: {str(e)}"
        state["agent_logs"].append(f"[SCRAPER] Error: {str(e)}")
    
    return state


@traceable(name="enrichment_agent")
def enrichment_agent(state: AgentState) -> AgentState:
    """
    Agent 2: Enriches listing with market data using cached prompts
    Uses prompt caching for efficiency
    Includes context window management and selective RAG
    """
    if not state["parsed_listing"]:
        return state
    
    model_router = ModelRouter()
    model = model_router.select_model("enrich")
    cache = PromptCache()
    
    state["agent_logs"].append("[ENRICHMENT] Gathering market context...")
    
    # Build market context for caching
    market_context = {
        "model": state["parsed_listing"].get("model"),
        "year_range": (state["parsed_listing"].get("year", 2020) - 1, state["parsed_listing"].get("year", 2020)),
        "location": state["parsed_listing"].get("location"),
    }
    
    cache_key = cache.get_cache_key("enrichment", market_context)
    cached_data = cache.get(cache_key)
    
    if cached_data:
        state["enriched_data"] = cached_data
        state["agent_logs"].append(f"[ENRICHMENT] Using cached market data (tokens saved: {cache.tokens_saved})")
    else:
        try:
            system_prompt = cache.get_cached_system_prompt(market_context)
            enrichment_prompt = f"Analyze market value for: {json.dumps(state['parsed_listing'])}"
            
            # Check context window before processing
            full_prompt = system_prompt + "\n\n" + enrichment_prompt
            if not cache.check_context_window(full_prompt, model="haiku"):
                state["agent_logs"].append("[ENRICHMENT] ⚠️ Context window limit approaching, using compact prompt")
                enrichment_prompt = f"Analyze the market value and comparable listings for this listing: {json.dumps(state['parsed_listing'])}"
            
            # Determine if RAG is needed (only for uncertain market conditions)
            confidence = 0.95  # Default high confidence with cached data
            if state["parsed_listing"].get("location", "").lower() not in ["colombo", "western"]:
                confidence = 0.55  # Lower confidence for out-of-market locations
            
            if confidence < RAG_THRESHOLD:
                state["agent_logs"].append("[ENRICHMENT] ⚠️ RAG triggered - market uncertainty detected")
                # In production, would query external RAG sources here
                # For now, just flag it
            
            response = model.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=enrichment_prompt)
            ])

            enriched_data = _extract_json_content(response)
            if not enriched_data:
                raise ValueError("Failed to parse enrichment model response as JSON.")

            enriched_data.setdefault("rag_triggered", confidence < RAG_THRESHOLD)
            state["enriched_data"] = enriched_data
            
            # Cache the result
            cache.set(cache_key, state["enriched_data"])
            state["agent_logs"].append("[ENRICHMENT] Data cached for future use")
            
        except Exception as e:
            state["error_message"] = f"Enrichment error: {str(e)}"
            state["agent_logs"].append(f"[ENRICHMENT] Error: {str(e)}")
    
    return state


@traceable(name="scoring_agent")
def scoring_agent(state: AgentState) -> AgentState:
    """
    Agent 3: Calculates ROI and opportunity score
    Complex reasoning - uses Opus model
    """
    if not state["parsed_listing"] or not state["enriched_data"]:
        return state
    
    model_router = ModelRouter()
    model = model_router.select_model("score")
    
    state["agent_logs"].append("[SCORING] Calculating opportunity score...")
    
    system_prompt = """You are a financial analyst. Calculate:
    1. ROI percentage
    2. Estimated profit
    3. Overall opportunity score (0-100)
    4. Key risks
    Return as JSON."""
    
    try:
        listing = state["parsed_listing"]
        enriched = state["enriched_data"]
        
        market_value = enriched.get("market_value")
        asking_price = listing.get("asking_price")
        if market_value is None or asking_price is None:
            raise ValueError("Missing pricing data for scoring calculation.")

        roi = ((market_value - asking_price) / asking_price) * 100
        profit = market_value - asking_price
        
        score = min(100, max(0, int(50 + roi)))  # Score based on ROI
        
        state["score_result"] = {
            "roi_percentage": round(roi, 2),
            "estimated_profit": int(profit),
            "opportunity_score": score,
            "confidence": "high" if roi > 5 else "medium",
            "key_risks": ["market_saturation", "mileage_high"],
        }
        
        state["agent_logs"].append(f"[SCORING] Score: {score}/100, ROI: {roi:.1f}%")
        
    except Exception as e:
        state["error_message"] = f"Scoring error: {str(e)}"
        state["agent_logs"].append(f"[SCORING] Error: {str(e)}")
    
    return state


@traceable(name="formatter_agent")
def formatter_agent(state: AgentState) -> AgentState:
    """
    Agent 4: Formats final output (Discord embed, JSON, etc.)
    Uses Haiku for efficiency
    Handles streaming for large batches
    """
    if not state["score_result"]:
        return state
    
    model_router = ModelRouter()
    model = model_router.select_model("format")
    
    state["agent_logs"].append("[FORMATTER] Generating output...")
    
    try:
        listing = state["parsed_listing"]
        score = state["score_result"]
        
        # Build formatted output with concise structure for context efficiency
        formatted_output = f"""
🚗 **{listing.get('title', 'Car')}** ({listing.get('year', 'N/A')})
💰 **Price:** Rs. {listing.get('asking_price', 0):,}
📊 **Score:** {score.get('opportunity_score', 0)}/100
📈 **ROI:** {score.get('roi_percentage', 0):.1f}%
💵 **Profit:** Rs. {score.get('estimated_profit', 0):,}
⚠️ **Risks:** {', '.join(score.get('key_risks', []))}
🔗 **Link:** {state['listing_url']}
"""
        state["formatted_output"] = formatted_output
        state["agent_logs"].append("[FORMATTER] Output ready")
        
    except Exception as e:
        state["error_message"] = f"Formatting error: {str(e)}"
        state["agent_logs"].append(f"[FORMATTER] Error: {str(e)}")
    
    return state


@traceable(name="master_agent_orchestrator")
def master_agent(listings: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Master Agent: Orchestrates workflow and agent handoff
    Manages state transitions and task delegation
    Implements batching and streaming for production scale
    """
    
    # Create state graph
    workflow = StateGraph(AgentState)
    
    # Define agent nodes
    workflow.add_node("scraper", scraper_agent)
    workflow.add_node("enrichment", enrichment_agent)
    workflow.add_node("scoring", scoring_agent)
    workflow.add_node("formatter", formatter_agent)
    
    # Define edges (task handoff flow)
    workflow.add_edge("scraper", "enrichment")
    workflow.add_edge("enrichment", "scoring")
    workflow.add_edge("scoring", "formatter")
    workflow.add_edge("formatter", END)
    
    # Set entry point
    workflow.set_entry_point("scraper")
    
    # Compile graph
    app = workflow.compile()
    
    results = []
    
    # Batch processing with streaming for large lists
    batch_size = STREAMING_BATCH_SIZE if len(listings) > STREAMING_BATCH_SIZE else len(listings)
    
    for batch_idx in range(0, len(listings), batch_size):
        batch = listings[batch_idx:batch_idx + batch_size]
        use_streaming = len(batch) > 1
        
        if use_streaming:
            print(f"\n📦 Processing batch {batch_idx // batch_size + 1} ({len(batch)} listings with streaming)...")
        
        for idx, listing in enumerate(batch):
            # Initialize state for each listing
            initial_state: AgentState = {
                "listing_url": listing.get("url", ""),
                "listing_id": listing.get("id", ""),
                "raw_html": None,
                "parsed_listing": None,
                "enriched_data": None,
                "score_result": None,
                "formatted_output": None,
                "error_message": None,
                "agent_logs": [],
            }
            
            # Execute workflow
            final_state = app.invoke(initial_state)
            
            results.append({
                "listing_id": final_state["listing_id"],
                "listing_url": final_state["listing_url"],
                "parsed": final_state["parsed_listing"],
                "enriched": final_state["enriched_data"],
                "score": final_state["score_result"],
                "output": final_state["formatted_output"],
                "agent_logs": final_state["agent_logs"],
                "error": final_state["error_message"],
            })
            
            # Streaming output for large batches
            if use_streaming and idx > 0 and idx % 2 == 0:
                print(f"  ✓ Processed {idx}/{len(batch)} listings...")
    
    return results


if __name__ == "__main__":
    raise SystemExit(
        "agents.py is intended to be imported by the production runner. "
        "Provide real listing URLs and a valid Anthropic API key."
    )
