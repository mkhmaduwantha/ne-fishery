# memory.py
import json
from datetime import datetime
from pathlib import Path


class MemoryManager:
    def __init__(self, agent_names: list, data_dir: str):
        self.memories = {name: [] for name in agent_names}
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def write(self, agent: str, round_num: int, entry_type: str,
              content: str, salience: str = "normal"):
        """
        entry_type: observed | self_said | heard_group | heard_direct |
                    reflection | unresolved_intent | second_hand
        salience: normal | high
        """
        entry = {
            "round": round_num,
            "type": entry_type,
            "content": content,
            "salience": salience,
            "timestamp": datetime.now().isoformat()
        }
        self.memories[agent].append(entry)
        self._save_agent(agent)

    def get_prompt_memories(self, agent: str, window: int,
                            salience_types: list) -> list:
        """
        Returns last `window` memories, always including high-salience entries.
        """
        all_mem = self.memories[agent]
        high_sal = [m for m in all_mem
                    if m["salience"] == "high" or m["type"] in salience_types]
        recent = all_mem[-window:]

        # Merge, deduplicate, sort by round
        combined = {id(m): m for m in high_sal + recent}
        return sorted(combined.values(), key=lambda x: x["round"])

    def get_full_history(self, agent: str) -> list:
        return self.memories[agent]

    def _save_agent(self, agent: str):
        path = self.data_dir / f"{agent}.json"
        with open(path, "w") as f:
            json.dump(self.memories[agent], f, indent=2)

    def load_all(self):
        """Load persisted memories on restart."""
        for path in self.data_dir.glob("*.json"):
            name = path.stem
            if name in self.memories:
                with open(path) as f:
                    self.memories[name] = json.load(f)


class MessageRouter:
    def __init__(self):
        self.pending = []   # Messages not yet delivered

    def enqueue(self, from_agent: str, to: str, content: str,
                round_num: int, co_present: bool):
        """
        to: agent name | "GROUP"
        co_present: whether sender and recipient are at same location
        """
        msg = {
            "from": from_agent,
            "to": to,
            "content": content,
            "round": round_num,
            "delivered": co_present or to == "GROUP",
            "relayed_by": None
        }
        self.pending.append(msg)
        return msg

    def get_messages_for(self, agent: str, current_round: int) -> list:
        """Get all delivered messages addressed to this agent or GROUP."""
        return [
            m for m in self.pending
            if m["delivered"] and
            (m["to"] == agent or m["to"] == "GROUP") and
            m["round"] == current_round - 1  # Previous round's messages
        ]

    def try_relay(self, held_for: str, relay_agent: str,
                  relay_location: str, target_location: str) -> list:
        """
        If relay_agent and held_for agent are now co-present,
        deliver previously undelivered messages.
        """
        relayed = []
        if relay_location == target_location:
            for msg in self.pending:
                if not msg["delivered"] and msg["to"] == held_for:
                    msg["delivered"] = True
                    msg["relayed_by"] = relay_agent
                    relayed.append(msg)
        return relayed
