# state.py
import json
from pathlib import Path


class StateExporter:
    def __init__(self, state_path: str, log_path: str):
        self.state_path = Path(state_path)
        self.log_path = Path(log_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.full_log = []

    def write_round(self, round_num, lake, agents, locations,
                    actual_harvests, harvest_history, conversations,
                    norm_tracker, raw_decisions):

        agent_states = []
        for agent_cfg in agents:
            name = agent_cfg["name"]
            decision = raw_decisions[name]["decision"]
            agent_states.append({
                "name": name,
                "location": locations[name],
                "harvest": actual_harvests.get(name, 0),
                "harvest_history": harvest_history[name],
                "last_speech": {
                    "type": decision.get("speech_type", "SILENT"),
                    "addressee": decision.get("addressee"),
                    "content": decision.get("message"),
                    "norm_signal": decision.get("norm_signal", False)
                },
                "reflect": decision.get("reflect", ""),
                "raw_prompt": raw_decisions[name].get("raw_prompt", ""),
                "raw_response": raw_decisions[name].get("raw", ""),
                "raw_extractor_prompt": decision.get("_raw_extractor_prompt", ""),
                "raw_extractor": decision.get("_raw_extractor", ""),
            })

        state = {
            "round": round_num,
            "total_rounds": 30,
            "lake": {
                "current": lake.stock,
                "max": lake.max_stock,
                "history": lake.history,
                "status": lake.get_status()
            },
            "agents": agent_states,
            "conversations": conversations,
            "norm_tracker": norm_tracker
        }

        with open(self.state_path, "w") as f:
            json.dump(state, f, indent=2)

        self.full_log.append(state)
        with open(self.log_path, "w") as f:
            json.dump(self.full_log, f, indent=2)
