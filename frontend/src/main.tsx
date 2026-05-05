import React from "react";
import ReactDOM from "react-dom/client";
import { Activity, AlertTriangle, BarChart3, Database, GitBranch, Gauge, Map, ShieldCheck, SlidersHorizontal, Workflow } from "lucide-react";
import * as echarts from "echarts";
import "./styles/app.css";

type Risk = "Critical" | "High" | "Medium" | "Low" | "Normal";

type Overview = {
  kpis: Record<string, number | string>;
  zones: Array<{ name: string; risk: Risk; openAlerts: number; lossPct: number; loadPct: number }>;
  alerts: Array<{
    id: string;
    meterId: string;
    zone: string;
    risk: Risk;
    status: string;
    type: string;
    probability: number;
    revenueImpact: number;
    detectors: string[];
    summary: string;
    nextAction: string;
  }>;
  forecast: Array<{ timestamp: string; actual: number | null; forecast: number; lower90: number; upper90: number; lower99: number; upper99: number }>;
  detectors: Array<{ name: string; purpose: string; status: string; metric: string; coverage: number }>;
  pipeline: Array<{ layer: string; name: string; items: string[]; status: string }>;
  data_quality: Array<{ source: string; freshness: string; missingPct: number; status: string }>;
};

const configuredApiUrl = import.meta.env.VITE_API_URL || "";
const API_BASE = configuredApiUrl
  ? configuredApiUrl.startsWith("http")
    ? configuredApiUrl
    : `https://${configuredApiUrl}`
  : "";

const fallback: Overview = {
  kpis: {
    metersMonitored: 2000000,
    readsPerDay: 192000000,
    openAlerts: 148,
    criticalAlerts: 12,
    precisionAt50: 0.78,
    forecastMape: 0.041,
    revenueAtRisk: 18750000,
    recoveredMtd: 6420000
  },
  zones: [
    { name: "Indiranagar", risk: "Critical", openAlerts: 31, lossPct: 10.8, loadPct: 93 },
    { name: "Rajajinagar", risk: "High", openAlerts: 24, lossPct: 8.7, loadPct: 86 },
    { name: "Jayanagar", risk: "Medium", openAlerts: 18, lossPct: 5.9, loadPct: 74 },
    { name: "Whitefield", risk: "High", openAlerts: 27, lossPct: 7.6, loadPct: 82 },
    { name: "Yelahanka", risk: "Normal", openAlerts: 8, lossPct: 2.8, loadPct: 61 }
  ],
  alerts: [],
  forecast: Array.from({ length: 24 }, (_, i) => ({
    timestamp: `${i}:00`,
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

function useOverview() {
  const [data, setData] = React.useState<Overview>(fallback);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch(`${API_BASE}/api/v1/dashboard/overview`)
      .then((res) => res.ok ? res.json() : Promise.reject())
      .then(setData)
      .catch(() => setData(fallback))
      .finally(() => setLoading(false));
  }, []);

  return { data, loading };
}

function ForecastChart({ points }: { points: Overview["forecast"] }) {
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    const labels = points.map((point) => new Date(point.timestamp).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }));
    chart.setOption({
      tooltip: { trigger: "axis" },
      grid: { top: 20, right: 18, bottom: 28, left: 42 },
      xAxis: { type: "category", data: labels, axisLabel: { color: "#667085" } },
      yAxis: { type: "value", axisLabel: { color: "#667085" }, splitLine: { lineStyle: { color: "#eceff3" } } },
      series: [
        { name: "99% band", type: "line", data: points.map((p) => p.upper99), lineStyle: { opacity: 0 }, stack: "band99", symbol: "none" },
        { name: "99% lower", type: "line", data: points.map((p) => p.lower99), lineStyle: { opacity: 0 }, areaStyle: { color: "rgba(208, 213, 221, .45)" }, stack: "band99", symbol: "none" },
        { name: "Forecast", type: "line", data: points.map((p) => p.forecast), smooth: true, lineStyle: { width: 3, color: "#2563eb" }, symbol: "none" },
        { name: "Actual", type: "line", data: points.map((p) => p.actual), smooth: true, lineStyle: { width: 2, color: "#111827" }, symbolSize: 6 }
      ]
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [points]);

  return <div className="chart" ref={ref} />;
}

function App() {
  const { data, loading } = useOverview();
  const [scenarioTemp, setScenarioTemp] = React.useState(2);
  const nav = [
    ["Overview", Gauge],
    ["Alerts", AlertTriangle],
    ["Forecast", BarChart3],
    ["Zones", Map],
    ["Models", Activity],
    ["Pipeline", Workflow],
    ["Data", Database],
    ["Audit", ShieldCheck]
  ] as const;

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">B</span>
          <div>
            <strong>BESCOM AI</strong>
            <small>Smart meter operations</small>
          </div>
        </div>
        <nav>
          {nav.map(([label, Icon]) => (
            <a href={`#${label.toLowerCase()}`} key={label}>
              <Icon size={18} />
              {label}
            </a>
          ))}
        </nav>
      </aside>

      <section className="content">
        <header className="topbar">
          <div>
            <h1>Operations Dashboard</h1>
            <p>Demand forecasting, theft detection, field action, and audit readiness in one view.</p>
          </div>
          <div className={loading ? "sync loading" : "sync"}>{loading ? "Syncing" : "Live sample data"}</div>
        </header>

        <section id="overview" className="kpi-grid">
          <Metric icon={Gauge} label="Meters monitored" value={formatCompact(data.kpis.metersMonitored)} />
          <Metric icon={Database} label="15-min reads/day" value={formatCompact(data.kpis.readsPerDay)} />
          <Metric icon={AlertTriangle} label="Open alerts" value={formatCompact(data.kpis.openAlerts)} tone="warn" />
          <Metric icon={ShieldCheck} label="Precision@50" value={`${Math.round(Number(data.kpis.precisionAt50) * 100)}%`} />
          <Metric icon={BarChart3} label="Forecast MAPE" value={`${(Number(data.kpis.forecastMape) * 100).toFixed(1)}%`} />
          <Metric icon={Activity} label="Recovered MTD" value={money(Number(data.kpis.recoveredMtd))} />
        </section>

        <section className="dashboard-grid">
          <Panel id="alerts" title="Priority Alert Queue" action="Top ranked">
            <div className="alert-list">
              {data.alerts.map((alert) => (
                <article className="alert-row" key={alert.id}>
                  <div>
                    <span className={riskClass(alert.risk)}>{alert.risk}</span>
                    <strong>{alert.meterId}</strong>
                    <small>{alert.zone} · {alert.type} · {Math.round(alert.probability * 100)}%</small>
                    <p>{alert.summary}</p>
                  </div>
                  <div className="alert-meta">
                    <strong>{money(alert.revenueImpact)}</strong>
                    <small>{alert.nextAction}</small>
                  </div>
                </article>
              ))}
            </div>
          </Panel>

          <Panel id="zones" title="Zone Risk" action="Bangalore service area">
            <div className="zone-list">
              {data.zones.map((zone) => (
                <div className="zone-row" key={zone.name}>
                  <span className={riskClass(zone.risk)}>{zone.risk}</span>
                  <strong>{zone.name}</strong>
                  <div className="bar"><span style={{ width: `${zone.loadPct}%` }} /></div>
                  <small>{zone.openAlerts} alerts · {zone.lossPct}% loss</small>
                </div>
              ))}
            </div>
          </Panel>

          <Panel id="forecast" title="Demand Forecast" action="24 hour conformal band" wide>
            <ForecastChart points={data.forecast} />
          </Panel>

          <Panel id="models" title="Detector Coverage" action="Model layer">
            <div className="detector-grid">
              {data.detectors.map((detector) => (
                <div className="detector" key={detector.name}>
                  <div>
                    <strong>{detector.name}</strong>
                    <small>{detector.purpose}</small>
                  </div>
                  <span>{detector.metric}</span>
                  <div className="bar"><span style={{ width: `${detector.coverage}%` }} /></div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel id="pipeline" title="Feature Pipeline" action="Feature reflected">
            <div className="pipeline">
              {data.pipeline.map((layer) => (
                <div className="pipeline-step" key={layer.layer}>
                  <span>{layer.layer}</span>
                  <strong>{layer.name}</strong>
                  <small>{layer.items.join(" · ")}</small>
                  <em>{layer.status}</em>
                </div>
              ))}
            </div>
          </Panel>

          <Panel id="data" title="Data Quality" action="Operational inputs">
            <table>
              <thead>
                <tr><th>Source</th><th>Fresh</th><th>Missing</th><th>Status</th></tr>
              </thead>
              <tbody>
                {data.data_quality.map((row) => (
                  <tr key={row.source}>
                    <td>{row.source}</td>
                    <td>{row.freshness}</td>
                    <td>{row.missingPct}%</td>
                    <td>{row.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="Topology Trace" action="GNN ready">
            <div className="topology">
              {["Substation", "Feeder", "Transformer", "Meter"].map((node, index) => (
                <div className="topology-node" key={node}>
                  <GitBranch size={16} />
                  <strong>{node}</strong>
                  <small>{index === 3 ? "BES-4872193" : `Grid level ${index + 1}`}</small>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Scenario Lab" action="What-if">
            <div className="scenario">
              <SlidersHorizontal size={20} />
              <strong>Temperature sensitivity</strong>
              <input type="range" min="-4" max="8" value={scenarioTemp} onChange={(event) => setScenarioTemp(Number(event.target.value))} />
              <p>{scenarioTemp > 0 ? "+" : ""}{scenarioTemp}°C shifts peak demand by {(scenarioTemp * 1.2).toFixed(1)}% before capacity checks.</p>
            </div>
          </Panel>
        </section>
      </section>
    </main>
  );
}

function Metric({ icon: Icon, label, value, tone }: { icon: typeof Gauge; label: string; value: string; tone?: string }) {
  return (
    <article className={`metric ${tone || ""}`}>
      <Icon size={18} />
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function Panel({ id, title, action, children, wide }: { id?: string; title: string; action: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <section id={id} className={wide ? "panel wide" : "panel"}>
      <header>
        <h2>{title}</h2>
        <span>{action}</span>
      </header>
      {children}
    </section>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
