"""LLM reasoning layer.

This module is deliberately the *only* place the language model is involved,
and it is deliberately blind to the database. It accepts the pre-computed,
verified statistics payload produced by stats.py, hands it to Claude, and
returns the model's structured advisory. It performs no arithmetic and reads no
raw price rows -- the model reasons over facts that were already computed and
rounded upstream.
"""

import json
import os

from dotenv import load_dotenv

load_dotenv()

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 1500

SYSTEM_PROMPT = """You are a knowledgeable vinyl record collection advisor. \
You will be given a structured summary of a collector's Discogs collection, \
including per-record price data and collection-level statistics that have \
already been computed. Your job is to interpret this data and produce a clear, \
useful advisory report.

Critical rules:
- Only use the numbers provided. Do not invent or estimate any figures, prices, \
or percentages. Every number you cite must come directly from the input data.
- If the data is insufficient to make a claim, say so rather than guessing.
- Be specific and reference actual records by name.
- Write for the collector: practical, direct, no filler.

Return your response as JSON with exactly these fields:
- "overview": collection total value and where value is concentrated
- "movers": records that appreciated or declined meaningfully, with the actual figures
- "consider_selling": records where the data suggests it may be a good time to \
sell, with reasoning; be honest about uncertainty
- "watch_list": records showing volatility or momentum worth monitoring

Each field should be a string of readable prose (or a short list). Return only \
the JSON, no preamble or markdown fences."""

REQUIRED_FIELDS = ("overview", "movers", "consider_selling", "watch_list")


class AdvisorError(RuntimeError):
    """Raised when a usable advisory could not be produced."""


def _strip_fences(text):
    """Tolerate a model that wraps JSON in ```json ... ``` despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        if text.endswith("```"):
            text = text[: -3]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    return text.strip()


def _parse_advisory(text):
    data = json.loads(_strip_fences(text))
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        raise ValueError(f"advisory missing fields: {missing}")
    return {f: data[f] for f in REQUIRED_FIELDS}


def generate_advisory(stats_payload):
    """Send computed stats to Claude and return the parsed advisory dict.

    Retries once if the model returns malformed JSON, then fails with a clear
    error rather than crashing the caller.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise AdvisorError("ANTHROPIC_API_KEY is not set.")

    # Imported here so the deterministic stats layer stays importable (and
    # testable) without the anthropic package installed.
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    user_message = (
        "Here is the computed summary of the collection. Reason only over these "
        "numbers.\n\n" + json.dumps(stats_payload, indent=2)
    )

    last_error = None
    for attempt in range(2):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            text = "".join(block.text for block in response.content if block.type == "text")
            return _parse_advisory(text)
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e  # malformed output -- try once more
            continue

    raise AdvisorError(f"Model did not return valid advisory JSON: {last_error}")


def fallback_advisory(stats_payload):
    """A deterministic, offline stand-in for the model's advisory.

    This is NOT the language model. It is a plain template that fills the same
    four sections from the pre-computed statistics, so the app is fully runnable
    and screenshot-able without an Anthropic API key. It intentionally reuses the
    verified numbers rather than inventing any -- the same discipline the real
    advisory is held to. The UI labels it clearly as an offline sample.
    """
    col = stats_payload["collection"]

    def money(v):
        return f"${v:,.2f}" if v is not None else "n/a"

    # Overview
    top = col["value_concentration"]["records"]
    conc = col["value_concentration"]
    if top:
        lead = ", ".join(f"{r['title']} ({money(r['current_price'])})" for r in top[:3])
        overview = (
            f"This collection holds {col['record_count']} records worth "
            f"{money(col['total_current_value'])} in total. Value is concentrated at "
            f"the top: the {conc['top_n']} most valuable records account for "
            f"{conc['top_n_pct_of_total']}% of it, led by {lead}."
        )
    else:
        overview = (
            f"This collection holds {col['record_count']} records worth "
            f"{money(col['total_current_value'])} in total."
        )

    # Movers
    def mover_line(r, sign):
        return (f"{r['title']}: {money(r['first_price'])} → {money(r['current_price'])} "
                f"({sign}{r['change_pct']}% over {r['snapshots']} snapshots)")

    gainers, losers = col["biggest_gainers"], col["biggest_losers"]
    parts = []
    if gainers:
        parts.append("Up: " + "; ".join(mover_line(r, "+") for r in gainers[:3]) + ".")
    if losers:
        parts.append("Down: " + "; ".join(mover_line(r, "") for r in losers[:3]) + ".")
    movers = " ".join(parts) if parts else (
        "No records have enough price history yet to measure a change. Run sync.py "
        "again over time to build a window.")

    # Consider selling: gainers currently sitting at their tracked high.
    at_high = [r for r in gainers if r["current_price"] is not None]
    if at_high:
        consider_selling = (
            "These are near the top of their tracked range after rising, so it may be "
            "worth checking live listings: "
            + "; ".join(f"{r['title']} (now {money(r['current_price'])}, up {r['change_pct']}%)"
                        for r in at_high[:3])
            + ". Marketplace 'lowest listing' prices are noisy, so treat this as a prompt "
              "to look, not a signal to act.")
    else:
        consider_selling = (
            "Nothing stands out as an obvious sell on the current data. With more price "
            "history the picture will sharpen.")

    # Watch list: most volatile.
    vol = col["most_volatile"]
    if vol:
        watch_list = (
            "Prices here have swung the most and are worth monitoring: "
            + "; ".join(f"{r['title']} (range {money(r['min_price'])}–{money(r['max_price'])}, "
                        f"std dev {money(r['volatility_std_dev'])})" for r in vol[:3])
            + ".")
    else:
        watch_list = "Not enough repeated snapshots yet to flag volatility."

    return {
        "overview": overview,
        "movers": movers,
        "consider_selling": consider_selling,
        "watch_list": watch_list,
    }
