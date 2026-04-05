# simulation.py
# FisherySimulation — world state holder + LangGraph round pipeline.
#
# The LangGraph StateGraph models one simulation round as a sequence of
# named nodes. Each node receives the full RoundState, performs one
# well-defined step, and returns the keys it modified.
#
# Round pipeline:
#   prepare_round → invoke_agents → apply_world → route_speech
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

from config import WORLD_CONFIG, AGENTS
from world import Lake
from memory import MemoryManager, MessageRouter
from agents import build_agent_prompt, call_agent_llm, call_reflection_llm
from extractor import extract_decision
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

    # ── Node 4: route_speech ──────────────────────────────────────────────────
    def route_speech(state: RoundState) -> dict:
        """
        Enforce dock-only communication, enqueue messages, write memories.
        Agents who are fishing cannot speak to anyone this round.
        Pending intents (wanted to speak but couldn't) are written as observations.
        """
        round_num = state["round_num"]
        dock_agents = state["dock_agents"]
        # All agents currently at dock (used as participant list for GROUP)
        conversations: list[dict] = []

        for agent_cfg in AGENTS:
            name = agent_cfg["name"]
            location = sim.locations[name]
            decision = state["decisions"][name]
            speech_type = decision.get("speech_type", "SILENT")
            message = decision.get("message")
            addressee = decision.get("addressee")
            is_norm = decision.get("norm_signal", False)
            pending_intent = decision.get("pending_intent")

            # ── RULE: only dock agents can speak ──────────────────────────────
            if location == "fishing" and speech_type in ("GROUP", "DIRECT"):
                # Agent is out fishing — can't speak; convert to pending intent
                if message:
                    target = addressee if speech_type == "DIRECT" else "everyone"
                    intent_note = (
                        f"Wanted to say to {target}: \"{message}\" "
                        f"— but was out fishing, not at the dock."
                    )
                    sim.memory.write(name, round_num, "unresolved_intent",
                                     intent_note, salience="normal")
                    sim.pending_intents[name] = intent_note
                speech_type = "SILENT"

            # ── GROUP speech (dock agents only) ───────────────────────────────
            if speech_type == "GROUP" and message and name in dock_agents:
                sim.router.enqueue(name, "GROUP", message, round_num, True)
                conversations.append({
                    "from": name,
                    "to": "GROUP",
                    "participants": dock_agents,   # who was present to hear this
                    "content": message,
                    "round": round_num,
                    "norm_signal": is_norm,
                    "delivered": True,
                })
                sim.memory.write(name, round_num, "self_said",
                                 f"You said to everyone at the dock: \"{message}\"")
                for other in dock_agents:
                    if other != name:
                        sim.memory.write(
                            other, round_num, "heard_group",
                            f"{name} said to everyone at the dock: \"{message}\"",
                            salience="high" if is_norm else "normal",
                        )

            # ── DIRECT speech (both must be at dock) ──────────────────────────
            elif speech_type == "DIRECT" and message and addressee:
                co_present = name in dock_agents and addressee in dock_agents
                sim.router.enqueue(name, addressee, message, round_num, co_present)
                conversations.append({
                    "from": name,
                    "to": addressee,
                    "participants": [name, addressee],
                    "content": message,
                    "round": round_num,
                    "norm_signal": is_norm,
                    "delivered": co_present,
                })
                sim.memory.write(name, round_num, "self_said",
                                 f"You said to {addressee}: \"{message}\"")
                if co_present:
                    sim.memory.write(
                        addressee, round_num, "heard_direct",
                        f"{name} said to you directly: \"{message}\"",
                        salience="high" if is_norm else "normal",
                    )
                elif name in dock_agents:
                    # Wanted to speak directly but addressee is fishing
                    intent_note = (
                        f"Wanted to speak to {addressee} directly but they were out fishing."
                    )
                    sim.memory.write(name, round_num, "unresolved_intent",
                                     intent_note, salience="normal")
                    sim.pending_intents[name] = (
                        decision.get("pending_intent") or intent_note
                    )

            # ── Write pending_intent extracted by LLM as observation ──────────
            # (separate from the dock-enforcement intents above)
            if pending_intent and speech_type not in ("GROUP", "DIRECT"):
                sim.memory.write(name, round_num, "unresolved_intent",
                                 f"Intended to say: {pending_intent}",
                                 salience="normal")

        return {"conversations": conversations}

    # ── Node 5: write_memories ────────────────────────────────────────────────
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

    # ── Node 6: check_reflections ─────────────────────────────────────────────
    def check_reflections(state: RoundState) -> dict:
        """Trigger crisis reflections if lake dropped >15% this round."""
        round_num = state["round_num"]
        hist = sim.lake.history
        prev = hist[-2] if len(hist) >= 2 else sim.lake.stock
        drop_pct = ((prev - sim.lake.stock) / prev * 100) if prev > 0 else 0

        if drop_pct > 15:
            logger.info(f"  Lake dropped {drop_pct:.1f}% — triggering reflections")
            for agent_cfg in AGENTS:
                name = agent_cfg["name"]
                recent = sim.memory.get_prompt_memories(name, 5, [])
                reflection = call_reflection_llm(name, agent_cfg["disposition"], recent)
                sim.memory.write(name, round_num, "reflection",
                                 reflection, salience="high")
        return {}

    # ── Node 7: update_norms ──────────────────────────────────────────────────
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

    # ── Node 8: export_state ──────────────────────────────────────────────────
    def export_state(state: RoundState) -> dict:
        """Update agent locations; write JSON state files for the UI."""
        round_num = state["round_num"]

        # Build raw_decisions structure expected by StateExporter
        raw_decisions = {
            name: {
                "raw_prompt": state["raw_prompts"].get(name, ""),
                "raw": state["raw_responses"].get(name, ""),
                "decision": state["decisions"][name],
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

    graph.add_node("prepare_round",     prepare_round)
    graph.add_node("invoke_agents",     invoke_agents)
    graph.add_node("apply_world",       apply_world)
    graph.add_node("route_speech",      route_speech)
    graph.add_node("write_memories",    write_memories)
    graph.add_node("check_reflections", check_reflections)
    graph.add_node("update_norms",      update_norms)
    graph.add_node("export_state",      export_state)

    graph.set_entry_point("prepare_round")
    graph.add_edge("prepare_round",     "invoke_agents")
    graph.add_edge("invoke_agents",     "apply_world")
    graph.add_edge("apply_world",       "route_speech")
    graph.add_edge("route_speech",      "write_memories")
    graph.add_edge("write_memories",    "check_reflections")
    graph.add_edge("check_reflections", "update_norms")
    graph.add_edge("update_norms",      "export_state")
    graph.add_edge("export_state",      END)

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
        self._run_round()

    def run(self):
        self.running = True
        logger.info("Simulation started.")
        for round_num in range(self.current_round + 1, WORLD_CONFIG["rounds_total"] + 1):
            while self.paused:
                time.sleep(0.5)
            self.current_round = round_num
            self._run_round()
            time.sleep(self.round_delay)
        self.running = False
        logger.info("Simulation complete.")

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
        }
        self._round_graph.invoke(initial)
