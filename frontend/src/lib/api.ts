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
  residents?: number;
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

export interface PersonaDecisionOptionDetail {
  est_minutes: number;
  cost_idr: number;
  flooded_on_route: boolean;
}

export interface PersonaDecisionEntry {
  tick: number;
  options_detail: Record<string, PersonaDecisionOptionDetail>;
  probabilities: Record<string, number>;
  chosen: string;
  reason_short: string;
  decided_by: string;
}

export interface PersonaDecisionRecord {
  persona_id: string;
  decisions: PersonaDecisionEntry[];
}

export function tickToLocalTime(tick: number): string {
  const totalMinutes = 5 * 60 + tick * 5;
  const hours = Math.floor(totalMinutes / 60) % 24;
  const minutes = totalMinutes % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

async function fetchOrchestrator(path: string, init?: RequestInit): Promise<Response> {
  if (
    typeof window !== "undefined" &&
    window.location.hostname !== "localhost" &&
    window.location.hostname !== "127.0.0.1"
  ) {
    try {
      const sameOriginRes = await fetch(path, init);
      if (
        sameOriginRes.status !== 404 ||
        sameOriginRes.headers.get("content-type")?.includes("application/json")
      ) {
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

export interface ScenarioCompareResponse {
  base: ScenarioMetrics;
  variant: ScenarioMetrics;
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

export async function fetchScenarioCompare(
  scenarioId: string,
  baseScenarioId?: string | null
): Promise<ScenarioCompareResponse | null> {
  const query = baseScenarioId ? `?base=${encodeURIComponent(baseScenarioId)}` : "";
  const res = await fetchOrchestrator(`/v1/scenarios/${scenarioId}/compare${query}`, {
    cache: "no-store",
  });
  if (res.status === 400 || res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Failed to fetch comparison for ${scenarioId}: HTTP ${res.status}`);
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
  if ("mapValue" in val) {
    const fields =
      (val.mapValue as { fields?: Record<string, Record<string, unknown>> })?.fields || {};
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(fields)) {
      out[k] = parseFirestoreValue(v);
    }
    return out;
  }
  return null;
}

/**
 * Fetch a persona document via GET /v1/personas/{persona_id} (CONTRACT.md §3).
 */
export async function fetchPersona(personaId: string): Promise<Persona | null> {
  const res = await fetchOrchestrator(`/v1/personas/${encodeURIComponent(personaId)}`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Failed to fetch persona ${personaId}: HTTP ${res.status}`);
  }
  return res.json();
}

/**
 * Load per-persona decision evidence chain (`scenarios/{scenarioId}/decisions/{personaId}`)
 * from the named Firestore database `shadow-city` (CONTRACT.md v1.5 §4.5).
 */
export async function fetchPersonaDecisions(
  scenarioId: string,
  personaId: string
): Promise<PersonaDecisionRecord | null> {
  try {
    const { fetchPersonaDecisionsViaFirestoreSdk } = await import("./firestore");
    const sdkDoc = await fetchPersonaDecisionsViaFirestoreSdk(scenarioId, personaId);
    if (sdkDoc) return sdkDoc;
  } catch (err) {
    console.warn("Firestore Web SDK decision read fell back to Firestore REST:", err);
  }

  const fsUrl = `https://firestore.googleapis.com/v1/projects/${APP_CONFIG.gcpProjectId}/databases/${APP_CONFIG.firestoreDatabase}/documents/scenarios/${scenarioId}/decisions/${encodeURIComponent(personaId)}`;
  const fsRes = await fetch(fsUrl, { cache: "no-store" });
  if (fsRes.status === 404) return null;
  if (!fsRes.ok) {
    throw new Error(
      `Failed to read scenarios/${scenarioId}/decisions/${personaId} from Firestore: HTTP ${fsRes.status}`
    );
  }
  const docBody = await fsRes.json();
  const f = docBody.fields || {};
  return {
    persona_id: String(parseFirestoreValue(f.persona_id || {}) || personaId),
    decisions:
      (parseFirestoreValue(f.decisions || {}) as PersonaDecisionEntry[]) || [],
  };
}

/**
 * Load all tick documents (`0000`..`0203`) for a scenario directly from the
 * named Firestore database `shadow-city` in project `ebc-cloud-dev-03` (CONTRACT.md §3, §5).
 */
export async function loadScenarioTicks(
  scenario: Scenario,
  _metrics: ScenarioMetrics | null
): Promise<TickData[]> {
  const scenarioId = scenario.scenario_id;

  // 1. Primary: Firebase Web SDK `getFirestore(app, "shadow-city")` (`scenarios/{scenarioId}/ticks`)
  try {
    const { fetchTicksViaFirestoreSdk } = await import("./firestore");
    const sdkTicks = await fetchTicksViaFirestoreSdk(scenarioId);
    if (sdkTicks.length > 0) {
      return sdkTicks;
    }
  } catch (err) {
    console.warn("Firestore Web SDK tick query fell back to Firestore REST:", err);
  }

  // 2. Direct Firestore v1 REST API on named database `shadow-city` in project `ebc-cloud-dev-03`
  const fsUrl = `https://firestore.googleapis.com/v1/projects/${APP_CONFIG.gcpProjectId}/databases/${APP_CONFIG.firestoreDatabase}/documents/scenarios/${scenarioId}/ticks?pageSize=250`;
  const fsRes = await fetch(fsUrl, { cache: "no-store" });
  if (!fsRes.ok) {
    throw new Error(
      `Failed to read scenarios/${scenarioId}/ticks from Firestore database ${APP_CONFIG.firestoreDatabase}: HTTP ${fsRes.status}`
    );
  }
  const body = await fsRes.json();
  const docs = body.documents || [];
  const ticks: TickData[] = docs.map(
    (doc: { fields?: Record<string, Record<string, unknown>> }) => {
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
    }
  );
  ticks.sort((a, b) => a.tick - b.tick);
  return ticks;
}

