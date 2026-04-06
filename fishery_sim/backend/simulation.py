# simulation.py
# FisherySimulation — world state holder + LangGraph round pipeline.
#
# The LangGraph StateGraph models one simulation round as a sequence of
# named nodes. Each node receives the full RoundState, performs one
# well-defined step, and returns the keys it modified.
#
# Round pipeline:
#   prepare_round → invoke_agents → apply_world
#       → handle_fishing_intents → conversation_phase
#       → write_memories → check_reflections → update_norms → export_state
#
# The FisherySimulation object holds all mutable world state (lake, memory,
# router, etc.). Graph nodes close over a reference to it so they can read
# and mutate world state without it being part of the graph's own state.

import time
import logging
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypedDict, Any

from langgraph.graph import StateGraph, END

from config import WORLD_CONFIG, AGENTS, CONVERSATION_TURNS
from world import Lake
from memory import MemoryManager, MessageRouter
from agents import build_agent_prompt, build_conversation_prompt, call_agent_llm
from extractor import extract_decision, extract_conversation_turn
from state import StateExporter

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_BASE = Path(__file__).parent


# ── Round State ───────────────────────────────────────────────────────────────
# Carried through the LangGraph pipeline for one round.
# World state (lake, memory, etc.) lives on FisherySimulation, not here.

class RoundState(TypedDict):
    round_num: int
    dock_agents: list[str]          # agents at dock at start of round
    raw_prompts: dict[str, str]     # name → prompt sent to agent LLM
    raw_responses: dict[str, str]   # name → raw agent LLM text
    decisions: dict[str, Any]       # name → extracted decision dict (includes _raw_extractor)
    harvests_declared: dict[str, float]
    actual_harvests: dict[str, float]
    conversations: list[dict]       # messages spoken this round
    conv_raw: dict[str, list]       # name → [{turn, prompt, raw, extractor_prompt, extractor}]


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_round_graph(sim: "FisherySimulation"):
    """
    Build and compile the LangGraph StateGraph for one simulation round.
    All nodes close over `sim` to access world state.
    Returns a compiled LangGraph app.
    """

    # ── Node 1: prepare_round ─────────────────────────────────────────────────
    def prepare_round(state: RoundState) -> dict:
        """Determine dock/fishing split; process pending message relays."""
        round_num = state["round_num"]
        dock_agents = [n for n, loc in sim.locations.items() if loc == "dock"]
        logger.info(f"  Dock: {dock_agents or ['(empty)']}")

        # Relay any previously undelivered direct messages
        for msg in sim.router.pending:
            if not msg["delivered"]:
                for dock_agent in dock_agents:
                    relayed = sim.router.try_relay(
                        held_for=msg["to"],
                        relay_agent=dock_agent,
                        relay_location="dock",
                        target_location=sim.locations.get(msg["to"], "fishing"),
                    )
                    for r in relayed:
                        sim.memory.write(
                            r["to"], round_num, "second_hand",
                            f"{r['from']} said (via {r['relayed_by']}): \"{r['content']}\"",
                            salience="high",
                        )

        return {"dock_agents": dock_agents}

    # ── Node 2: invoke_agents ─────────────────────────────────────────────────
    def invoke_agents(state: RoundState) -> dict:
        """
        Call every agent's LLM in parallel (ThreadPoolExecutor).
        Returns raw_responses, decisions, harvests_declared.
        """
        round_num = state["round_num"]
        dock_agents = state["dock_agents"]

        last_harvests = {
            n: (sim.harvest_history[n][-1] if sim.harvest_history[n] else "?")
            for n in sim.agent_names
        }

        fishing_agents = [n for n, loc in sim.locations.items() if loc == "fishing"]

        def _call_one(agent_cfg):
            name = agent_cfg["name"]
            world_state = {
                "round": round_num,
                "lake": {
                    "current": sim.lake.stock,
                    "previous": sim.lake.previous_stock(),
                    "status": sim.lake.get_status(),
                },
                "agent_location": sim.locations[name],
                "dock_agents": [n for n in dock_agents if n != name],
                "fishing_agents": [n for n in fishing_agents if n != name],
                "observed_harvests": last_harvests,
                "prev_locations": sim.prev_locations,
            }
            memories = sim.memory.get_prompt_memories(
                name, 8, ["proposal", "conflict", "agreement", "reflection"]
            )
            messages = sim.router.get_messages_for(name, round_num)
            prompt = build_agent_prompt(
                agent_cfg, world_state, memories, messages,
                sim.pending_intents[name],
            )
            logger.info(f"  [{name}] calling LLM...")
            raw = call_agent_llm(prompt)
            agent_location = sim.locations[name]
            decision = extract_decision(
                name, raw,
                available_at_dock=[n for n in dock_agents if n != name],
                agent_location=agent_location,
            )
            # Enforce: agents at dock are not fishing — harvest must be 0
            if agent_location == "dock":
                decision["harvest"] = 0
            logger.info(f"  [{name}] harvest={decision['harvest']} "
                        f"speech={decision['speech_type']} "
                        f"next={decision['next_location']}")
            return name, prompt, raw, decision

        raw_prompts: dict[str, str] = {}
        raw_responses: dict[str, str] = {}
        decisions: dict[str, Any] = {}
        harvests_declared: dict[str, float] = {}

        with ThreadPoolExecutor(max_workers=len(AGENTS)) as pool:
            futures = {pool.submit(_call_one, cfg): cfg for cfg in AGENTS}
            for future in as_completed(futures):
                cfg = futures[future]
                name = cfg["name"]
                try:
                    name, prompt, raw, decision = future.result()
                    raw_prompts[name] = prompt
                    raw_responses[name] = raw
                    decisions[name] = decision
                    harvests_declared[name] = decision["harvest"]
                    sim.pending_intents[name] = decision.get("pending_intent")
                    if decision.get("reflect"):
                        sim.memory.write(name, round_num, "reflection",
                                         decision["reflect"], salience="normal")
                except Exception as e:
                    logger.error(f"  [{name}] LLM call failed: {e}")
                    raw_prompts[name] = ""
                    raw_responses[name] = ""
                    decisions[name] = {
                        "harvest": 9, "next_location": "fishing",
                        "speech_type": "SILENT", "addressee": None,
                        "message": None, "reflect": "Error in call.",
                        "norm_signal": False, "pending_intent": None,
                        "_raw_extractor": f"[agent call error: {e}]",
                    }
                    harvests_declared[name] = 9

        return {
            "raw_prompts": raw_prompts,
            "raw_responses": raw_responses,
            "decisions": decisions,
            "harvests_declared": harvests_declared,
        }

    # ── Node 3: apply_world ───────────────────────────────────────────────────
    def apply_world(state: RoundState) -> dict:
        """Apply declared harvests to the lake; record actual amounts."""
        actual = sim.lake.apply_harvests(state["harvests_declared"])
        for name, amount in actual.items():
            sim.harvest_history[name].append(amount)
        logger.info(f"  Harvests: {actual} | Lake after: {sim.lake.stock}t")
        return {"actual_harvests": actual}

    # ── Node 4: handle_fishing_intents ───────────────────────────────────────
    def handle_fishing_intents(state: RoundState) -> dict:
        """
        For agents who are out fishing, capture any speech intent they expressed
        as a pending observation. Dock agents' communication happens in
        conversation_phase instead.
        """
        round_num = state["round_num"]
        dock_agents = state["dock_agents"]
        fishing_agents_now = [n for n in sim.agent_names if n not in dock_agents]

        for agent_cfg in AGENTS:
            name = agent_cfg["name"]
            if name not in fishing_agents_now:
                continue
            decision = state["decisions"][name]
            speech_type = decision.get("speech_type", "SILENT")
            message = decision.get("message")
            addressee = decision.get("addressee")
            pending_intent = decision.get("pending_intent")

            if speech_type in ("GROUP", "DIRECT") and message:
                target = addressee if speech_type == "DIRECT" else "everyone"
                intent_note = (
                    f"Wanted to say to {target}: \"{message}\" "
                    f"— but was out fishing, not at the dock."
                )
                sim.memory.write(name, round_num, "unresolved_intent",
                                 intent_note, salience="normal")
                sim.pending_intents[name] = intent_note
            elif pending_intent:
                sim.memory.write(name, round_num, "unresolved_intent",
                                 f"Intended to say: {pending_intent}",
                                 salience="normal")
                sim.pending_intents[name] = pending_intent

        return {}

    # ── Node 5: conversation_phase ────────────────────────────────────────────
    def conversation_phase(state: RoundState) -> dict:
        """
        Multi-turn dock conversation phase.

        All agents currently at the dock participate — next_location only takes
        effect next round. SILENT = listening, not leaving.
        Exits early if no agent speaks in a turn.
        Fishing agents get an observation that a dock conversation occurred.
        """
        round_num = state["round_num"]
        dock_agents = state["dock_agents"]
        conversations: list[dict] = []
        transcript: list[dict] = []
        conv_raw: dict[str, list] = {n: [] for n in sim.agent_names}

        if not dock_agents and not any(
            state["decisions"].get(n, {}).get("next_location") == "dock"
            for n in sim.agent_names if n not in dock_agents
        ):
            return {"conversations": conversations, "conv_raw": conv_raw}

        lake_status = (
            f"{sim.lake.stock}t remaining, condition: {sim.lake.get_status()}"
        )
        # Build conversation participant list based on where each agent ends up:
        #   dock→dock   : was at dock, stays at dock → participates
        #   dock→fishing: was at dock, heads out     → skips conversation
        #   fishing→dock: was fishing, comes in      → participates
        #   fishing→fishing: stays on water          → no conversation
        active_participants: list[str] = []
        skipped: list[str] = []          # dock agents who head out early
        arriving: list[str] = []         # fishing agents who come to dock
        staying_out: list[str] = []      # fishing agents who stay fishing

        for name in sim.agent_names:
            next_loc = state["decisions"].get(name, {}).get("next_location", "fishing")
            was_at_dock = name in dock_agents
            if next_loc == "dock":
                active_participants.append(name)
                if not was_at_dock:
                    arriving.append(name)
            else:
                if was_at_dock:
                    skipped.append(name)
                else:
                    staying_out.append(name)

        # Memory: dock agents who left early
        for name in skipped:
            sim.memory.write(
                name, round_num, "observed",
                "You headed straight out to fish and missed the dock conversation.",
                salience="normal",
            )
        # Memory: remaining dock agents notified of who left / who arrived
        if active_participants:
            if skipped:
                for staying in active_participants:
                    sim.memory.write(
                        staying, round_num, "observed",
                        f"{', '.join(skipped)} left for the water before the conversation.",
                        salience="normal",
                    )
            if arriving:
                for staying in active_participants:
                    if staying not in arriving:
                        sim.memory.write(
                            staying, round_num, "observed",
                            f"{', '.join(arriving)} came in from fishing and joined the dock.",
                            salience="normal",
                        )

        logger.info(
            f"  Conversation phase — active: {active_participants} "
            f"(arriving from sea: {arriving}), skipped: {skipped}, turns: {CONVERSATION_TURNS}"
        )

        if len(active_participants) < 1:
            return {"conversations": conversations, "conv_raw": conv_raw}

        for turn in range(CONVERSATION_TURNS):
            turn_had_speech = False
            logger.info(f"    Turn {turn + 1}/{CONVERSATION_TURNS}")

            # Sequential — each agent sees what was just said before responding.
            # SILENT agents stay and listen; they are NOT removed.
            for agent_cfg in AGENTS:
                name = agent_cfg["name"]
                if name not in active_participants:
                    continue

                memories = sim.memory.get_prompt_memories(
                    name, 8, ["proposal", "conflict", "agreement", "reflection"]
                )
                prompt = build_conversation_prompt(
                    agent_cfg, round_num, lake_status, active_participants,
                    transcript, sim.pending_intents.get(name), memories,
                )
                logger.info(f"      [{name}] conversation turn {turn + 1}...")
                raw = call_agent_llm(prompt)

                decision = extract_conversation_turn(
                    name, raw,
                    available_at_dock=[n for n in active_participants if n != name],
                )

                # Capture raw data for this turn
                conv_raw[name].append({
                    "turn": turn + 1,
                    "prompt": prompt,
                    "raw": raw,
                    "extractor_prompt": decision.get("_raw_extractor_prompt", ""),
                    "extractor": decision.get("_raw_extractor", ""),
                })

                speech_type = decision.get("speech_type", "SILENT")
                message = decision.get("message")
                addressee = decision.get("addressee")
                is_norm = decision.get("norm_signal", False)

                if decision.get("reflect"):
                    sim.memory.write(name, round_num, "reflection",
                                     decision["reflect"], salience="normal")

                # ── GROUP ──────────────────────────────────────────────────────
                if speech_type == "GROUP" and message:
                    transcript.append({"from": name, "to": "GROUP",
                                       "content": message, "turn": turn + 1})
                    turn_had_speech = True
                    sim.router.enqueue(name, "GROUP", message, round_num, True,
                                       participants=list(active_participants))
                    conversations.append({
                        "from": name, "to": "GROUP",
                        "participants": list(active_participants),
                        "content": message, "round": round_num,
                        "turn": turn + 1,
                        "norm_signal": is_norm, "delivered": True,
                    })
                    sim.memory.write(name, round_num, "self_said",
                                     f"You said to everyone at the dock: \"{message}\"")
                    for other in active_participants:
                        if other != name:
                            sim.memory.write(
                                other, round_num, "heard_group",
                                f"{name} said to everyone at the dock: \"{message}\"",
                                salience="high" if is_norm else "normal",
                            )
                    logger.info(f"      [{name}] → GROUP: {message[:60]!r}")

                # ── DIRECT ─────────────────────────────────────────────────────
                elif speech_type == "DIRECT" and message and addressee:
                    if addressee in active_participants:
                        transcript.append({"from": name, "to": addressee,
                                           "content": message, "turn": turn + 1})
                        turn_had_speech = True
                        sim.router.enqueue(name, addressee, message,
                                           round_num, True)
                        # Visible to everyone present at the dock
                        conversations.append({
                            "from": name, "to": addressee,
                            "participants": list(active_participants),
                            "content": message, "round": round_num,
                            "turn": turn + 1,
                            "norm_signal": is_norm, "delivered": True,
                        })
                        sim.memory.write(name, round_num, "self_said",
                                         f"You said to {addressee}: \"{message}\"")
                        sim.memory.write(
                            addressee, round_num, "heard_direct",
                            f"{name} said to you directly: \"{message}\"",
                            salience="high" if is_norm else "normal",
                        )
                        # Bystanders overhear the direct exchange
                        for bystander in active_participants:
                            if bystander in (name, addressee):
                                continue
                            sim.memory.write(
                                bystander, round_num, "heard_group",
                                f"{name} said to {addressee} (you overheard): \"{message}\"",
                                salience="high" if is_norm else "normal",
                            )
                        logger.info(f"      [{name}] → {addressee}: {message[:60]!r}")
                    else:
                        # Addressee is not present (fishing or left early)
                        intent_note = (
                            f"Wanted to speak to {addressee} directly "
                            f"but they were not at the dock."
                        )
                        sim.memory.write(name, round_num, "unresolved_intent",
                                         intent_note, salience="normal")
                        sim.pending_intents[name] = intent_note
                        sim.memory.write(
                            addressee, round_num, "observed",
                            f"{name} wanted to speak to you at the dock "
                            f"but you were not there.",
                            salience="high",
                        )

            # Early exit if nobody spoke this turn
            if not turn_had_speech:
                logger.info(f"    No speech in turn {turn + 1} — ending conversation")
                break

        # Agents who stayed out fishing get a brief observation
        if transcript and staying_out:
            speakers = list({t["from"] for t in transcript})
            for name in staying_out:
                sim.memory.write(
                    name, round_num, "observed",
                    f"While you were out fishing, {', '.join(speakers)} "
                    f"had a conversation at the dock — you did not hear it.",
                    salience="normal",
                )

        return {"conversations": conversations, "conv_raw": conv_raw}

    # ── Node 6: write_memories ────────────────────────────────────────────────
    def write_memories(state: RoundState) -> dict:
        """Write per-agent observation memories for this round."""
        round_num = state["round_num"]
        actual = state["actual_harvests"]
        dock_agents = state["dock_agents"]
        fishing_agents = [n for n in sim.agent_names if n not in dock_agents]

        harvest_summary = ", ".join(
            [f"{n}={actual[n]}t" for n in sim.agent_names]
        )
        dock_summary = (", ".join(dock_agents)) if dock_agents else "nobody"
        fishing_summary = (", ".join(fishing_agents)) if fishing_agents else "nobody"

        for agent_cfg in AGENTS:
            sim.memory.write(
                agent_cfg["name"], round_num, "observed",
                f"Harvests this round: {harvest_summary}. "
                f"Lake now at {sim.lake.stock}t. "
                f"At dock: {dock_summary}. Out fishing: {fishing_summary}.",
            )
        return {}

    # ── Node 7: check_reflections ─────────────────────────────────────────────
    def check_reflections(state: RoundState) -> dict:
        """Trigger crisis reflections if lake dropped >15% this round."""
        round_num = state["round_num"]
        hist = sim.lake.history
        prev = hist[-2] if len(hist) >= 2 else sim.lake.stock
        drop_pct = ((prev - sim.lake.stock) / prev * 100) if prev > 0 else 0

        if drop_pct > 15:
            logger.info(f"  Lake dropped {drop_pct:.1f}% — notable drop, no reflection LLM call")
        return {}

    # ── Node 8: update_norms ──────────────────────────────────────────────────
    def update_norms(state: RoundState) -> dict:
        """Append new norm proposals to the tracker (append-only)."""
        round_num = state["round_num"]
        for conv in state["conversations"]:
            if conv.get("norm_signal"):
                sim.norm_tracker.append({
                    "round": round_num,
                    "proposer": conv["from"],
                    "to": conv["to"],
                    "content": conv["content"],
                    "status": "active",
                    "responses": {},
                })
        return {}

    # ── Node 9: export_state ──────────────────────────────────────────────────
    def export_state(state: RoundState) -> dict:
        """Update agent locations; write JSON state files for the UI."""
        round_num = state["round_num"]

        # Build raw_decisions structure expected by StateExporter
        dock_this_round = set(state["dock_agents"])
        raw_decisions = {
            name: {
                "raw_prompt": state["raw_prompts"].get(name, ""),
                "raw": state["raw_responses"].get(name, ""),
                "decision": state["decisions"][name],
                "conv_turns": state.get("conv_raw", {}).get(name, []),
                "location_this_round": "dock" if name in dock_this_round else "fishing",
            }
            for name in sim.agent_names
        }

        # Save current locations as prev before overwriting
        sim.prev_locations = dict(sim.locations)

        # Update locations for next round
        for agent_cfg in AGENTS:
            name = agent_cfg["name"]
            sim.locations[name] = state["decisions"][name].get(
                "next_location", "fishing"
            )

        sim.exporter.write_round(
            round_num=round_num,
            lake=sim.lake,
            agents=AGENTS,
            locations=sim.locations,
            actual_harvests=state["actual_harvests"],
            harvest_history=sim.harvest_history,
            conversations=state["conversations"],
            norm_tracker=sim.norm_tracker,
            raw_decisions=raw_decisions,
        )
        return {}

    # ── Assemble graph ────────────────────────────────────────────────────────
    graph = StateGraph(RoundState)

    graph.add_node("prepare_round",         prepare_round)
    graph.add_node("invoke_agents",         invoke_agents)
    graph.add_node("apply_world",           apply_world)
    graph.add_node("handle_fishing_intents", handle_fishing_intents)
    graph.add_node("conversation_phase",    conversation_phase)
    graph.add_node("write_memories",        write_memories)
    graph.add_node("check_reflections",     check_reflections)
    graph.add_node("update_norms",          update_norms)
    graph.add_node("export_state",          export_state)

    graph.set_entry_point("prepare_round")
    graph.add_edge("prepare_round",          "invoke_agents")
    graph.add_edge("invoke_agents",          "apply_world")
    graph.add_edge("apply_world",            "handle_fishing_intents")
    graph.add_edge("handle_fishing_intents", "conversation_phase")
    graph.add_edge("conversation_phase",     "write_memories")
    graph.add_edge("write_memories",         "check_reflections")
    graph.add_edge("check_reflections",      "update_norms")
    graph.add_edge("update_norms",           "export_state")
    graph.add_edge("export_state",           END)

    return graph.compile()


# ── Simulation controller ─────────────────────────────────────────────────────

class FisherySimulation:
    def __init__(self):
        self.lake = Lake(WORLD_CONFIG)
        self.agent_names = [a["name"] for a in AGENTS]
        self.memory = MemoryManager(
            self.agent_names, str(_BASE / "data/agent_histories")
        )
        self.router = MessageRouter()
        self.exporter = StateExporter(
            str(_BASE / "data/current_state.json"),
            str(_BASE / "data/full_log.json"),
        )

        # Control
        self.paused = False
        self.running = False
        self.current_round = 0
        self.round_delay = WORLD_CONFIG["round_delay_seconds"]
        self.control_lock = threading.Lock()

        # World state
        self.locations = {name: "fishing" for name in self.agent_names}
        self.prev_locations: dict[str, str] = {}   # locations from previous round
        self.pending_intents = {name: None for name in self.agent_names}
        self.harvest_history = {name: [] for name in self.agent_names}
        self.norm_tracker: list[dict] = []

        # Build the LangGraph round pipeline once
        self._round_graph = build_round_graph(self)

    def pause(self):
        with self.control_lock:
            self.paused = True
            logger.info("Simulation paused.")

    def resume(self):
        with self.control_lock:
            self.paused = False
            logger.info("Simulation resumed.")

    def set_speed(self, delay_seconds: float):
        self.round_delay = max(0.5, min(10.0, delay_seconds))
        logger.info(f"Round delay set to {self.round_delay}s")

    def step(self):
        """Run exactly one round regardless of pause state."""
        self.current_round += 1
        try:
            self._run_round()
        except Exception as e:
            logger.error(f"Round {self.current_round} failed: {e}", exc_info=True)

    def run(self):
        self.running = True
        logger.info("Simulation started.")
        try:
            for round_num in range(self.current_round + 1, WORLD_CONFIG["rounds_total"] + 1):
                while self.paused:
                    time.sleep(0.5)
                self.current_round = round_num
                try:
                    self._run_round()
                except Exception as e:
                    logger.error(f"Round {round_num} failed: {e}", exc_info=True)
                    # Continue to next round rather than dying entirely
                time.sleep(self.round_delay)
        finally:
            self.running = False
            logger.info("Simulation run ended.")

    def _run_round(self):
        round_num = self.current_round
        logger.info(f"=== Round {round_num} | Lake: {self.lake.stock}t "
                    f"({self.lake.get_status()}) ===")

        # Seed the initial round state and let the graph run it end-to-end
        initial: RoundState = {
            "round_num": round_num,
            "dock_agents": [],
            "raw_prompts": {},
            "raw_responses": {},
            "decisions": {},
            "harvests_declared": {},
            "actual_harvests": {},
            "conversations": [],
            "conv_raw": {},
        }
        self._round_graph.invoke(initial)
