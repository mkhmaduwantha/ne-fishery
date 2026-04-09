"""
export_readable.py
Reads full_log.json and writes a clean, human-readable summary to
data/readable_log.txt showing:
  - Lake status per round
  - Each agent's reasoning (raw response) and harvest
  - Dock conversations (who said what to whom)

Usage:
    python3 export_readable.py
    python3 export_readable.py --log data/full_log.json --out data/readable_log.txt
"""

import json
import argparse
from pathlib import Path

_SEP  = "=" * 72
_DASH = "-" * 48
AGENT_ORDER = ["Ana", "Marco", "Sofia", "James", "Yuki"]


def agent_sort_key(name):
    try:
        return AGENT_ORDER.index(name)
    except ValueError:
        return 999


def format_round(round_state: dict) -> str:
    lines = []
    rnum  = round_state["round"]
    lake  = round_state["lake"]
    agents = round_state["agents"]
    convs  = round_state.get("conversations", [])

    # ── Round header ──────────────────────────────────────────────────────────
    lines.append(_SEP)
    lines.append(f"ROUND {rnum}  |  Lake: {lake['current']}t / {lake['max']}t  ({lake['status'].upper()})")
    lines.append(_SEP)

    # ── Harvests summary ──────────────────────────────────────────────────────
    sorted_agents = sorted(agents, key=lambda a: agent_sort_key(a["name"]))
    harvest_parts = [f"{a['name']} {a['harvest']}t" for a in sorted_agents]
    lines.append(f"Harvests: {',  '.join(harvest_parts)}")
    lines.append("")

    # ── Per-agent reasoning ───────────────────────────────────────────────────
    lines.append("DECISIONS")
    lines.append(_DASH)
    for agent in sorted_agents:
        name     = agent["name"]
        harvest  = agent["harvest"]
        response = (agent.get("raw_response") or "").strip()
        location = agent.get("location", "?")
        loc_label = "→ dock" if location == "dock" else "→ fishing"

        lines.append(f"{name}  [{harvest}t harvested]  [{loc_label}]")
        if response:
            # Indent each line of the response
            for line in response.splitlines():
                lines.append(f"  {line}")
        else:
            lines.append("  (no response recorded)")
        lines.append("")

    # ── Dock conversation ─────────────────────────────────────────────────────
    if convs:
        lines.append("DOCK CONVERSATION")
        lines.append(_DASH)
        # Sort by turn, then by order of appearance
        sorted_convs = sorted(convs, key=lambda c: (c.get("turn", 0), convs.index(c)))
        seen_turns = set()
        for conv in sorted_convs:
            turn = conv.get("turn")
            if turn and turn not in seen_turns:
                seen_turns.add(turn)
                lines.append(f"  — Turn {turn} —")
            frm      = conv["from"]
            to       = conv["to"]
            content  = conv.get("content", "").strip()
            is_norm  = conv.get("norm_signal", False)
            norm_tag = "  [NORM PROPOSAL]" if is_norm else ""

            if to == "GROUP":
                audience = "everyone"
            else:
                audience = f"→ {to}"

            lines.append(f"  {frm} ({audience}): \"{content}\"{norm_tag}")
        lines.append("")
    else:
        lines.append("DOCK CONVERSATION")
        lines.append(_DASH)
        lines.append("  (no dock conversation this round)")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Export readable simulation log")
    parser.add_argument("--log", default="data/full_log.json",
                        help="Path to full_log.json")
    parser.add_argument("--out", default="data/readable_log.txt",
                        help="Output text file path")
    args = parser.parse_args()

    log_path = Path(args.log)
    out_path = Path(args.out)

    if not log_path.exists():
        print(f"Error: {log_path} not found.")
        return

    with open(log_path, encoding="utf-8") as f:
        full_log = json.load(f)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("FISHERY SIMULATION — READABLE LOG\n")
        f.write(f"Rounds recorded: {len(full_log)}\n")
        f.write("\n")
        for round_state in full_log:
            f.write(format_round(round_state))
            f.write("\n\n")

    print(f"Written to {out_path}  ({len(full_log)} rounds)")


if __name__ == "__main__":
    main()
