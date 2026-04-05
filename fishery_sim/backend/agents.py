# agents.py
# LangChain LCEL chains for agent and reflection LLM calls.

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from config import AGENT_MODEL_CONFIG, get_llm

# ── Build chains once at import time ──────────────────────────────────────────

_agent_llm = get_llm("agent")

_agent_prompt = ChatPromptTemplate.from_messages([
    ("system", AGENT_MODEL_CONFIG["system"]),
    ("human", "{prompt_text}"),
])

agent_chain = _agent_prompt | _agent_llm | StrOutputParser()

_reflection_prompt = ChatPromptTemplate.from_messages([
    ("system", AGENT_MODEL_CONFIG["system"]),
    ("human", "{reflection_text}"),
])

reflection_chain = _reflection_prompt | _agent_llm | StrOutputParser()


# ── Public helpers ─────────────────────────────────────────────────────────────

def build_agent_prompt(agent_config: dict, world_state: dict,
                       memories: list, messages: list,
                       pending_intent: str | None) -> str:
    """Assemble the full prompt text for one agent for one round."""
    name = agent_config["name"]
    disposition = agent_config["disposition"]

    lake = world_state["lake"]
    round_num = world_state["round"]
    all_harvests = world_state["observed_harvests"]
    location = world_state["agent_location"]
    dock_agents = world_state["dock_agents"]        # others at dock (not self)
    fishing_agents = world_state["fishing_agents"]  # others fishing (not self)
    prev_locations = world_state.get("prev_locations", {})

    # ── Who is where ──────────────────────────────────────────────────────────
    at_dock_all = sorted(([name] if location == "dock" else []) + dock_agents)
    at_fishing_all = sorted(([name] if location == "fishing" else []) + fishing_agents)

    dock_line = ("At the dock: " + ", ".join(at_dock_all)) if at_dock_all else "Nobody at the dock."
    fishing_line = ("Out fishing: " + ", ".join(at_fishing_all)) if at_fishing_all else "Nobody out fishing."

    # ── Where you are ─────────────────────────────────────────────────────────
    if location == "dock":
        your_situation = "You are at the dock today — you are not fishing this round."
    else:
        your_situation = "You are out on the lake fishing today."

    # ── Last round harvests (annotate zeros from dock stays) ──────────────────
    # "?" means no history yet (round 1) — treat same as no data
    has_data = any(v != "?" for v in all_harvests.values()) if all_harvests else False
    if has_data:
        harvest_lines = []
        for n, v in all_harvests.items():
            if v == "?":
                harvest_lines.append(f"  {n}: unknown")
                continue
            line = f"  {n}: {v} tons"
            try:
                if float(v) == 0 and prev_locations.get(n) == "dock":
                    line += f" ({n} was at the dock last round)"
            except (ValueError, TypeError):
                pass
            harvest_lines.append(line)
        harvest_block = "\n".join(harvest_lines)
    else:
        harvest_block = "  (no data yet — this is the first round)"

    # ── Memory ────────────────────────────────────────────────────────────────
    memory_text = ""
    if memories:
        memory_text = "\nWhat you remember from previous rounds:\n"
        for m in memories:
            memory_text += f"  Round {m['round']}: {m['content']}\n"

    # ── Incoming messages ─────────────────────────────────────────────────────
    messages_text = ""
    if messages:
        messages_text = "\nMessages waiting for you:\n"
        for msg in messages:
            relay = f" (passed on by {msg['relayed_by']})" if msg.get("relayed_by") else ""
            messages_text += f"  {msg['from']}{relay}: \"{msg['content']}\"\n"

    # ── Pending intent reminder ───────────────────────────────────────────────
    intent_text = ""
    if pending_intent:
        intent_text = (
            f"\nReminder: Last round you wanted to say something but couldn't. "
            f"({pending_intent})\n"
        )

    return f"""{disposition}

---

Round {round_num}.
Lake: {lake['current']} tons remaining (was {lake['previous']} last round). Condition: {lake['status']}.

{dock_line}
{fishing_line}

{your_situation}

Last round's harvests:
{harvest_block}
{memory_text}{messages_text}{intent_text}
Given what you observe right now, what do you do?

You may:
- Say something to the group (everyone at the dock will hear — you need to be at the dock too)
- Say something to a specific person (only if you are both at the dock right now; otherwise you will have to wait until you are both there)
- Say something only to yourself (internal reflection, nobody hears)
- Do nothing and simply decide something without saying it out loud

Also decide:
- How many tons to harvest today (between 0 and 12; choose 0 if you are at the dock or decide not to fish)
- Whether to go to the dock after fishing today, or stay out fishing

Write your response as plain prose — no bullet points, no bold text, no headers, no lists. Just speak as a person would."""


def call_agent_llm(prompt: str) -> str:
    """Invoke the agent chain. Returns raw text response."""
    return agent_chain.invoke({"prompt_text": prompt})


def call_reflection_llm(agent_name: str, disposition: str,
                         recent_memories: list) -> str:
    """Triggered by threshold events. Returns an internal reflection string."""
    memory_text = "\n".join(
        [f"  Round {m['round']}: {m['content']}" for m in recent_memories[-5:]]
    )

    text = f"""{disposition}

Based on your recent experiences:
{memory_text}

In one or two plain sentences, what do you privately believe is happening?
What, if anything, do you think should change?
No formatting, no bullet points — just your private thought in plain prose."""

    return reflection_chain.invoke({"reflection_text": text})
