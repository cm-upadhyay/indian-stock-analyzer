"""Agentic tool-calling loop — LLM decides which MCP tools to call.

What "agentic" means here:
    In Phase 2, the pipeline was FIXED: always fetch technical, fundamental, option chain,
    corporate, news, and macro — regardless of whether the LLM needed all of them.

    In Phase 3A, the pipeline is AGENTIC for the data-fetching step:
    - Technical signals are ALWAYS pre-loaded (12 votes, cheap, small data)
    - The LLM then receives: technical signals + the MCP tool catalog
    - The LLM decides which additional tools it needs based on what it sees:
        * "IRCTC has a very low RSI and I see news about earnings — I need corporate_actions"
        * "HDFC Bank looks standard — only technicals are enough"
    - Max 5 tool calls per stock (safety cap — prevents runaway token consumption)
    - After tool calls, the LLM produces a final StockVerdict

Fallback:
    If ENABLE_AGENTIC_MODE=false (or the token budget is exhausted), we fall back
    to calling call_analyst() directly with all Phase 2 data. Graceful degradation.

How tool calling works technically:
    LiteLLM supports OpenAI's function calling API. We pass a list of tool schemas
    (JSON Schema format) and the LLM response may include tool_calls. We execute
    those tools locally (calling our MCP tool functions directly), then append the
    results back to the messages list and call the LLM again.

Env:
    ENABLE_AGENTIC_MODE  — "true"/"false" (default: true)
    MAX_TOOL_CALLS       — max tool calls per stock (default: 5)
"""

from __future__ import annotations

import json

import structlog

from analyzer.adapters.openai import PRIMARY_MODEL
from analyzer.config import settings
from analyzer.data.models import (
    NewsItem,
    ScoringResult,
    StockData,
    StockVerdict,
    TechnicalSignals,
)
from analyzer.flags import get_flag
from analyzer.llm.prompt_library import PromptLibrary
from analyzer.memory.context import MemoryContext

log = structlog.get_logger()

# _MAX_TOOL_CALLS is read once at import time (a numeric setting, not a toggle).
# _ENABLED is read per-call via get_flag() so flags.yaml flips take effect immediately.
_MAX_TOOL_CALLS = settings.max_tool_calls

# ── Tool schemas (JSON Schema, shown to the LLM) ──────────────────────────────

_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_option_chain",
            "description": (
                "Get Put/Call Ratio (PCR) and max pain price from the NSE option chain. "
                "Call this for F&O-eligible stocks when you need to understand options market sentiment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "NSE symbol WITHOUT .NS suffix, e.g. 'RELIANCE'",
                    }
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_corporate_actions",
            "description": (
                "Get upcoming earnings date, recent dividends, and stock splits. "
                "Call this when the stock shows unusual price/volume action near quarter-end, "
                "or when a RECENT news article (labelled '[1 day ago]' or '[2 days ago]' or no label) "
                "mentions upcoming earnings or an upcoming dividend. "
                "Do NOT call this for articles labelled '[X weeks ago]' or '[X months ago]' — "
                "those events have already passed and this tool returns forward-looking data only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "NSE symbol WITHOUT .NS suffix, e.g. 'RELIANCE'",
                    }
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_peer_comparison",
            "description": (
                "Compare the stock's PE/PB ratio and 1-month return to its sector peers. "
                "Call this when you need to know whether the stock is cheap or expensive "
                "relative to similar companies."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "NSE symbol WITHOUT .NS suffix, e.g. 'HDFC'",
                    }
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_macro_news",
            "description": (
                "Search for broad Indian market news and macro themes (RBI policy, FII flows, "
                "Nifty sector rotation, Union Budget, global cues). "
                "Call this when the stock's move seems driven by macro events rather than "
                "company-specific factors, or when stock-level news is sparse."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Specific search query, e.g. 'RBI rate decision impact on banking stocks'. "
                            "Leave empty for a broad Nifty/market overview."
                        ),
                    }
                },
                "required": [],
            },
        },
    },
]

# ── Tool executor (calls local MCP tool functions directly) ───────────────────


def _execute_tool(name: str, args: dict[str, str]) -> str:
    """Execute a tool by name and return the result as a JSON string."""
    symbol = args.get("symbol", "")
    try:
        if name == "get_option_chain":
            from mcp_server.tools.option_chain import run

            result = run(symbol)
        elif name == "get_corporate_actions":
            from mcp_server.tools.corporate import run

            result = run(symbol)
        elif name == "get_peer_comparison":
            from mcp_server.tools.peers import run

            result = run(symbol)
        elif name == "get_macro_news":
            from mcp_server.tools.macro_news import run as macro_run

            result = macro_run(query=args.get("query", ""))
        else:
            result = {"error": f"Unknown tool: {name}"}
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Agentic loop ──────────────────────────────────────────────────────────────


def _build_initial_message(
    stock: StockData,
    tech: TechnicalSignals,
    scoring: ScoringResult,
    news_context: str,
    memory_context: MemoryContext,
) -> str:
    """Build the initial user message for the agentic loop.

    This is intentionally leaner than the Phase 2 full message — we provide
    the technical signals and let the LLM decide if it needs more data.
    It can call tools to get fundamentals, option chain, etc.
    """
    mem_block = memory_context.to_prompt_block()

    lines = []
    if mem_block:
        lines += [mem_block, ""]

    lines += [
        f"Stock: {stock.symbol} ({stock.company_name})",
        f"Current price: ₹{stock.current_price:,.0f}",
        "",
        f"TECHNICAL SIGNALS ({len(tech.votes)} votes): {scoring.tech_summary}",
        f"  RSI {tech.rsi:.1f} ({tech.rsi_label}) | {tech.trend_ma200}",
        f"  Volume: {tech.volume_ratio:.1f}x avg | MACD: {tech.macd_label}",
        f"  52-week position: {tech.pct_from_low:.0f}% from year-low",
        f"  Delivery: {tech.delivery_label}",
        "",
        "Recent news:",
        news_context,
        "",
        "You have tools available to fetch more data if needed.",
        "Call them only if the additional context would change your verdict.",
        "After gathering enough information, produce the final verdict JSON.",
    ]
    return "\n".join(lines)


def run_agentic_analysis(
    stock: StockData,
    tech: TechnicalSignals,
    scoring: ScoringResult,
    news: list[NewsItem],
    news_context: str,
    memory_context: MemoryContext,
) -> StockVerdict:
    """Run the agentic tool-calling loop and return a StockVerdict.

    Loop:
        1. Send initial message with technical signals + tool catalog
        2. LLM responds with either tool_calls or a final JSON verdict
        3. If tool_calls: execute them, append results, call LLM again
        4. Repeat up to MAX_TOOL_CALLS times
        5. Return the final verdict

    Falls back to Phase 2 fixed pipeline if agentic mode is disabled or fails.
    Flag read per-call so flags.yaml changes take effect without restart.
    """
    if not get_flag("enable_agentic_mode", default=True):
        log.info("agentic_mode_disabled_by_flag", symbol=stock.symbol)
        from analyzer.llm.analyst import call_analyst

        return call_analyst(stock, tech, scoring, news, memory_context)

    system_prompt = PromptLibrary.get("analysis")
    user_message = _build_initial_message(stock, tech, scoring, news_context, memory_context)

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    tool_calls_made = 0

    for _ in range(_MAX_TOOL_CALLS + 1):  # +1 for the final verdict call
        try:
            import litellm

            resp = litellm.completion(
                model=PRIMARY_MODEL,
                messages=messages,
                tools=_TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.3,
                response_format={"type": "json_object"}
                if tool_calls_made == _MAX_TOOL_CALLS
                else None,
            )
        except Exception as e:
            log.error("agentic_llm_call_failed", symbol=stock.symbol, error=str(e))
            raise

        choice = resp.choices[0]
        message = choice.message

        # If the LLM wants to call tools
        if message.tool_calls and tool_calls_made < _MAX_TOOL_CALLS:
            messages.append(message.model_dump())  # append assistant message

            for tc in message.tool_calls:
                tool_name = tc.function.name
                tool_args = json.loads(tc.function.arguments or "{}")
                log.info(
                    "agentic_tool_call",
                    symbol=stock.symbol,
                    tool=tool_name,
                    args=tool_args,
                    call_num=tool_calls_made + 1,
                )
                result = _execute_tool(tool_name, tool_args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    }
                )
                tool_calls_made += 1

            continue  # loop again with tool results in context

        # No more tool calls — extract the verdict JSON
        content = message.content or ""
        usage = resp.usage
        log.info(
            "agentic_done",
            symbol=stock.symbol,
            tool_calls_made=tool_calls_made,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

        raw = json.loads(content)
        _VALID_SIGNALS = {
            "BUY",
            "SELL",
            "HOLD",
            "STRONG BUY",
            "STRONG SELL",
            "LEAN BUY",
            "LEAN SELL",
            "NEUTRAL",
        }
        signal = raw.get("signal", "")
        if signal not in _VALID_SIGNALS:
            raise ValueError(f"Agentic LLM returned unexpected signal '{signal}'")

        return StockVerdict(
            signal=signal,
            confidence=float(raw["confidence"]),
            entry=int(raw["entry"]) if raw.get("entry") else None,
            stop_loss=int(raw["stop_loss"]) if raw.get("stop_loss") else None,
            target=int(raw["target"]) if raw.get("target") else None,
            whats_happening=raw.get("whats_happening", ""),
            why_it_matters=raw.get("why_it_matters", ""),
            watch_out_for=raw.get("watch_out_for", ""),
            trader_action=raw.get("trader_action", ""),
            investor_action=raw.get("investor_action", ""),
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    raise ValueError(f"Agentic loop exceeded {_MAX_TOOL_CALLS} tool calls without verdict")
