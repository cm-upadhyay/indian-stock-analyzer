"""MCP server — exposes all data fetchers as Model Context Protocol tools.

What is MCP?
    MCP (Model Context Protocol) is an open standard by Anthropic that defines how
    AI models can call external tools. Think of it like a USB standard for AI tools —
    any MCP client (Claude, a LangGraph agent, a test script) can connect to any
    MCP server and call its tools, without knowing the implementation details.

Why we expose our fetchers as MCP tools:
    In Phase 2, the pipeline always fetched everything (technical, fundamental,
    option chain, corporate events, peers). Whether the LLM needed them or not.
    This is wasteful for a large-cap stable stock where only technicals matter.

    With MCP, the LLM can decide: "For IRCTC, I need corporate actions because
    there's an earnings announcement. For HDFC Bank, I only need technicals."
    This reduces data fetches and LLM prompt size for simple cases.

Running the MCP server:
    python -m mcp_server.server          # starts stdio server (for testing)
    python -m mcp_server.server --port 8001  # starts HTTP server (for production)

Tools exposed:
    get_technical_signals(symbol)     — 12 technical votes
    get_fundamental_signals(symbol)   — 15 fundamental votes
    get_option_chain(symbol)          — PCR, max pain, OI analysis
    get_corporate_actions(symbol)     — dividends, earnings, splits
    get_peer_comparison(symbol)       — sector PE/PB, peer list
    get_news(symbol)                  — recent news headlines + summaries
    get_macro_context(symbol)         — market overview, FII/DII, sector return

Each tool returns a Pydantic model serialised to a dict.
The LLM sees a compact JSON summary, not the full DataFrame.
"""

from __future__ import annotations

import structlog
from mcp.server.fastmcp import FastMCP  # type: ignore[import-untyped]

from mcp_server.tools import corporate, option_chain, peers
from mcp_server.tools import technical as tech_tool

log = structlog.get_logger()

# FastMCP is the high-level interface — it handles the MCP protocol boilerplate.
# You just write Python functions with type hints and docstrings.
mcp = FastMCP(
    name="Indian Stock Analyzer",
    instructions="Stock analysis tools for NSE/BSE listed Indian equities",
)


# ── Tool registrations ────────────────────────────────────────────────────────
# Each @mcp.tool() decorated function becomes a callable tool in the MCP catalog.
# The function signature defines the input schema (shown to the LLM).
# The docstring is the tool description (used by the LLM to decide when to call it).


@mcp.tool()
def get_technical_signals(symbol: str) -> dict:  # type: ignore[type-arg]
    """Compute 12 technical signals for a stock.

    Returns RSI, moving averages (20/50/200), MACD, volume ratio,
    52-week position, Stochastic %K/%D, Bollinger Bands, Williams %R,
    CCI, and NSE delivery %. Each indicator votes BUY/NEUTRAL/SELL.

    Use this as the starting point for every analysis — it's always called.

    Args:
        symbol: NSE symbol with exchange suffix, e.g. "RELIANCE.NS"
    """
    return tech_tool.run(symbol)


@mcp.tool()
def get_option_chain(symbol: str) -> dict:  # type: ignore[type-arg]
    """Get option chain analysis for a stock: Put/Call Ratio (PCR) and max pain.

    PCR < 0.7 → bullish (calls dominate, market expects rally)
    PCR > 1.2 → bearish (puts dominate, market expects decline)
    Max pain  → the price at which most options expire worthless

    Call this for stocks where options data would help interpret direction —
    especially mid-cap/large-cap stocks with active F&O participation.
    Not useful for small-cap stocks without option chains.

    Args:
        symbol: NSE symbol WITHOUT .NS suffix, e.g. "RELIANCE"
    """
    clean = symbol.replace(".NS", "")
    return option_chain.run(clean)


@mcp.tool()
def get_corporate_actions(symbol: str) -> dict:  # type: ignore[type-arg]
    """Get upcoming and recent corporate events: earnings, dividends, splits, AGMs.

    Returns next earnings date, dividend history (last 3), ex-dividend dates,
    stock splits, and any upcoming board meetings.

    Call this when:
        - The news mentions an earnings report, dividend announcement, or board meeting
        - You need to understand whether a price move is driven by a corporate event
        - The stock shows unusual volume or price action near quarter-end

    Args:
        symbol: NSE symbol with or without .NS suffix, e.g. "RELIANCE" or "RELIANCE.NS"
    """
    clean = symbol.replace(".NS", "")
    return corporate.run(clean)


@mcp.tool()
def get_peer_comparison(symbol: str) -> dict:  # type: ignore[type-arg]
    """Compare a stock to its sector peers: relative PE, PB, and returns.

    Returns the stock's PE/PB vs sector median, the 5 closest peers by market cap,
    and the stock's 1-month return vs the sector average.

    Call this when:
        - You want to know if the stock is cheap/expensive vs peers
        - The stock's sector is performing differently from the overall market
        - You need context on whether the fundamental data is unusual for this sector

    Args:
        symbol: NSE symbol with or without .NS suffix, e.g. "HDFC.NS"
    """
    clean = symbol.replace(".NS", "")
    return peers.run(clean)


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    """Start the MCP server. Default: stdio transport for development."""
    log.info("mcp_server_start", name="Indian Stock Analyzer")
    mcp.run()


if __name__ == "__main__":
    main()
