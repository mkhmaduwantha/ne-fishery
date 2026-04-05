# Fishery Norm Entrepreneurship Simulation

A multi-agent simulation of fishermen sharing a common-pool resource (a lake), studying how informal norms emerge spontaneously through agent interaction.

## Setup

```bash
cd fishery_sim

# Install dependencies
pip install -r requirements.txt

# Create .env file with your Anthropic API key
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Run the server (from the backend directory)
cd backend
python server.py
```

Then open http://localhost:5000 in your browser.

## Controls

- **START** — Begin the 30-round simulation
- **PAUSE** — Freeze after the current round completes
- **RESUME** — Continue from pause
- **STEP** — Run exactly one round (only when paused)
- **SPEED** — Slider to control delay between rounds (0.5s–10s)

## Architecture

- `backend/config.py` — All parameters, agent dispositions, model configs
- `backend/agents.py` — Prompt builder + Claude Opus LLM caller
- `backend/extractor.py` — Structured decision extraction (Claude Haiku)
- `backend/world.py` — Lake regeneration model
- `backend/memory.py` — Per-agent memory + message routing
- `backend/simulation.py` — Main round loop (parallelised agent calls)
- `backend/state.py` — JSON state exporter
- `backend/server.py` — Flask REST server
- `frontend/App.jsx` — React single-file UI

## Data Output

All simulation data is saved to `backend/data/`:
- `current_state.json` — Current round state (polled by UI)
- `full_log.json` — Complete round-by-round history
- `agent_histories/[Name].json` — Per-agent memory logs

## Research Notes

- Agents are never told rules, quotas, or enforcement mechanisms
- Norms emerge purely from agent language, memory, and social interaction
- The dock is an opportunistic meeting point — not guaranteed
- Communication is always a choice — SILENT is always valid
- `norm_signal: true` in extracted decisions flags norm-like language
- The REFLECT field captures internal framing work (shown in purple in UI)
