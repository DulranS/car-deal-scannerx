"""
LangSmith Integration & Observability
Tracing for all agent interactions, API calls, and LLM usage.
Includes metrics, latency tracking, and error monitoring.
"""

import os
import time
from typing import Dict, Any, Optional, Callable
from functools import wraps
from datetime import datetime
import json

from langsmith import Client, wrappers
from langsmith.run_trees import RunTree
from langsmith.schemas import RunBase
from dotenv import load_dotenv

load_dotenv()


class LangSmithTracer:
    """
    Central tracing system for observability
    Integrates with LangSmith for:
    - Agent execution tracing
    - LLM call monitoring
    - Cost tracking
    - Latency metrics
    """
    
    def __init__(self):
        self.client = Client()
        self.langsmith_key = os.getenv("LANGSMITH_API_KEY")
        self.langsmith_project = os.getenv("LANGSMITH_PROJECT", "car-deal-scanner")
        self.traces: Dict[str, Any] = {}
        
        if self.langsmith_key:
            os.environ["LANGSMITH_TRACING"] = "true"
            os.environ["LANGSMITH_PROJECT"] = self.langsmith_project
    
    def trace_agent_execution(self, agent_name: str):
        """Decorator for tracing agent execution"""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                start_time = time.time()
                run_tree = RunTree(
                    name=agent_name,
                    run_type="chain",
                    inputs={"args": str(args[:2]) if args else "", "kwargs": str(kwargs)},
                )
                
                try:
                    result = func(*args, **kwargs)
                    
                    duration = time.time() - start_time
                    run_tree.end(
                        outputs={"success": True, "duration_seconds": duration},
                    )
                    
                    self.log_metric(agent_name, "execution_time", duration)
                    self.log_metric(agent_name, "executions", 1)
                    
                    return result
                    
                except Exception as e:
                    duration = time.time() - start_time
                    run_tree.end(
                        error=str(e),
                        outputs={"success": False, "error": str(e), "duration_seconds": duration},
                    )
                    
                    self.log_metric(agent_name, "errors", 1)
                    raise
            
            return wrapper
        return decorator
    
    def trace_llm_call(self, model_name: str, tokens_used: Dict[str, int]):
        """Trace LLM API calls with token usage"""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                start_time = time.time()
                run_tree = RunTree(
                    name=f"llm_{model_name}",
                    run_type="llm",
                    inputs={"model": model_name},
                )
                
                try:
                    result = func(*args, **kwargs)
                    
                    duration = time.time() - start_time
                    
                    # Log token usage
                    if isinstance(tokens_used, dict):
                        input_tokens = tokens_used.get("input_tokens", 0)
                        output_tokens = tokens_used.get("output_tokens", 0)
                    else:
                        input_tokens = 0
                        output_tokens = 0
                    
                    run_tree.end(
                        outputs={
                            "model": model_name,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "duration_seconds": duration,
                        },
                    )
                    
                    # Log metrics
                    self.log_metric(f"llm_{model_name}", "input_tokens", input_tokens)
                    self.log_metric(f"llm_{model_name}", "output_tokens", output_tokens)
                    self.log_metric(f"llm_{model_name}", "api_calls", 1)
                    self.log_metric(f"llm_{model_name}", "latency_ms", duration * 1000)
                    
                    return result
                    
                except Exception as e:
                    run_tree.end(error=str(e))
                    self.log_metric(f"llm_{model_name}", "errors", 1)
                    raise
            
            return wrapper
        return decorator
    
    def trace_cache_hit(self, cache_type: str, key: str):
        """Trace cache hits for metrics"""
        self.log_metric(f"cache_{cache_type}", "hits", 1)
        self.log_event({
            "type": "cache_hit",
            "cache_type": cache_type,
            "key_hash": hash(key),
            "timestamp": datetime.now().isoformat(),
        })
    
    def log_metric(self, namespace: str, metric_name: str, value: float):
        """Log a metric to LangSmith"""
        metric_key = f"{namespace}:{metric_name}"
        if metric_key not in self.traces:
            self.traces[metric_key] = []
        
        self.traces[metric_key].append({
            "value": value,
            "timestamp": datetime.now().isoformat(),
        })
    
    def log_event(self, event: Dict[str, Any]):
        """Log an event (cache hit, error, etc.)"""
        run_tree = RunTree(
            name="event",
            run_type="tool",
            inputs=event,
        )
        run_tree.end(outputs={"logged": True})
    
    def get_execution_summary(self) -> Dict[str, Any]:
        """Get summary of all traced metrics"""
        summary = {}
        
        for metric_key, values in self.traces.items():
            if values:
                namespace, metric = metric_key.rsplit(":", 1)
                
                if namespace not in summary:
                    summary[namespace] = {}
                
                summary[namespace][metric] = {
                    "total": sum(v["value"] for v in values),
                    "count": len(values),
                    "average": sum(v["value"] for v in values) / len(values),
                    "min": min(v["value"] for v in values),
                    "max": max(v["value"] for v in values),
                }
        
        return summary
    
    def get_cost_analysis(self) -> Dict[str, float]:
        """Calculate costs based on token usage"""
        # Claude 3.5 Haiku pricing
        haiku_input_cost = 0.00080 / 1000  # per token
        haiku_output_cost = 0.0040 / 1000
        
        # Claude 3.5 Sonnet pricing
        sonnet_input_cost = 0.003 / 1000
        sonnet_output_cost = 0.015 / 1000
        
        costs = {
            "haiku": {
                "input_cost": 0.0,
                "output_cost": 0.0,
                "total": 0.0,
            },
            "sonnet": {
                "input_cost": 0.0,
                "output_cost": 0.0,
                "total": 0.0,
            },
        }
        
        summary = self.get_execution_summary()
        
        for model_key in ["llm_claude-3-5-haiku-20241022", "llm_claude-3-5-sonnet-20241022"]:
            if model_key in summary:
                metrics = summary[model_key]
                
                if "input_tokens" in metrics:
                    haiku_in = metrics["input_tokens"]["total"] * haiku_input_cost
                    sonnet_in = metrics["input_tokens"]["total"] * sonnet_input_cost
                    
                if "output_tokens" in metrics:
                    haiku_out = metrics["output_tokens"]["total"] * haiku_output_cost
                    sonnet_out = metrics["output_tokens"]["total"] * sonnet_output_cost
        
        return costs
    
    def print_trace_report(self):
        """Print a formatted trace report"""
        summary = self.get_execution_summary()
        
        print("\n" + "="*70)
        print("LANGSMITH TRACE REPORT")
        print("="*70)
        
        for namespace, metrics in summary.items():
            print(f"\n📊 {namespace.upper()}")
            for metric_name, values in metrics.items():
                print(f"  • {metric_name}:")
                print(f"      Total: {values['total']:.2f}")
                print(f"      Average: {values['average']:.2f}")
                print(f"      Min: {values['min']:.2f} | Max: {values['max']:.2f}")
        
        costs = self.get_cost_analysis()
        print(f"\n💰 COST ANALYSIS")
        for model, cost_data in costs.items():
            if cost_data["total"] > 0:
                print(f"  • {model}: ${cost_data['total']:.4f}")
        
        print("\n" + "="*70)


# Global tracer instance
tracer = LangSmithTracer()


def setup_langsmith():
    """Configure LangSmith environment"""
    api_key = os.getenv("LANGSMITH_API_KEY")
    project = os.getenv("LANGSMITH_PROJECT", "car-deal-scanner")
    
    if api_key:
        os.environ["LANGSMITH_API_KEY"] = api_key
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_PROJECT"] = project
        print(f"✓ LangSmith configured (project: {project})")
    else:
        print("⚠ LANGSMITH_API_KEY not set - tracing disabled")
