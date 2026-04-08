# agents.py
# LangChain LCEL chains for agent LLM calls.
# Two prompt builders:
#   build_agent_prompt         — fishing phase (harvest + location decision)
#   build_conversation_prompt  — dock conversation phase (one turn in the dialogue)

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from config import AGENT_MODEL_CONFIG, get_llm

# ── Build chain once at import time ───────────────────────────────────────────

_agent_llm = get_llm("agent")

_agent_prompt = ChatPromptTemplate.from_messages([
    ("system", AGENT_MODEL_CONFIG["system"]),
    ("human", "{prompt_text}"),
])

agent_chain = _agent_prompt | _agent_llm | StrOutputParser()


# ── Fishing-phase prompt ───────────────────────────────────────────────────────

def build_agent_prompt(agent_config: dict, world_state: dict,
                       memories: list, messages: list,
                       pending_intent: str | None) -> str:
    """
    Prompt for the fishing phase of a round.
    Dock agents: only decide next_location (harvest forced to 0).
    Fishing agents: decide harvest + next_location + any pending speech intent.
    Conversation at the dock happens in a separate phase.
    """
    name = agent_config["name"]
    disposition = agent_config["disposition"]

    lake = world_state["lake"]
    round_num = world_state["round"]
    all_harvests = world_state["observed_harvests"]
    location = world_state["agent_location"]
    dock_agents = world_state["dock_agents"]
    fishing_agents = world_state["fishing_agents"]
    prev_locations = world_state.get("prev_locations", {})

    # ── Who is where ──────────────────────────────────────────────────────────
    at_dock_all = sorted(([name] if location == "dock" else []) + dock_agents)
    at_fishing_all = sorted(([name] if location == "fishing" else []) + fishing_agents)

    dock_line    = ("At the dock: "    + ", ".join(at_dock_all))    if at_dock_all    else "Nobody at the dock."
    fishing_line = ("Out fishing: "   + ", ".join(at_fishing_all)) if at_fishing_all else "Nobody out fishing."

    # ── Last round harvests ───────────────────────────────────────────────────
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
    _COMM_TYPES = {"heard_group", "heard_direct", "second_hand"}
    valid_memories = [
        m for m in memories
        if m["type"] not in _COMM_TYPES or m.get("salience") != "undelivered"
    ]
    memory_text = ""
    if valid_memories:
        memory_text = "\nWhat you remember from previous rounds:\n"
        for m in valid_memories:
            memory_text += f"  Round {m['round']}: {m['content']}\n"

    # ── Messages heard at dock last round ─────────────────────────────────────
    messages_text = ""
    if messages:
        messages_text = "\nMessages you heard at the dock last round:\n"
        for msg in messages:
            relay = f" (passed on by {msg['relayed_by']})" if msg.get("relayed_by") else ""
            to_label = "to everyone" if msg["to"] == "GROUP" else "to you"
            messages_text += f"  {msg['from']}{relay} ({to_label}): \"{msg['content']}\"\n"

    # ── Pending intent reminder ───────────────────────────────────────────────
    intent_text = ""
    if pending_intent:
        intent_text = (
            f"\nReminder: Last round you wanted to say something but couldn't. "
            f"({pending_intent})\n"
        )

    # ── Branch: dock vs fishing ───────────────────────────────────────────────
    if location == "dock":
        situation = (
            "You are at the dock today — you are not fishing this round. "
            "Shortly you will have a chance to talk with the others at the dock."
        )
        decision_block = (
            "For now, just decide: will you stay at the dock again next round, "
            "or go out fishing tomorrow? "
            "Your harvest today is zero."
        )
    else:
        situation = "You are out on the lake fishing today."
        decision_block = (
            "Decide how many tons to harvest today (0 to 12).\n"
            "Also decide: will you go to the dock after fishing today, "
            "or stay out on the water tomorrow?\n"
            "If you wanted to say something to someone at the dock, "
            "note that intention — you may get a chance when you arrive."
        )

    return f"""{disposition}

---

Round {round_num}.
Lake: {lake['current']} tons remaining (was {lake['previous']} last round). Condition: {lake['status']}.

{dock_line}
{fishing_line}

{situation}

Last round's harvests:
{harvest_block}
{memory_text}{messages_text}{intent_text}
{decision_block}
{"" if round_num == 1 else """
Before responding, consider: what did you actually observe this round, and does anything you see change what you plan to do?
"""}
Then write what is genuinely on your mind — your reasoning, your concerns, your decision. Not dialogue, not atmosphere. Just your actual thinking and what you choose to do."""


# ── Dock conversation-turn prompt ─────────────────────────────────────────────

def build_conversation_prompt(agent_config: dict, round_num: int,
                               lake_status: str, dock_agents: list[str],
                               transcript: list[dict],
                               pending_intent: str | None,
                               memories: list | None = None) -> str:
    """
    Prompt for one turn of the dock conversation phase.
    transcript: list of {from, to, content} spoken so far this round at the dock.
    memories: recent memory entries to give the agent context.
    """
    name = agent_config["name"]
    disposition = agent_config["disposition"]
    others = [n for n in dock_agents if n != name]

    # Format transcript
    if transcript:
        transcript_lines = []
        for t in transcript:
            to_label = "to everyone" if t["to"] == "GROUP" else f"to {t['to']}"
            transcript_lines.append(f"  {t['from']} ({to_label}): \"{t['content']}\"")
        transcript_text = "\n".join(transcript_lines)
    else:
        transcript_text = "  (nothing has been said yet)"

    others_text = ", ".join(others) if others else "nobody else"

    intent_text = ""
    if pending_intent:
        intent_text = f"\nYou had something you wanted to say: {pending_intent}\n"

    # Recent memories / observations
    _COMM_TYPES = {"heard_group", "heard_direct", "second_hand"}
    valid_memories = [
        m for m in (memories or [])
        if m["type"] not in _COMM_TYPES or m.get("salience") != "undelivered"
    ]
    memory_text = ""
    if valid_memories:
        memory_text = "\nWhat you remember from previous rounds:\n"
        for m in valid_memories:
            memory_text += f"  Round {m['round']}: {m['content']}\n"

    return f"""{disposition}

---

Round {round_num} — dock conversation.
Lake condition: {lake_status}.
Others at the dock with you: {others_text}.
{intent_text}{memory_text}
What has been said at the dock so far this round:
{transcript_text}

Given what you have just heard, what do you say next — if anything?

You may speak to everyone, speak to one person directly, or say nothing.
Keep it brief — one or two sentences at most. If you have nothing genuine to add, say nothing.
{"" if round_num == 1 else """
Before responding, consider: is there anything you actually want to say or find out, based on what you heard?
"""}
Then write only what you would genuinely say out loud — or nothing at all. Not atmosphere, not performance. Just what you would actually say."""


def call_agent_llm(prompt: str) -> str:
    """Invoke the agent chain. Returns raw text response."""
    return agent_chain.invoke({"prompt_text": prompt})
