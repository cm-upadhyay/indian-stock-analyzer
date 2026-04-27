"""8 AM morning note LLM call — interprets overnight developments vs yesterday's signal."""

from __future__ import annotations

import structlog

from analyzer.adapters import openai as llm_adapter
from analyzer.data.models import GlobalCues, MorningNote, StockVerdict
from analyzer.llm.prompt_library import PromptLibrary

log = structlog.get_logger()


def _build_user_message(
    symbol: str,
    company_name: str,
    sector_name: str,
    verdict: StockVerdict,
    cues: GlobalCues,
) -> str:
    lines = [
        f"Stock: {symbol} ({company_name}) — Sector: {sector_name}",
        "",
        "4 PM signal (computed yesterday):",
        f"  Signal: {verdict.signal}  Confidence: {verdict.confidence:.0%}",
        *(
            [f"  Entry ₹{verdict.entry:,}  Stop ₹{verdict.stop_loss:,}  Target ₹{verdict.target:,}"]
            if verdict.entry is not None
            else ["  No trade levels — HOLD signal"]
        ),
        "",
        "Overnight developments (since 4 PM yesterday):",
    ]

    if cues.sp_ret is not None:
        base = f"  US S&P 500: {cues.sp_ret:+.2f}%"
        if cues.nq_ret is not None:
            base += f"  Nasdaq: {cues.nq_ret:+.2f}%"
        lines.append(base)
    if cues.nk_ret is not None:
        lines.append(f"  Nikkei: {cues.nk_ret:+.2f}%")
    if cues.hsi_ret is not None:
        lines.append(f"  Hang Seng: {cues.hsi_ret:+.2f}%")
    if cues.esf_ret is not None:
        lines.append(f"  S&P futures: {cues.esf_ret:+.2f}% (live)")
    if cues.brent_ret is not None and cues.brent_price is not None:
        lines.append(f"  Brent crude: ${cues.brent_price:.1f}  {cues.brent_ret:+.2f}%")
    if cues.gold_ret is not None and cues.gold_price is not None:
        lines.append(f"  Gold: ${cues.gold_price:,.0f}  {cues.gold_ret:+.2f}%")
    if cues.usdinr is not None:
        lines.append(f"  USD/INR: ₹{cues.usdinr:.2f}")

    return "\n".join(lines)


def _extract_status(text: str) -> str:
    text_upper = text.upper()
    for marker in ["SIGNAL STRENGTHENED", "SIGNAL WEAKENED", "SIGNAL INTACT"]:
        if marker in text_upper:
            return marker.replace("SIGNAL ", "")
    log.warning("morning_status_not_found_defaulting_intact")
    return "INTACT"


def call_morning_note(
    symbol: str,
    company_name: str,
    sector_name: str,
    verdict: StockVerdict,
    cues: GlobalCues,
) -> MorningNote:
    log.info("call_morning_note_start", symbol=symbol)
    system_prompt = PromptLibrary.get("morning", signal=verdict.signal)
    user_message = _build_user_message(symbol, company_name, sector_name, verdict, cues)

    content, input_tok, output_tok = llm_adapter.chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.2,
    )
    log.info(
        "call_morning_note_done", symbol=symbol, input_tokens=input_tok, output_tokens=output_tok
    )

    return MorningNote(
        symbol=symbol,
        company_name=company_name,
        previous_signal=verdict.signal,
        morning_text=content.strip(),
        status=_extract_status(content),
        input_tokens=input_tok,
        output_tokens=output_tok,
    )
