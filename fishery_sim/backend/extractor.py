# extractor.py
# LangChain LCEL chain for structured decision extraction.
# Uses a separate LLM config — never influences agent tone.

import json
import re
import logging
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import BaseOutputParser
from config import EXTRACTOR_MODEL_CONFIG, get_llm

logger = logging.getLogger(__name__)

_FALLBACK: dict = {
    "harvest": 6,
    "next_location": "fishing",
    "speech_type": "SILENT",
    "addressee": None,
    "message": None,
    "reflect": "Could not parse response.",
    "norm_signal": False,
    "pending_intent": None,
}

# Word-to-number map so "twelve tons" → 12
_WORD_NUMS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12,
}


def _parse_json_from_text(text: str) -> dict | None:
    """Try multiple strategies to extract a JSON object from model output."""
    if not text or not text.strip():
        return None

    candidates = []
    candidates.append(text.strip())

    # Strip markdown fences
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    # First {...} block (handles preamble/postamble)
    brace_match = re.search(r"\{[\s\S]*\}", text)
    if brace_match:
        candidates.append(brace_match.group(0))

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


class RobustJsonParser(BaseOutputParser[dict]):
    """Multi-strategy JSON extractor with word-number normalisation."""

    def parse(self, text: str) -> dict:
        result = _parse_json_from_text(text)

        if result is None:
            logger.warning(f"[extractor] All JSON strategies failed | raw: {text[:150]!r}")
            fallback = dict(_FALLBACK)
            fallback["_raw_extractor"] = text if text.strip() else "[model returned empty string]"
            return fallback

        for k, v in _FALLBACK.items():
            result.setdefault(k, v)

        # Normalise harvest — handle word numbers and floats
        h = result.get("harvest", 6)
        if isinstance(h, str):
            h = _WORD_NUMS.get(h.lower().strip(), 6)
        try:
            h = int(float(h))
        except (ValueError, TypeError):
            h = 6
        result["harvest"] = max(0, min(12, h))

        result["_raw_extractor"] = text
        return result

    @property
    def _type(self) -> str:
        return "robust_json"


# ── Build extractor chain with Ollama JSON mode ────────────────────────────────
# json_mode=True enables Ollama's native constrained JSON output.
# This is the primary fix for the "[model returned empty string]" issue —
# the model is forced to produce JSON tokens rather than stalling.

_extractor_llm = get_llm("extractor", json_mode=True)

_extractor_prompt = ChatPromptTemplate.from_messages([
    ("system", EXTRACTOR_MODEL_CONFIG["system"]),
    ("human", "{prompt_text}"),
])

extractor_chain = _extractor_prompt | _extractor_llm | RobustJsonParser()


# ── Extraction prompt ──────────────────────────────────────────────────────────
# IMPORTANT: uses __MARKER__ placeholders, NOT Python .format() placeholders.
# This is deliberate — agent responses often contain { } characters (prices,
# ranges, etc.) which break str.format(). We substitute with .replace() instead.

_EXTRACTION_PROMPT_TEMPLATE = """You are extracting structured data from a fisherman's statement.

Read the statement below and fill in the JSON template.

STATEMENT:
\"\"\"
__RAW_RESPONSE__
\"\"\"

Context:
- Agent name: __AGENT_NAME__
- Agents currently at the dock: __DOCK_AGENTS__

Fill this JSON template — replace every value with what you extract, output only JSON:

{
  "harvest": 6,
  "next_location": "fishing",
  "speech_type": "SILENT",
  "addressee": null,
  "message": null,
  "reflect": "one sentence internal thought",
  "norm_signal": false,
  "pending_intent": null
}

Field rules:
- harvest: integer 0-12. Count tons explicitly mentioned ("twelve tons"=12, "six"=6). Use 0 if they say they won't fish or are at the dock. Default 6 if not stated.
- next_location: "dock" if they mention going to dock, selling, or meeting others. Otherwise "fishing".
- speech_type: "GROUP"=talks to everyone, "DIRECT"=talks to one named person, "SELF"=thinks privately, "SILENT"=says nothing.
- addressee: name of person if speech_type is "DIRECT", otherwise null.
- message: exact words they plan to say out loud (GROUP or DIRECT only), null otherwise.
- reflect: single sentence capturing their private internal thought or motivation.
- norm_signal: true if message proposes a rule, limit, fairness agreement, or collective action.
- pending_intent: if they want to speak to someone DIRECT who is NOT in the dock list, write who and why. Otherwise null.

Output only the filled JSON object."""


# ── Public helper ──────────────────────────────────────────────────────────────

def extract_decision(agent_name: str, raw_response: str,
                     available_at_dock: list,
                     agent_location: str = "fishing") -> dict:
    """
    Extract structured decisions from the agent's free-form response.
    Retries once if the model returns empty.
    """
    if not raw_response or not raw_response.strip():
        fallback = dict(_FALLBACK)
        fallback["harvest"] = 0 if agent_location == "dock" else _FALLBACK["harvest"]
        fallback["_raw_extractor"] = "[empty agent response — skipped extraction]"
        fallback["_raw_extractor_prompt"] = "[skipped — no agent response to extract from]"
        logger.warning(f"[extractor] Empty agent response for {agent_name}")
        return fallback

    # Safe substitution — avoids KeyError when agent response contains { }
    dock_str = ", ".join(available_at_dock) if available_at_dock else "none"
    prompt_text = (
        _EXTRACTION_PROMPT_TEMPLATE
        .replace("__RAW_RESPONSE__", raw_response)
        .replace("__AGENT_NAME__", agent_name)
        .replace("__DOCK_AGENTS__", dock_str)
    )

    # Append location constraint so model knows the physical rules
    if agent_location == "dock":
        prompt_text += (
            "\n\nNOTE: If the agent is at the dock this round, harvest MUST be 0."
            "This overrides any stated intention to fish or harvest. "
        )
    else:
        prompt_text += (
            "\n\nNOTE: If the agent is out fishing, not at the dock. "
            "Set speech_type to SILENT or SELF only — they cannot speak to anyone."
        )

    for attempt in range(2):
        try:
            result = extractor_chain.invoke({"prompt_text": prompt_text})
            result["_raw_extractor_prompt"] = prompt_text   # always attach prompt
            raw_ext = result.get("_raw_extractor", "").strip()
            if not raw_ext or raw_ext == "[model returned empty string]":
                logger.warning(f"[extractor] Empty model output for {agent_name} "
                               f"(attempt {attempt + 1})")
                if attempt == 0:
                    continue  # retry once
            return result
        except Exception as e:
            logger.error(f"[extractor] Chain error for {agent_name} "
                         f"(attempt {attempt + 1}): {e}")
            if attempt == 1:
                fallback = dict(_FALLBACK)
                fallback["_raw_extractor"] = f"[chain error: {e}]"
                fallback["_raw_extractor_prompt"] = prompt_text
                return fallback

    fallback = dict(_FALLBACK)
    fallback["_raw_extractor"] = "[model returned empty on both attempts]"
    fallback["_raw_extractor_prompt"] = prompt_text
    return fallback
