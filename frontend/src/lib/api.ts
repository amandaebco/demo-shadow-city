import { APP_CONFIG } from "./config";

export interface PolicyItem {
  type: "parking_tariff" | "transit_fare" | "road_closure";
  zone?: string;
  change_ratio: number;
}

export interface EventItem {
  type: "flood";
  area_id: string;
  start_tick: number;
  end_tick: number;
  depth_cm: number;
}

export interface Scenario {
  scenario_id: string;
  name: string;
  base_scenario_id: string | null;
  seed: number;
  population_size: number;
  population_id?: string;
  policies: PolicyItem[];
  events: EventItem[];
  status: "queued" | "generating_population" | "running" | "analyzing" | "completed" | "failed";
  progress: {
    current_tick: number;
    total_ticks: number;
  };
  created_at?: string;
  updated_at?: string;
}

export interface KelurahanMetric {
  kelurahan: string;
  avg_travel_min: number;
  avg_cost_idr: number;
  mode_share: Record<string, number>;
  stuck_count: number;
  cancelled_count: number;
}

export interface IncomeBandMetric {
  income_band: string;
  avg_travel_min: number;
  avg_cost_idr: number;
  stuck_count: number;
}

export interface ScenarioMetrics {
  scenario_id: string;
  by_kelurahan: KelurahanMetric[];
  by_income_band: IncomeBandMetric[];
  citywide: {
    avg_travel_min: number;
    avg_cost_idr?: number;
    mode_share: Record<string, number>;
    stuck_count?: number;
    cancelled_count?: number;
  };
}

export interface AnalystReport {
  report_id: string;
  scenario_id: string;
  base_scenario_id: string | null;
  headline: string;
  winners: string[];
  losers: string[];
  recommendations: string[];
  caveats: string[];
  generated_by: string;
}

export interface TickData {
  scenario_id: string;
  tick: number;
  persona_ids: string[];
  lat: number[];
  lng: number[];
  mode: string[];
  status: string[];
}

export interface Persona {
  persona_id: string;
  cluster_id: string;
  population_id?: string;
  home: { kelurahan: string; lat: number; lng: number };
  work: { kelurahan: string; lat: number; lng: number };
  age: number;
  occupation: string;
  income_band: string;
  vehicles: string[];
  usual_mode: string;
  usual_departure_tick: number;
  cost_sensitivity: number;
  time_sensitivity: number;
  profile_summary: string;
}

export function tickToLocalTime(tick: number): string {
  const totalMinutes = 5 * 60 + tick * 5;
  const hours = Math.floor(totalMinutes / 60) % 24;
  const minutes = totalMinutes % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

async function fetchOrchestrator(path: string, init?: RequestInit): Promise<Response> {
  if (typeof window !== "undefined" && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
    try {
      const sameOriginRes = await fetch(path, init);
      if (sameOriginRes.status !== 404 || sameOriginRes.headers.get("content-type")?.includes("application/json")) {
        return sameOriginRes;
      }
    } catch {
      // Fall back to direct Cloud Run URL
    }
  }
  return fetch(`${APP_CONFIG.orchestratorUrl}${path}`, init);
}

export async function fetchScenarios(): Promise<Scenario[]> {
  const res = await fetchOrchestrator(`/v1/scenarios`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch scenarios: HTTP ${res.status}`);
  }
  const data = await res.json();
  return Array.isArray(data) ? data : data.items || [];
}

export async function fetchScenario(scenarioId: string): Promise<Scenario> {
  const res = await fetchOrchestrator(`/v1/scenarios/${scenarioId}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch scenario ${scenarioId}: HTTP ${res.status}`);
  }
  return res.json();
}

export async function createScenario(payload: {
  name: string;
  base_scenario_id: string | null;
  seed: number;
  population_size: number;
  policies: PolicyItem[];
  events: EventItem[];
}): Promise<{ scenario_id: string }> {
  const res = await fetchOrchestrator(`/v1/scenarios`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Failed to create scenario: HTTP ${res.status} ${errText}`);
  }
  return res.json();
}

export async function fetchScenarioMetrics(scenarioId: string): Promise<ScenarioMetrics | null> {
  const res = await fetchOrchestrator(`/v1/scenarios/${scenarioId}/metrics`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Failed to fetch metrics for ${scenarioId}: HTTP ${res.status}`);
  }
  return res.json();
}

export async function fetchScenarioReport(scenarioId: string): Promise<AnalystReport | null> {
  const res = await fetchOrchestrator(`/v1/scenarios/${scenarioId}/report`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Failed to fetch report for ${scenarioId}: HTTP ${res.status}`);
  }
  return res.json();
}

function parseFirestoreValue(val: Record<string, unknown>): unknown {
  if ("stringValue" in val) return val.stringValue;
  if ("integerValue" in val) return Number(val.integerValue);
  if ("doubleValue" in val) return Number(val.doubleValue);
  if ("booleanValue" in val) return Boolean(val.booleanValue);
  if ("arrayValue" in val) {
    const arr = (val.arrayValue as { values?: Record<string, unknown>[] })?.values || [];
    return arr.map(parseFirestoreValue);
  }
  return null;
}

/**
 * Load all 204 tick documents for a scenario:
 * 1. Try Firebase Web SDK `getFirestore(app, "shadow-city")` (`scenarios/{scenarioId}/ticks`)
 * 2. Try static cached bundle `/ticks/${scenarioId}.json` if bundled
 * 3. Fallback: reconstruct deterministic straight-line ticks from Orchestrator personas + metrics
 */
export async function loadScenarioTicks(
  scenario: Scenario,
  metrics: ScenarioMetrics | null
): Promise<TickData[]> {
  const scenarioId = scenario.scenario_id;

  // 1. Try Firebase Web SDK on named database `shadow-city` in project `ebc-cloud-dev-03`
  try {
    const { fetchTicksViaFirestoreSdk } = await import("./firestore");
    const sdkTicks = await fetchTicksViaFirestoreSdk(scenarioId);
    if (sdkTicks.length > 0) {
      return sdkTicks;
    }
  } catch {
    // Ignore if rules are not yet deployed or offline, and fall back to static/REST
  }

  // 2. Check bundled static snapshot (instant load for pre-baked scenarios)
  try {
    const staticRes = await fetch(`/ticks/${scenarioId}.json`, { cache: "no-store" });
    if (staticRes.ok) {
      const staticTicks: TickData[] = await staticRes.json();
      if (Array.isArray(staticTicks) && staticTicks.length > 0) {
        return staticTicks;
      }
    }
  } catch {
    // Ignore and try REST / Orchestrator fallback next
  }

  // 3. Try Firestore REST API on database `shadow-city` in project `ebc-cloud-dev-03`
  try {
    const fsUrl = `https://firestore.googleapis.com/v1/projects/${APP_CONFIG.gcpProjectId}/databases/${APP_CONFIG.firestoreDatabase}/documents/scenarios/${scenarioId}/ticks?pageSize=250`;
    const fsRes = await fetch(fsUrl, { cache: "no-store" });
    if (fsRes.ok) {
      const body = await fsRes.json();
      const docs = body.documents || [];
      if (docs.length > 0) {
        const ticks: TickData[] = docs.map((doc: { fields?: Record<string, Record<string, unknown>> }) => {
          const f = doc.fields || {};
          return {
            scenario_id: String(parseFirestoreValue(f.scenario_id || {}) || scenarioId),
            tick: Number(parseFirestoreValue(f.tick || {}) ?? 0),
            persona_ids: (parseFirestoreValue(f.persona_ids || {}) as string[]) || [],
            lat: (parseFirestoreValue(f.lat || {}) as number[]) || [],
            lng: (parseFirestoreValue(f.lng || {}) as number[]) || [],
            mode: (parseFirestoreValue(f.mode || {}) as string[]) || [],
            status: (parseFirestoreValue(f.status || {}) as string[]) || [],
          };
        });
        ticks.sort((a, b) => a.tick - b.tick);
        return ticks;
      }
    }
  } catch {
    // Ignore and fall back to Orchestrator persona interpolation
  }

  // 3. Reconstruct from Orchestrator personas if Firestore direct browser read is restricted
  const popSize = Math.min(scenario.population_size || 50, 100);
  const seed = scenario.seed ?? 42;
  const personaIds = Array.from(
    { length: popSize },
    (_, i) => `p_s${seed}_n${scenario.population_size}_${String(i).padStart(5, "0")}`
  );

  const personas: Persona[] = [];
  const batchSize = 10;
  for (let i = 0; i < personaIds.length; i += batchSize) {
    const batch = personaIds.slice(i, i + batchSize);
    const fetched = await Promise.all(
      batch.map(async (pid) => {
        try {
          const r = await fetch(`${APP_CONFIG.orchestratorUrl}/v1/personas/${pid}`);
          return r.ok ? ((await r.json()) as Persona) : null;
        } catch {
          return null;
        }
      })
    );
    for (const p of fetched) {
      if (p) personas.push(p);
    }
  }

  if (personas.length === 0) return [];

  // Assign modes matching kelurahan mode_share if metrics exist, else usual_mode
  const kelShareMap = new Map<string, string[]>();
  if (metrics?.by_kelurahan) {
    for (const row of metrics.by_kelurahan) {
      const expanded: string[] = [];
      for (const [m, share] of Object.entries(row.mode_share || {})) {
        const count = Math.max(1, Math.round(share * 20));
        for (let k = 0; k < count; k++) expanded.push(m);
      }
      kelShareMap.set(row.kelurahan, expanded);
    }
  }

  const totalTicks = scenario.progress?.total_ticks || 204;
  const ticks: TickData[] = [];
  for (let tick = 0; tick < totalTicks; tick++) {
    const pids: string[] = [];
    const lats: number[] = [];
    const lngs: number[] = [];
    const modes: string[] = [];
    const statuses: string[] = [];

    personas.forEach((p, idx) => {
      pids.push(p.persona_id);
      const kelList = kelShareMap.get(p.home.kelurahan);
      const mode = kelList && kelList.length > 0 ? kelList[idx % kelList.length] : p.usual_mode;
      modes.push(mode);

      const depTick = p.usual_departure_tick ?? 24;
      const travelTicks = 12;
      const arrTick = depTick + travelTicks;

      if (tick < depTick) {
        lats.push(p.home.lat);
        lngs.push(p.home.lng);
        statuses.push("at_home");
      } else if (tick < arrTick) {
        const frac = (tick - depTick + 1) / (travelTicks + 1);
        lats.push(Number((p.home.lat + (p.work.lat - p.home.lat) * frac).toFixed(5)));
        lngs.push(Number((p.home.lng + (p.work.lng - p.home.lng) * frac).toFixed(5)));
        statuses.push("traveling");
      } else {
        lats.push(p.work.lat);
        lngs.push(p.work.lng);
        statuses.push("at_work");
      }
    });

    ticks.push({
      scenario_id: scenarioId,
      tick,
      persona_ids: pids,
      lat: lats,
      lng: lngs,
      mode: modes,
      status: statuses,
    });
  }

  return ticks;
}

