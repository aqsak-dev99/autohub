"""Groq list prices in USD per 1 million tokens: (input, output).

Source: console.groq.com/docs/models (checked Oct 2026). Prices change, so
they live in one table. A model missing from the table costs 0 and is
flagged `priced=False`, so the dashboard can show "unknown cost" instead
of silently pretending it was free.
"""
PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-safeguard-20b": (0.075, 0.30),
    "qwen/qwen3.8-27b": (0.80, 4.00),
}


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> tuple[float, bool]:
    """Return (cost, priced). `priced` is False when the model isn't in the table."""
    price = PRICES_PER_MILLION.get(model)
    if price is None:
        return 0.0, False
    input_price, output_price = price
    cost = (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000
    return round(cost, 8), True
