# config.py
# All tunable parameters in one place.
# Two separate model configs: one for agents, one for extraction.
# Swap models by changing the "model" key — nothing else needs to change.

from dotenv import load_dotenv

load_dotenv()

# ── Model configurations ───────────────────────────────────────────────────────
# Both point at the local Ollama server (http://localhost:11434 by default).
# To swap models later: change "model" here — agents.py / extractor.py use
# get_llm() which reads these configs at chain-build time.

AGENT_MODEL_CONFIG = {
    "model": "gpt-oss:20b",
    "max_tokens": 2048,          # maps to num_predict in Ollama; generous to prevent mid-sentence cutoff
    "temperature": 0.9,          # higher → more varied, human-like responses
    "system": (
        "You are a fisherman in a small fishing community sharing a lake. "
        "You make decisions based on your experience, observations, and conversations. "
        "You have no external authority telling you what to do. "
        "Respond naturally, as a person would — with uncertainty, self-interest, "
        "and social awareness. Never use bureaucratic or institutional language. "
        "Be direct and practical. Do not tell stories, use metaphors, or dramatise. "
        "Write in plain prose paragraphs only. "
        "Do NOT use markdown, bullet points, bold text, headers, or any special formatting."
    )
}

EXTRACTOR_MODEL_CONFIG = {
    "model": "gpt-oss:20b",
    "max_tokens": 2048,           # JSON output is compact; no need for more
    "temperature": 0.1,          # 0.0 causes some Ollama models to return empty; 0.1 is stable
    "system": (
        "You extract structured data from text and return only valid JSON. "
        "No explanation. No markdown. No preamble. Output only the JSON object."
    )
}


def get_llm(config_key: str, json_mode: bool = False):
    """
    Model factory — returns a LangChain ChatOllama for the named config.
    config_key: "agent" | "extractor"
    json_mode:  True enables Ollama's native JSON output mode (extractor only).

    To plug in a new model later:
      - Change the "model" value in AGENT_MODEL_CONFIG / EXTRACTOR_MODEL_CONFIG
      - Or add a new config dict and a new config_key branch here
      - Nothing in agents.py or extractor.py needs to change
    """
    from langchain_ollama import ChatOllama

    cfg = AGENT_MODEL_CONFIG if config_key == "agent" else EXTRACTOR_MODEL_CONFIG
    kwargs = dict(
        model=cfg["model"],
        temperature=cfg["temperature"],
        num_predict=cfg.get("max_tokens", 800),
    )
    if json_mode:
        kwargs["format"] = "json"   # Ollama native JSON mode — forces valid JSON output
    return ChatOllama(**kwargs)


# ── World parameters ──────────────────────────────────────────────────────────

CONVERSATION_TURNS = 2   # max turns in the dock conversation phase per round

WORLD_CONFIG = {
    "lake_initial": 100,        # tons
    "lake_max": 100,
    "regeneration_rate": 0.07,  # 7% — at full stock ~35t/round; beatable by moderate collective harvest
    "min_harvest": 0,
    "max_harvest": 12,
    "rounds_total": 30,
    "round_delay_seconds": 3,
}

# ── Agent dispositions ────────────────────────────────────────────────────────

AGENTS = [
    {
        "name": "Ana",
        "disposition": (
            "You are Ana, a fisherwoman in your late thirties. You have been "
            "fishing this lake for twelve years. You have two children and the "
            "income matters a great deal to your household. You are generally "
            "quiet but thoughtful, and you tend to take your time before saying "
            "something."
        )
    },
    {
        "name": "Marco",
        "disposition": (
            "You are Marco, a fisherman in your mid-forties. You fish to support "
            "yourself and send money to your parents. You have fished many lakes "
            "over the years and have seen some dry up. You are straightforward and "
            "say what you think without much ceremony."
        )
    },
    {
        "name": "Sofia",
        "disposition": (
            "You are Sofia, a fisherwoman in your early thirties. You are relatively "
            "new to this lake — about three years. You came from a coastal fishing "
            "village where the community had its own ways of doing things. You are "
            "curious and sociable by nature."
        )
    },
    {
        "name": "James",
        "disposition": (
            "You are James, a fisherman in your fifties. You have fished this lake "
            "longer than anyone here — over twenty years. You have seen the stock "
            "fluctuate. You are not particularly talkative but you notice a great "
            "deal. You are methodical in how you work."
        )
    },
    {
        "name": "Yuki",
        "disposition": (
            "You are Yuki, a fisherman in your late twenties. This is your second "
            "year here. You are still learning the rhythms of this particular lake "
            "and the people around it. You are observant and try not to make "
            "assumptions before you have enough information."
        )
    }
]

# ── Memory parameters ─────────────────────────────────────────────────────────

MEMORY_WINDOW = 8
MEMORY_SALIENCE_TYPES = ["proposal", "conflict", "agreement", "reflection"]

REFLECTION_TRIGGERS = {
    "lake_drop_percent": 15,
    "called_out": True,
    "proposal_received": True,
}
