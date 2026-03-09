import os
def ai_enabled():
    return os.getenv("AI_MODE","off").strip().lower() in {"1","true","on","yes"}
def ai_recommendation(context):
    return (
        "AI(v0) — spiegazione contesto\n"
        f"- symbol: {context.get('symbol')}\n"
        f"- tf: {context.get('timeframe')}\n"
        f"- regime: {context.get('regime')}\n"
        f"- price: {context.get('price')}\n"
        f"- signal: {context.get('signal')}\n"
        f"- mode: {context.get('mode')}\n"
        "Nota: AI v0 non decide trade."
    )
