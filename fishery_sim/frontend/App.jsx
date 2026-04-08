// App.jsx — Fishery Norm Entrepreneurship Simulation UI
// Dark maritime research dashboard

const { useState, useEffect, useCallback, useRef } = React;

// ─── Constants ──────────────────────────────────────────────────────────────

const AGENT_COLORS = {
  Ana:   { bg: "bg-violet-500",  text: "text-violet-400",  border: "border-violet-500",  hex: "#8b5cf6" },
  Marco: { bg: "bg-amber-500",   text: "text-amber-400",   border: "border-amber-500",   hex: "#f59e0b" },
  Sofia: { bg: "bg-teal-500",    text: "text-teal-400",    border: "border-teal-500",    hex: "#14b8a6" },
  James: { bg: "bg-sky-500",     text: "text-sky-400",     border: "border-sky-500",     hex: "#0ea5e9" },
  Yuki:  { bg: "bg-rose-500",    text: "text-rose-400",    border: "border-rose-500",    hex: "#f43f5e" },
};

const MEMORY_TYPE_STYLES = {
  observed:          { label: "observed",    color: "text-gray-400",    bg: "bg-gray-800" },
  self_said:         { label: "self",        color: "text-blue-400",    bg: "bg-blue-950" },
  heard_group:       { label: "group",       color: "text-teal-400",    bg: "bg-teal-950" },
  heard_direct:      { label: "direct",      color: "text-yellow-400",  bg: "bg-yellow-950" },
  reflection:        { label: "reflect",     color: "text-purple-400",  bg: "bg-purple-950" },
  second_hand:       { label: "relay",       color: "text-orange-400",  bg: "bg-orange-950" },
  unresolved_intent: { label: "pending",     color: "text-pink-400",    bg: "bg-pink-950" },
};

// ─── API helpers ─────────────────────────────────────────────────────────────

async function apiControl(action, extra = {}) {
  await fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...extra }),
  });
}

// ─── Lake Health Bar ──────────────────────────────────────────────────────────

function LakeHealthBar({ lake }) {
  if (!lake || !lake.max) return null;
  const pct = Math.max(0, Math.min(100, (lake.current / lake.max) * 100));

  let barColor = "bg-teal-500";
  let textColor = "text-teal-400";
  let pulse = false;

  if (pct <= 20) { barColor = "bg-red-500"; textColor = "text-red-400"; pulse = true; }
  else if (pct <= 40) { barColor = "bg-orange-500"; textColor = "text-orange-400"; }
  else if (pct <= 70) { barColor = "bg-amber-500"; textColor = "text-amber-400"; }

  return (
    <div className="flex items-center gap-3 flex-1">
      <span className={`text-xs font-mono ${textColor} whitespace-nowrap`}>
        LAKE {lake.current?.toFixed(1)}t / {lake.max}t
      </span>
      <div className="flex-1 h-3 bg-gray-800 rounded-full overflow-hidden border border-gray-700">
        <div
          className={`h-full rounded-full transition-all duration-1000 ${barColor} ${pulse ? "pulse-red" : ""}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`text-xs font-mono uppercase tracking-wider ${textColor}`}>
        {lake.status}
      </span>
    </div>
  );
}

// ─── Controls ────────────────────────────────────────────────────────────────

function Controls({ status, onAction }) {
  const [speed, setSpeed] = useState(3);
  const { running, paused, round, total_rounds } = status;

  const handleSpeed = (v) => {
    setSpeed(v);
    apiControl("speed", { value: v });
  };

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {!running && (
        <button
          onClick={() => onAction("start")}
          className="px-3 py-1.5 bg-teal-700 hover:bg-teal-600 text-teal-100 text-xs rounded border border-teal-600 transition-colors"
        >
          ▶ START
        </button>
      )}
      {running && !paused && (
        <button
          onClick={() => onAction("pause")}
          className="px-3 py-1.5 bg-amber-700 hover:bg-amber-600 text-amber-100 text-xs rounded border border-amber-600 transition-colors"
        >
          ⏸ PAUSE
        </button>
      )}
      {running && paused && (
        <button
          onClick={() => onAction("resume")}
          className="px-3 py-1.5 bg-teal-700 hover:bg-teal-600 text-teal-100 text-xs rounded border border-teal-600 transition-colors"
        >
          ▶ RESUME
        </button>
      )}
      {paused && (
        <button
          onClick={() => onAction("step")}
          className="px-3 py-1.5 bg-sky-700 hover:bg-sky-600 text-sky-100 text-xs rounded border border-sky-600 transition-colors"
        >
          ⏭ STEP
        </button>
      )}
      <div className="flex items-center gap-2 ml-2">
        <span className="text-xs text-gray-500">SPEED</span>
        <input
          type="range" min="0.5" max="10" step="0.5" value={speed}
          onChange={e => handleSpeed(parseFloat(e.target.value))}
          className="w-20 accent-teal-500"
        />
        <span className="text-xs text-gray-400 font-mono">{speed}s</span>
      </div>
      <span className="text-xs text-gray-500 font-mono ml-2">
        R {round || 0}/{total_rounds || 30}
      </span>
      {running && !paused && (
        <span className="text-xs text-teal-400 animate-pulse">● LIVE</span>
      )}
      {paused && (
        <span className="text-xs text-amber-400">⏸ PAUSED</span>
      )}
    </div>
  );
}

// ─── Zone Map ─────────────────────────────────────────────────────────────────

function ZoneMap({ agents, onAgentClick }) {
  const fishingAgents = agents.filter(a => a.location === "fishing");
  const dockAgents = agents.filter(a => a.location === "dock");

  const AgentDot = ({ agent }) => {
    const colors = AGENT_COLORS[agent.name] || { bg: "bg-gray-500", text: "text-gray-400", hex: "#888" };
    const isNorm = agent.last_speech?.norm_signal;
    return (
      <div
        className={`agent-dot flex flex-col items-center gap-1 cursor-pointer`}
        onClick={() => onAgentClick(agent.name)}
        title={`${agent.name} — ${agent.harvest}t harvested`}
      >
        <div className={`w-10 h-10 rounded-full ${colors.bg} flex items-center justify-center text-white text-xs font-bold shadow-lg ${isNorm ? "ring-2 ring-teal-400 norm-glow" : ""}`}>
          {agent.name[0]}
        </div>
        <span className={`text-xs ${colors.text} font-mono`}>{agent.name}</span>
        <span className="text-xs text-gray-500 font-mono">{agent.harvest || 0}t</span>
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-3">
      {/* Fishing zone */}
      <div className="border border-sky-900 rounded-lg bg-navy-800 p-3" style={{ minHeight: 120 }}>
        <div className="text-xs text-sky-600 font-mono tracking-widest mb-3 uppercase">⚓ Fishing Zone</div>
        <div className="flex flex-wrap gap-4 justify-center">
          {fishingAgents.length === 0 && (
            <span className="text-xs text-gray-600 italic">no agents fishing</span>
          )}
          {fishingAgents.map(a => <AgentDot key={a.name} agent={a} />)}
        </div>
      </div>

      {/* Dock zone */}
      <div className="border border-amber-900 rounded-lg bg-navy-800 p-3" style={{ minHeight: 100 }}>
        <div className="text-xs text-amber-600 font-mono tracking-widest mb-3 uppercase">🪵 Dock</div>
        <div className="flex flex-wrap gap-4 justify-center">
          {dockAgents.length === 0 && (
            <span className="text-xs text-gray-600 italic">no agents at dock</span>
          )}
          {dockAgents.map(a => <AgentDot key={a.name} agent={a} />)}
        </div>
      </div>
    </div>
  );
}

// ─── Conversation Feed ────────────────────────────────────────────────────────

function ConversationFeed({ conversations }) {
  const feedRef = useRef(null);

  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [conversations]);

  if (!conversations || conversations.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-600 text-sm italic">
        No conversations yet. Start the simulation.
      </div>
    );
  }

  return (
    <div
      ref={feedRef}
      className="flex-1 overflow-y-auto scrollbar-thin space-y-2 pr-1"
    >
      {conversations.map((conv, i) => {
        const fromColors = AGENT_COLORS[conv.from] || { text: "text-gray-400", hex: "#888" };
        const isNorm = conv.norm_signal;
        const isGroup = conv.to === "GROUP";
        const isUndelivered = !conv.delivered && !isGroup;

        // Participant label: "Everyone (Ana, Marco, Sofia)" or "Ana ↔ Marco"
        const participantLabel = isGroup
          ? `Everyone${conv.participants?.length ? " (" + conv.participants.join(", ") + ")" : ""}`
          : (conv.participants || [conv.from, conv.to]).join(" ↔ ");

        return (
          <div
            key={i}
            className={`rounded-lg border overflow-hidden text-xs transition-all ${
              isNorm
                ? "border-teal-600 bg-teal-950 norm-glow"
                : isUndelivered
                ? "border-gray-700 bg-gray-900 opacity-50"
                : "border-gray-800 bg-gray-900"
            }`}
          >
            {/* Header row: round + participants */}
            <div className={`flex items-center gap-2 px-2.5 py-1.5 border-b flex-wrap ${
              isNorm ? "border-teal-800 bg-teal-900" :
              isUndelivered ? "border-gray-700 bg-gray-800" :
              "border-gray-800 bg-gray-800"
            }`}>
              <span className="text-gray-500 font-mono">R{conv.round}</span>
              <span className="text-gray-600">·</span>
              <span className={`font-mono font-bold ${isGroup ? "text-teal-400" : "text-yellow-400"}`}>
                {participantLabel}
              </span>
              {isNorm && <span className="text-teal-300 ml-1">🌊</span>}
              {isUndelivered && (
                <span className="text-gray-500 italic text-xs ml-auto">(pending)</span>
              )}
              {conv.relayed_by && (
                <span className="text-orange-400 text-xs ml-auto">via {conv.relayed_by}</span>
              )}
            </div>
            {/* Message body */}
            <div className="px-2.5 py-2">
              <span className={`font-bold mr-1.5 ${fromColors.text}`}>{conv.from}:</span>
              <span className={`${isNorm ? "text-teal-100" : "text-gray-300"} leading-relaxed`}>
                "{conv.content}"
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Norm Tracker ─────────────────────────────────────────────────────────────

function NormTracker({ norms }) {
  if (!norms || norms.length === 0) return null;

  return (
    <div className="border-t border-gray-800 pt-3 mt-3">
      <div className="text-xs text-teal-600 font-mono tracking-widest mb-2 uppercase">
        🌊 Norm Signals ({norms.length})
      </div>
      <div className="space-y-1.5 max-h-40 overflow-y-auto scrollbar-thin">
        {norms.map((norm, i) => {
          const colors = AGENT_COLORS[norm.proposer] || { text: "text-gray-400" };
          return (
            <div key={i} className="border border-teal-900 bg-teal-950 rounded p-2 text-xs">
              <div className="flex items-center gap-2 mb-1">
                <span className={`font-bold ${colors.text}`}>{norm.proposer}</span>
                <span className="text-gray-500">R{norm.round}</span>
                <span className={`ml-auto px-1.5 py-0.5 rounded text-xs ${
                  norm.status === "adopted" ? "bg-teal-700 text-teal-100" :
                  norm.status === "faded" ? "bg-gray-700 text-gray-400" :
                  "bg-amber-900 text-amber-300"
                }`}>
                  {norm.status || "active"}
                </span>
              </div>
              <div className="text-teal-200 truncate" title={norm.content}>
                "{norm.content}"
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Harvest Chart (SVG sparkline) ────────────────────────────────────────────

function HarvestChart({ lake, agents }) {
  const W = 800, H = 160;
  const PADDING = { top: 10, right: 20, bottom: 30, left: 40 };
  const chartW = W - PADDING.left - PADDING.right;
  const chartH = H - PADDING.top - PADDING.bottom;

  const history = lake?.history || [200];
  const maxVal = lake?.max || 200;
  const n = history.length;

  if (n < 2) return (
    <div className="flex items-center justify-center h-40 text-gray-600 text-sm italic">
      Chart will appear after round 1
    </div>
  );

  const xScale = (i) => PADDING.left + (i / (n - 1)) * chartW;
  const yScale = (v) => PADDING.top + chartH - (v / maxVal) * chartH;

  // Lake history line
  const lakePath = history.map((v, i) =>
    `${i === 0 ? "M" : "L"} ${xScale(i)} ${yScale(v)}`
  ).join(" ");

  // Area fill
  const lakeArea = `${lakePath} L ${xScale(n - 1)} ${yScale(0)} L ${xScale(0)} ${yScale(0)} Z`;

  // Agent harvest bars (stacked, tiny, below main chart)
  const barZoneTop = PADDING.top + chartH + 5;
  const barH = 10;
  const barW = n > 1 ? Math.max(2, chartW / (n - 1) / (agents.length + 1)) : 8;

  // Y-axis labels
  const yTicks = [0, maxVal * 0.25, maxVal * 0.5, maxVal * 0.75, maxVal].map(v => Math.round(v));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 160 }}>
      {/* Grid lines */}
      {yTicks.map(v => (
        <g key={v}>
          <line
            x1={PADDING.left} y1={yScale(v)}
            x2={W - PADDING.right} y2={yScale(v)}
            stroke="#1e3a5f" strokeWidth="0.5" strokeDasharray="4,4"
          />
          <text x={PADDING.left - 4} y={yScale(v) + 4} fill="#4b6a8a"
                fontSize="9" textAnchor="end">{v}</text>
        </g>
      ))}

      {/* Lake area */}
      <path d={lakeArea} fill="rgba(14,165,233,0.1)" />
      <path d={lakePath} fill="none" stroke="#0ea5e9" strokeWidth="2" strokeLinejoin="round" />

      {/* Agent harvest bars */}
      {agents.map((agent, ai) => {
        const colors = AGENT_COLORS[agent.name] || { hex: "#888" };
        return (agent.harvest_history || []).map((h, ri) => {
          const x = xScale(ri) + ai * (barW + 0.5) - (agents.length * (barW + 0.5)) / 2;
          const bh = Math.max(1, (h / 20) * barH);
          return (
            <rect
              key={`${ai}-${ri}`}
              x={x} y={barZoneTop + barH - bh}
              width={barW} height={bh}
              fill={colors.hex} opacity="0.7"
            />
          );
        });
      })}

      {/* X-axis round labels */}
      {history.map((_, i) => {
        if (i % Math.max(1, Math.floor(n / 10)) !== 0) return null;
        return (
          <text key={i} x={xScale(i)} y={H - 4} fill="#4b6a8a"
                fontSize="8" textAnchor="middle">R{i}</text>
        );
      })}

      {/* Legend */}
      <line x1={W - 80} y1={15} x2={W - 65} y2={15} stroke="#0ea5e9" strokeWidth="2" />
      <text x={W - 62} y={19} fill="#0ea5e9" fontSize="8">Lake stock</text>
    </svg>
  );
}

// ─── Agent Inspector Modal ────────────────────────────────────────────────────

// ─── Raw Section (collapsible text block) ────────────────────────────────────

function RawSection({ label, labelColor, borderColor, bgColor, content, emptyText, collapsible }) {
  const [open, setOpen] = useState(!collapsible);

  return (
    <div className={`border-t ${borderColor}`}>
      <button
        onClick={() => collapsible && setOpen(o => !o)}
        className={`w-full flex items-center gap-2 px-3 py-1.5 ${bgColor} text-left`}
        style={{ cursor: collapsible ? "pointer" : "default" }}
      >
        <span className={`text-xs font-mono font-bold ${labelColor}`}>{label}</span>
        {collapsible && (
          <span className={`ml-auto text-xs ${labelColor} opacity-60`}>{open ? "▲" : "▼"}</span>
        )}
        {!content && (
          <span className="ml-auto text-xs text-gray-600 italic">{emptyText}</span>
        )}
      </button>
      {open && content && (
        <div className="px-3 py-2">
          <pre className="text-xs text-gray-300 leading-relaxed whitespace-pre-wrap font-mono break-words">
            {content}
          </pre>
        </div>
      )}
    </div>
  );
}

// ─── Agent Inspector Modal ────────────────────────────────────────────────────

function AgentInspector({ agentName, onClose }) {
  const [tab, setTab] = useState("memory");
  const [history, setHistory] = useState([]);
  const [fullLog, setFullLog] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const [h, l] = await Promise.all([
          fetch(`/api/agent/${agentName}`).then(r => r.json()),
          fetch("/api/log").then(r => r.json()),
        ]);
        setHistory(h);
        setFullLog(l);
      } catch (e) { console.error(e); }
      setLoading(false);
    }
    load();
  }, [agentName]);

  const colors = AGENT_COLORS[agentName] || { text: "text-gray-400", bg: "bg-gray-700", border: "border-gray-600" };

  // Decisions extracted from full log for this agent
  const decisions = fullLog.map(roundState => {
    const agent = roundState.agents?.find(a => a.name === agentName);
    if (!agent) return null;
    return {
      round: roundState.round,
      harvest: agent.harvest,
      location: agent.location,
      speech: agent.last_speech,
      reflect: agent.reflect,
      raw_prompt: agent.raw_prompt || "",
      raw: agent.raw_response || "",
      raw_extractor_prompt: agent.raw_extractor_prompt || "",
      raw_extractor: agent.raw_extractor || "",
      conv_turns: agent.conv_turns || [],
    };
  }).filter(Boolean);

  const tabs = [
    { id: "memory",    label: "Memory" },
    { id: "decisions", label: "Decisions" },
    { id: "raw",       label: "Raw LLM" },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-70 p-4">
      <div className="bg-gray-950 border border-gray-700 rounded-xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl">
        {/* Header */}
        <div className={`flex items-center justify-between p-4 border-b border-gray-800`}>
          <div className="flex items-center gap-3">
            <div className={`w-9 h-9 rounded-full ${colors.bg} flex items-center justify-center text-white font-bold text-sm`}>
              {agentName[0]}
            </div>
            <span className={`font-bold text-lg ${colors.text}`}>{agentName}</span>
            <span className="text-gray-500 text-sm">{history.length} memory entries</span>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors text-xl">✕</button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-800">
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-4 py-2 text-xs font-mono transition-colors ${
                tab === t.id
                  ? `${colors.text} border-b-2 ${colors.border}`
                  : "text-gray-500 hover:text-gray-300"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto scrollbar-thin p-4">
          {loading && <div className="text-gray-500 text-sm text-center py-8">Loading...</div>}

          {/* MEMORY TAB */}
          {!loading && tab === "memory" && (
            <div className="space-y-2">
              {history.length === 0 && (
                <div className="text-gray-600 italic text-sm text-center py-8">No memories yet.</div>
              )}
              {history.map((entry, i) => {
                const style = MEMORY_TYPE_STYLES[entry.type] || MEMORY_TYPE_STYLES.observed;
                const isReflect = entry.type === "reflection";
                return (
                  <div key={i} className={`rounded-lg border border-gray-800 p-2.5 ${entry.salience === "high" ? "border-l-2 border-l-amber-500" : ""}`}>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-gray-600 font-mono text-xs">R{entry.round}</span>
                      <span className={`text-xs px-1.5 py-0.5 rounded ${style.bg} ${style.color} font-mono`}>
                        {style.label}
                      </span>
                      {entry.salience === "high" && (
                        <span className="text-amber-400 text-xs">★ high</span>
                      )}
                    </div>
                    <div className={`text-xs leading-relaxed ${isReflect ? "text-purple-300 italic" : "text-gray-300"}`}>
                      {entry.content}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* DECISIONS TAB */}
          {!loading && tab === "decisions" && (
            <div className="space-y-2">
              {decisions.length === 0 && (
                <div className="text-gray-600 italic text-sm text-center py-8">No decisions yet.</div>
              )}
              {decisions.map((d, i) => (
                <div
                  key={i}
                  className={`rounded-lg border p-3 text-xs ${
                    d.speech?.norm_signal ? "border-teal-700 bg-teal-950" : "border-gray-800 bg-gray-900"
                  }`}
                >
                  <div className="flex items-center gap-3 mb-2 flex-wrap">
                    <span className="font-mono text-gray-400">R{d.round}</span>
                    <span className="text-sky-400 font-mono">{d.harvest}t</span>
                    <span className={`px-1.5 py-0.5 rounded font-mono ${d.location === "dock" ? "bg-amber-900 text-amber-300" : "bg-sky-900 text-sky-300"}`}>
                      {d.location}
                    </span>
                    {d.speech?.type && d.speech.type !== "SILENT" && (
                      <span className={`px-1.5 py-0.5 rounded font-mono ${d.speech.type === "GROUP" ? "bg-teal-900 text-teal-300" : "bg-yellow-900 text-yellow-300"}`}>
                        {d.speech.type}
                        {d.speech.addressee ? ` → ${d.speech.addressee}` : ""}
                      </span>
                    )}
                    {d.speech?.norm_signal && <span className="text-teal-300">🌊 NORM</span>}
                  </div>
                  {d.speech?.content && (
                    <div className={`mb-2 ${d.speech.norm_signal ? "text-teal-200" : "text-gray-300"}`}>
                      "{d.speech.content}"
                    </div>
                  )}
                  {d.reflect && (
                    <div className="text-purple-300 italic border-t border-gray-800 pt-1 mt-1">
                      💭 {d.reflect}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* RAW LLM TAB */}
          {!loading && tab === "raw" && (
            <div className="space-y-6">
              {decisions.length === 0 && (
                <div className="text-gray-600 italic text-sm text-center py-8">No responses yet.</div>
              )}
              {decisions.map((d, i) => (
                <div key={i} className="rounded-lg border border-gray-800 bg-gray-900 overflow-hidden">
                  {/* Round header */}
                  <div className="flex items-center gap-2 px-3 py-2 bg-gray-800 border-b border-gray-700">
                    <span className="text-xs text-gray-400 font-mono font-bold">Round {d.round}</span>
                    <span className="text-xs text-sky-700 font-mono uppercase ml-1">Fishing phase</span>
                  </div>

                  {/* 1 — Prompt sent to agent */}
                  <RawSection
                    label="PROMPT → Agent LLM"
                    labelColor="text-sky-400"
                    borderColor="border-sky-900"
                    bgColor="bg-sky-950"
                    content={d.raw_prompt}
                    emptyText="(prompt not recorded)"
                    collapsible={true}
                  />

                  {/* 2 — Agent raw response */}
                  <RawSection
                    label="RESPONSE ← Agent LLM"
                    labelColor="text-violet-400"
                    borderColor="border-violet-900"
                    bgColor="bg-violet-950"
                    content={d.raw}
                    emptyText="(no agent response)"
                    collapsible={false}
                  />

                  {/* 3 — Prompt sent to extractor */}
                  <RawSection
                    label="PROMPT → Extractor LLM"
                    labelColor="text-orange-400"
                    borderColor="border-orange-900"
                    bgColor="bg-orange-950"
                    content={d.raw_extractor_prompt}
                    emptyText="(extractor prompt not recorded)"
                    collapsible={true}
                  />

                  {/* 4 — Extractor raw output */}
                  <RawSection
                    label="RESPONSE ← Extractor LLM"
                    labelColor="text-amber-400"
                    borderColor="border-amber-900"
                    bgColor="bg-amber-950"
                    content={d.raw_extractor}
                    emptyText="(no extractor output)"
                    collapsible={false}
                  />

                  {/* 5 — Conversation turns (dock phase) */}
                  {d.conv_turns && d.conv_turns.length > 0 && (
                    <div className="border-t border-gray-700">
                      <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-800">
                        <span className="text-xs text-amber-600 font-mono uppercase tracking-wider">
                          Dock conversation — {d.conv_turns.length} turn{d.conv_turns.length !== 1 ? "s" : ""}
                        </span>
                      </div>
                      {d.conv_turns.map((t, ti) => (
                        <div key={ti} className="border-t border-gray-800">
                          {/* Turn sub-header */}
                          <div className="px-3 py-1 bg-gray-850" style={{ background: "#111827" }}>
                            <span className="text-xs text-amber-500 font-mono">Turn {t.turn}</span>
                          </div>
                          <RawSection
                            label="PROMPT → Agent LLM (conv)"
                            labelColor="text-sky-400"
                            borderColor="border-sky-900"
                            bgColor="bg-sky-950"
                            content={t.prompt}
                            emptyText="(prompt not recorded)"
                            collapsible={true}
                          />
                          <RawSection
                            label="RESPONSE ← Agent LLM (conv)"
                            labelColor="text-violet-400"
                            borderColor="border-violet-900"
                            bgColor="bg-violet-950"
                            content={t.raw}
                            emptyText="(no response)"
                            collapsible={false}
                          />
                          <RawSection
                            label="PROMPT → Extractor LLM (conv)"
                            labelColor="text-orange-400"
                            borderColor="border-orange-900"
                            bgColor="bg-orange-950"
                            content={t.extractor_prompt}
                            emptyText="(extractor prompt not recorded)"
                            collapsible={true}
                          />
                          <RawSection
                            label="RESPONSE ← Extractor LLM (conv)"
                            labelColor="text-amber-400"
                            borderColor="border-amber-900"
                            bgColor="bg-amber-950"
                            content={t.extractor}
                            emptyText="(no extractor output)"
                            collapsible={false}
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────

function App() {
  const [state, setState] = useState(null);
  const [simStatus, setSimStatus] = useState({ running: false, paused: false, round: 0, total_rounds: 30 });
  const [allConversations, setAllConversations] = useState([]);
  const [inspectedAgent, setInspectedAgent] = useState(null);

  // Poll state every 2s
  useEffect(() => {
    const poll = async () => {
      try {
        const data = await fetch("/api/state").then(r => r.json());
        setState(data);
        // Accumulate conversations across rounds
        if (data.conversations && data.conversations.length > 0) {
          setAllConversations(prev => {
            // Merge: avoid duplicates by checking round + from + to + content
            const existing = new Set(prev.map(c => `${c.round}|${c.from}|${c.to}|${c.content}`));
            const newOnes = data.conversations.filter(c =>
              !existing.has(`${c.round}|${c.from}|${c.to}|${c.content}`)
            );
            return [...prev, ...newOnes];
          });
        }
      } catch (e) { console.warn("state poll error", e); }
    };
    poll();
    const id = setInterval(poll, 2000);
    return () => clearInterval(id);
  }, []);

  // Poll status every 1s
  useEffect(() => {
    const poll = async () => {
      try {
        const data = await fetch("/api/status").then(r => r.json());
        setSimStatus(data);
      } catch (e) { }
    };
    poll();
    const id = setInterval(poll, 1000);
    return () => clearInterval(id);
  }, []);

  const handleControl = useCallback(async (action) => {
    await apiControl(action);
  }, []);

  const lakeMax = state?.lake?.max || 200;
  const lake = state?.lake || { current: lakeMax, max: lakeMax, history: [lakeMax], status: "healthy" };
  const agents = state?.agents || [];
  const norms = state?.norm_tracker || [];

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "#0a0f1e" }}>
      {/* ── HEADER ── */}
      <header className="border-b border-gray-800 bg-gray-950 px-4 py-2.5">
        <div className="max-w-screen-2xl mx-auto flex items-center gap-4 flex-wrap">
          <div>
            <div className="text-sm font-bold text-teal-400 tracking-widest uppercase font-mono">
              Fishery · Norm Emergence
            </div>
            <div className="text-xs text-gray-600 font-mono">Common-pool resource simulation</div>
          </div>
          <div className="flex-1 flex items-center gap-4">
            <LakeHealthBar lake={lake} />
          </div>
          <Controls status={simStatus} onAction={handleControl} />
        </div>
      </header>

      {/* ── MAIN CONTENT ── */}
      <main className="flex-1 flex overflow-hidden max-w-screen-2xl mx-auto w-full">

        {/* LEFT PANEL — Zone Map */}
        <div className="w-72 flex-shrink-0 border-r border-gray-800 p-4 flex flex-col gap-4 overflow-y-auto scrollbar-thin">
          <div className="text-xs text-gray-600 font-mono tracking-widest uppercase mb-1">Locations</div>
          <ZoneMap agents={agents} onAgentClick={setInspectedAgent} />

          {/* Agent harvest summaries */}
          <div className="border-t border-gray-800 pt-3">
            <div className="text-xs text-gray-600 font-mono tracking-widest uppercase mb-2">This Round</div>
            <div className="space-y-1.5">
              {agents.map(agent => {
                const colors = AGENT_COLORS[agent.name] || { text: "text-gray-400", bg: "bg-gray-700" };
                const speech = agent.last_speech;
                return (
                  <div
                    key={agent.name}
                    className="flex items-center gap-2 cursor-pointer hover:bg-gray-900 rounded px-1 py-0.5 transition-colors"
                    onClick={() => setInspectedAgent(agent.name)}
                  >
                    <div className={`w-2 h-2 rounded-full ${colors.bg}`} />
                    <span className={`text-xs ${colors.text} font-mono w-12`}>{agent.name}</span>
                    <span className="text-xs text-sky-400 font-mono w-8">{agent.harvest || 0}t</span>
                    {speech?.type && speech.type !== "SILENT" && (
                      <span className={`text-xs px-1 rounded ${speech.norm_signal ? "text-teal-300" : "text-gray-500"}`}>
                        {speech.norm_signal ? "🌊" : speech.type === "GROUP" ? "📢" : "💬"}
                      </span>
                    )}
                    {agent.reflect && (
                      <span className="text-xs text-purple-400 truncate max-w-20 italic" title={agent.reflect}>
                        💭
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Click hint */}
          <div className="text-xs text-gray-700 italic text-center">
            Click an agent to inspect
          </div>
        </div>

        {/* RIGHT PANEL — Conversations + Norms */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex-1 flex flex-col p-4 overflow-hidden">
            <div className="text-xs text-gray-600 font-mono tracking-widest uppercase mb-3">
              Conversation Feed ({allConversations.length} messages)
            </div>
            <ConversationFeed conversations={allConversations} />
            <NormTracker norms={norms} />
          </div>
        </div>
      </main>

      {/* ── BOTTOM CHART ── */}
      <div className="border-t border-gray-800 bg-gray-950 p-4">
        <div className="max-w-screen-2xl mx-auto">
          <div className="flex items-center gap-4 mb-2 flex-wrap">
            <div className="text-xs text-gray-600 font-mono tracking-widest uppercase">Lake History</div>
            <div className="flex gap-3 flex-wrap">
              {agents.map(a => {
                const c = AGENT_COLORS[a.name] || { hex: "#888", text: "text-gray-400" };
                return (
                  <div key={a.name} className="flex items-center gap-1">
                    <div className="w-2 h-2 rounded-sm" style={{ background: c.hex }} />
                    <span className={`text-xs ${c.text} font-mono`}>{a.name}</span>
                  </div>
                );
              })}
            </div>
          </div>
          <HarvestChart lake={lake} agents={agents} />
        </div>
      </div>

      {/* ── AGENT INSPECTOR MODAL ── */}
      {inspectedAgent && (
        <AgentInspector
          agentName={inspectedAgent}
          onClose={() => setInspectedAgent(null)}
        />
      )}
    </div>
  );
}

// Mount
const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
