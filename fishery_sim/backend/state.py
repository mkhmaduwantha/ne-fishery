# state.py
import json
from pathlib import Path

_SEP  = "=" * 80
_DASH = "-" * 60


class StateExporter:
    def __init__(self, state_path: str, log_path: str):
        self.state_path   = Path(state_path)
        self.log_path     = Path(log_path)
        self.raw_log_path = self.state_path.parent / "raw_llm_log.txt"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.full_log = []

    # ── helpers ───────────────────────────────────────────────────────────────

    def _block(self, label: str, text: str) -> str:
        return f"{label}\n{text.strip() if text else '(empty)'}\n"

    def _append_raw_log(self, text: str):
        with open(self.raw_log_path, "a", encoding="utf-8") as f:
            f.write(text)

    # ── main write ────────────────────────────────────────────────────────────

    def write_round(self, round_num, lake, agents, locations,
                    actual_harvests, harvest_history, conversations,
                    norm_tracker, raw_decisions):

        agent_states = []
        raw_log_lines = [f"\n{_SEP}\nROUND {round_num}\n{_SEP}\n"]

        for agent_cfg in agents:
            name     = agent_cfg["name"]
            decision = raw_decisions[name]["decision"]

            agent_states.append({
                "name":               name,
                "location":           locations[name],
                "harvest":            actual_harvests.get(name, 0),
                "harvest_history":    harvest_history[name],
                "last_speech": {
                    "type":        decision.get("speech_type", "SILENT"),
                    "addressee":   decision.get("addressee"),
                    "content":     decision.get("message"),
                    "norm_signal": decision.get("norm_signal", False),
                },
                "reflect":            decision.get("reflect", ""),
                "raw_prompt":         raw_decisions[name].get("raw_prompt", ""),
                "raw_response":       raw_decisions[name].get("raw", ""),
                "raw_extractor_prompt": decision.get("_raw_extractor_prompt", ""),
                "raw_extractor":      decision.get("_raw_extractor", ""),
                "conv_turns":         raw_decisions[name].get("conv_turns", []),
            })

            # ── decision phase log entry ──────────────────────────────────────
            loc = raw_decisions[name].get("location_this_round", "fishing")
            phase_label = "DOCK — Decision Phase" if loc == "dock" else "FISHING PHASE"
            raw_log_lines.append(
                f"\n{_DASH}\n{name}  [{phase_label}]\n{_DASH}\n"
            )
            raw_log_lines.append(self._block(
                "PROMPT → Agent LLM:",
                raw_decisions[name].get("raw_prompt", ""),
            ))
            raw_log_lines.append(self._block(
                "RESPONSE ← Agent LLM:",
                raw_decisions[name].get("raw", ""),
            ))
            raw_log_lines.append(self._block(
                "PROMPT → Extractor LLM:",
                decision.get("_raw_extractor_prompt", ""),
            ))
            raw_log_lines.append(self._block(
                "RESPONSE ← Extractor LLM:",
                decision.get("_raw_extractor", ""),
            ))

        # ── conversation turns — logged in execution order ────────────────────
        # Execution order: turn 1 (all agents in agent order), turn 2, ...
        all_conv_turns = {
            name: raw_decisions[name].get("conv_turns", [])
            for agent_cfg in agents
            for name in [agent_cfg["name"]]
        }
        max_turn = max(
            (t["turn"] for turns in all_conv_turns.values() for t in turns),
            default=0,
        )
        for turn_num in range(1, max_turn + 1):
            for agent_cfg in agents:
                name = agent_cfg["name"]
                t = next(
                    (x for x in all_conv_turns.get(name, []) if x["turn"] == turn_num),
                    None,
                )
                if t is None:
                    continue
                raw_log_lines.append(
                    f"\n{_DASH}\n{name}  [DOCK CONVERSATION — Turn {t['turn']}]\n{_DASH}\n"
                )
                raw_log_lines.append(self._block(
                    "PROMPT → Agent LLM (conv):",
                    t.get("prompt", ""),
                ))
                raw_log_lines.append(self._block(
                    "RESPONSE ← Agent LLM (conv):",
                    t.get("raw", ""),
                ))
                raw_log_lines.append(self._block(
                    "PROMPT → Extractor LLM (conv):",
                    t.get("extractor_prompt", ""),
                ))
                raw_log_lines.append(self._block(
                    "RESPONSE ← Extractor LLM (conv):",
                    t.get("extractor", ""),
                ))

        self._append_raw_log("\n".join(raw_log_lines))

        # ── JSON state files ──────────────────────────────────────────────────
        state = {
            "round":        round_num,
            "total_rounds": 30,
            "lake": {
                "current": lake.stock,
                "max":     lake.max_stock,
                "history": lake.history,
                "status":  lake.get_status(),
            },
            "agents":       agent_states,
            "conversations": conversations,
            "norm_tracker": norm_tracker,
        }

        with open(self.state_path, "w") as f:
            json.dump(state, f, indent=2)

        self.full_log.append(state)
        with open(self.log_path, "w") as f:
            json.dump(self.full_log, f, indent=2)
