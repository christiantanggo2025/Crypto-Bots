import { useEffect, useState } from "react";

/** Vercel: leave unset → same-origin /api → serverless proxy to Railway (RAILWAY_API_BASE_URL). Or set VITE_API_BASE_URL for direct calls. */
const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const API = API_BASE ? `${API_BASE}/api` : "/api";
const LAB = "/lab"; // API + LAB = full /api/lab or https://host/api/lab

type TabId = "overview" | "gen1" | "gen2" | "gen3" | "gen4" | "gen5" | "gen6" | "gen7" | "comparison" | "settings";

const TAB_TO_GEN_ID: Partial<Record<TabId, string>> = {
  gen1: "1",
  gen2: "2",
  gen3: "3",
  gen4: "4",
  gen5: "5",
  gen6: "6",
};

type GenStatus = {
  gen_id: string;
  label: string;
  enabled: boolean;
  balance_usd: number;
  total_value_usd: number;
  total_pnl_usd: number;
  total_pnl_percent: number;
  positions_count: number;
  trade_count_today: number;
  last_run: string | null;
  last_decision?: string | null;
  last_reasoning?: string | null;
};

type LabOverview = {
  total_bots_active: number;
  combined_pnl_usd: number;
  combined_pnl_percent: number;
  total_open_positions: number;
  last_cycle: string | null;
  generations: GenStatus[];
  recent_activity: Array<{ gen_id: string; label: string; timestamp: string; symbol: string; side: string; reason: string }>;
};

/** GET /api/lab/worker-status — proof the cloud scheduler is looping */
type WorkerStatus = {
  where_this_runs: string;
  lab_worker_disabled: boolean;
  process_boot_at: string | null;
  scheduler_interval_seconds: number | null;
  lab_last_cycle_at: string | null;
  seconds_since_last_lab_cycle: number | null;
  check_logs_for: string;
};

type Position = {
  symbol: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  value_usd: number;
  pnl_usd: number;
  pnl_percent: number;
};

type Trade = {
  id: string;
  symbol: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  total_usd: number;
  reason: string;
  timestamp: string;
  world_signal: string | null;
  fee_usd?: number | null;
  /** Sell: net gain/loss vs avg entry. Buy: null. */
  realized_pnl_usd?: number | null;
};

type ComparisonRow = {
  gen_id: string;
  label: string;
  pnl_usd: number;
  pnl_percent: number;
  trade_count: number;
  win_count: number;
  win_rate: number | null;
  open_positions: number;
  drawdown_pct: number | null;
  avg_per_trade_usd: number | null;
  cash_balance: number;
  exposure_usd: number;
};

type MarketTick = {
  symbol: string;
  price: number;
  price_cad: number | null;
  change_24h: number;
  volume_24h: number;
  timestamp: string;
};

function usePoll<T>(url: string, intervalMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refetch = async () => {
    try {
      const fullUrl = url.startsWith("http") ? url : (url.startsWith("/api") ? url : API + url);
      const r = await fetch(fullUrl);
      if (!r.ok) throw new Error(r.statusText);
      setData(await r.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch");
    }
  };
  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      try {
        const fullUrl = url.startsWith("http") ? url : (url.startsWith("/api") ? url : API + url);
        const r = await fetch(fullUrl);
        if (!r.ok) throw new Error(r.statusText);
        const j = await r.json();
        if (!cancelled) setData(j);
        setError(null);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to fetch");
      }
    };
    fetchData();
    const id = setInterval(fetchData, intervalMs);
    return () => { cancelled = true; clearInterval(id); };
  }, [url, intervalMs]);
  return { data, error, refetch };
}

function formatUsd(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
}
function formatPct(n: number) {
  return n >= 0 ? `+${n.toFixed(2)}%` : `${n.toFixed(2)}%`;
}
/** Display all lab/API times in Toronto (Eastern). */
const DISPLAY_TZ = "America/Toronto";

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString("en-CA", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: DISPLAY_TZ,
  });
}

function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString("en-CA", { hour12: false, timeZone: DISPLAY_TZ });
}

/** Cash deployed on a buy (notional + fee). */
function tradeBuySpendUsd(t: Trade): number {
  return t.total_usd + (t.fee_usd ?? 0);
}

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "gen1", label: "Gen 1" },
  { id: "gen2", label: "Gen 2" },
  { id: "gen3", label: "Gen 3" },
  { id: "gen4", label: "Gen 4" },
  { id: "gen5", label: "Gen 5" },
  { id: "gen6", label: "Gen 6" },
  { id: "gen7", label: "Gen 7" },
  { id: "comparison", label: "Comparison" },
  { id: "settings", label: "Settings" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const { data: overview, error: overviewErr } = usePoll<LabOverview>(API + LAB + "/overview", 5000);
  const { data: workerStatus, error: workerErr } = usePoll<WorkerStatus>(API + LAB + "/worker-status", 5000);
  const { data: market } = usePoll<MarketTick[]>(API + "/market", 10000);
  const { data: comparison } = usePoll<ComparisonRow[]>(API + LAB + "/comparison", 5000);
  const [genDetail, setGenDetail] = useState<Record<string, { status: any; positions: Position[]; trades: Trade[] }>>({});
  const [genDetailLoading, setGenDetailLoading] = useState<Record<string, boolean>>({});
  const [genDetailError, setGenDetailError] = useState<Record<string, string>>({});

  useEffect(() => {
    const genId = TAB_TO_GEN_ID[activeTab];
    const isGenTab = Boolean(genId);
    if (isGenTab && genId) {
      setGenDetailLoading((prev) => ({ ...prev, [genId]: true }));
      setGenDetailError((prev) => ({ ...prev, [genId]: "" }));
      const base = API + LAB + "/generations/" + genId;
      Promise.all([
        fetch(base + "/status").then((r) => (r.ok ? r.json() : null)),
        fetch(base + "/positions").then((r) => (r.ok ? r.json() : null)),
        fetch(base + "/trades?limit=50").then((r) => (r.ok ? r.json() : null)),
      ])
        .then(([status, positionsResp, tradesResp]) => {
          if (!status) {
            setGenDetailError((prev) => ({ ...prev, [genId]: "Could not load status." }));
            setGenDetailLoading((prev) => ({ ...prev, [genId]: false }));
            return;
          }
          const positions = Array.isArray(status.positions)
            ? status.positions
            : Array.isArray(positionsResp)
              ? positionsResp
              : [];
          const trades = Array.isArray(status.trades)
            ? status.trades
            : Array.isArray(tradesResp)
              ? tradesResp
              : Array.isArray(status.state?.trades)
                ? [...status.state.trades].reverse()
                : [];
          setGenDetail((prev) => ({ ...prev, [genId]: { status, positions, trades } }));
          setGenDetailError((prev) => ({ ...prev, [genId]: "" }));
        })
        .catch((err) => {
          setGenDetailError((prev) => ({ ...prev, [genId]: err?.message || "Failed to load." }));
        })
        .finally(() => {
          setGenDetailLoading((prev) => ({ ...prev, [genId]: false }));
        });
    }
  }, [activeTab, overview?.last_cycle]);

  return (
    <div style={{ minHeight: "100vh", paddingBottom: "2rem" }}>
      <header style={{ borderBottom: "1px solid var(--border)", padding: "1rem 2rem", background: "var(--surface)" }}>
        <h1 style={{ margin: 0, fontSize: "1.5rem", fontWeight: 700, color: "var(--accent)" }}>Crypto Strategy Lab</h1>
        <p style={{ margin: "0.25rem 0 0", color: "var(--text-muted)", fontSize: "0.9rem" }}>Multi-generation paper trading · Compare and optimize</p>
        <nav style={{ display: "flex", gap: "0.25rem", marginTop: "1rem", flexWrap: "wrap" }}>
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              style={{
                padding: "0.5rem 1rem",
                border: "1px solid var(--border)",
                borderRadius: 8,
                background: activeTab === t.id ? "var(--accent)" : "transparent",
                color: activeTab === t.id ? "var(--bg)" : "var(--text)",
                cursor: "pointer",
                fontWeight: activeTab === t.id ? 600 : 400,
              }}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      {(overviewErr || !overview) && activeTab !== "settings" && (
        <div style={{ margin: "1rem 2rem", padding: "1rem", background: "var(--red)", color: "#fff", borderRadius: 8 }}>
          {overviewErr ? `Cannot reach API: ${overviewErr}. Is the backend running?` : "Loading…"}
        </div>
      )}

      <main style={{ maxWidth: 1400, margin: "0 auto", padding: "1.5rem 2rem" }}>
        {activeTab === "overview" && overview && (
          <OverviewTab overview={overview} market={market || []} worker={workerStatus} workerError={workerErr} />
        )}
        {activeTab === "gen1" && <GenTab genId="1" label="Gen 1: Baseline Bot" description="Original bot. Unchanged for comparison. Buys dips, sells on rise. No smart prediction." detail={genDetail["1"]} summary={overview?.generations?.find((g) => g.gen_id === "1")} loading={genDetailLoading["1"]} error={genDetailError["1"]} />}
        {activeTab === "gen2" && <GenTab genId="2" label="Gen 2: Optimized Bot" description="Same dip-buy idea with tighter risk: smaller positions, more cooldown, disciplined exits." detail={genDetail["2"]} summary={overview?.generations?.find((g) => g.gen_id === "2")} loading={genDetailLoading["2"]} error={genDetailError["2"]} />}
        {activeTab === "gen3" && <GenTab genId="3" label="Gen 3: Adaptive Bot" description="Reads market context (uptrend/sideways/downtrend). Only buys dips when context allows." detail={genDetail["3"]} summary={overview?.generations?.find((g) => g.gen_id === "3")} loading={genDetailLoading["3"]} error={genDetailError["3"]} />}
        {activeTab === "gen4" && <GenTab genId="4" label="Gen 4: AI Supervisor Bot" description="AI and news decide allow/limit/block. More selective and strategic." detail={genDetail["4"]} summary={overview?.generations?.find((g) => g.gen_id === "4")} loading={genDetailLoading["4"]} error={genDetailError["4"]} isAi />}
        {activeTab === "gen5" && <GenTab genId="5" label="Gen 5: Aggressive Scalper Bot" description="Intraday-focused: smaller positions, faster profit targets, shorter holds. Looks for quick rebound opportunities and backs off when the market is weak or messy." detail={genDetail["5"]} summary={overview?.generations?.find((g) => g.gen_id === "5")} loading={genDetailLoading["5"]} error={genDetailError["5"]} isScalper />}
        {activeTab === "gen6" && <GenTab genId="6" label="Gen 6: Momentum Rider Bot" description="Hybrid scalper / trend rider: disciplined rebound entries, tight initial risk, staged profits, runner mode with trailing exits—captures larger moves without a single fixed take-profit." detail={genDetail["6"]} summary={overview?.generations?.find((g) => g.gen_id === "6")} loading={genDetailLoading["6"]} error={genDetailError["6"]} isMomentumRider />}
        {activeTab === "gen7" && <GenTab genId="7" label="Gen 7: Active Micro-Movement Trader" description="Aggressive short-hold micro-trader: many small intraday-style opportunities, quick targets, tight stops, stall and time exits—not a long-hold runner like Gen 6." detail={genDetail["7"]} summary={overview?.generations?.find((g) => g.gen_id === "7")} loading={genDetailLoading["7"]} error={genDetailError["7"]} isMicroTrader />}
        {activeTab === "comparison" && comparison && <ComparisonTab rows={comparison} />}
        {activeTab === "settings" && <SettingsTab />}
      </main>
    </div>
  );
}

function Card({ title, value, sub, positive }: { title: string; value: string; sub?: string; positive?: boolean }) {
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 10,
        padding: "1rem",
        minHeight: 96,
        width: "100%",
        boxSizing: "border-box",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>{title}</div>
      <div style={{ fontSize: "1.2rem", fontWeight: 600, marginTop: "0.25rem", flex: 1, display: "flex", alignItems: "center" }}>{value}</div>
      <div
        style={{
          fontSize: "0.9rem",
          minHeight: "1.35em",
          marginTop: "0.15rem",
          lineHeight: 1.35,
          color: sub != null ? (positive === false ? "var(--red)" : positive === true ? "var(--green)" : "var(--text-muted)") : "var(--text-muted)",
        }}
      >
        {sub != null ? sub : "\u00a0"}
      </div>
    </div>
  );
}

const STARTING_BALANCE = 10_000;

function WorkerLiveBanner({ worker, error }: { worker: WorkerStatus | null; error: string | null }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  if (error) {
    return (
      <div
        style={{
          background: "var(--red)",
          color: "#fff",
          borderRadius: 10,
          padding: "1rem 1.25rem",
          marginBottom: "1.5rem",
          fontWeight: 600,
        }}
      >
        Worker status unreachable: {error}. On Vercel set RAILWAY_API_BASE_URL (proxy) or VITE_API_BASE_URL (direct), then redeploy.
      </div>
    );
  }
  if (!worker) {
    return (
      <div style={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 10, padding: "1rem", marginBottom: "1.5rem" }}>
        Loading cloud worker status…
      </div>
    );
  }

  const intervalSec = worker.scheduler_interval_seconds && worker.scheduler_interval_seconds > 0 ? worker.scheduler_interval_seconds : 90;
  const lastIso = worker.lab_last_cycle_at;
  const lastMs = lastIso ? Date.parse(lastIso) : NaN;
  const agoSec = Number.isFinite(lastMs) ? Math.max(0, Math.floor((Date.now() - lastMs) / 1000)) : null;

  let headline: string;
  let sub: string;
  let bg: string;
  let border: string;

  if (worker.lab_worker_disabled) {
    headline = "Background worker OFF";
    sub = "LAB_WORKER_DISABLED is set on the server. The lab will not run scheduled trading cycles.";
    bg = "rgba(180, 80, 80, 0.2)";
    border = "var(--red)";
  } else if (agoSec == null) {
    headline = "Worker starting — no full cycle yet";
    sub = `Scheduler interval ~${intervalSec}s. If this stays for many minutes, check CoinGecko / logs for ${worker.check_logs_for}.`;
    bg = "rgba(200, 160, 60, 0.2)";
    border = "#c9a227";
  } else if (agoSec <= Math.max(intervalSec * 3, intervalSec + 120)) {
    headline = "CLOUD WORKER LIVE";
    sub = `Last lab cycle ${agoSec}s ago (Toronto clock below). This runs on the server — you can close your laptop. Target cadence ~${intervalSec}s.`;
    bg = "rgba(60, 140, 80, 0.25)";
    border = "var(--green)";
  } else {
    headline = "Worker may be stuck or prices unavailable";
    sub = `No successful cycle for ~${agoSec}s (expected about every ${intervalSec}s). Check Railway logs for ${worker.check_logs_for} or CoinGecko 429.`;
    bg = "rgba(200, 120, 60, 0.2)";
    border = "#c97a27";
  }

  return (
    <div
      style={{
        background: bg,
        border: `2px solid ${border}`,
        borderRadius: 12,
        padding: "1.1rem 1.35rem",
        marginBottom: "1.5rem",
      }}
    >
      <div style={{ fontSize: "1.15rem", fontWeight: 700, letterSpacing: "0.02em", marginBottom: "0.5rem" }}>{headline}</div>
      <div style={{ fontSize: "0.9rem", color: "var(--text-muted)", lineHeight: 1.5, marginBottom: "0.65rem" }}>{sub}</div>
      <div style={{ fontSize: "0.8rem", fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
        <div>Server boot: {worker.process_boot_at ? formatDateTime(worker.process_boot_at) : "—"}</div>
        <div>Last cycle (UTC from API): {lastIso ? formatDateTime(lastIso) : "—"}</div>
        <div>{worker.where_this_runs}</div>
      </div>
    </div>
  );
}

function OverviewTab({
  overview,
  market,
  worker,
  workerError,
}: {
  overview: LabOverview;
  market: MarketTick[];
  worker: WorkerStatus | null;
  workerError: string | null;
}) {
  const [reportRange, setReportRange] = useState("all_time");
  const [reportFormat, setReportFormat] = useState("zip");
  const [reportDownloading, setReportDownloading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  async function downloadAnalysisReport() {
    setReportError(null);
    setReportDownloading(true);
    try {
      const url = `${API}${LAB}/report/export?range=${encodeURIComponent(reportRange)}&format=${encodeURIComponent(reportFormat)}`;
      const r = await fetch(url);
      if (!r.ok) {
        const t = await r.text();
        let msg = t || r.statusText;
        try {
          const j = JSON.parse(t) as { detail?: string | unknown };
          if (j?.detail != null) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
        } catch {
          /* use raw text */
        }
        throw new Error(msg.slice(0, 400));
      }
      const blob = await r.blob();
      const cd = r.headers.get("Content-Disposition");
      let name =
        reportFormat === "zip"
          ? "crypto_lab_report.zip"
          : reportFormat === "json"
            ? "report.json"
            : reportFormat === "csv"
              ? "report.csv"
              : "report.md";
      const m = cd?.match(/filename="([^"]+)"/);
      if (m) name = m[1];
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e: unknown) {
      setReportError(e instanceof Error ? e.message : "Download failed");
    } finally {
      setReportDownloading(false);
    }
  }

  const gens = overview.generations;
  const values = gens.length ? gens.map((g) => g.total_value_usd) : [STARTING_BALANCE];
  const scaleMin = Math.max(0, Math.min(STARTING_BALANCE, ...values) - 500);
  const scaleMax = Math.max(STARTING_BALANCE, ...values) + 500;
  const scaleRange = scaleMax - scaleMin;
  const refLinePct = scaleRange ? ((STARTING_BALANCE - scaleMin) / scaleRange) * 100 : 50;

  return (
    <>
      <WorkerLiveBanner worker={worker} error={workerError} />
      <h2 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem" }}>Dashboard</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "1rem", marginBottom: "2rem" }}>
        <Card title="Bots active" value={String(overview.total_bots_active)} />
        <Card title="Combined P&L" value={formatUsd(overview.combined_pnl_usd)} sub={formatPct(overview.combined_pnl_percent)} positive={overview.combined_pnl_usd >= 0} />
        <Card title="Open positions" value={String(overview.total_open_positions)} />
        <Card
          title="Last lab cycle"
          value={worker?.lab_last_cycle_at ? formatTime(worker.lab_last_cycle_at) : overview.last_cycle ? formatTime(overview.last_cycle) : "—"}
          sub={
            worker?.lab_last_cycle_at
              ? "Same clock as banner — updates when the cloud worker finishes a cycle"
              : overview.last_cycle
                ? "From overview"
                : undefined
          }
        />
      </div>
      <h3 style={{ fontSize: "1rem", color: "var(--text-muted)", marginBottom: "0.75rem" }}>Portfolio value vs $10k</h3>
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: "1rem 1.25rem", marginBottom: "2rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem", fontSize: "0.75rem", color: "var(--text-muted)" }}>
          <span>{formatUsd(scaleMin)}</span>
          <div style={{ flex: 1, position: "relative", height: 4, background: "var(--border)", borderRadius: 2 }}>
            <div style={{ position: "absolute", left: `${refLinePct}%`, top: -2, width: 2, height: 8, background: "var(--text-muted)", borderRadius: 1 }} title="$10k start" />
          </div>
          <span>{formatUsd(scaleMax)}</span>
        </div>
        {gens.map((g) => {
          const pct = Math.min(100, Math.max(0, ((g.total_value_usd - scaleMin) / scaleRange) * 100));
          const isPositive = g.total_value_usd >= STARTING_BALANCE;
          return (
            <div key={g.gen_id} style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "0.75rem" }}>
              <div style={{ width: 140, flexShrink: 0, fontSize: "0.9rem", fontWeight: 500, color: "var(--accent)" }}>{g.label}</div>
              <div style={{ flex: 1, position: "relative", height: 28, background: "var(--surface2)", borderRadius: 6, overflow: "hidden" }}>
                <div style={{ position: "absolute", left: `${refLinePct}%`, top: 0, bottom: 0, width: 2, background: "var(--text-muted)", opacity: 0.8 }} />
                <div
                  style={{
                    position: "absolute",
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: `${pct}%`,
                    background: isPositive ? "var(--green)" : "var(--red)",
                    opacity: 0.85,
                    borderRadius: "6px 0 0 6px",
                  }}
                />
              </div>
              <div style={{ width: 90, textAlign: "right", fontFamily: "var(--font-mono)", fontSize: "0.9rem", color: isPositive ? "var(--green)" : "var(--red)" }}>{formatUsd(g.total_value_usd)}</div>
            </div>
          );
        })}
        <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.5rem" }}>Reference line: $10,000 starting balance</div>
      </div>
      <h3 style={{ fontSize: "1rem", color: "var(--text-muted)", marginBottom: "0.75rem" }}>Performance snapshot</h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "1rem", marginBottom: "2rem" }}>
        {overview.generations.map((g) => (
          <div key={g.gen_id} style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: "1rem" }}>
            <div style={{ fontWeight: 600, color: "var(--accent)" }}>{g.label}</div>
            <div style={{ fontSize: "0.85rem", marginTop: "0.5rem" }}>P&L {formatUsd(g.total_pnl_usd)} ({formatPct(g.total_pnl_percent)})</div>
            <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>Positions: {g.positions_count} · Trades today: {g.trade_count_today}</div>
          </div>
        ))}
      </div>
      <h3 style={{ fontSize: "1rem", color: "var(--text-muted)", marginBottom: "0.75rem" }}>Analysis report</h3>
      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 10,
          padding: "1rem 1.25rem",
          marginBottom: "2rem",
        }}
      >
        <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", margin: "0 0 1rem" }}>
          Export structured data for spreadsheets, quick reading, or AI (ChatGPT). ZIP includes <code style={{ fontSize: "0.8rem" }}>report.json</code>,{" "}
          <code style={{ fontSize: "0.8rem" }}>report.csv</code>, and <code style={{ fontSize: "0.8rem" }}>report.md</code>. API:{" "}
          <code style={{ fontSize: "0.75rem" }}>GET /api/lab/report/export</code>
        </p>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.75rem" }}>
          <label style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
            Range{" "}
            <select
              value={reportRange}
              onChange={(e) => setReportRange(e.target.value)}
              style={{ marginLeft: 4, padding: "0.35rem 0.5rem", borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface2)", color: "inherit" }}
            >
              <option value="all_time">All time</option>
              <option value="last_1h">Last 1 hour</option>
              <option value="last_24h">Last 24 hours</option>
              <option value="last_7d">Last 7 days</option>
            </select>
          </label>
          <label style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
            Format{" "}
            <select
              value={reportFormat}
              onChange={(e) => setReportFormat(e.target.value)}
              style={{ marginLeft: 4, padding: "0.35rem 0.5rem", borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface2)", color: "inherit" }}
            >
              <option value="zip">ZIP (default)</option>
              <option value="json">JSON only</option>
              <option value="csv">CSV only</option>
              <option value="md">Markdown only</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => void downloadAnalysisReport()}
            disabled={reportDownloading}
            style={{
              padding: "0.45rem 1rem",
              borderRadius: 8,
              border: "none",
              background: "var(--accent)",
              color: "#fff",
              fontWeight: 600,
              cursor: reportDownloading ? "wait" : "pointer",
              opacity: reportDownloading ? 0.7 : 1,
            }}
          >
            {reportDownloading ? "Downloading…" : "Download Analysis Report"}
          </button>
        </div>
        {reportError ? (
          <div style={{ marginTop: "0.75rem", fontSize: "0.85rem", color: "var(--red)" }}>{reportError}</div>
        ) : null}
      </div>
      <h3 style={{ fontSize: "1rem", color: "var(--text-muted)", marginBottom: "0.75rem" }}>Market</h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "0.75rem", marginBottom: "2rem" }}>
        {market.slice(0, 6).map((t) => (
          <div key={t.symbol} style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "0.75rem", fontFamily: "var(--font-mono)" }}>
            <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>{t.symbol.replace("USDT", "")}</div>
            <div style={{ fontWeight: 600 }}>{formatUsd(t.price)}</div>
            <div style={{ color: t.change_24h >= 0 ? "var(--green)" : "var(--red)", fontSize: "0.85rem" }}>{formatPct(t.change_24h)} 24h</div>
          </div>
        ))}
      </div>
      <h3 style={{ fontSize: "1rem", color: "var(--text-muted)", marginBottom: "0.75rem" }}>Recent activity</h3>
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, overflow: "auto", maxHeight: 300 }}>
        {overview.recent_activity.length ? (
          overview.recent_activity.slice(0, 25).map((a, i) => (
            <div key={i} style={{ padding: "0.5rem 1rem", borderBottom: "1px solid var(--border)", fontSize: "0.85rem" }}>
              <strong>{a.label}</strong> {a.side?.toUpperCase()} {a.symbol?.replace("USDT", "")} — {a.reason?.slice(0, 50)}… {a.timestamp && formatTime(a.timestamp)}
            </div>
          ))
        ) : (
          <div style={{ padding: "1rem", color: "var(--text-muted)" }}>No activity yet.</div>
        )}
      </div>
    </>
  );
}

function GenTab({
  genId,
  label,
  description,
  detail,
  summary,
  loading,
  error,
  isAi,
  isScalper,
  isMomentumRider,
  isMicroTrader,
}: {
  genId: string;
  label: string;
  description: string;
  detail?: { status: any; positions: Position[]; trades: Trade[] };
  summary?: GenStatus | null;
  loading?: boolean;
  error?: string;
  isAi?: boolean;
  isScalper?: boolean;
  isMomentumRider?: boolean;
  isMicroTrader?: boolean;
}) {
  const [resetting, setResetting] = useState(false);
  const status = detail?.status;
  const positions = Array.isArray(detail?.positions) ? detail.positions : [];
  const trades = Array.isArray(detail?.trades) ? detail.trades : [];
  const decisions = Array.isArray(status?.decisions) ? status.decisions : [];
  const balance = status?.balance_usd ?? summary?.balance_usd;
  const totalValue = status?.total_value_usd ?? summary?.total_value_usd;
  const pnlUsd = status?.total_pnl_usd ?? summary?.total_pnl_usd;
  const pnlPct = status?.total_pnl_percent ?? summary?.total_pnl_percent;
  const tradeCountToday = status?.trade_count_today ?? summary?.trade_count_today ?? 0;
  const sellsWithPnl = trades.filter((t) => t.side === "sell" && t.realized_pnl_usd != null);
  const winCount = sellsWithPnl.filter((t) => (t.realized_pnl_usd ?? 0) > 0).length;
  const winRate = sellsWithPnl.length ? (winCount / sellsWithPnl.length) * 100 : null;
  const avgPerTrade = trades.length && pnlUsd != null ? pnlUsd / trades.length : null;
  const exposureUsd = positions.reduce((s, p) => s + p.value_usd, 0);
  const unrealizedPnl = positions.reduce((s, p) => s + p.pnl_usd, 0);
  const realizedPnl = pnlUsd != null && unrealizedPnl != null ? pnlUsd - unrealizedPnl : null;

  return (
    <>
      <h2 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "0.5rem" }}>{label}</h2>
      <p style={{ color: "var(--text-muted)", marginBottom: "1rem", maxWidth: 600 }}>{description}</p>
      {error && (
        <div style={{ marginBottom: "1rem", padding: "0.75rem", background: "var(--red)", color: "#fff", borderRadius: 8, fontSize: "0.9rem" }}>
          {error}
        </div>
      )}
      {loading && (
        <p style={{ color: "var(--text-muted)", marginBottom: "1rem" }}>Loading positions and trades…</p>
      )}
      {isScalper && (
        <div style={{ marginBottom: "1.5rem" }}>
          <h3 style={{ fontSize: "1rem", color: "var(--text-muted)", marginBottom: "0.75rem" }}>Gen 5: Active strategy</h3>
          <div style={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 10, padding: "1.25rem", display: "grid", gap: "1rem" }}>
            <div>
              <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Status</div>
              <div style={{ fontSize: "1rem", fontWeight: 600 }}>
                {summary?.enabled === false ? "Disabled" : status?.gen5_activity_mode === "protective" ? "Protective mode" : status?.gen5_activity_mode === "waiting" ? "Waiting for conditions" : "Active"}
              </div>
            </div>
            <div>
              <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Strategy summary</div>
              <div style={{ fontSize: "0.95rem" }}>{status?.gen5_strategy_summary ?? "No summary from last cycle yet."}</div>
            </div>
            <div>
              <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Intraday activity</div>
              <div style={{ fontSize: "0.9rem" }}>
                {status?.gen5_activity_mode === "active" && "Actively looking for quick rebound opportunities and short profit windows."}
                {status?.gen5_activity_mode === "protective" && "Market is weak; reducing new entries and only managing existing positions."}
                {status?.gen5_activity_mode === "waiting" && "Market is mixed; waiting for clearer conditions before scalping."}
                {(!status?.gen5_activity_mode || (status?.gen5_activity_mode !== "active" && status?.gen5_activity_mode !== "protective" && status?.gen5_activity_mode !== "waiting")) && "—"}
              </div>
              {tradeCountToday != null && (
                <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: "0.5rem" }}>Trades today: {tradeCountToday}</div>
              )}
            </div>
            <div style={{ borderTop: "1px solid var(--border)", paddingTop: "1rem", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "0.75rem", fontFamily: "var(--font-mono)", fontSize: "0.9rem" }}>
              <div><span style={{ color: "var(--text-muted)" }}>Total P&L</span><br />{pnlUsd != null ? formatUsd(pnlUsd) : "—"}</div>
              <div><span style={{ color: "var(--text-muted)" }}>Win rate</span><br />{winRate != null ? `${winRate.toFixed(1)}%` : "—"}</div>
              <div><span style={{ color: "var(--text-muted)" }}>Trades</span><br />{trades.length}</div>
              <div><span style={{ color: "var(--text-muted)" }}>Avg per trade</span><br />{avgPerTrade != null ? formatUsd(avgPerTrade) : "—"}</div>
              <div><span style={{ color: "var(--text-muted)" }}>Exposure</span><br />{formatUsd(exposureUsd)}</div>
              <div><span style={{ color: "var(--text-muted)" }}>Realized P&L</span><br />{realizedPnl != null ? formatUsd(realizedPnl) : "—"}</div>
              <div><span style={{ color: "var(--text-muted)" }}>Unrealized P&L</span><br /><span style={{ color: unrealizedPnl >= 0 ? "var(--green)" : "var(--red)" }}>{formatUsd(unrealizedPnl)}</span></div>
            </div>
          </div>
        </div>
      )}
      {isMomentumRider && (
        <div style={{ marginBottom: "1.5rem" }}>
          <h3 style={{ fontSize: "1rem", color: "var(--text-muted)", marginBottom: "0.75rem" }}>Gen 6: Momentum rider status</h3>
          <div style={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 10, padding: "1.25rem", display: "grid", gap: "1rem" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "0.75rem", fontSize: "0.9rem" }}>
              <div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Market regime</div>
                <div style={{ fontWeight: 600 }}>{status?.gen6_market_regime ?? "—"}</div>
              </div>
              <div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Runner mode</div>
                <div style={{ fontWeight: 600, color: status?.gen6_any_runner ? "var(--green)" : "var(--text)" }}>{status?.gen6_any_runner ? "Active (≥1 position)" : "None"}</div>
              </div>
              <div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>New entries</div>
                <div style={{ fontWeight: 600 }}>{status?.gen6_protective_entries ? "Paused (weak market)" : "Allowed"}</div>
              </div>
              <div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Avg 24h</div>
                <div style={{ fontFamily: "var(--font-mono)" }}>{status?.gen6_market_avg_24h != null ? formatPct(status.gen6_market_avg_24h) : "—"}</div>
              </div>
            </div>
            <div>
              <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Strategy summary</div>
              <div style={{ fontSize: "0.95rem" }}>{status?.gen6_strategy_summary ?? "No summary from last cycle yet."}</div>
            </div>
            {(status?.gen6_last_exit_reason || status?.gen6_last_exit_tag) && (
              <div style={{ padding: "0.75rem", background: "var(--surface)", borderRadius: 8, border: "1px solid var(--border)" }}>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.35rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Latest exit (last cycle)</div>
                <div style={{ fontSize: "0.9rem", fontWeight: 600 }}>{status?.gen6_last_exit_reason ?? "—"}</div>
                {status?.gen6_last_exit_tag && (
                  <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", fontFamily: "var(--font-mono)", marginTop: "0.25rem" }}>{String(status.gen6_last_exit_tag)}</div>
                )}
              </div>
            )}
            {status?.gen6_evaluation_metrics && typeof status.gen6_evaluation_metrics === "object" && (
              <div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.5rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Tuning &amp; evaluation metrics</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "0.5rem 1rem", fontSize: "0.85rem", fontFamily: "var(--font-mono)" }}>
                  {(() => {
                    const ev = status.gen6_evaluation_metrics as Record<string, unknown>;
                    const n = (k: string) => (typeof ev[k] === "number" ? ev[k] as number : null);
                    const fmt = (k: string) => {
                      const v = n(k);
                      return v != null ? String(v) : "—";
                    };
                    const fmtPct = (k: string) => {
                      const v = n(k);
                      return v != null ? `${(v as number).toFixed(2)}%` : "—";
                    };
                    const fmtUsd = (k: string) => {
                      const v = n(k);
                      return v != null ? formatUsd(v as number) : "—";
                    };
                    return (
                      <>
                        <span>Runner activations: {fmt("runner_activations")}</span>
                        <span>Protected activations: {fmt("protected_activations")}</span>
                        <span>Scale-outs: {fmt("scaleouts")}</span>
                        <span>Exits — trailing: {fmt("exits_trailing")}</span>
                        <span>Exits — timeout: {fmt("exits_timeout")}</span>
                        <span>Exits — weak mom.: {fmt("exits_weak_momentum")}</span>
                        <span>Exits — runner fade: {fmt("exits_runner_weak")}</span>
                        <span>Exits — failed rebound: {fmt("exits_failed_rebound")}</span>
                        <span style={{ gridColumn: "1 / -1", marginTop: "0.35rem", paddingTop: "0.5rem", borderTop: "1px solid var(--border)" }} />
                        <span>Avg peak P&amp;L% (legs): {fmtPct("avg_peak_pnl_pct")}</span>
                        <span>Avg P&amp;L% at exit: {fmtPct("avg_pnl_at_exit_pct")}</span>
                        <span>Avg giveback from peak%: {fmtPct("avg_giveback_pct")}</span>
                        <span>Avg cycles (winners): {fmt("avg_cycles_winners")}</span>
                        <span>Avg cycles (losers / flat exit): {fmt("avg_cycles_losers")}</span>
                        <span>Avg realized $ / Gen6 sell: {fmtUsd("avg_realized_pnl_usd")}</span>
                        <span>Gen6 sells w/ P&amp;L: {fmt("gen6_scored_sell_count")}</span>
                      </>
                    );
                  })()}
                </div>
                <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.75rem", marginBottom: 0 }}>
                  Counters accrue since bot state was last reset. Leg averages use recent closed legs (incl. partial scale-outs in history).
                </p>
              </div>
            )}
            {Array.isArray(status?.gen6_position_snapshots) && status.gen6_position_snapshots.length > 0 && (
              <div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.5rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Open positions (per-symbol state)</div>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--font-mono)", fontSize: "0.8rem" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                        <th style={{ padding: "0.35rem 0.5rem", color: "var(--text-muted)" }}>Symbol</th>
                        <th style={{ padding: "0.35rem 0.5rem", color: "var(--text-muted)" }}>Stage</th>
                        <th style={{ padding: "0.35rem 0.5rem", color: "var(--text-muted)" }}>Runner</th>
                        <th style={{ padding: "0.35rem 0.5rem", color: "var(--text-muted)" }}>Prot.</th>
                        <th style={{ padding: "0.35rem 0.5rem", color: "var(--text-muted)" }}>Scaled</th>
                        <th style={{ padding: "0.35rem 0.5rem", color: "var(--text-muted)" }}>P&amp;L%</th>
                        <th style={{ padding: "0.35rem 0.5rem", color: "var(--text-muted)" }}>Max seen%</th>
                        <th style={{ padding: "0.35rem 0.5rem", color: "var(--text-muted)" }}>DD peak%</th>
                        <th style={{ padding: "0.35rem 0.5rem", color: "var(--text-muted)" }}>Cyc</th>
                        <th style={{ padding: "0.35rem 0.5rem", color: "var(--text-muted)" }}>Trail%</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(status.gen6_position_snapshots as any[]).map((row: any, i: number) => (
                        <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
                          <td style={{ padding: "0.35rem 0.5rem" }}>{(row.symbol || "").replace("USDT", "")}</td>
                          <td style={{ padding: "0.35rem 0.5rem" }}>{row.stage ?? "—"}</td>
                          <td style={{ padding: "0.35rem 0.5rem" }}>{row.runner_active ? "yes" : "no"}</td>
                          <td style={{ padding: "0.35rem 0.5rem" }}>{row.protected ? "yes" : "no"}</td>
                          <td style={{ padding: "0.35rem 0.5rem" }}>{row.scaled_out ? "yes" : "no"}</td>
                          <td style={{ padding: "0.35rem 0.5rem" }}>{row.pnl_pct != null ? formatPct(row.pnl_pct) : "—"}</td>
                          <td style={{ padding: "0.35rem 0.5rem" }}>{row.max_pnl_pct_seen != null ? formatPct(row.max_pnl_pct_seen) : "—"}</td>
                          <td style={{ padding: "0.35rem 0.5rem" }}>{row.drawdown_from_peak_pct != null ? formatPct(row.drawdown_from_peak_pct) : "—"}</td>
                          <td style={{ padding: "0.35rem 0.5rem" }}>{row.cycles_held ?? "—"}</td>
                          <td style={{ padding: "0.35rem 0.5rem" }}>{row.trail_threshold_pct != null ? `${Number(row.trail_threshold_pct).toFixed(2)}%` : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
            <div style={{ borderTop: "1px solid var(--border)", paddingTop: "1rem", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "0.75rem", fontFamily: "var(--font-mono)", fontSize: "0.9rem" }}>
              <div><span style={{ color: "var(--text-muted)" }}>Total P&amp;L</span><br />{pnlUsd != null ? formatUsd(pnlUsd) : "—"}</div>
              <div><span style={{ color: "var(--text-muted)" }}>Win rate (scored sells)</span><br />{winRate != null ? `${winRate.toFixed(1)}%` : "—"}</div>
              <div><span style={{ color: "var(--text-muted)" }}>Trades</span><br />{trades.length}</div>
              <div><span style={{ color: "var(--text-muted)" }}>Exposure</span><br />{formatUsd(exposureUsd)}</div>
              <div><span style={{ color: "var(--text-muted)" }}>Unrealized P&amp;L</span><br /><span style={{ color: unrealizedPnl >= 0 ? "var(--green)" : "var(--red)" }}>{formatUsd(unrealizedPnl)}</span></div>
            </div>
          </div>
        </div>
      )}
      {isMicroTrader && (
        <div style={{ marginBottom: "1.5rem" }}>
          <h3 style={{ fontSize: "1rem", color: "var(--text-muted)", marginBottom: "0.75rem" }}>Gen 7: Micro-trader status</h3>
          <div style={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 10, padding: "1.25rem", display: "grid", gap: "1rem" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "0.75rem", fontSize: "0.9rem" }}>
              <div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Operational state</div>
                <div style={{ fontWeight: 600 }}>
                  {summary?.enabled === false
                    ? "Disabled"
                    : status?.gen7_operational_state === "defensive_mode"
                      ? "Defensive mode"
                      : status?.gen7_operational_state === "in_trade"
                        ? "In a trade"
                        : "Scanning"}
                </div>
              </div>
              <div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Market regime</div>
                <div style={{ fontWeight: 600 }}>{status?.gen7_market_regime ?? "—"}</div>
              </div>
              <div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>New entries</div>
                <div style={{ fontWeight: 600 }}>{status?.gen7_defensive_entries ? "Paused (defensive)" : "Allowed"}</div>
              </div>
              <div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Avg 24h</div>
                <div style={{ fontFamily: "var(--font-mono)" }}>{status?.gen7_market_avg_24h != null ? formatPct(status.gen7_market_avg_24h) : "—"}</div>
              </div>
            </div>
            <div>
              <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Strategy summary</div>
              <div style={{ fontSize: "0.95rem" }}>{status?.gen7_strategy_summary ?? "No summary from last cycle yet."}</div>
            </div>
            <div style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
              Identity: short holds, small targets, frequent turnover — harvests repeated small moves; does not ride large trends like Gen 6.
            </div>
            {(status?.gen7_last_exit_reason || status?.gen7_last_exit_tag) && (
              <div style={{ padding: "0.75rem", background: "var(--surface)", borderRadius: 8, border: "1px solid var(--border)" }}>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.35rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Latest exit (last cycle)</div>
                <div style={{ fontSize: "0.9rem", fontWeight: 600 }}>{status?.gen7_last_exit_reason ?? "—"}</div>
                {status?.gen7_last_exit_tag && (
                  <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", fontFamily: "var(--font-mono)", marginTop: "0.25rem" }}>{String(status.gen7_last_exit_tag)}</div>
                )}
              </div>
            )}
            {status?.gen7_evaluation_metrics && typeof status.gen7_evaluation_metrics === "object" && (
              <div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.5rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Session counters (since reset)</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "0.5rem 1rem", fontSize: "0.85rem", fontFamily: "var(--font-mono)" }}>
                  {(() => {
                    const ev = status.gen7_evaluation_metrics as Record<string, unknown>;
                    const n = (k: string) => (typeof ev[k] === "number" ? (ev[k] as number) : null);
                    const fmt = (k: string) => {
                      const v = n(k);
                      return v != null ? String(v) : "—";
                    };
                    return (
                      <>
                        <span>Micro entries: {fmt("gen7_entries")}</span>
                        <span>Exits — quick profit: {fmt("gen7_exits_quick_profit")}</span>
                        <span>Exits — stop: {fmt("gen7_exits_stop")}</span>
                        <span>Exits — timeout: {fmt("gen7_exits_timeout")}</span>
                        <span>Exits — stall: {fmt("gen7_exits_stall")}</span>
                        <span>Exits — momentum / tape: {fmt("gen7_exits_momentum")}</span>
                      </>
                    );
                  })()}
                </div>
              </div>
            )}
            {Array.isArray(status?.gen7_position_snapshots) && status.gen7_position_snapshots.length > 0 && (
              <div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.5rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Open positions (per-symbol state)</div>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--font-mono)", fontSize: "0.8rem" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                        <th style={{ padding: "0.35rem 0.5rem", color: "var(--text-muted)" }}>Symbol</th>
                        <th style={{ padding: "0.35rem 0.5rem", color: "var(--text-muted)" }}>Stage</th>
                        <th style={{ padding: "0.35rem 0.5rem", color: "var(--text-muted)" }}>P&amp;L%</th>
                        <th style={{ padding: "0.35rem 0.5rem", color: "var(--text-muted)" }}>Max seen%</th>
                        <th style={{ padding: "0.35rem 0.5rem", color: "var(--text-muted)" }}>Cycles</th>
                        <th style={{ padding: "0.35rem 0.5rem", color: "var(--text-muted)" }}>Stall</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(status.gen7_position_snapshots as any[]).map((row: any, i: number) => (
                        <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
                          <td style={{ padding: "0.35rem 0.5rem" }}>{(row.symbol || "").replace("USDT", "")}</td>
                          <td style={{ padding: "0.35rem 0.5rem" }}>{row.stage ?? "—"}</td>
                          <td style={{ padding: "0.35rem 0.5rem" }}>{row.pnl_pct != null ? formatPct(row.pnl_pct) : "—"}</td>
                          <td style={{ padding: "0.35rem 0.5rem" }}>{row.max_pnl_pct_seen != null ? formatPct(row.max_pnl_pct_seen) : "—"}</td>
                          <td style={{ padding: "0.35rem 0.5rem" }}>{row.cycles_held ?? "—"}</td>
                          <td style={{ padding: "0.35rem 0.5rem" }}>{row.stall_cycles ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
            <div style={{ borderTop: "1px solid var(--border)", paddingTop: "1rem", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "0.75rem", fontFamily: "var(--font-mono)", fontSize: "0.9rem" }}>
              <div><span style={{ color: "var(--text-muted)" }}>Total P&amp;L</span><br />{pnlUsd != null ? formatUsd(pnlUsd) : "—"}</div>
              <div><span style={{ color: "var(--text-muted)" }}>Win rate (scored sells)</span><br />{winRate != null ? `${winRate.toFixed(1)}%` : "—"}</div>
              <div><span style={{ color: "var(--text-muted)" }}>Trades</span><br />{trades.length}</div>
              <div><span style={{ color: "var(--text-muted)" }}>Trades today</span><br />{tradeCountToday}</div>
              <div><span style={{ color: "var(--text-muted)" }}>Exposure</span><br />{formatUsd(exposureUsd)}</div>
              <div><span style={{ color: "var(--text-muted)" }}>Unrealized P&amp;L</span><br /><span style={{ color: unrealizedPnl >= 0 ? "var(--green)" : "var(--red)" }}>{formatUsd(unrealizedPnl)}</span></div>
            </div>
          </div>
        </div>
      )}
      {isAi && (
        <div style={{ marginBottom: "1.5rem" }}>
          <h3 style={{ fontSize: "1rem", color: "var(--text-muted)", marginBottom: "0.75rem" }}>Gen 4 decision</h3>
          <div style={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 10, padding: "1.25rem", display: "grid", gap: "1rem" }}>
            {/* 1. Final decision */}
            <div>
              <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Final decision</div>
              <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "var(--accent)" }}>
                {(status?.last_decision ?? summary?.last_decision) || "—"}
              </div>
            </div>
            {/* 2. Safety override */}
            <div>
              <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Safety override applied</div>
              <div style={{ fontSize: "0.95rem" }}>
                {status?.last_ai_override_applied === true ? (
                  <>Yes — {status?.last_ai_override_type === "all_red_significant_down" ? "All symbols significantly down → block" : status?.last_ai_override_type === "all_red_meaningful_weakness" ? "All symbols red, meaningful weakness → at least limit" : String(status?.last_ai_override_type ?? "override")}</>
                ) : status?.last_ai_override_applied === false || status?.last_decision != null || summary?.last_decision != null ? (
                  "No"
                ) : (
                  "—"
                )}
              </div>
            </div>
            {/* 3. Market summary values */}
            {status?.last_ai_market_stats && (
              <div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.5rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Market summary (used for decision)</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "0.5rem 1.5rem", fontSize: "0.9rem", fontFamily: "var(--font-mono)" }}>
                  <span>Avg 24h: {formatPct((status?.last_ai_market_stats as any)?.average_24h ?? 0)}</span>
                  <span>Red / Green: {(status?.last_ai_market_stats as any)?.red_count ?? "—"} / {(status?.last_ai_market_stats as any)?.green_count ?? "—"}</span>
                  <span>Strongest loser: {(status?.last_ai_market_stats as any)?.strongest_loser_symbol ?? "—"} {formatPct((status?.last_ai_market_stats as any)?.strongest_loser ?? 0)}</span>
                  <span>Strongest gainer: {(status?.last_ai_market_stats as any)?.strongest_gainer_symbol ?? "—"} {formatPct((status?.last_ai_market_stats as any)?.strongest_gainer ?? 0)}</span>
                  <span>Broad weakness: {(status?.last_ai_market_stats as any)?.broad_weakness ? "yes" : "no"}</span>
                  <span>Market character: {(status?.last_ai_market_stats as any)?.market_look ?? "—"}</span>
                </div>
              </div>
            )}
            {/* 4. Decision source */}
            <div>
              <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Decision from</div>
              <div style={{ fontSize: "0.95rem" }}>
                {status?.last_ai_decision_source === "ai_only" && "AI only"}
                {status?.last_ai_decision_source === "ai_plus_override" && "AI + safety override"}
                {status?.last_ai_decision_source === "fallback_limit" && "Fallback to conservative limit"}
                {(!status?.last_ai_decision_source && (status?.last_decision != null || summary?.last_decision != null)) && "—"}
                {!status?.last_ai_decision_source && status?.last_decision == null && summary?.last_decision == null && "No decision from last cycle yet."}
              </div>
            </div>
            {/* Reasoning */}
            <div style={{ borderTop: "1px solid var(--border)", paddingTop: "1rem" }}>
              <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Reasoning</div>
              {(status?.last_reasoning ?? summary?.last_reasoning) ? (
                <div style={{ fontSize: "0.9rem" }}>{status?.last_reasoning ?? summary?.last_reasoning}</div>
              ) : (
                <div style={{ fontSize: "0.9rem", color: "var(--text-muted)" }}>No reasoning from last cycle yet.</div>
              )}
              <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "0.5rem" }}>Each buy/sell in the table below includes this reasoning.</div>
            </div>
          </div>
        </div>
      )}
      {isAi && Array.isArray(status?.gen4_decision_history) && status.gen4_decision_history.length > 0 && (
        <>
          <h3 style={{ fontSize: "1rem", color: "var(--text-muted)", marginBottom: "0.5rem" }}>Recent decision log</h3>
          <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, overflowX: "auto", marginBottom: "1.5rem" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--font-mono)", fontSize: "0.8rem" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                  <th style={{ padding: "0.5rem 0.75rem", color: "var(--text-muted)", whiteSpace: "nowrap" }}>Time</th>
                  <th style={{ padding: "0.5rem 0.75rem", color: "var(--text-muted)" }}>Decision</th>
                  <th style={{ padding: "0.5rem 0.75rem", color: "var(--text-muted)" }}>Source</th>
                  <th style={{ padding: "0.5rem 0.75rem", color: "var(--text-muted)" }}>Override</th>
                  <th style={{ padding: "0.5rem 0.75rem", color: "var(--text-muted)" }}>Override type</th>
                  <th style={{ padding: "0.5rem 0.75rem", color: "var(--text-muted)" }}>Avg 24h</th>
                  <th style={{ padding: "0.5rem 0.75rem", color: "var(--text-muted)" }}>R / G</th>
                  <th style={{ padding: "0.5rem 0.75rem", color: "var(--text-muted)" }}>Broad weak</th>
                  <th style={{ padding: "0.5rem 0.75rem", color: "var(--text-muted)" }}>Character</th>
                  <th style={{ padding: "0.5rem 0.75rem", color: "var(--text-muted)", maxWidth: 220 }}>Reasoning</th>
                </tr>
              </thead>
              <tbody>
                {[...(status.gen4_decision_history as any[])].reverse().slice(0, 25).map((h, i) => (
                  <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: "0.5rem 0.75rem", color: "var(--text-muted)", whiteSpace: "nowrap" }}>{h.timestamp ? formatDateTime(h.timestamp) : "—"}</td>
                    <td style={{ padding: "0.5rem 0.75rem", fontWeight: 600, color: "var(--accent)" }}>{h.decision ?? "—"}</td>
                    <td style={{ padding: "0.5rem 0.75rem" }}>{h.decision_source === "ai_only" ? "AI only" : h.decision_source === "ai_plus_override" ? "AI + override" : h.decision_source === "fallback_limit" ? "Fallback" : h.decision_source ?? "—"}</td>
                    <td style={{ padding: "0.5rem 0.75rem" }}>{h.override_applied === true ? "Yes" : "No"}</td>
                    <td style={{ padding: "0.5rem 0.75rem" }}>{h.override_applied === true && h.override_type ? (h.override_type === "all_red_significant_down" ? "→ block" : h.override_type === "all_red_meaningful_weakness" ? "→ limit" : String(h.override_type)) : "—"}</td>
                    <td style={{ padding: "0.5rem 0.75rem" }}>{h.average_24h != null ? formatPct(h.average_24h) : "—"}</td>
                    <td style={{ padding: "0.5rem 0.75rem" }}>{h.red_count != null && h.green_count != null ? `${h.red_count} / ${h.green_count}` : "—"}</td>
                    <td style={{ padding: "0.5rem 0.75rem" }}>{h.broad_weakness === true ? "yes" : h.broad_weakness === false ? "no" : "—"}</td>
                    <td style={{ padding: "0.5rem 0.75rem" }}>{h.market_look ?? "—"}</td>
                    <td style={{ padding: "0.5rem 0.75rem", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis" }} title={h.reasoning_summary ?? ""}>{h.reasoning_summary ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "stretch", marginBottom: "1rem" }}>
        <div style={{ flex: "1 1 150px", minWidth: 140, maxWidth: 260, display: "flex" }}>
          <Card title="Balance" value={balance != null ? formatUsd(balance) : "—"} />
        </div>
        <div style={{ flex: "1 1 150px", minWidth: 140, maxWidth: 260, display: "flex" }}>
          <Card title="Portfolio value" value={totalValue != null ? formatUsd(totalValue) : "—"} />
        </div>
        <div style={{ flex: "1 1 150px", minWidth: 140, maxWidth: 260, display: "flex" }}>
          <Card title="P&L" value={pnlUsd != null ? formatUsd(pnlUsd) : "—"} sub={pnlPct != null ? formatPct(pnlPct) : undefined} positive={pnlUsd != null ? pnlUsd >= 0 : undefined} />
        </div>
        <div style={{ flex: "1 1 150px", minWidth: 140, maxWidth: 260, display: "flex" }}>
          <Card title="Trades today" value={String(tradeCountToday)} />
        </div>
        <button
          onClick={async () => {
            setResetting(true);
            await fetch(API + LAB + "/generations/" + genId + "/reset", { method: "POST" });
            setResetting(false);
            window.location.reload();
          }}
          disabled={resetting}
          style={{ padding: "0.5rem 1rem", background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text)", cursor: resetting ? "not-allowed" : "pointer", alignSelf: "center" }}
        >
          {resetting ? "Resetting…" : "Reset to fresh balance"}
        </button>
      </div>
      <h3 style={{ fontSize: "1rem", marginBottom: "0.5rem" }}>Positions</h3>
      {positions.length ? (
        <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--font-mono)", fontSize: "0.9rem", marginBottom: "1.5rem" }}>
          <thead><tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}><th style={{ padding: "0.5rem 1rem", color: "var(--text-muted)" }}>Symbol</th><th style={{ padding: "0.5rem 1rem", color: "var(--text-muted)" }}>Qty</th><th style={{ padding: "0.5rem 1rem", color: "var(--text-muted)" }}>Value</th><th style={{ padding: "0.5rem 1rem", color: "var(--text-muted)" }}>P&L</th></tr></thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.symbol} style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "0.5rem 1rem" }}>{p.symbol.replace("USDT", "")}</td>
                <td style={{ padding: "0.5rem 1rem" }}>{p.quantity.toFixed(6)}</td>
                <td style={{ padding: "0.5rem 1rem" }}>{formatUsd(p.value_usd)}</td>
                <td style={{ padding: "0.5rem 1rem", color: p.pnl_usd >= 0 ? "var(--green)" : "var(--red)" }}>{formatUsd(p.pnl_usd)} ({formatPct(p.pnl_percent)})</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p style={{ color: "var(--text-muted)", marginBottom: "1.5rem" }}>No open positions.</p>
      )}
      <h3 style={{ fontSize: "1rem", marginBottom: "0.5rem" }}>Recent trades</h3>
      {trades.length ? (
        <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--font-mono)", fontSize: "0.85rem" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
              <th style={{ padding: "0.5rem 1rem", color: "var(--text-muted)" }}>Time</th>
              <th style={{ padding: "0.5rem 1rem", color: "var(--text-muted)" }}>Side</th>
              <th style={{ padding: "0.5rem 1rem", color: "var(--text-muted)" }}>Symbol</th>
              <th style={{ padding: "0.5rem 1rem", color: "var(--text-muted)", whiteSpace: "nowrap" }}>Gain / loss</th>
              <th style={{ padding: "0.5rem 1rem", color: "var(--text-muted)" }}>Why</th>
            </tr>
          </thead>
          <tbody>
            {trades.slice(0, 20).map((t) => (
              <tr key={t.id} style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "0.5rem 1rem", color: "var(--text-muted)" }}>{formatTime(t.timestamp)}</td>
                <td style={{ padding: "0.5rem 1rem", color: t.side === "buy" ? "var(--green)" : "var(--red)" }}>{t.side.toUpperCase()}</td>
                <td style={{ padding: "0.5rem 1rem" }}>{t.symbol.replace("USDT", "")}</td>
                <td style={{ padding: "0.5rem 1rem", fontVariantNumeric: "tabular-nums" }}>
                  {t.side === "sell" && t.realized_pnl_usd != null ? (
                    <span style={{ fontWeight: 600, color: t.realized_pnl_usd >= 0 ? "var(--green)" : "var(--red)" }} title="Realized vs average entry (after fee)">
                      {t.realized_pnl_usd >= 0 ? "+" : "−"}
                      {formatUsd(Math.abs(t.realized_pnl_usd))}
                    </span>
                  ) : t.side === "buy" ? (
                    <span style={{ color: "var(--text-muted)" }} title="Cash deployed; P&amp;L is unrealized until you sell">
                      {formatUsd(-tradeBuySpendUsd(t))} out
                    </span>
                  ) : (
                    <span style={{ color: "var(--text-muted)" }}>—</span>
                  )}
                </td>
                <td style={{ padding: "0.5rem 1rem" }}>{t.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p style={{ color: "var(--text-muted)" }}>No trades yet.</p>
      )}
      {(genId === "3" || genId === "6") && (
        <>
          <h3 style={{ fontSize: "1rem", marginTop: "1.5rem", marginBottom: "0.5rem" }}>{genId === "6" ? "Recent decisions & reasoning" : "Why no trade"}</h3>
          {decisions.length ? (
            <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--font-mono)", fontSize: "0.85rem" }}>
              <thead><tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}><th style={{ padding: "0.5rem 1rem", color: "var(--text-muted)" }}>Time</th><th style={{ padding: "0.5rem 1rem", color: "var(--text-muted)" }}>Symbol</th><th style={{ padding: "0.5rem 1rem", color: "var(--text-muted)" }}>Action</th><th style={{ padding: "0.5rem 1rem", color: "var(--text-muted)" }}>Reason</th></tr></thead>
              <tbody>
                {[...decisions].reverse().slice(0, 20).map((d, i) => (
                  <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: "0.5rem 1rem", color: "var(--text-muted)" }}>{d.timestamp ? formatDateTime(d.timestamp) : "—"}</td>
                    <td style={{ padding: "0.5rem 1rem" }}>{(d.symbol || "").replace("USDT", "")}</td>
                    <td style={{ padding: "0.5rem 1rem", color: "var(--text-muted)" }}>{d.action || "skip"}</td>
                    <td style={{ padding: "0.5rem 1rem" }}>{d.reason || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p style={{ color: "var(--text-muted)" }}>
              {genId === "6"
                ? "No decisions logged yet. Entries, exits, scale-outs, and status updates appear here each cycle."
                : "No decisions recorded yet. Skip reasons will appear here when the bot chooses not to buy."}
            </p>
          )}
        </>
      )}
    </>
  );
}

function ComparisonTab({ rows }: { rows: ComparisonRow[] }) {
  const sorted = [...rows].sort((a, b) => b.pnl_usd - a.pnl_usd);
  return (
    <>
      <h2 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "0.5rem" }}>Side-by-side comparison</h2>
      <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "1rem", maxWidth: 800 }}>
        <strong>Win rate</strong> = percentage of <strong>sells</strong> that locked in a <strong>profit</strong> (realized P&amp;L vs average entry, after fees). Buys are not part of this ratio. If no sells have P&amp;L recorded yet, the rate shows &quot;—&quot;.
      </p>
      <div style={{ overflowX: "auto", border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface)" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--font-mono)", fontSize: "0.9rem" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
              <th style={{ padding: "0.75rem 1rem", color: "var(--text-muted)" }}>Generation</th>
              <th style={{ padding: "0.75rem 1rem", color: "var(--text-muted)" }}>P&L</th>
              <th style={{ padding: "0.75rem 1rem", color: "var(--text-muted)" }}>Trades</th>
              <th style={{ padding: "0.75rem 1rem", color: "var(--text-muted)" }}>Win rate</th>
              <th style={{ padding: "0.75rem 1rem", color: "var(--text-muted)" }}>Open pos</th>
              <th style={{ padding: "0.75rem 1rem", color: "var(--text-muted)" }}>Cash</th>
              <th style={{ padding: "0.75rem 1rem", color: "var(--text-muted)" }}>Exposure</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              <tr key={r.gen_id} style={{ borderBottom: "1px solid var(--border)", background: i === 0 ? "var(--surface2)" : undefined }}>
                <td style={{ padding: "0.75rem 1rem", fontWeight: 600 }}>{r.label}{i === 0 ? " ↑" : ""}</td>
                <td style={{ padding: "0.75rem 1rem", color: r.pnl_usd >= 0 ? "var(--green)" : "var(--red)" }}>{formatUsd(r.pnl_usd)} ({formatPct(r.pnl_percent)})</td>
                <td style={{ padding: "0.75rem 1rem" }}>{r.trade_count}</td>
                <td style={{ padding: "0.75rem 1rem" }}>{r.win_rate != null ? r.win_rate.toFixed(1) + "%" : "—"}</td>
                <td style={{ padding: "0.75rem 1rem" }}>{r.open_positions}</td>
                <td style={{ padding: "0.75rem 1rem" }}>{formatUsd(r.cash_balance)}</td>
                <td style={{ padding: "0.75rem 1rem" }}>{formatUsd(r.exposure_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function SettingsTab() {
  const { data: settings, refetch } = usePoll<{ global_defaults: Record<string, any>; generations: Record<string, any>; api_keys: Record<string, string> }>(API + LAB + "/settings", 30000);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<typeof settings>(null);

  useEffect(() => {
    if (settings) setForm(settings);
  }, [settings]);

  if (!form) return <p style={{ color: "var(--text-muted)" }}>Loading settings…</p>;

  const global = form.global_defaults || {};
  const updateGlobal = (k: string, v: any) => setForm((f) => f ? { ...f, global_defaults: { ...f.global_defaults, [k]: v } } : f);

  return (
    <>
      <h2 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem" }}>Settings</h2>
      <p style={{ color: "var(--text-muted)", marginBottom: "1.5rem" }}>Configure paper trading defaults and API keys. Stored on the server only.</p>
      <section style={{ marginBottom: "2rem" }}>
        <h3 style={{ fontSize: "1rem", marginBottom: "0.75rem" }}>Global defaults</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "1rem" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Starting balance ($)</span>
            <input type="number" step="100" value={global.starting_balance ?? 10000} onChange={(e) => updateGlobal("starting_balance", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Price update interval (sec)</span>
            <input type="number" min="60" value={global.price_update_interval_seconds ?? 90} onChange={(e) => updateGlobal("price_update_interval_seconds", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Position size %</span>
            <input type="number" step="0.5" value={global.position_size_pct ?? 10} onChange={(e) => updateGlobal("position_size_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Max open positions</span>
            <input type="number" min="1" value={global.max_open_positions ?? 5} onChange={(e) => updateGlobal("max_open_positions", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
          </label>
        </div>
      </section>
      <section style={{ marginBottom: "2rem" }}>
        <h3 style={{ fontSize: "1rem", marginBottom: "0.75rem" }}>Gen 5: Aggressive Scalper Bot</h3>
        <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "1rem" }}>Intraday scalper: smaller positions, faster targets, shorter holds. Configure pacing, sizing, and risk.</p>
        {(() => {
          const gens = form.generations || {};
          const g5 = gens["5"] || { enabled: true, label: "Aggressive Scalper Bot", overrides: {} };
          const ov = g5.overrides || {};
          const update5 = (key: string, val: any) => setForm((f) => {
            if (!f) return f;
            const generations = { ...f.generations };
            generations["5"] = { ...generations["5"], overrides: { ...(generations["5"]?.overrides || {}), [key]: val } };
            return { ...f, generations };
          });
          const update5Enabled = (v: boolean) => setForm((f) => {
            if (!f) return f;
            const generations = { ...f.generations };
            generations["5"] = { ...generations["5"], enabled: v };
            return { ...f, generations };
          });
          return (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "1rem", padding: "1rem", background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 10 }}>
              <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <input type="checkbox" checked={g5.enabled !== false} onChange={(e) => update5Enabled(e.target.checked)} />
                <span style={{ fontSize: "0.9rem" }}>Enabled</span>
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Starting balance ($)</span>
                <input type="number" step="100" min="0" value={ov.starting_balance ?? 10000} onChange={(e) => update5("starting_balance", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Position size %</span>
                <input type="number" step="0.5" min="0.5" value={ov.position_size_pct ?? 3} onChange={(e) => update5("position_size_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Cooldown (min)</span>
                <input type="number" step="1" min="0" value={ov.cooldown_minutes ?? 5} onChange={(e) => update5("cooldown_minutes", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Take profit %</span>
                <input type="number" step="0.1" value={ov.take_profit_pct ?? 0.4} onChange={(e) => update5("take_profit_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Stop loss %</span>
                <input type="number" step="0.1" value={ov.stop_loss_pct ?? -0.6} onChange={(e) => update5("stop_loss_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Max open positions</span>
                <input type="number" min="1" value={ov.max_open_positions ?? 4} onChange={(e) => update5("max_open_positions", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Max exposure per coin %</span>
                <input type="number" step="1" value={ov.max_exposure_per_coin_pct ?? 12} onChange={(e) => update5("max_exposure_per_coin_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Max total exposure %</span>
                <input type="number" step="1" value={ov.max_total_exposure_pct ?? 50} onChange={(e) => update5("max_total_exposure_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Max trades per day</span>
                <input type="number" min="1" value={ov.max_trades_per_day ?? 30} onChange={(e) => update5("max_trades_per_day", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Min trade USD</span>
                <input type="number" min="0" value={ov.min_trade_usd ?? 25} onChange={(e) => update5("min_trade_usd", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
            </div>
          );
        })()}
      </section>
      <section style={{ marginBottom: "2rem" }}>
        <h3 style={{ fontSize: "1rem", marginBottom: "0.75rem" }}>Gen 6: Momentum Rider Bot</h3>
        <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "1rem" }}>
          Staged profit, runner mode, trailing exits, partial scale-out. Entries need dip context <strong>plus</strong> rebound/stabilization vs the prior lab price tick (not dip-only).
        </p>
        {(() => {
          const gens = form.generations || {};
          const g6 = gens["6"] || { enabled: true, label: "Momentum Rider Bot", overrides: {} };
          const ov = g6.overrides || {};
          const update6 = (key: string, val: any) => setForm((f) => {
            if (!f) return f;
            const generations = { ...f.generations };
            generations["6"] = { ...generations["6"], overrides: { ...(generations["6"]?.overrides || {}), [key]: val } };
            return { ...f, generations };
          });
          const update6Enabled = (v: boolean) => setForm((f) => {
            if (!f) return f;
            const generations = { ...f.generations };
            generations["6"] = { ...generations["6"], enabled: v };
            return { ...f, generations };
          });
          return (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "1rem", padding: "1rem", background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 10 }}>
              <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <input type="checkbox" checked={g6.enabled !== false} onChange={(e) => update6Enabled(e.target.checked)} />
                <span style={{ fontSize: "0.9rem" }}>Enabled</span>
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Starting balance ($)</span>
                <input type="number" step="100" min="0" value={ov.starting_balance ?? 10000} onChange={(e) => update6("starting_balance", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Position size %</span>
                <input type="number" step="0.5" min="0.5" value={ov.position_size_pct ?? 5} onChange={(e) => update6("position_size_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Cooldown (min)</span>
                <input type="number" step="1" min="0" value={ov.cooldown_minutes ?? 7} onChange={(e) => update6("cooldown_minutes", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Stop loss % (position)</span>
                <input type="number" step="0.05" value={ov.stop_loss_pct ?? -1.12} onChange={(e) => update6("stop_loss_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Min dip % (entry 24h)</span>
                <input type="number" step="0.05" value={ov.min_price_drop_pct ?? -1.08} onChange={(e) => update6("min_price_drop_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Protected profit % (stage 1)</span>
                <input type="number" step="0.05" value={ov.gen6_protect_profit_pct ?? 0.42} onChange={(e) => update6("gen6_protect_profit_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Runner activation %</span>
                <input type="number" step="0.05" value={ov.gen6_runner_activation_pct ?? 0.52} onChange={(e) => update6("gen6_runner_activation_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Scale-out at % profit</span>
                <input type="number" step="0.05" value={ov.gen6_scaleout_pct ?? 0.78} onChange={(e) => update6("gen6_scaleout_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Scale-out fraction (0–1)</span>
                <input type="number" step="0.05" min="0" max="1" value={ov.gen6_scaleout_fraction ?? 0.28} onChange={(e) => update6("gen6_scaleout_fraction", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Max hold (cycles)</span>
                <input type="number" min="5" value={ov.gen6_max_hold_cycles ?? 46} onChange={(e) => update6("gen6_max_hold_cycles", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Stall cycles (weak exit)</span>
                <input type="number" min="1" value={ov.gen6_stall_cycles ?? 11} onChange={(e) => update6("gen6_stall_cycles", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Stall epsilon % (flat detection)</span>
                <input type="number" step="0.01" min="0.02" value={ov.gen6_stall_epsilon_pct ?? 0.055} onChange={(e) => update6("gen6_stall_epsilon_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Max trades / day</span>
                <input type="number" min="1" value={ov.max_trades_per_day ?? 40} onChange={(e) => update6("max_trades_per_day", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
            </div>
          );
        })()}
      </section>
      <section style={{ marginBottom: "2rem" }}>
        <h3 style={{ fontSize: "1rem", marginBottom: "0.75rem" }}>Gen 7: Active Micro-Movement Trader</h3>
        <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "1rem" }}>
          Short-hold micro strategy: small take-profit, tight stop, stall/time exits, defensive mode on broad weakness.
        </p>
        {(() => {
          const gens = form.generations || {};
          const g7 = gens["7"] || { enabled: true, label: "Active Micro-Movement Trader", overrides: {} };
          const ov = g7.overrides || {};
          const update7 = (key: string, val: any) => setForm((f) => {
            if (!f) return f;
            const generations = { ...f.generations };
            generations["7"] = { ...generations["7"], overrides: { ...(generations["7"]?.overrides || {}), [key]: val } };
            return { ...f, generations };
          });
          const update7Enabled = (v: boolean) => setForm((f) => {
            if (!f) return f;
            const generations = { ...f.generations };
            generations["7"] = { ...generations["7"], enabled: v };
            return { ...f, generations };
          });
          return (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "1rem", padding: "1rem", background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 10 }}>
              <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <input type="checkbox" checked={g7.enabled !== false} onChange={(e) => update7Enabled(e.target.checked)} />
                <span style={{ fontSize: "0.9rem" }}>Enabled</span>
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Starting balance ($)</span>
                <input type="number" step="100" min="0" value={ov.starting_balance ?? 10000} onChange={(e) => update7("starting_balance", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Position size %</span>
                <input type="number" step="0.5" min="0.5" value={ov.position_size_pct ?? 2.5} onChange={(e) => update7("position_size_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Cooldown (min)</span>
                <input type="number" step="0.5" min="0" value={ov.cooldown_minutes ?? 3} onChange={(e) => update7("cooldown_minutes", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Take profit % (micro)</span>
                <input type="number" step="0.02" value={ov.gen7_take_profit_pct ?? 0.22} onChange={(e) => update7("gen7_take_profit_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Stop loss %</span>
                <input type="number" step="0.02" value={ov.gen7_stop_loss_pct ?? -0.36} onChange={(e) => update7("gen7_stop_loss_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Max hold (cycles)</span>
                <input type="number" min="3" value={ov.gen7_max_hold_cycles ?? 9} onChange={(e) => update7("gen7_max_hold_cycles", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Hard max hold (cycles)</span>
                <input type="number" min="4" value={ov.gen7_max_hold_hard_cycles ?? 14} onChange={(e) => update7("gen7_max_hold_hard_cycles", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Stall exit (cycles)</span>
                <input type="number" min="2" value={ov.gen7_stall_cycles ?? 4} onChange={(e) => update7("gen7_stall_cycles", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Min dip % (24h entry)</span>
                <input type="number" step="0.02" value={ov.gen7_min_price_drop_pct ?? -0.38} onChange={(e) => update7("gen7_min_price_drop_pct", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Max trades / day</span>
                <input type="number" min="1" value={ov.max_trades_per_day ?? 48} onChange={(e) => update7("max_trades_per_day", e.target.valueAsNumber)} style={{ padding: "0.5rem", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} />
              </label>
            </div>
          );
        })()}
      </section>
      <section style={{ marginBottom: "2rem" }}>
        <h3 style={{ fontSize: "1rem", marginBottom: "0.75rem" }}>API keys (stored on server only)</h3>
        <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "0.5rem" }}>Leave blank or enter new value. Masked values (***) are already set.</p>
        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", maxWidth: 400 }}>
          <label><span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>OpenAI API key</span><input type="password" placeholder={form.api_keys?.openai_api_key || "Optional"} style={{ display: "block", width: "100%", marginTop: "0.25rem", padding: "0.5rem", background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} onChange={(e) => setForm((f) => f ? { ...f, api_keys: { ...f.api_keys, openai_api_key: e.target.value } } : f)} /></label>
          <label><span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>CryptoPanic API key</span><input type="password" placeholder="Optional" style={{ display: "block", width: "100%", marginTop: "0.25rem", padding: "0.5rem", background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} onChange={(e) => setForm((f) => f ? { ...f, api_keys: { ...f.api_keys, cryptopanic_api_key: e.target.value } } : f)} /></label>
          <label><span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>NewsAPI key</span><input type="password" placeholder="Optional" style={{ display: "block", width: "100%", marginTop: "0.25rem", padding: "0.5rem", background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)" }} onChange={(e) => setForm((f) => f ? { ...f, api_keys: { ...f.api_keys, news_api_key: e.target.value } } : f)} /></label>
        </div>
      </section>
      <button
        onClick={async () => {
          setSaving(true);
          await fetch(API + LAB + "/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
          refetch();
          setSaving(false);
        }}
        disabled={saving}
        style={{ padding: "0.6rem 1.2rem", background: "var(--accent)", color: "var(--bg)", border: "none", borderRadius: 8, fontWeight: 600, cursor: saving ? "not-allowed" : "pointer" }}
      >
        {saving ? "Saving…" : "Save settings"}
      </button>
    </>
  );
}
