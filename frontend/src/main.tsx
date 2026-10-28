import React from "react";
import ReactDOM from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bot,
  Calendar,
  Check,
  ChevronRight,
  ClipboardCheck,
  Database,
  FileDown,
  Gauge,
  Loader2,
  Map as MapIcon,
  Maximize2,
  MessageSquare,
  Minimize2,
  Move,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  SlidersHorizontal,
  UserPlus,
  Workflow,
  X,
  Zap
} from "lucide-react";
import * as echarts from "echarts";
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  type Edge,
  type Node
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./styles/app.css";

type Risk = "Critical" | "High" | "Medium" | "Low" | "Normal";
type Page = "command" | "alerts" | "meters" | "forecast" | "grid" | "models" | "audit" | "energy";
type EASummary = { total_input_kwh: number; total_metered_kwh: number; total_technical_loss_kwh: number; total_unexplained_kwh: number; unexplained_pct: number; note?: string };
type EATransformerItem = { transformer_id: string; feeder_id: string; zone: string; rated_kva: number; location_type: string; total_input_kwh: number; total_metered_kwh: number; total_technical_loss_kwh: number; total_unexplained_kwh: number; unexplained_pct: number; days_in_range: number };
type EATransformerDetail = { transformer: Record<string, string | number>; daily_series: Array<{ date: string; input_kwh: number; metered_kwh: number; technical_loss_kwh: number; unexplained_kwh: number; unexplained_pct: number }>; meters: Array<{ meter_id: string; feeder_id: string; substation_id: string; zone: string }>; related_alerts: Array<{ alert_id: string; meter_id: string; alert_timestamp: string; severity: string; status: string; anomaly_score: number; consumption_drop_pct: number; estimated_daily_loss_inr: number }> };
type AlertItem = {
  id: string;
  meterId: string;
  zone: string;
  risk: Risk;
  status: string;
  type: string;
  probability: number;
  revenueImpact: number;
  detectorsAgreeing?: number;
  summary: string;
  nextAction: string;
  urgencyScore?: number;
  transformerId?: string;
  dtUnexplainedPct?: number;
  combinedRiskScore?: number;
};
type Overview = {
  kpis: Record<string, number | string>;
  zones: Array<{ name: string; risk: Risk; openAlerts: number; lossPct: number; feederLossPct?: number; loadPct: number; lat?: number; lon?: number; meterCount?: number; feederCount?: number }>;
  alerts: AlertItem[];
  forecast: ForecastPoint[];
  detectors: Array<{ name: string; purpose: string; status: string; metric: string; coverage: number }>;
  pipeline: Array<{ layer: string; name: string; items: string[]; status: string }>;
  data_quality: Array<{ source: string; freshness: string; missingPct: number; qualityScore?: number; status: string }>;
};
type ForecastPoint = { timestamp: string; actual: number | null; forecast: number; scenario?: number; lower90: number; upper90: number; lower99: number; upper99: number; p50?: number; confidence?: number };
type MeterRow = { meterId: string; consumerType: string; zone: string; feederId: string; tariffCode: string; address: string; active: boolean };
type MeterDetail = {
  meterId: string;
  consumerType: string;
  zone: string;
  substationId: string;
  feederId: string;
  tariffCode: string;
  phase: string;
  contractedKw: number;
  installDate: string;
  latitude: number;
  longitude: number;
  address: string;
  wardName: string;
  communicationProtocol: string;
  firmwareVersion: string;
  meterMake: string;
  mapsUrl: string;
  heatmap: Array<{ day: number; hour: number; kwh: number; zScore: number }>;
  peer: Array<{ timestamp: string; meterKwh: number; peerMean: number; peerUpper: number; peerLower: number }>;
  alerts: AlertItem[];
  audit: Array<{ time: string; action: string; inspector: string; outcome: string; remarks: string }>;
};
type AlertDetail = AlertItem & {
  meter: MeterDetail | null;
  confidence: { totalDetectors: number; detectorsAgreeing: number; consensusLabel: string; breakdown: Array<{ detector: string; score: number | null; status: string }> };
  shap: Array<{ name: string; value: number }>;
  feedback: Array<Record<string, string>>;
};
type ChatMessage = { role: "assistant" | "user"; content: string; sources?: string[]; warnings?: string[] };

const configuredApiUrl = import.meta.env.VITE_API_URL || "";
const localApiUrl =
  typeof window !== "undefined" &&
  ["127.0.0.1", "localhost"].includes(window.location.hostname)
    ? `http://${window.location.hostname}:8000`
    : "";
const API_BASE = configuredApiUrl
  ? configuredApiUrl.startsWith("http")
    ? configuredApiUrl
    : `https://${configuredApiUrl}`
  : localApiUrl;

const fallback: Overview = {
  kpis: {
    metersMonitored: 500,
    readsPerDay: 100000,
    openAlerts: 148,
    criticalAlerts: 12,
    precisionAt50: 0.78,
    forecastMape: 0.041,
    revenueAtRisk: 18750000,
    recoveredMtd: 6420000
  },
  zones: [
    { name: "Indiranagar", risk: "Critical", openAlerts: 31, lossPct: 10.8, loadPct: 93 },
    { name: "Whitefield", risk: "High", openAlerts: 27, lossPct: 7.6, loadPct: 82 },
    { name: "Jayanagar", risk: "Medium", openAlerts: 18, lossPct: 5.9, loadPct: 74 }
  ],
  alerts: [],
  forecast: Array.from({ length: 24 }, (_, i) => ({
    timestamp: new Date(Date.now() + i * 3600000).toISOString(),
    actual: i < 8 ? 38 + i : null,
    forecast: 42 + Math.sin(i / 3) * 7,
    lower90: 36 + Math.sin(i / 3) * 6,
    upper90: 48 + Math.sin(i / 3) * 8,
    lower99: 33 + Math.sin(i / 3) * 6,
    upper99: 52 + Math.sin(i / 3) * 8
  })),
  detectors: [],
  pipeline: [],
  data_quality: []
};

function formatCompact(value: number | string) {
  if (typeof value === "string") return value;
  return Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function money(value: number) {
  return Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value);
}

function riskClass(risk: string) {
  return `risk risk-${risk.toLowerCase()}`;
}

async function api<T>(path: string, fallbackValue: T, init?: RequestInit): Promise<T> {
  try {
    const res = await fetch(`${API_BASE}${path}`, init);
    if (!res.ok) throw new Error(path);
    return await res.json();
  } catch {
    return fallbackValue;
  }
}

function useDashboardData() {
  const [overview, setOverview] = React.useState<Overview>(fallback);
  const [alerts, setAlerts] = React.useState<AlertItem[]>([]);
  const [meters, setMeters] = React.useState<MeterRow[]>([]);
  const [models, setModels] = React.useState<any[]>([]);
  const [drift, setDrift] = React.useState<any[]>([]);
  const [dqTrend, setDqTrend] = React.useState<any[]>([]);
  const [revenue, setRevenue] = React.useState<any>({ trend: [], byZone: [], byInspector: [] });
  const [feeders, setFeeders] = React.useState<any[]>([]);
  const [graph, setGraph] = React.useState<any>({ nodes: [], edges: [] });
  const [audit, setAudit] = React.useState<any[]>([]);
  const [zoneMap, setZoneMap] = React.useState<any>({ features: [] });
  const [eaSummary, setEaSummary] = React.useState<EASummary | null>(null);
  const [eaTransformers, setEaTransformers] = React.useState<EATransformerItem[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [refreshToken, setRefreshToken] = React.useState(0);

  React.useEffect(() => {
    setLoading(true);
    Promise.all([
      api<Overview>("/api/v1/dashboard/overview", fallback),
      api<{ items: AlertItem[] }>("/api/v1/alerts", { items: [] }),
      api<{ items: MeterRow[] }>("/api/v1/meters?limit=80", { items: [] }),
      api<any[]>("/api/v1/models/health", []),
      api<any[]>("/api/v1/models/drift-history", []),
      api<any[]>("/api/v1/data-quality/trend", []),
      api<any>("/api/v1/revenue/trend", { trend: [], byZone: [], byInspector: [] }),
      api<any[]>("/api/v1/feeders/balance", []),
      api<any>("/api/v1/feeders/graph", { nodes: [], edges: [] }),
      api<any[]>("/api/v1/audit", []),
      api<any>("/api/v1/zones/map", { features: [] }),
      api<EASummary | null>("/api/v1/energy-accounting/summary?start_date=2023-01-01&end_date=2024-12-31", null),
      api<{ items: EATransformerItem[] }>("/api/v1/energy-accounting/transformers?limit=50&start_date=2023-01-01&end_date=2024-12-31", { items: [] })
    ])
      .then(([nextOverview, alertResp, meterResp, modelResp, driftResp, dqResp, revenueResp, feederResp, graphResp, auditResp, mapResp, eaSummaryResp, eaTransformersResp]) => {
        setOverview(nextOverview);
        setAlerts(alertResp.items.length ? alertResp.items : nextOverview.alerts);
        setMeters(meterResp.items);
        setModels(modelResp);
        setDrift(driftResp);
        setDqTrend(dqResp);
        setRevenue(revenueResp);
        setFeeders(feederResp);
        setGraph(graphResp);
        setAudit(auditResp);
        setZoneMap(mapResp);
        setEaSummary(eaSummaryResp);
        setEaTransformers(eaTransformersResp.items);
      })
      .finally(() => setLoading(false));
  }, [refreshToken]);

  return { overview, alerts, setAlerts, meters, models, drift, dqTrend, revenue, feeders, graph, audit, zoneMap, eaSummary, eaTransformers, loading, refresh: () => setRefreshToken((value) => value + 1) };
}

function useScenario(temp: number, multiplier: number, holiday: boolean) {
  const [points, setPoints] = React.useState<ForecastPoint[]>(fallback.forecast);
  React.useEffect(() => {
    api<ForecastPoint[]>(`/api/v1/scenario?temperature_delta=${temp}&industrial_multiplier=${multiplier}&holiday=${holiday}`, fallback.forecast).then(setPoints);
  }, [temp, multiplier, holiday]);
  return points;
}

function Chart({ option, height = 300 }: { option: echarts.EChartsOption; height?: number }) {
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption(option);
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [option]);
  return <div className="chart" style={{ height }} ref={ref} />;
}

function lineOption(points: ForecastPoint[], scenario = false): echarts.EChartsOption {
  const labels = points.map((point) => new Date(point.timestamp).toLocaleString("en-IN", { hour: "2-digit", day: "2-digit", month: "short" }));
  const series: echarts.SeriesOption[] = [
    { name: "99% upper", type: "line", data: points.map((p) => p.upper99), lineStyle: { opacity: 0 }, stack: "band99", symbol: "none" },
    { name: "99% band", type: "line", data: points.map((p) => p.lower99), lineStyle: { opacity: 0 }, areaStyle: { color: "rgba(152, 162, 179, .24)" }, stack: "band99", symbol: "none" },
    { name: "Forecast", type: "line", data: points.map((p) => p.forecast), smooth: true, lineStyle: { width: 3, color: "#2563eb" }, symbol: "none" },
    { name: "Actual", type: "line", data: points.map((p) => p.actual), smooth: true, lineStyle: { width: 2, color: "#101828" }, symbolSize: 5 }
  ];
  if (scenario) {
    series.push({ name: "Scenario", type: "line", data: points.map((p) => p.scenario), smooth: true, lineStyle: { width: 3, color: "#16a34a" }, symbol: "none" });
  }
  return {
    tooltip: { trigger: "axis" },
    legend: { top: 0, textStyle: { color: "#667085" } },
    grid: { top: 42, right: 16, bottom: 28, left: 48 },
    xAxis: { type: "category", data: labels, axisLabel: { color: "#667085" } },
    yAxis: { type: "value", axisLabel: { color: "#667085" }, splitLine: { lineStyle: { color: "#edf0f4" } } },
    series
  };
}

function AssistantWidget({ data, page, selectedAlert, selectedMeter }: { data: ReturnType<typeof useDashboardData>; page: Page; selectedAlert: string; selectedMeter: string }) {
  const quickPrompts = [
    "Summarize today's risks",
    "Explain the forecast band",
    "High-risk zones",
  ];
  const [open, setOpen] = React.useState(false);
  const [maximized, setMaximized] = React.useState(false);
  const [position, setPosition] = React.useState({ right: 22, bottom: 22 });
  const [input, setInput] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [messages, setMessages] = React.useState<ChatMessage[]>([
    {
      role: "assistant",
      content: "I can summarize risks, explain forecast uncertainty, and help investigate potential irregularities using the current dashboard context."
    }
  ]);
  const endRef = React.useRef<HTMLDivElement>(null);
  const dragRef = React.useRef<{ startX: number; startY: number; startRight: number; startBottom: number } | null>(null);

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy, open]);

  const dragStart = (event: React.PointerEvent<HTMLElement>) => {
    if (maximized) return;
    dragRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      startRight: position.right,
      startBottom: position.bottom
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const dragMove = (event: React.PointerEvent<HTMLElement>) => {
    if (!dragRef.current || maximized) return;
    const panelHeight = 690;
    const nextRight = dragRef.current.startRight - (event.clientX - dragRef.current.startX);
    const nextBottom = dragRef.current.startBottom - (event.clientY - dragRef.current.startY);
    setPosition({
      right: Math.max(8, Math.min(window.innerWidth - 72, nextRight)),
      bottom: Math.max(8, Math.min(window.innerHeight - Math.min(panelHeight, window.innerHeight - 96), nextBottom))
    });
  };

  const dragEnd = (event: React.PointerEvent<HTMLElement>) => {
    dragRef.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const send = async (text = input) => {
    const message = text.trim();
    if (!message || busy) return;
    setOpen(true);
    setInput("");
    setBusy(true);
    setMessages((items) => [...items, { role: "user", content: message }]);
    const context = {
      page,
      selectedAlert,
      selectedMeter,
      kpis: data.overview.kpis,
      zones: data.overview.zones.slice(0, 6),
      alerts: data.alerts.slice(0, 6),
      forecast: data.overview.forecast.slice(0, 12),
      feeders: data.feeders.slice(0, 6),
      dataQuality: data.overview.data_quality.slice(0, 4)
    };
    try {
      const res = await fetch(`${API_BASE}/api/v1/assistant/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, context })
      });
      if (!res.ok) throw new Error("assistant");
      const payload = await res.json();
      setMessages((items) => [...items, { role: "assistant", content: payload.answer, sources: payload.sources, warnings: payload.warnings }]);
    } catch {
      setMessages((items) => [
        ...items,
        {
          role: "assistant",
          content: "I could not reach the assistant API. Check that the backend is running and that GROQ_API_KEY is set in the backend environment."
        }
      ]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside
      className={`${open ? "assistant-shell open" : "assistant-shell"} ${maximized ? "maximized" : ""}`}
      style={maximized ? undefined : { right: position.right, bottom: position.bottom }}
    >
      {open && (
        <section className="assistant-panel" aria-label="AI Analyst Assistant">
          <header onPointerDown={dragStart} onPointerMove={dragMove} onPointerUp={dragEnd} onPointerCancel={dragEnd}>
            <div><Bot size={18} /><span><strong>EnergiX Copilot</strong><small>Grid operations assistant</small></span></div>
            <div className="assistant-window-actions">
              <Move size={16} />
              <button
                onClick={(event) => {
                  event.stopPropagation();
                  setMaximized((value) => !value);
                }}
                onPointerDown={(event) => event.stopPropagation()}
                title={maximized ? "Restore assistant" : "Maximize assistant"}
              >
                {maximized ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
              </button>
              <button
                onClick={(event) => {
                  event.stopPropagation();
                  setOpen(false);
                }}
                onPointerDown={(event) => event.stopPropagation()}
                title="Close assistant"
              >
                <X size={18} />
              </button>
            </div>
          </header>
          <div className="assistant-context">
            <span>{page}</span>
            {selectedAlert && <span>Alert {selectedAlert}</span>}
            {selectedMeter && <span>Meter selected</span>}
          </div>
          <div className="assistant-messages">
            {messages.map((item, index) => (
              <article className={`chat-bubble ${item.role}`} key={`${item.role}-${index}`}>
                <MarkdownText text={item.content} />
                {item.sources?.length ? <small>Sources: {item.sources.join(", ")}</small> : null}
              </article>
            ))}
            {busy && <article className="chat-bubble assistant loading"><Loader2 size={15} /> Thinking through the dashboard data</article>}
            <div ref={endRef} />
          </div>
          <div className="assistant-chips">
            {quickPrompts.map((prompt) => <button key={prompt} onClick={() => send(prompt)}>{prompt}</button>)}
          </div>
          <form className="assistant-input" onSubmit={(event) => { event.preventDefault(); send(); }}>
            <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="Ask about forecasts, anomalies, zones..." />
            <button disabled={busy || !input.trim()} title="Send question"><Send size={17} /></button>
          </form>
        </section>
      )}
      <button className="assistant-fab" onClick={() => setOpen((value) => !value)} title="Open EnergiX Copilot">
        {open ? <X size={20} /> : <Sparkles size={21} />}
      </button>
    </aside>
  );
}

function MarkdownText({ text }: { text: string }) {
  return (
    <div>
      {text.split("\n").filter(Boolean).map((line, index) => {
        const cleaned = line.replace(/^[-*]\s+/, "");
        return <p key={`${cleaned}-${index}`}>{cleaned}</p>;
      })}
    </div>
  );
}

function App() {
  const data = useDashboardData();
  const [page, setPage] = React.useState<Page>(() => (window.location.hash.replace("#", "") as Page) || "command");
  const [selectedAlert, setSelectedAlert] = React.useState<string>("");
  const [selectedMeter, setSelectedMeter] = React.useState<string>("");

  React.useEffect(() => {
    const onHash = () => setPage((window.location.hash.replace("#", "") as Page) || "command");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const nav = [
    ["command", "Command", Gauge],
    ["alerts", "Alerts", AlertTriangle],
    ["meters", "Meters", Search],
    ["forecast", "Forecast", BarChart3],
    ["grid", "Grid", MapIcon],
    ["models", "Models", Activity],
    ["audit", "Audit", ClipboardCheck],
    ["energy", "Energy", Zap]
  ] as const;

  return (
    <main className="app-shell">
      <header className="fixed-nav">
        <a className="brand" href="#command">
          <span className="brand-mark">B</span>
          <span><strong>EnergiX</strong><small>Smart meter operations</small></span>
        </a>
        <nav>
          {nav.map(([id, label, Icon]) => (
            <a className={page === id ? "active" : ""} href={`#${id}`} key={id}>
              <Icon size={17} /> {label}
            </a>
          ))}
        </nav>
        <button className={data.loading ? "sync loading" : "sync"} onClick={data.refresh} title="Reload dashboard data from the local API">{data.loading ? "Syncing" : "Refresh sample data"}</button>
      </header>

      <section className="content">
        {page === "command" && <CommandCenter data={data} openAlert={(id) => { setSelectedAlert(id); window.location.hash = "alerts"; }} />}
        {page === "alerts" && <AlertsPage alerts={data.alerts} setAlerts={data.setAlerts} selectedAlert={selectedAlert} setSelectedAlert={setSelectedAlert} openMeter={(id) => { setSelectedMeter(id); window.location.hash = "meters"; }} />}
        {page === "meters" && <MetersPage meters={data.meters} selectedMeter={selectedMeter} setSelectedMeter={setSelectedMeter} />}
        {page === "forecast" && <ForecastPage forecast={data.overview.forecast} revenue={data.revenue} />}
        {page === "grid" && <GridPage zones={data.overview.zones} zoneMap={data.zoneMap} feeders={data.feeders} graph={data.graph} />}
        {page === "models" && <ModelsDataPage models={data.models} drift={data.drift} dataQuality={data.overview.data_quality} dqTrend={data.dqTrend} detectors={data.overview.detectors} pipeline={data.overview.pipeline} />}
        {page === "audit" && <AuditPage audit={data.audit} revenue={data.revenue} />}
        {page === "energy" && <EnergyAccountingPage summary={data.eaSummary} transformers={data.eaTransformers} />}
      </section>
      <AssistantWidget data={data} page={page} selectedAlert={selectedAlert} selectedMeter={selectedMeter} />
    </main>
  );
}

function CommandCenter({ data, openAlert }: { data: ReturnType<typeof useDashboardData>; openAlert: (id: string) => void }) {
  const { overview } = data;
  return (
    <>
      <PageHeader title="Operations Command Center" subtitle="A compact view of forecasting, alerts, revenue, data quality, and grid stress." />
      <section className="kpi-grid">
        <Metric icon={Gauge} label="Meters monitored" value={formatCompact(overview.kpis.metersMonitored)} />
        <Metric icon={Database} label="Readings loaded" value={formatCompact(overview.kpis.readsPerDay)} />
        <Metric icon={AlertTriangle} label="Open alerts" value={formatCompact(overview.kpis.openAlerts)} tone="warn" />
        <Metric icon={ShieldCheck} label="Precision@50" value={`${Math.round(Number(overview.kpis.precisionAt50) * 100)}%`} />
        <Metric icon={BarChart3} label="Forecast MAPE" value={`${(Number(overview.kpis.forecastMape) * 100).toFixed(1)}%`} />
        <Metric icon={Activity} label="Recovered MTD" value={money(Number(overview.kpis.recoveredMtd))} />
      </section>
      <section className="dashboard-grid">
        <Panel title="Priority Alerts" action="Click for detail">
          <div className="alert-list compact">
            {overview.alerts.map((alert) => (
              <button className="alert-row clickable" key={alert.id} onClick={() => openAlert(alert.id)}>
                <div>
                  <span className={riskClass(alert.risk)}>{alert.risk}</span>
                  <strong>{alert.meterId}</strong>
                  <small>{alert.zone} / {alert.type} / {Math.round(alert.probability * 100)}%</small>
                  <p>{alert.summary}</p>
                </div>
                <ChevronRight size={18} />
              </button>
            ))}
          </div>
        </Panel>
        <Panel title="Zone Risk" action="Service area">
          <div className="zone-list">
            {overview.zones.slice(0, 8).map((zone) => <ZoneRow zone={zone} key={zone.name} />)}
          </div>
        </Panel>
        <Panel title="Demand Forecast" action="24 hour band" wide>
          <Chart option={lineOption(overview.forecast)} height={320} />
        </Panel>
      </section>
    </>
  );
}

function AlertsPage({ alerts, setAlerts, selectedAlert, setSelectedAlert, openMeter }: { alerts: AlertItem[]; setAlerts: React.Dispatch<React.SetStateAction<AlertItem[]>>; selectedAlert: string; setSelectedAlert: (id: string) => void; openMeter: (id: string) => void }) {
  const [risk, setRisk] = React.useState("all");
  const [status, setStatus] = React.useState("all");
  const [detail, setDetail] = React.useState<AlertDetail | null>(null);

  React.useEffect(() => {
    const first = selectedAlert || alerts[0]?.id || "";
    if (!first) return;
    setSelectedAlert(first);
    api<AlertDetail | null>(`/api/v1/alerts/${first}`, null).then(setDetail);
  }, [selectedAlert, alerts]);

  const filtered = alerts.filter((alert) => (risk === "all" || alert.risk.toLowerCase() === risk) && (status === "all" || alert.status.toLowerCase() === status));
  const updateStatus = async (id: string, action: "assign" | "snooze" | "close") => {
    const res = await api<{ saved: boolean; item?: AlertItem }>(`/api/v1/alerts/${id}/action`, { saved: false }, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action })
    });
    if (!res.saved || !res.item) return;
    setAlerts((items) => items.map((item) => item.id === id ? res.item! : item));
    if (selectedAlert === id) {
      api<AlertDetail | null>(`/api/v1/alerts/${id}`, null).then(setDetail);
    }
  };

  return (
    <>
      <PageHeader title="Alert Operations" subtitle="Rank, explain, assign, snooze, close, and feed analyst judgement back to the model loop." />
      <section className="toolbar">
        <Segment value={risk} onChange={setRisk} options={["all", "critical", "high", "medium", "low"]} />
        <Segment value={status} onChange={setStatus} options={["all", "open", "investigating", "resolved", "false positive", "snoozed", "assigned"]} />
      </section>
      <section className="split-grid">
        <Panel title="Intelligent Alert Queue" action={`${filtered.length} visible`}>
          <div className="alert-list">
            {filtered.map((alert) => (
              <article className={`alert-row ${selectedAlert === alert.id ? "selected" : ""}`} key={alert.id}>
                <button className="plain" onClick={() => setSelectedAlert(alert.id)}>
                  <span className={riskClass(alert.risk)}>{alert.risk}</span>
                  <strong>{alert.meterId}</strong>
                  <small>{alert.zone} / {alert.type} / {alert.detectorsAgreeing || 1}/4 detectors</small>
                  <small>Status: {alert.status}</small>
                  <p>{alert.summary}</p>
                  {alert.transformerId && (
                    <small style={{ color: "#475467", marginTop: 4, display: "block" }}>
                      Parent transformer {alert.transformerId}: unexplained loss {alert.dtUnexplainedPct !== undefined && alert.dtUnexplainedPct !== null ? `${alert.dtUnexplainedPct.toFixed(1)}%` : "N/A"} this period
                    </small>
                  )}
                </button>
                <div className="action-stack">
                  <strong>{money(alert.revenueImpact)}</strong>
                  <button onClick={() => updateStatus(alert.id, "assign")}><UserPlus size={15} /> Assign</button>
                  <button onClick={() => updateStatus(alert.id, "snooze")}><MessageSquare size={15} /> Snooze</button>
                  <button onClick={() => updateStatus(alert.id, "close")}><Check size={15} /> Close</button>
                </div>
              </article>
            ))}
          </div>
        </Panel>
        <AlertDetailPanel detail={detail} openMeter={openMeter} />
      </section>
    </>
  );
}

function AlertDetailPanel({ detail, openMeter }: { detail: AlertDetail | null; openMeter: (id: string) => void }) {
  const [feedbackType, setFeedbackType] = React.useState("true_positive");
  const [reason, setReason] = React.useState("theft_confirmed");
  const [notes, setNotes] = React.useState("");
  const [saved, setSaved] = React.useState("");
  if (!detail) return <Panel title="Alert Detail" action="Select alert"><p className="muted">Choose an alert to inspect detector consensus, SHAP features, meter context, and feedback history.</p></Panel>;
  const maxShap = Math.max(0.01, ...detail.shap.map((item) => Math.abs(item.value)));
  const submit = async () => {
    const res = await api<any>(`/api/v1/alerts/${detail.id}/feedback`, { saved: false }, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ feedback_type: feedbackType, reason_code: reason, confidence: "high", narrative: notes })
    } as RequestInit);
    setSaved(res.saved ? "Feedback captured for model retraining." : "Feedback noted locally.");
  };
  return (
    <Panel title="Alert Detail" action={detail.id}>
      <div className="detail-stack">
        <div className="summary-callout">
          <strong>{detail.confidence.consensusLabel}</strong>
          <p>{detail.summary}</p>
          {detail.transformerId && (
            <p style={{ fontSize: 12, color: "#475467", marginTop: 6, marginBottom: 6 }}>
              Parent transformer <strong>{detail.transformerId}</strong>: unexplained loss <strong>{detail.dtUnexplainedPct !== undefined && detail.dtUnexplainedPct !== null ? `${detail.dtUnexplainedPct.toFixed(2)}%` : "N/A"}</strong> this period (corroborating context to prioritize investigation).
            </p>
          )}
          <button onClick={() => openMeter(detail.meterId)}>Open meter deep dive</button>
        </div>
        <section>
          <h3>Detector Confidence</h3>
          <div className="detector-grid">
            {detail.confidence.breakdown.map((item) => (
              <div className="detector-mini" key={item.detector}>
                <strong>{item.detector}</strong>
                <span>{item.score === null ? item.status : `${Math.round(item.score * 100)}%`}</span>
                <small>{item.status}</small>
              </div>
            ))}
          </div>
        </section>
        <section>
          <h3>SHAP Waterfall</h3>
          <div className="waterfall">
            {detail.shap.map((item) => (
              <div key={item.name}>
                <span>{item.name}</span>
                <div><b style={{ width: `${Math.abs(item.value) / maxShap * 100}%` }} /></div>
                <strong>{item.value.toFixed(3)}</strong>
              </div>
            ))}
          </div>
        </section>
        <section>
          <h3>Analyst Feedback</h3>
          <div className="form-grid">
            <select value={feedbackType} onChange={(e) => setFeedbackType(e.target.value)}>
              <option value="true_positive">True positive</option>
              <option value="false_positive">False positive</option>
              <option value="inconclusive">Inconclusive</option>
            </select>
            <select value={reason} onChange={(e) => setReason(e.target.value)}>
              <option value="theft_confirmed">Theft confirmed</option>
              <option value="meter_malfunction">Meter malfunction</option>
              <option value="legitimate_behavior_change">Legitimate behavior change</option>
              <option value="phase_reversal">Phase reversal</option>
              <option value="insufficient_evidence">Insufficient evidence</option>
            </select>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Inspection notes" />
            <button onClick={submit}><ClipboardCheck size={15} /> Submit feedback</button>
            {saved && <small>{saved}</small>}
          </div>
        </section>
      </div>
    </Panel>
  );
}

function MetersPage({ meters, selectedMeter, setSelectedMeter }: { meters: MeterRow[]; selectedMeter: string; setSelectedMeter: (id: string) => void }) {
  const [query, setQuery] = React.useState("");
  const [detail, setDetail] = React.useState<MeterDetail | null>(null);
  const visible = meters.filter((meter) => `${meter.meterId} ${meter.zone} ${meter.consumerType} ${meter.feederId}`.toLowerCase().includes(query.toLowerCase()));
  React.useEffect(() => {
    const id = selectedMeter || visible[0]?.meterId;
    if (!id) return;
    setSelectedMeter(id);
    api<MeterDetail | null>(`/api/v1/meters/${id}/detail`, null).then(setDetail);
  }, [selectedMeter, meters]);
  return (
    <>
      <PageHeader title="Meter Deep Dive" subtitle="Meter profile, location, 90-day style heatmap sample, peer comparison, alerts, and inspection history." />
      <section className="toolbar">
        <label className="search-box"><Search size={16} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find meter, feeder, zone, or consumer type" /></label>
      </section>
      <section className="split-grid">
        <Panel title="Meter Registry" action={`${visible.length} shown`}>
          <div className="table-scroll">
            <table>
              <thead><tr><th>Meter</th><th>Zone</th><th>Type</th><th>Feeder</th></tr></thead>
              <tbody>
                {visible.slice(0, 60).map((meter) => (
                  <tr className={selectedMeter === meter.meterId ? "selected-row" : ""} key={meter.meterId} onClick={() => setSelectedMeter(meter.meterId)}>
                    <td>{meter.meterId}</td><td>{meter.zone}</td><td>{meter.consumerType}</td><td>{meter.feederId}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <MeterDetailPanel detail={detail} />
      </section>
    </>
  );
}

function MeterDetailPanel({ detail }: { detail: MeterDetail | null }) {
  if (!detail) return <Panel title="Meter Detail" action="Select meter"><p className="muted">Select a meter to inspect its readings and field history.</p></Panel>;
  return (
    <Panel title="Meter Detail" action={detail.meterId}>
      <div className="detail-stack">
        <div className="identity-grid">
          <Info label="Address" value={detail.address} />
          <Info label="Consumer" value={`${detail.consumerType} / ${detail.tariffCode}`} />
          <Info label="Feeder" value={`${detail.substationId} / ${detail.feederId}`} />
          <Info label="Meter" value={`${detail.meterMake} ${detail.firmwareVersion}`} />
          <Info label="Contract" value={`${detail.contractedKw} kW / ${detail.phase}`} />
          <button
            className="button-link"
            onClick={() => {
              const popup = window.open(detail.mapsUrl, "_blank", "noopener,noreferrer");
              if (!popup) window.location.assign(detail.mapsUrl);
            }}
          >
            Open map
          </button>
        </div>
        <section>
          <h3>Consumption Heatmap</h3>
          <div className="heatmap-grid">
            {Array.from({ length: 7 * 24 }, (_, i) => {
              const day = Math.floor(i / 24);
              const hour = i % 24;
              const cell = detail.heatmap.find((item) => item.day === day && item.hour === hour);
              const intensity = Math.min(1, (cell?.kwh || 0) / 5);
              return <span key={i} title={`Day ${day}, ${hour}:00 - ${cell?.kwh || 0} kWh`} style={{ background: `rgba(37, 99, 235, ${0.08 + intensity * 0.82})` }} />;
            })}
          </div>
        </section>
        <section>
          <h3>Peer Comparison</h3>
          <Chart height={230} option={{
            tooltip: { trigger: "axis" },
            grid: { top: 20, right: 12, bottom: 24, left: 38 },
            xAxis: { type: "category", data: detail.peer.map((p) => new Date(p.timestamp).toLocaleTimeString("en-IN", { hour: "2-digit" })) },
            yAxis: { type: "value", splitLine: { lineStyle: { color: "#edf0f4" } } },
            series: [
              { name: "Meter", type: "line", smooth: true, data: detail.peer.map((p) => p.meterKwh), symbol: "none", lineStyle: { color: "#2563eb", width: 3 } },
              { name: "Peer mean", type: "line", smooth: true, data: detail.peer.map((p) => p.peerMean), symbol: "none", lineStyle: { color: "#16a34a", width: 2 } }
            ]
          }} />
        </section>
        <section>
          <h3>Inspection History</h3>
          <Timeline rows={detail.audit.map((item) => ({ title: item.action, meta: `${item.inspector} / ${item.outcome}`, body: item.remarks }))} />
        </section>
      </div>
    </Panel>
  );
}

function ForecastPage({ forecast, revenue }: { forecast: ForecastPoint[]; revenue: any }) {
  const [temp, setTemp] = React.useState(2);
  const [industrial, setIndustrial] = React.useState(1.2);
  const [holiday, setHoliday] = React.useState(false);
  const scenario = useScenario(temp, industrial, holiday);
  const modifier = 1 + temp * 0.012 + (industrial - 1) * 0.35 - (holiday ? 0.08 : 0);
  return (
    <>
      <PageHeader title="Forecast and Scenario Simulator" subtitle="Compare the baseline demand band against temperature, industrial load, and holiday assumptions." />
      <section className="dashboard-grid">
        <Panel title="Scenario Controls" action={`${((modifier - 1) * 100).toFixed(1)}% peak shift`}>
          <div className="scenario">
            <Control label={`Temperature delta: ${temp > 0 ? "+" : ""}${temp} C`}><input type="range" min="-4" max="8" value={temp} onChange={(e) => setTemp(Number(e.target.value))} /></Control>
            <Control label={`Industrial load: ${industrial.toFixed(1)}x`}><input type="range" min="0.5" max="2" step="0.1" value={industrial} onChange={(e) => setIndustrial(Number(e.target.value))} /></Control>
            <label className="toggle"><input type="checkbox" checked={holiday} onChange={(e) => setHoliday(e.target.checked)} /> Holiday load profile</label>
            <p>Scenario formula uses weather sensitivity, industrial multiplier, and holiday reduction to redraw the forecast band.</p>
          </div>
        </Panel>
        <Panel title="Scenario Result" action="Baseline vs modified" wide>
          <Chart option={lineOption(scenario.length ? scenario : forecast, true)} height={360} />
        </Panel>
        <Panel title="Revenue Recovery Trend" action="Cumulative">
          <Chart height={260} option={revenueOption(revenue.trend || [])} />
        </Panel>
      </section>
    </>
  );
}

function GridPage({ zones, zoneMap, feeders, graph }: { zones: Overview["zones"]; zoneMap: any; feeders: any[]; graph: any }) {
  return (
    <>
      <PageHeader title="Grid and Zone Operations" subtitle="Zone risk choropleth, feeder energy balance, and graph-ready topology in one place." />
      <section className="dashboard-grid">
        <Panel title="Zone Risk Map" action={`${zoneMap.features?.length || zones.length} zones`}>
          <div className="map-board">
            {(zoneMap.features || []).map((feature: any, i: number) => (
              <button className={`map-zone risk-bg-${String(feature.properties.risk_level).toLowerCase()}`} style={{ left: `${8 + (i % 4) * 22}%`, top: `${12 + Math.floor(i / 4) * 25}%` }} key={feature.id}>
                <strong>{feature.properties.zone}</strong>
                <span>{feature.properties.load_pct}% load</span>
                <small>{feature.properties.open_alerts} alerts</small>
              </button>
            ))}
          </div>
        </Panel>
        <Panel title="Feeder Energy Balance" action="GNN loss estimate">
          <div className="zone-list">
            {feeders.slice(0, 12).map((row) => (
              <div className="zone-row" key={row.feederId}>
                <strong>{row.feederId}</strong>
                <small>{row.zone} / {row.theftAlertsYtd} theft alerts YTD</small>
                <div className="bar"><span style={{ width: `${Math.min(100, row.lossPct * 4)}%` }} /></div>
                <small>{row.lossPct}% feeder loss / {row.nonTechnicalLossPct}% non-technical</small>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Topology Graph" action={`${graph.nodes?.length || 0} nodes`} wide>
          <TopologyGraph graph={graph} />
        </Panel>
      </section>
    </>
  );
}

function TopologyGraph({ graph }: { graph: any }) {
  const flow = React.useMemo(() => {
    const substations = (graph.nodes || []).filter((node: any) => node.type === "Substation").slice(0, 6);
    const feeders = (graph.nodes || []).filter((node: any) => node.type === "Feeder").slice(0, 18);
    const visibleIds = new Set([...substations, ...feeders].map((node: any) => node.id));
    const feederByParent = feeders.reduce((acc: Record<string, any[]>, feeder: any) => {
      const key = feeder.parent || "unassigned";
      acc[key] = [...(acc[key] || []), feeder];
      return acc;
    }, {});
    const nodes: Node[] = [];
    const nodeRiskColor = (risk: string) => {
      if (risk === "Critical") return "#dc2626";
      if (risk === "High") return "#f97316";
      if (risk === "Medium") return "#ca8a04";
      return "#16a34a";
    };

    substations.forEach((node: any, index: number) => {
      const linked = feederByParent[node.id] || [];
      nodes.push({
        id: node.id,
        position: { x: 40, y: 36 + index * 132 },
        data: {
          label: (
            <div className="flow-node-copy">
              <strong>{node.label}</strong>
              <span>Substation</span>
              <small>{linked.length} feeders</small>
            </div>
          )
        },
        style: {
          width: 184,
          border: "1px solid #bfdbfe",
          background: "#eef4ff",
          color: "#1d4ed8",
          borderRadius: 8,
          padding: 10,
          boxShadow: "0 1px 2px rgba(16, 24, 40, .08)"
        }
      });
      linked.forEach((feeder: any, feederIndex: number) => {
        nodes.push({
          id: feeder.id,
          position: { x: 360 + feederIndex * 244, y: 26 + index * 132 },
          data: {
            label: (
              <div className="flow-node-copy">
                <strong>{feeder.label}</strong>
                <span>{feeder.risk} feeder</span>
                <small>{feeder.loadPct}% load / {feeder.meterCount} meters</small>
              </div>
            )
          },
          style: {
            width: 214,
            border: `1px solid ${nodeRiskColor(feeder.risk)}`,
            background: "#ffffff",
            color: "#101828",
            borderRadius: 8,
            padding: 10,
            boxShadow: "0 1px 2px rgba(16, 24, 40, .08)"
          }
        });
      });
    });

    const edges: Edge[] = (graph.edges || [])
      .filter((edge: any) => visibleIds.has(edge.source) && visibleIds.has(edge.target))
      .map((edge: any) => ({
        id: `${edge.source}-${edge.target}`,
        source: edge.source,
        target: edge.target,
        animated: Number(edge.weight || 0) > 18,
        label: `${edge.weight || 0} meters`,
        markerEnd: { type: MarkerType.ArrowClosed },
        style: { stroke: "#64748b", strokeWidth: 1.8 },
        labelStyle: { fill: "#475467", fontSize: 11, fontWeight: 700 },
        labelBgStyle: { fill: "#ffffff", fillOpacity: 0.92 }
      }));
    return { nodes, edges };
  }, [graph]);

  return (
    <div className="topology-flow">
      <ReactFlow
        nodes={flow.nodes}
        edges={flow.edges}
        fitView
        fitViewOptions={{ padding: 0.18 }}
        minZoom={0.35}
        maxZoom={1.6}
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} color="#d0d5dd" gap={22} />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          nodeStrokeWidth={2}
          nodeColor={(node) => node.id.startsWith("SS-") ? "#bfdbfe" : "#dbeafe"}
        />
      </ReactFlow>
    </div>
  );
}

function ModelsDataPage({ models, drift, dataQuality, dqTrend, detectors, pipeline }: { models: any[]; drift: any[]; dataQuality: Overview["data_quality"]; dqTrend: any[]; detectors: Overview["detectors"]; pipeline: Overview["pipeline"] }) {
  return (
    <>
      <PageHeader title="Models, Drift, and Data Quality" subtitle="Model health, drift history, detector coverage, pipeline readiness, and operational data quality trends." />
      <section className="dashboard-grid">
        <Panel title="Model Health" action="Latest evaluation">
          <div className="detector-grid">
            {models.map((model) => (
              <div className="detector" key={model.model}>
                <div><strong>{model.model}</strong><small>v{model.version} / trained {model.lastTrained}</small></div>
                <span className={riskClass(model.status === "Critical" ? "Critical" : model.status === "Watch" ? "High" : "Normal")}>{model.status}</span>
                <div className="bar"><span style={{ width: `${Math.min(100, model.drift * 300)}%` }} /></div>
                <small>PSI {model.drift} / Precision {Math.round((model.precision || 0) * 100)}% / Recall {Math.round((model.recall || 0) * 100)}%</small>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Drift Trend" action="PSI and MAPE">
          <Chart height={320} option={driftOption(drift)} />
        </Panel>
        <Panel title="Data Quality Trend" action="90 day correlation" wide>
          <Chart height={280} option={dqOption(dqTrend)} />
        </Panel>
        <Panel title="Detector Coverage" action="Runtime layer">
          <div className="detector-grid">
            {detectors.map((detector) => <div className="detector" key={detector.name}><div><strong>{detector.name}</strong><small>{detector.purpose}</small></div><span>{detector.metric}</span><div className="bar"><span style={{ width: `${detector.coverage}%` }} /></div></div>)}
          </div>
        </Panel>
        <Panel title="Feature Pipeline" action="Feature reflected">
          <div className="pipeline">{pipeline.map((layer) => <div className="pipeline-step" key={layer.layer}><span>{layer.layer}</span><strong>{layer.name}</strong><small>{layer.items.join(" / ")}</small><em>{layer.status}</em></div>)}</div>
        </Panel>
        <Panel title="Data Quality Snapshot" action="By zone">
          <table><thead><tr><th>Zone</th><th>Fresh</th><th>Missing</th><th>Status</th></tr></thead><tbody>{dataQuality.map((row) => <tr key={row.source}><td>{row.source}</td><td>{row.freshness}</td><td>{row.missingPct}%</td><td>{row.status}</td></tr>)}</tbody></table>
        </Panel>
      </section>
    </>
  );
}

function AuditPage({ audit, revenue }: { audit: any[]; revenue: any }) {
  return (
    <>
      <PageHeader title="Audit and Revenue Impact" subtitle="Inspection actions, fines, cumulative recovery, and field productivity views." />
      <section className="dashboard-grid">
        <Panel title="Cumulative Recovery" action="Daily trend" wide>
          <Chart height={320} option={revenueOption(revenue.trend || [])} />
        </Panel>
        <Panel title="Recovery by Zone" action="Top contributors">
          <RankList rows={revenue.byZone || []} />
        </Panel>
        <Panel title="Recovery by Inspector" action="Field teams">
          <RankList rows={revenue.byInspector || []} />
        </Panel>
        <Panel title="Audit Trail" action="Latest actions" wide>
          <Timeline rows={audit.map((item) => ({ title: `${item.event} / ${item.meterId}`, meta: `${item.actor} / ${item.outcome}`, body: item.hash }))} />
        </Panel>
      </section>
    </>
  );
}

function Metric({ icon: Icon, label, value, tone }: { icon: typeof Gauge; label: string; value: string; tone?: string }) {
  return <article className={`metric ${tone || ""}`}><Icon size={18} /><span>{label}</span><strong>{value}</strong></article>;
}

function Panel({ title, action, children, wide }: { title: string; action: string; children: React.ReactNode; wide?: boolean }) {
  return <section className={wide ? "panel wide" : "panel"}><header><h2>{title}</h2><span>{action}</span></header>{children}</section>;
}

function PageHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return <header className="page-header"><div><h1>{title}</h1><p>{subtitle}</p></div><button onClick={() => window.print()} title="Open print preview so this page can be saved as PDF"><FileDown size={16} /> Export view</button></header>;
}

function Segment({ value, onChange, options }: { value: string; onChange: (value: string) => void; options: string[] }) {
  return <div className="segment">{options.map((option) => <button className={value === option ? "active" : ""} onClick={() => onChange(option)} key={option}>{option}</button>)}</div>;
}

function ZoneRow({ zone }: { zone: Overview["zones"][number] }) {
  return <div className="zone-row"><span className={riskClass(zone.risk)}>{zone.risk}</span><strong>{zone.name}</strong><div className="bar"><span style={{ width: `${zone.loadPct}%` }} /></div><small>{zone.openAlerts} alerts / {zone.lossPct}% loss / {zone.meterCount || 0} meters</small></div>;
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="info"><small>{label}</small><strong>{value}</strong></div>;
}

function Control({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="control"><span>{label}</span>{children}</label>;
}

function Timeline({ rows }: { rows: Array<{ title: string; meta: string; body: string }> }) {
  return <div className="timeline">{rows.length ? rows.map((row, i) => <article key={`${row.title}-${i}`}><strong>{row.title}</strong><small>{row.meta}</small><p>{row.body}</p></article>) : <p className="muted">No events found.</p>}</div>;
}

function RankList({ rows }: { rows: Array<{ name: string; value: number }> }) {
  const max = Math.max(1, ...rows.map((row) => row.value));
  return <div className="zone-list">{rows.map((row) => <div className="zone-row" key={row.name}><strong>{row.name}</strong><div className="bar"><span style={{ width: `${row.value / max * 100}%` }} /></div><small>{money(row.value)}</small></div>)}</div>;
}

function revenueOption(rows: any[]): echarts.EChartsOption {
  return {
    tooltip: { trigger: "axis" },
    grid: { top: 20, right: 16, bottom: 28, left: 56 },
    xAxis: { type: "category", data: rows.map((row) => row.date), axisLabel: { color: "#667085" } },
    yAxis: { type: "value", axisLabel: { color: "#667085" }, splitLine: { lineStyle: { color: "#edf0f4" } } },
    series: [
      { name: "Daily", type: "bar", data: rows.map((row) => row.dailyRecovery), itemStyle: { color: "#9ca3af" } },
      { name: "Cumulative", type: "line", data: rows.map((row) => row.cumulativeRecovery), smooth: true, lineStyle: { color: "#2563eb", width: 3 }, symbol: "none" }
    ]
  };
}

function driftOption(rows: any[]): echarts.EChartsOption {
  const filtered = rows.filter((row) => row.metric === "mape_pct").slice(-80);
  return {
    tooltip: { trigger: "axis" },
    grid: { top: 20, right: 16, bottom: 28, left: 42 },
    xAxis: { type: "category", data: filtered.map((row) => row.date), axisLabel: { color: "#667085" } },
    yAxis: { type: "value", axisLabel: { color: "#667085" }, splitLine: { lineStyle: { color: "#edf0f4" } } },
    series: [
      { name: "MAPE", type: "line", smooth: true, data: filtered.map((row) => row.value), symbol: "none", lineStyle: { color: "#2563eb", width: 3 } },
      { name: "PSI", type: "line", smooth: true, data: filtered.map((row) => row.psi), symbol: "none", lineStyle: { color: "#dc2626", width: 2 } }
    ]
  };
}

function dqOption(rows: any[]): echarts.EChartsOption {
  return {
    tooltip: { trigger: "axis" },
    legend: { top: 0 },
    grid: { top: 42, right: 16, bottom: 28, left: 42 },
    xAxis: { type: "category", data: rows.map((row) => row.date), axisLabel: { color: "#667085" } },
    yAxis: { type: "value", axisLabel: { color: "#667085" }, splitLine: { lineStyle: { color: "#edf0f4" } } },
    series: [
      { name: "Quality", type: "line", data: rows.map((row) => row.quality), smooth: true, symbol: "none", lineStyle: { color: "#16a34a", width: 3 } },
      { name: "Completeness", type: "line", data: rows.map((row) => row.completeness / 100), smooth: true, symbol: "none", lineStyle: { color: "#2563eb", width: 2 } },
      { name: "Drift PSI", type: "line", data: rows.map((row) => row.psi), smooth: true, symbol: "none", lineStyle: { color: "#dc2626", width: 2 } }
    ]
  };
}

// ── Energy Accounting helpers ────────────────────────────────────────────────

function eaUnexplainedBarOption(series: EATransformerDetail["daily_series"]): echarts.EChartsOption {
  const dates = series.map((r) => r.date);
  return {
    tooltip: { trigger: "axis" },
    legend: { top: 0, textStyle: { color: "#667085" } },
    grid: { top: 42, right: 16, bottom: 28, left: 64 },
    xAxis: { type: "category", data: dates, axisLabel: { color: "#667085", rotate: 30 } },
    yAxis: { type: "value", name: "kWh", axisLabel: { color: "#667085" }, splitLine: { lineStyle: { color: "#edf0f4" } } },
    series: [
      { name: "Input", type: "bar", stack: "total", data: series.map((r) => r.input_kwh), itemStyle: { color: "#93c5fd" } },
      { name: "Metered", type: "line", data: series.map((r) => r.metered_kwh), smooth: true, symbol: "none", lineStyle: { color: "#2563eb", width: 2 } },
      { name: "Unexplained kWh", type: "bar", data: series.map((r) => r.unexplained_kwh), itemStyle: { color: "#f97316" } }
    ]
  };
}

function eaUnexplainedPctOption(series: EATransformerDetail["daily_series"]): echarts.EChartsOption {
  const dates = series.map((r) => r.date);
  return {
    tooltip: { trigger: "axis", formatter: (params: any) => `${params[0].name}<br/>Unexplained: ${Number(params[0].value).toFixed(3)}%` },
    grid: { top: 12, right: 16, bottom: 28, left: 56 },
    xAxis: { type: "category", data: dates, axisLabel: { color: "#667085", rotate: 30 } },
    yAxis: { type: "value", name: "%", axisLabel: { color: "#667085" }, splitLine: { lineStyle: { color: "#edf0f4" } } },
    series: [
      { name: "Unexplained %", type: "line", data: series.map((r) => r.unexplained_pct), smooth: true, symbol: "none", lineStyle: { color: "#dc2626", width: 2 }, areaStyle: { color: "rgba(220,38,38,0.12)" } }
    ]
  };
}

// ── EnergyAccountingPage ─────────────────────────────────────────────────────

const ANCHOR_END = "2024-12-31";

function computePresetRange(preset: string): { start: string; end: string; label: string } {
  if (preset === "7d") {
    return { start: "2024-12-25", end: ANCHOR_END, label: "Last 7 days" };
  } else if (preset === "30d") {
    return { start: "2024-12-02", end: ANCHOR_END, label: "Last 30 days" };
  } else if (preset === "90d") {
    return { start: "2024-10-03", end: ANCHOR_END, label: "Last 90 days" };
  } else if (preset === "1y") {
    return { start: "2024-01-01", end: ANCHOR_END, label: "Last 1 year" };
  } else if (preset === "all") {
    return { start: "2023-01-01", end: ANCHOR_END, label: "All time" };
  }
  return { start: "2024-12-02", end: ANCHOR_END, label: "Last 30 days" };
}

function EnergyAccountingPage({ summary: initialSummary, transformers: initialTransformers }: { summary?: EASummary | null; transformers?: EATransformerItem[] }) {
  const [rangeKey, setRangeKey] = React.useState<string>("30d");
  const [customStart, setCustomStart] = React.useState<string>("2024-12-01");
  const [customEnd, setCustomEnd] = React.useState<string>("2024-12-31");
  const [activeRange, setActiveRange] = React.useState<{ start: string; end: string; label: string }>(() => computePresetRange("30d"));

  const [summary, setSummary] = React.useState<EASummary | null>(null);
  const [transformers, setTransformers] = React.useState<EATransformerItem[]>([]);
  const [eaLoading, setEaLoading] = React.useState<boolean>(false);

  const [selectedDt, setSelectedDt] = React.useState<string>("");
  const [detail, setDetail] = React.useState<EATransformerDetail | null>(null);
  const [detailLoading, setDetailLoading] = React.useState<boolean>(false);
  const [zoneFilter, setZoneFilter] = React.useState<string>("all");

  const handlePresetChange = (key: string) => {
    setRangeKey(key);
    if (key !== "custom") {
      setActiveRange(computePresetRange(key));
    }
  };

  const applyCustomRange = () => {
    if (!customStart || !customEnd) return;
    const start = customStart <= customEnd ? customStart : customEnd;
    const end = customStart <= customEnd ? customEnd : customStart;
    setActiveRange({
      start,
      end,
      label: `${start} to ${end}`
    });
  };

  // Re-fetch summary & ranked transformers whenever activeRange changes
  React.useEffect(() => {
    setEaLoading(true);
    const q = `?start_date=${encodeURIComponent(activeRange.start)}&end_date=${encodeURIComponent(activeRange.end)}`;
    Promise.all([
      api<EASummary | null>(`/api/v1/energy-accounting/summary${q}`, null),
      api<{ items: EATransformerItem[] }>(`/api/v1/energy-accounting/transformers${q}&limit=50`, { items: [] })
    ])
      .then(([s, t]) => {
        setSummary(s);
        setTransformers(t.items);
      })
      .finally(() => setEaLoading(false));
  }, [activeRange]);

  // Re-fetch detail whenever selectedDt OR activeRange changes
  React.useEffect(() => {
    if (!selectedDt) {
      setDetail(null);
      return;
    }
    setDetailLoading(true);
    const q = `?start_date=${encodeURIComponent(activeRange.start)}&end_date=${encodeURIComponent(activeRange.end)}`;
    api<EATransformerDetail | null>(
      `/api/v1/energy-accounting/transformers/${encodeURIComponent(selectedDt)}${q}`,
      null
    )
      .then((res) => setDetail(res))
      .finally(() => setDetailLoading(false));
  }, [selectedDt, activeRange]);

  const selectDt = React.useCallback((tid: string) => {
    setSelectedDt(tid);
  }, []);

  const zones = React.useMemo(() => ["all", ...Array.from(new Set(transformers.map((t) => t.zone))).sort()], [transformers]);
  const filtered = zoneFilter === "all" ? transformers : transformers.filter((t) => t.zone === zoneFilter);

  const fmtKwh = (v: number) => Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(v) + " kWh";

  return (
    <>
      <PageHeader
        title="Energy Accounting"
        subtitle="Distribution-transformer level energy balance — a network-level view independent of per-meter consumption signals. Technical-loss figures are synthetic/parametric (not field-measured)."
      />

      {/* ── Date range selector toolbar ── */}
      <section className="toolbar" style={{ alignItems: "center", gap: 12, marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Calendar size={16} color="#475467" />
          <span style={{ fontSize: 13, fontWeight: 600, color: "#344054" }}>Date range:</span>
          <select
            id="ea-date-range-select"
            value={rangeKey}
            onChange={(e) => handlePresetChange(e.target.value)}
            style={{
              minHeight: 36,
              padding: "6px 12px",
              borderRadius: 8,
              border: "1px solid #d0d5dd",
              background: "#ffffff",
              fontSize: 13,
              fontWeight: 500,
              color: "#1d2939",
              cursor: "pointer"
            }}
          >
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
            <option value="90d">Last 90 days</option>
            <option value="1y">Last 1 year</option>
            <option value="all">All time</option>
            <option value="custom">Custom range</option>
          </select>
        </div>

        {rangeKey === "custom" && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "#475467" }}>
              <span>From:</span>
              <input
                id="ea-custom-start-date"
                type="date"
                value={customStart}
                min="2023-01-01"
                max="2024-12-31"
                onChange={(e) => setCustomStart(e.target.value)}
                style={{
                  minHeight: 36,
                  padding: "6px 10px",
                  borderRadius: 8,
                  border: "1px solid #d0d5dd",
                  background: "#ffffff",
                  fontSize: 13,
                  color: "#1d2939"
                }}
              />
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "#475467" }}>
              <span>To:</span>
              <input
                id="ea-custom-end-date"
                type="date"
                value={customEnd}
                min="2023-01-01"
                max="2024-12-31"
                onChange={(e) => setCustomEnd(e.target.value)}
                style={{
                  minHeight: 36,
                  padding: "6px 10px",
                  borderRadius: 8,
                  border: "1px solid #d0d5dd",
                  background: "#ffffff",
                  fontSize: 13,
                  color: "#1d2939"
                }}
              />
            </label>
            <button
              id="ea-apply-custom-date-range"
              className="sync"
              style={{ padding: "6px 14px", minHeight: 36, fontWeight: 600 }}
              onClick={applyCustomRange}
            >
              Apply range
            </button>
          </div>
        )}

        <div style={{ marginLeft: "auto", fontSize: 12, color: "#667085" }}>
          {eaLoading ? (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> Fetching accounting data…
            </span>
          ) : (
            <span>Scope: <strong>{activeRange.start || "2023-01-01"}</strong> to <strong>{activeRange.end || "2024-12-31"}</strong> ({activeRange.label})</span>
          )}
        </div>
      </section>

      {/* ── Summary KPI strip ── */}
      {summary && (
        <section className="kpi-grid">
          <Metric icon={Zap} label={`Total input (${activeRange.label})`} value={fmtKwh(summary.total_input_kwh)} />
          <Metric icon={Activity} label="Total metered" value={fmtKwh(summary.total_metered_kwh)} />
          <Metric icon={Database} label="Technical loss (parametric)" value={fmtKwh(summary.total_technical_loss_kwh)} />
          <Metric icon={AlertTriangle} label="Unexplained energy" value={fmtKwh(summary.total_unexplained_kwh)} tone="warn" />
          <Metric icon={BarChart3} label="Unexplained %" value={`${summary.unexplained_pct.toFixed(3)}%`} tone={summary.unexplained_pct > 2 ? "warn" : ""} />
        </section>
      )}

      <section className="dashboard-grid">
        {/* ── Ranked DT table ── */}
        <Panel title="Transformers Requiring Review" action="Ranked by unexplained %">
          <div className="toolbar" style={{ marginBottom: 8 }}>
            <Segment value={zoneFilter} onChange={setZoneFilter} options={zones} />
          </div>
          <div className="alert-list" style={{ maxHeight: 520, overflowY: "auto" }}>
            {filtered.length === 0 && <p className="muted">No data for selected filters.</p>}
            {filtered.map((dt) => (
              <button
                id={`ea-dt-${dt.transformer_id}`}
                className={`alert-row clickable${selectedDt === dt.transformer_id ? " selected" : ""}`}
                key={dt.transformer_id}
                onClick={() => selectDt(dt.transformer_id)}
              >
                <div>
                  <span className={riskClass(dt.unexplained_pct > 5 ? "Critical" : dt.unexplained_pct > 2 ? "High" : dt.unexplained_pct > 0.5 ? "Medium" : "Normal")}>
                    {dt.unexplained_pct.toFixed(2)}%
                  </span>
                  <strong>{dt.transformer_id}</strong>
                  <small>{dt.zone} / {dt.feeder_id} / {dt.rated_kva} kVA / {dt.location_type}</small>
                  <p>Input {fmtKwh(dt.total_input_kwh)} · Metered {fmtKwh(dt.total_metered_kwh)} · Unexplained {fmtKwh(dt.total_unexplained_kwh)} over {dt.days_in_range} days</p>
                </div>
                <ChevronRight size={18} />
              </button>
            ))}
          </div>
        </Panel>

        {/* ── Drill-down panel ── */}
        <Panel title="Transformer Detail" action={selectedDt || "Select a transformer"}>
          {!selectedDt && (
            <p className="muted">Click a row on the left to see its daily energy-accounting trend, mapped meters, and any cross-referenced anomaly alerts.</p>
          )}
          {detailLoading && <p className="muted"><Loader2 size={15} style={{ display: "inline" }} /> Loading detail…</p>}
          {detail && !detailLoading && (
            <div className="detail-stack">
              {/* Transformer metadata */}
              <div className="info-grid">
                {Object.entries(detail.transformer).map(([k, v]) => (
                  <Info key={k} label={k.replace(/_/g, " ")} value={String(v)} />
                ))}
              </div>

              {/* Daily trend charts */}
              {detail.daily_series.length > 0 && (
                <>
                  <h3 style={{ marginTop: 16, marginBottom: 4, fontSize: 13, color: "#344054" }}>Daily energy balance (input / metered / unexplained kWh)</h3>
                  <Chart option={eaUnexplainedBarOption(detail.daily_series)} height={240} />
                  <h3 style={{ marginTop: 12, marginBottom: 4, fontSize: 13, color: "#344054" }}>Daily unexplained-energy percentage</h3>
                  <Chart option={eaUnexplainedPctOption(detail.daily_series)} height={180} />
                </>
              )}

              {/* Mapped meters */}
              <h3 style={{ marginTop: 16, marginBottom: 4, fontSize: 13, color: "#344054" }}>Meters mapped to this transformer ({detail.meters.length})</h3>
              <table>
                <thead><tr><th>Meter ID</th><th>Feeder</th><th>Substation</th><th>Zone</th></tr></thead>
                <tbody>
                  {detail.meters.map((m) => (
                    <tr key={m.meter_id}><td>{m.meter_id}</td><td>{m.feeder_id}</td><td>{m.substation_id}</td><td>{m.zone}</td></tr>
                  ))}
                </tbody>
              </table>

              {/* Cross-referenced alerts */}
              {detail.related_alerts.length > 0 && (
                <>
                  <h3 style={{ marginTop: 16, marginBottom: 4, fontSize: 13, color: "#344054" }}>Cross-referenced anomaly alerts ({detail.related_alerts.length})</h3>
                  <p className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Alerts from the meter-level ML pipeline for meters under this transformer. Listed for corroboration only — a meter-level consumption drop alone is not sufficient evidence of irregularity.</p>
                  <div className="alert-list compact">
                    {detail.related_alerts.map((a) => (
                      <div className="alert-row" key={a.alert_id}>
                        <div>
                          <span className={riskClass((a.severity as Risk) || "Medium")}>{a.severity}</span>
                          <strong>{a.meter_id}</strong>
                          <small>{a.alert_timestamp} · Score {a.anomaly_score.toFixed(2)} · Drop {a.consumption_drop_pct.toFixed(1)}%</small>
                          <p>Status: {a.status} · Est. loss INR {Intl.NumberFormat("en-IN").format(Math.round(a.estimated_daily_loss_inr))}/day</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
              {detail.related_alerts.length === 0 && (
                <p className="muted" style={{ marginTop: 12 }}>No anomaly alerts found for meters under this transformer in the selected date range.</p>
              )}
            </div>
          )}
        </Panel>
      </section>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
