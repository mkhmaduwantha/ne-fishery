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
        "You are a fisherman making decisions about your livelihood on a shared lake. "
        "You are not a character in a story. Do not perform, narrate, or use atmospheric language. "
        "Do not use fishing idioms or colourful expressions for effect. Do not address people dramatically. "
        "Think and respond like someone working through a real problem — practical, uncertain, sometimes social, "
        "always self-interested to some degree. You may be cooperative or not, but for genuine reasons based on "
        "what you observe, not for dramatic effect. "
        "If you have nothing genuine to say, say nothing. Silence is normal. "
        "Write in plain prose only. No bullet points, no bold text, no headers, no lists. No formatting of any kind."
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

CONVERSATION_TURNS = 3   # max turns in the dock conversation phase per round

WORLD_CONFIG = {
    "lake_initial": 200,        # tons
    "lake_max": 200,
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
            "Your name is Ana. You are thirty-eight years old. "
            "You have fished this lake for twelve years and it is your "
            "primary income. You have two children in school and the "
            "household depends on what you bring in. You have no other "
            "source of income."
        )
    },
    {
        "name": "Marco",
        "disposition": (
            "Your name is Marco. You are forty-four years old. "
            "You fish this lake seasonally and move to other lakes "
            "through the year. You send a portion of what you earn "
            "to your parents. You have no permanent stake in this "
            "particular lake."
        )
    },
    {
        "name": "Sofia",
        "disposition": (
            "Your name is Sofia. You are thirty-two years old. "
            "You have fished this lake for three years, having moved "
            "from a coastal fishing village where the fishermen had "
            "longstanding informal arrangements about the catch. "
            "This lake is your main income now."
        )
    },
    {
        "name": "James",
        "disposition": (
            "Your name is James. You are fifty-three years old. "
            "You have fished this lake for over twenty years — longer "
            "than anyone else here. You have watched the stock go up "
            "and down over that time and you have a good sense of "
            "what the lake can sustain. Fishing is all you have done."
        )
    },
    {
        "name": "Yuki",
        "disposition": (
            "Your name is Yuki. You are twenty-eight years old. "
            "This is your second year on this lake. You are still "
            "learning how it behaves across seasons. You do not yet "
            "know the other fishermen well."
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
