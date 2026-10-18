"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { APP_CONFIG } from "@/lib/config";
import {
  AnalystReport,
  BacktestResult,
  createScenario,
  fetchBacktest,
  fetchPersona,
  fetchPersonaDecisions,
  fetchScenario,
  fetchScenarioCompare,
  fetchScenarioMetrics,
  fetchScenarioReport,
  fetchScenarios,
  fetchScenarioVerification,
  loadScenarioTicks,
  Persona,
  PersonaDecisionRecord,
  RP1_BACKTEST_SCENARIO_ID,
  SCALE_5000_SCENARIO_ID,
  Scenario,
  ScenarioCompareResponse,
  ScenarioMetrics,
  TickData,
  tickToLocalTime,
  VerificationReport,
} from "@/lib/api";
import {
  KELURAHAN_TO_KECAMATAN,
  MIN_AREA_RESIDENTS,
  rollupByKecamatan,
} from "@/lib/kelurahanMap";

const MODE_COLORS: Record<string, string> = {
  car: "#ef4444",
  motorcycle: "#f59e0b",
  transjakarta: "#3b82f6",
  krl: "#10b981",
  mrt: "#8b5cf6",
  ojol: "#06b6d4",
  walk: "#e2e8f0",
};

const MODE_LABELS: Record<string, string> = {
  car: "Car",
  motorcycle: "Motorcycle",
  transjakarta: "Transjakarta",
  krl: "KRL Commuter",
  mrt: "MRT Jakarta",
  ojol: "Ojol",
  walk: "Walk",
};

const SCENARIO_STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  generating_population: "Generating population",
  running: "Running",
  analyzing: "Analyzing",
  completed: "Completed",
  failed: "Failed",
};

const RESIDENT_STATUS_LABELS: Record<string, string> = {
  at_home: "At home",
  traveling: "Traveling",
  stuck: "Stuck in flood",
  at_work: "At work",
};

const INCOME_BAND_LABELS: Record<string, string> = {
  low: "Low income",
  lower_middle: "Lower-middle",
  middle: "Middle income",
  upper_middle: "Upper-middle",
  high: "High income",
};

const VERIFICATION_CHECK_LABELS: Record<string, string> = {
  population_size_matches: "Population size matches scenario",
  home_distribution_vs_reference: "Home distribution vs reference",
  age_distribution_vs_reference: "Age distribution vs reference",
  income_distribution_vs_reference: "Income distribution vs reference",
  baseline_mode_share_vs_reference: "Baseline mode share vs reference",
  baseline_mode_share_plausible: "Baseline mode share plausible",
  baseline_without_events_has_no_stuck_residents:
    "Baseline without events has no stuck residents",
  persona_profile_coherence: "Persona profile coherence",
  policy_effect_direction_plausible: "Policy effect direction plausible",
  flood_effect_direction_plausible: "Flood effect direction plausible",
};

const DECIDED_BY_LABELS: Record<string, string> = {
  "gemini-system-two": "Gemini (System Two)",
  "gemma-system-one": "Gemma (System One)",
  "rule-mock": "Rule Mock",
  "rule-fallback": "Rule Fallback",
};

function formatScenarioStatus(status: string): string {
  return SCENARIO_STATUS_LABELS[status] || status;
}

function formatResidentStatus(status: string): string {
  return RESIDENT_STATUS_LABELS[status] || status;
}

function formatIncomeBand(band: string): string {
  return INCOME_BAND_LABELS[band] || band.replace(/_/g, "-");
}

function formatVerificationCheckName(name: string): string {
  if (VERIFICATION_CHECK_LABELS[name]) return VERIFICATION_CHECK_LABELS[name];
  return name
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatDecidedBy(decidedBy: string): string {
  return DECIDED_BY_LABELS[decidedBy] || decidedBy;
}

const CANONICAL_MODE_ORDER = [
  "transjakarta",
  "motorcycle",
  "ojol",
  "car",
  "krl",
  "mrt",
  "walk",
];

const FEATURED_SCALE_5000_RESIDENTS = [
  { id: "p_s42_n5000_00005", tag: "p_s42_n5000_00005 (Transjakarta · Shared)" },
  { id: "p_s42_n5000_00001", tag: "p_s42_n5000_00001 (Ojol · Shared)" },
  { id: "p_s42_n5000_00000", tag: "p_s42_n5000_00000 (Motorcycle · Rep)" },
];

const ZONE_LABEL_POINTS: GeoJSON.FeatureCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: {
        zone_id: "central",
        label:
          "CENTRAL PARKING ZONE (+100% TARIFF)\nGambir · Menteng · Tanah Abang · Setiabudi",
      },
      geometry: {
        type: "Point",
        coordinates: [106.824, -6.198],
      },
    },
    {
      type: "Feature",
      properties: {
        zone_id: "jakarta_utara",
        label:
          "NORTH JAKARTA TIDAL FLOOD AREA\nPenjaringan · Pademangan · Tg. Priok · Koja · Cilincing",
      },
      geometry: {
        type: "Point",
        coordinates: [106.855, -6.122],
      },
    },
  ],
};

const DEMO_SCENARIO_PRIORITY: Record<string, number> = {
  s_baseline_weekday_c4d9d5: 1,
  s_central_parking_100_3aeda8: 2,
  s_central_parking_100_with_north_jakarta_t_fe362a: 3,
  [SCALE_5000_SCENARIO_ID]: 4,
  [RP1_BACKTEST_SCENARIO_ID]: 5,
};

const V1_UNIFORM_SCENARIO_PRIORITY: Record<string, number> = {
  s_baseline_weekday_ea7247: 11,
  s_central_parking_100_af902a: 12,
  s_central_parking_100_with_north_jakarta_t_78f06b: 13,
  s_rp1_fare_day_24_april_2026_0acbd5: 14,
};

function parseReferenceSource(raw: string | null | undefined): {
  text: string;
  url: string | null;
} {
  if (!raw) return { text: "Reference pending", url: null };
  const match = raw.match(/https?:\/\/\S+/);
  if (!match) return { text: raw, url: null };
  const url = match[0].replace(/[);,]+$/, "");
  const text = raw
    .replace(match[0], "")
    .replace(/[;\s]+$/, "")
    .trim();
  return { text: text || url, url };
}

function formatScenarioPickerLabel(s: Scenario): string {
  if (s.scenario_id === SCALE_5000_SCENARIO_ID) {
    return "Scale: 5,000 residents (clustered)";
  }
  return `${s.name} (${s.population_size.toLocaleString()} residents · ${formatScenarioStatus(
    s.status
  )})`;
}

interface CachedScenarioBundle {
  scenario: Scenario;
  metrics: ScenarioMetrics | null;
  comparison: ScenarioCompareResponse | null;
  ticks: TickData[];
  report: AnalystReport | null;
  verification: VerificationReport | null;
}

interface ReusableGeoJSONBuffer {
  scenarioId: string;
  count: number;
  collection: GeoJSON.FeatureCollection<GeoJSON.Point>;
}

function updateReusableResidentsGeoJSON(
  tickData: TickData | undefined,
  bufferRef: React.MutableRefObject<ReusableGeoJSONBuffer | null>
): GeoJSON.FeatureCollection {
  if (!tickData || !tickData.persona_ids || tickData.persona_ids.length === 0) {
    return { type: "FeatureCollection", features: [] };
  }
  const count = tickData.persona_ids.length;
  let buf = bufferRef.current;

  if (!buf || buf.scenarioId !== tickData.scenario_id || buf.count !== count) {
    const features: GeoJSON.Feature<GeoJSON.Point>[] = new Array(count);
    for (let i = 0; i < count; i++) {
      features[i] = {
        type: "Feature",
        properties: {
          persona_id: tickData.persona_ids[i],
          mode: tickData.mode[i] || "motorcycle",
          status: tickData.status[i] || "at_home",
        },
        geometry: {
          type: "Point",
          coordinates: [tickData.lng[i] || 0, tickData.lat[i] || 0],
        },
      };
    }
    buf = {
      scenarioId: tickData.scenario_id,
      count,
      collection: { type: "FeatureCollection", features },
    };
    bufferRef.current = buf;
    return buf.collection;
  }

  const features = buf.collection.features;
  for (let i = 0; i < count; i++) {
    const feat = features[i];
    const coords = feat.geometry.coordinates;
    coords[0] = tickData.lng[i] || 0;
    coords[1] = tickData.lat[i] || 0;
    if (feat.properties) {
      feat.properties.status = tickData.status[i] || "at_home";
    }
  }
  return buf.collection;
}

function formatSignedDelta(val: number, decimals = 1, unit = ""): string {
  const rounded = Number(val.toFixed(decimals));
  if (Math.abs(rounded) < 1e-6) return `0${unit}`;
  const sign = rounded > 0 ? "+" : "";
  return `${sign}${rounded.toFixed(decimals)}${unit}`;
}

function formatSignedIdr(val: number): string {
  const rounded = Math.round(val);
  if (rounded === 0) return "Rp 0";
  const sign = rounded > 0 ? "+" : "-";
  return `${sign}Rp ${Math.abs(rounded).toLocaleString()}`;
}

export default function JakartaMap() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const scenarioCacheRef = useRef<Map<string, CachedScenarioBundle>>(new Map());
  const personaCacheRef = useRef<Map<string, Persona | null>>(new Map());
  const decisionCacheRef = useRef<Map<string, PersonaDecisionRecord | null>>(new Map());
  const reusableGeoJsonRef = useRef<ReusableGeoJSONBuffer | null>(null);

  const [mapReady, setMapReady] = useState<boolean>(false);
  const [showZones, setShowZones] = useState<boolean>(true);
  const [showReportDrawer, setShowReportDrawer] = useState<boolean>(true);
  const [showCreateModal, setShowCreateModal] = useState<boolean>(false);
  const [drawerTab, setDrawerTab] = useState<
    "report" | "verification" | "backtest" | "breakdown"
  >("report");
  const [kecamatanSearch, setKecamatanSearch] = useState<string>("");

  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>(
    APP_CONFIG.defaultScenarioId
  );
  const [compareBaseOverride, setCompareBaseOverride] = useState<string>("");
  const [activeScenario, setActiveScenario] = useState<Scenario | null>(null);
  const [metrics, setMetrics] = useState<ScenarioMetrics | null>(null);
  const [comparison, setComparison] = useState<ScenarioCompareResponse | null>(null);
  const [report, setReport] = useState<AnalystReport | null>(null);
  const [verification, setVerification] = useState<VerificationReport | null>(null);
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [ticks, setTicks] = useState<TickData[]>([]);
  const [currentTick, setCurrentTick] = useState<number>(22);
  const [isPlaying, setIsPlaying] = useState<boolean>(true);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(2);
  const [loadingScenario, setLoadingScenario] = useState<boolean>(false);
  const [loadingReport, setLoadingReport] = useState<boolean>(false);
  const [loadingVerification, setLoadingVerification] = useState<boolean>(false);
  const [loadingBacktest, setLoadingBacktest] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Selected & hovered resident decision (evidence chain) state
  const [selectedPersonaId, setSelectedPersonaId] = useState<string | null>(null);
  const [hoveredPersonaId, setHoveredPersonaId] = useState<string | null>(null);
  const [residentSearchInput, setResidentSearchInput] = useState<string>("");
  const [residentSearchFeedback, setResidentSearchFeedback] = useState<string | null>(null);
  const [selectedPersona, setSelectedPersona] = useState<Persona | null>(null);
  const [selectedDecision, setSelectedDecision] = useState<PersonaDecisionRecord | null>(null);
  const [selectedBaseDecision, setSelectedBaseDecision] = useState<PersonaDecisionRecord | null>(
    null
  );
  const [loadingDecision, setLoadingDecision] = useState<boolean>(false);

  // New scenario form state
  const [newName, setNewName] = useState<string>("Central parking +100%");
  const [newBaseId, setNewBaseId] = useState<string>("");
  const [newPopSize, setNewPopSize] = useState<number>(1000);
  const [newParkingRatio, setNewParkingRatio] = useState<number>(1.0);
  const [includeFlood, setIncludeFlood] = useState<boolean>(false);
  const [creatingScenario, setCreatingScenario] = useState<boolean>(false);
  const [createErrorMessage, setCreateErrorMessage] = useState<string | null>(null);

  // Initialize MapLibre map
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
      center: [APP_CONFIG.jakartaCenter.lng, APP_CONFIG.jakartaCenter.lat],
      zoom: APP_CONFIG.jakartaCenter.zoom,
      pitch: 0,
      bearing: 0,
      attributionControl: { compact: true },
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }), "bottom-left");

    const popup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 10,
    });
    popupRef.current = popup;

    map.on("load", () => {
      map.addSource("shadow-city-zones", {
        type: "geojson",
        data: "/zones.geojson",
      });

      map.addLayer({
        id: "zones-fill",
        type: "fill",
        source: "shadow-city-zones",
        layout: {
          visibility: "visible",
        },
        paint: {
          "fill-color": [
            "match",
            ["get", "zone_id"],
            "central",
            "#f59e0b",
            "jakarta_utara",
            "#38bdf8",
            "#94a3b8",
          ],
          "fill-opacity": 0.24,
        },
      });

      map.addLayer({
        id: "zones-outline-glow",
        type: "line",
        source: "shadow-city-zones",
        layout: {
          visibility: "visible",
        },
        paint: {
          "line-color": [
            "match",
            ["get", "zone_id"],
            "central",
            "#fbbf24",
            "jakarta_utara",
            "#38bdf8",
            "#cbd5e1",
          ],
          "line-width": 6,
          "line-opacity": 0.28,
          "line-blur": 1.6,
        },
      });

      map.addLayer({
        id: "zones-outline",
        type: "line",
        source: "shadow-city-zones",
        layout: {
          visibility: "visible",
        },
        paint: {
          "line-color": [
            "match",
            ["get", "zone_id"],
            "central",
            "#fde047",
            "jakarta_utara",
            "#7dd3fc",
            "#cbd5e1",
          ],
          "line-width": 2.6,
          "line-dasharray": [2, 1.5],
        },
      });

      // Resident dots source and layers
      map.addSource("residents-source", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      map.addLayer({
        id: "residents-glow",
        type: "circle",
        source: "residents-source",
        paint: {
          "circle-radius": [
            "match",
            ["get", "status"],
            "traveling",
            10.5,
            "stuck",
            13,
            7,
          ],
          "circle-color": [
            "match",
            ["get", "mode"],
            "car",
            MODE_COLORS.car,
            "motorcycle",
            MODE_COLORS.motorcycle,
            "transjakarta",
            MODE_COLORS.transjakarta,
            "krl",
            MODE_COLORS.krl,
            "mrt",
            MODE_COLORS.mrt,
            "ojol",
            MODE_COLORS.ojol,
            "walk",
            MODE_COLORS.walk,
            "#38bdf8",
          ],
          "circle-opacity": [
            "match",
            ["get", "status"],
            "traveling",
            0.35,
            "stuck",
            0.52,
            0.18,
          ],
          "circle-blur": 0.6,
        },
      });

      map.addLayer({
        id: "residents-circle",
        type: "circle",
        source: "residents-source",
        paint: {
          "circle-radius": [
            "match",
            ["get", "status"],
            "traveling",
            5.5,
            "stuck",
            7.0,
            4.2,
          ],
          "circle-color": [
            "match",
            ["get", "mode"],
            "car",
            MODE_COLORS.car,
            "motorcycle",
            MODE_COLORS.motorcycle,
            "transjakarta",
            MODE_COLORS.transjakarta,
            "krl",
            MODE_COLORS.krl,
            "mrt",
            MODE_COLORS.mrt,
            "ojol",
            MODE_COLORS.ojol,
            "walk",
            MODE_COLORS.walk,
            "#38bdf8",
          ],
          "circle-stroke-width": 1.3,
          "circle-stroke-color": [
            "match",
            ["get", "status"],
            "stuck",
            "#fef08a",
            "#0f172a",
          ],
        },
      });

      // Zone labels source and layer placed above resident dots for 1080p legibility
      map.addSource("shadow-city-zone-labels", {
        type: "geojson",
        data: ZONE_LABEL_POINTS,
      });

      map.addLayer({
        id: "zones-label",
        type: "symbol",
        source: "shadow-city-zone-labels",
        layout: {
          visibility: "visible",
          "text-field": ["get", "label"],
          "text-size": 12.5,
          "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"],
          "text-justify": "center",
          "text-anchor": "center",
          "text-allow-overlap": true,
        },
        paint: {
          "text-color": [
            "match",
            ["get", "zone_id"],
            "central",
            "#fef3c7",
            "jakarta_utara",
            "#e0f2fe",
            "#f8fafc",
          ],
          "text-halo-color": "#020617",
          "text-halo-width": 2.4,
        },
      });

      map.addLayer({
        id: "resident-hover-ring",
        type: "circle",
        source: "residents-source",
        filter: ["==", ["get", "persona_id"], ""],
        paint: {
          "circle-radius": 15,
          "circle-color": "rgba(250, 204, 21, 0.26)",
          "circle-stroke-width": 2.8,
          "circle-stroke-color": "#fde047",
        },
      });

      map.addLayer({
        id: "resident-selected-ring",
        type: "circle",
        source: "residents-source",
        filter: ["==", ["get", "persona_id"], ""],
        paint: {
          "circle-radius": 14,
          "circle-color": "rgba(56, 189, 248, 0.3)",
          "circle-stroke-width": 3,
          "circle-stroke-color": "#ffffff",
        },
      });

      map.addLayer({
        id: "resident-active-label",
        type: "symbol",
        source: "residents-source",
        filter: ["==", ["get", "persona_id"], ""],
        layout: {
          "text-field": ["get", "persona_id"],
          "text-size": 12,
          "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"],
          "text-offset": [0, -1.6],
          "text-anchor": "bottom",
          "text-allow-overlap": true,
        },
        paint: {
          "text-color": "#fef08a",
          "text-halo-color": "#020617",
          "text-halo-width": 2.2,
        },
      });

      map.on("mousemove", "residents-circle", (e) => {
        map.getCanvas().style.cursor = "pointer";
        const feat = e.features?.[0];
        if (!feat || feat.geometry.type !== "Point") return;
        const coords = feat.geometry.coordinates.slice() as [number, number];
        const props = feat.properties || {};
        const pid = String(props.persona_id || "");
        if (pid) {
          setHoveredPersonaId((prev) => (prev === pid ? prev : pid));
        }
        const modeLabel = MODE_LABELS[props.mode] || props.mode;
        const statusLabel = formatResidentStatus(String(props.status || "at_home"));
        popup
          .setLngLat(coords)
          .setHTML(
            `<div style="color:#0f172a;font-size:12.5px;line-height:1.45">
              <strong>Resident: ${pid}</strong><br/>
              Mode: <b>${modeLabel}</b><br/>
              Status: <b>${statusLabel}</b><br/>
              <span style="color:#0284c7;font-weight:700">Click dot to view decision &rarr;</span>
            </div>`
          )
          .addTo(map);
      });

      map.on("mouseleave", "residents-circle", () => {
        map.getCanvas().style.cursor = "";
        setHoveredPersonaId(null);
        popup.remove();
      });

      map.on("click", "residents-circle", (e) => {
        const feat = e.features?.[0];
        const pid = feat?.properties?.persona_id;
        if (typeof pid === "string" && pid) {
          setSelectedPersonaId(pid);
          setResidentSearchFeedback(null);
        }
      });

      setMapReady(true);
    });

    mapRef.current = map;

    return () => {
      popup.remove();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Toggle zone visibility
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const visibility = showZones ? "visible" : "none";
    for (const layerId of [
      "zones-fill",
      "zones-outline-glow",
      "zones-outline",
      "zones-label",
    ]) {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, "visibility", visibility);
      }
    }
  }, [showZones, mapReady]);

  // Load scenario list on mount
  const refreshScenarioList = useCallback(async (selectPreferredOnFirstLoad = false) => {
    try {
      const list = await fetchScenarios();
      const sorted = [...list].sort((a, b) => {
        const pa =
          DEMO_SCENARIO_PRIORITY[a.scenario_id] ??
          V1_UNIFORM_SCENARIO_PRIORITY[a.scenario_id] ??
          99;
        const pb =
          DEMO_SCENARIO_PRIORITY[b.scenario_id] ??
          V1_UNIFORM_SCENARIO_PRIORITY[b.scenario_id] ??
          99;
        if (pa !== pb) return pa - pb;
        return (b.created_at || "").localeCompare(a.created_at || "");
      });
      setScenarios(sorted);
      if (selectPreferredOnFirstLoad && sorted.length > 0) {
        const preferredFloodVariant = sorted.find(
          (s) => s.scenario_id === "s_central_parking_100_with_north_jakarta_t_fe362a"
        );
        const preferredVariant = sorted.find(
          (s) =>
            s.status === "completed" &&
            s.base_scenario_id &&
            s.name.toLowerCase().includes("central parking")
        );
        const preferredBase =
          sorted.find((s) => s.scenario_id === "s_baseline_weekday_c4d9d5") ||
          sorted.find(
            (s) =>
              s.status === "completed" &&
              s.name.toLowerCase() === "baseline weekday"
          );
        if (preferredBase) {
          setNewBaseId(preferredBase.scenario_id);
        }
        const targetId =
          preferredFloodVariant?.scenario_id ||
          preferredVariant?.scenario_id ||
          preferredBase?.scenario_id;
        if (targetId) {
          setSelectedScenarioId((prev) => (prev === targetId ? prev : targetId));
        }
      }
    } catch (err) {
      console.warn("Could not list scenarios:", err);
    }
  }, []);

  const loadBacktestData = useCallback(async () => {
    setLoadingBacktest(true);
    try {
      const bt = await fetchBacktest("b_0001");
      setBacktest(bt);
    } catch {
      setBacktest(null);
    } finally {
      setLoadingBacktest(false);
    }
  }, []);

  useEffect(() => {
    refreshScenarioList(true);
    loadBacktestData();
  }, [refreshScenarioList, loadBacktestData]);

  // Fetch a scenario bundle (used for both active scenario load and background prefetch)
  const fetchScenarioBundleRaw = useCallback(
    async (
      scenarioId: string,
      baseOverride?: string
    ): Promise<CachedScenarioBundle> => {
      const [scen, scenMetrics, rep, ver] = await Promise.all([
        fetchScenario(scenarioId),
        fetchScenarioMetrics(scenarioId).catch(() => null),
        fetchScenarioReport(scenarioId).catch(() => null),
        fetchScenarioVerification(scenarioId).catch(() => null),
      ]);

      const effectiveBaseId =
        baseOverride !== undefined
          ? baseOverride || null
          : scen.base_scenario_id || null;

      const [cmp, loadedTicks] = await Promise.all([
        effectiveBaseId && effectiveBaseId !== scenarioId && scenMetrics
          ? fetchScenarioCompare(scenarioId, effectiveBaseId).catch(() => null)
          : Promise.resolve(null),
        loadScenarioTicks(scen, scenMetrics),
      ]);

      return {
        scenario: scen,
        metrics: scenMetrics,
        comparison: cmp,
        ticks: loadedTicks,
        report: rep,
        verification: ver,
      };
    },
    []
  );

  // Load selected scenario details, ticks, metrics, comparison, and analyst report
  const loadScenarioBundle = useCallback(
    async (scenarioId: string, baseOverride?: string, forceRefresh = false) => {
      if (!scenarioId) return;
      setErrorMessage(null);

      const cacheKey = `${scenarioId}::${baseOverride ?? "default"}`;
      const cached = !forceRefresh ? scenarioCacheRef.current.get(cacheKey) : undefined;
      if (cached) {
        setActiveScenario(cached.scenario);
        setMetrics(cached.metrics);
        setComparison(cached.comparison);
        setTicks(cached.ticks);
        setReport(cached.report);
        setVerification(cached.verification);
        setLoadingScenario(false);
        setLoadingReport(false);
        setLoadingVerification(false);
        return;
      }

      setLoadingScenario(true);
      setLoadingReport(true);
      setLoadingVerification(true);
      try {
        const bundle = await fetchScenarioBundleRaw(scenarioId, baseOverride);
        setActiveScenario(bundle.scenario);
        setMetrics(bundle.metrics);
        setComparison(bundle.comparison);
        setTicks(bundle.ticks);
        setReport(bundle.report);
        setVerification(bundle.verification);

        if (bundle.scenario.status === "completed" && bundle.ticks.length > 0) {
          scenarioCacheRef.current.set(cacheKey, bundle);
        }
      } catch {
        setErrorMessage(
          "Unable to load scenario data right now. Please check your connection or click Refresh."
        );
      } finally {
        setLoadingScenario(false);
        setLoadingReport(false);
        setLoadingVerification(false);
      }
    },
    [fetchScenarioBundleRaw]
  );

  // Warm the in-memory cache for the other primary demo scenarios so video switching is instant
  useEffect(() => {
    const timer = setTimeout(() => {
      for (const demoId of Object.keys(DEMO_SCENARIO_PRIORITY)) {
        const key = `${demoId}::default`;
        if (!scenarioCacheRef.current.has(key)) {
          fetchScenarioBundleRaw(demoId)
            .then((bundle) => {
              if (bundle.scenario.status === "completed" && bundle.ticks.length > 0) {
                scenarioCacheRef.current.set(key, bundle);
              }
            })
            .catch(() => {
              // Ignore background prefetch errors
            });
        }
      }
    }, 800);
    return () => clearTimeout(timer);
  }, [fetchScenarioBundleRaw]);

  useEffect(() => {
    setCompareBaseOverride("");
    if (selectedScenarioId === RP1_BACKTEST_SCENARIO_ID) {
      setDrawerTab("backtest");
    }
    setSelectedPersonaId((prev) => {
      if (!prev) return null;
      const is5000Scenario = selectedScenarioId === SCALE_5000_SCENARIO_ID;
      const is5000Persona = prev.includes("_n5000_");
      if (is5000Scenario !== is5000Persona) return null;
      return prev;
    });
    loadScenarioBundle(selectedScenarioId);
  }, [selectedScenarioId, loadScenarioBundle]);

  const handleBaseOverrideChange = async (newBase: string) => {
    setCompareBaseOverride(newBase);
    if (!selectedScenarioId) return;
    if (!newBase || newBase === selectedScenarioId) {
      setComparison(null);
      return;
    }
    try {
      const cmp = await fetchScenarioCompare(selectedScenarioId, newBase);
      setComparison(cmp);
    } catch {
      setComparison(null);
    }
  };

  // Real-time Firestore subscription on database shadow-city while scenario is running
  useEffect(() => {
    if (!selectedScenarioId || !activeScenario || activeScenario.status !== "running") {
      return;
    }
    let unsubscribe: (() => void) | undefined;
    import("@/lib/firestore")
      .then(({ subscribeScenarioTicks }) => {
        unsubscribe = subscribeScenarioTicks(selectedScenarioId, (liveTicks) => {
          if (liveTicks.length > 0) {
            setTicks(liveTicks);
          }
        });
      })
      .catch(() => {
        // Ignore if subscription cannot attach
      });
    return () => {
      if (unsubscribe) unsubscribe();
    };
  }, [selectedScenarioId, activeScenario]);

  // Update GeoJSON source whenever currentTick or ticks change
  const currentTickData = useMemo(() => {
    if (!ticks.length) return undefined;
    return ticks[currentTick] || ticks.find((t) => t.tick === currentTick) || ticks[0];
  }, [ticks, currentTick]);

  const isLargeScaleScenario =
    (activeScenario?.population_size ?? 0) >= 2500 ||
    (currentTickData?.persona_ids?.length ?? 0) >= 2500;

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    if (map.getLayer("residents-glow")) {
      map.setPaintProperty(
        "residents-glow",
        "circle-radius",
        isLargeScaleScenario
          ? ["match", ["get", "status"], "traveling", 7.2, "stuck", 9.5, 4.5]
          : ["match", ["get", "status"], "traveling", 10.5, "stuck", 13, 7]
      );
      map.setPaintProperty(
        "residents-glow",
        "circle-opacity",
        isLargeScaleScenario
          ? ["match", ["get", "status"], "traveling", 0.26, "stuck", 0.45, 0.12]
          : ["match", ["get", "status"], "traveling", 0.35, "stuck", 0.52, 0.18]
      );
    }
    if (map.getLayer("residents-circle")) {
      map.setPaintProperty(
        "residents-circle",
        "circle-radius",
        isLargeScaleScenario
          ? ["match", ["get", "status"], "traveling", 3.8, "stuck", 5.2, 2.7]
          : ["match", ["get", "status"], "traveling", 5.5, "stuck", 7.0, 4.2]
      );
      map.setPaintProperty(
        "residents-circle",
        "circle-stroke-width",
        isLargeScaleScenario ? 0.9 : 1.3
      );
    }
  }, [isLargeScaleScenario, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const src = map.getSource("residents-source") as maplibregl.GeoJSONSource | undefined;
    if (src) {
      src.setData(updateReusableResidentsGeoJSON(currentTickData, reusableGeoJsonRef));
    }
  }, [currentTickData, mapReady]);

  // Highlight selected and hovered resident dots on the map
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    if (map.getLayer("resident-selected-ring")) {
      map.setFilter("resident-selected-ring", [
        "==",
        ["get", "persona_id"],
        selectedPersonaId || "",
      ]);
    }
    if (map.getLayer("resident-hover-ring")) {
      map.setFilter("resident-hover-ring", [
        "==",
        ["get", "persona_id"],
        hoveredPersonaId || "",
      ]);
    }
    if (map.getLayer("resident-active-label")) {
      const activeIds = [selectedPersonaId, hoveredPersonaId].filter(
        (id): id is string => Boolean(id)
      );
      map.setFilter(
        "resident-active-label",
        activeIds.length > 0
          ? ["in", ["get", "persona_id"], ["literal", activeIds]]
          : ["==", ["get", "persona_id"], ""]
      );
    }
  }, [selectedPersonaId, hoveredPersonaId, mapReady]);

  // Animation loop for ticks 0..203
  useEffect(() => {
    if (!isPlaying || ticks.length === 0) return;
    const intervalMs = Math.max(40, Math.round(240 / playbackSpeed));
    const timer = setInterval(() => {
      setCurrentTick((prev) => (prev + 1) % ticks.length);
    }, intervalMs);
    return () => clearInterval(timer);
  }, [isPlaying, playbackSpeed, ticks.length]);

  // Live status counts at current tick
  const statusCounts = useMemo(() => {
    const counts = { at_home: 0, traveling: 0, stuck: 0, at_work: 0 };
    if (!currentTickData?.status) return counts;
    for (const s of currentTickData.status) {
      if (s in counts) {
        counts[s as keyof typeof counts] += 1;
      }
    }
    return counts;
  }, [currentTickData]);

  // Compute combined mode list for side-by-side mode share comparison
  const comparedModes = useMemo(() => {
    if (!comparison) return [];
    const baseShare = comparison.base.citywide?.mode_share || {};
    const varShare = comparison.variant.citywide?.mode_share || {};
    const allModes = Array.from(
      new Set([...CANONICAL_MODE_ORDER, ...Object.keys(baseShare), ...Object.keys(varShare)])
    ).filter((m) => (baseShare[m] ?? 0) > 0 || (varShare[m] ?? 0) > 0);
    return allModes.map((m) => {
      const bPct = (baseShare[m] ?? 0) * 100;
      const vPct = (varShare[m] ?? 0) * 100;
      return {
        mode: m,
        label: MODE_LABELS[m] || m,
        color: MODE_COLORS[m] || "#64748b",
        basePct: bPct,
        varPct: vPct,
        deltaPp: vPct - bPct,
      };
    });
  }, [comparison]);

  // Compute per-income-band comparison rows
  const incomeComparisonRows = useMemo(() => {
    const varBands = comparison?.variant?.by_income_band || metrics?.by_income_band || [];
    const baseByBand = new Map(
      (comparison?.base?.by_income_band || []).map((row) => [row.income_band, row])
    );
    return varBands.map((vRow) => {
      const bRow = baseByBand.get(vRow.income_band);
      return {
        income_band: vRow.income_band,
        base_min: bRow?.avg_travel_min ?? null,
        var_min: vRow.avg_travel_min,
        delta_min: bRow ? vRow.avg_travel_min - bRow.avg_travel_min : null,
        base_cost: bRow?.avg_cost_idr ?? null,
        var_cost: vRow.avg_cost_idr,
        delta_cost: bRow ? vRow.avg_cost_idr - bRow.avg_cost_idr : null,
        base_stuck: bRow?.stuck_count ?? null,
        var_stuck: vRow.stuck_count,
      };
    });
  }, [comparison, metrics]);

  // Compute resident-weighted per-kecamatan comparison rows (mapping kelurahan -> kecamatan)
  const kecamatanComparisonRows = useMemo(() => {
    const varKel = comparison?.variant?.by_kelurahan || metrics?.by_kelurahan || [];
    const baseKel = comparison?.base?.by_kelurahan || [];
    const varKec = rollupByKecamatan(varKel);
    const baseByKec = new Map(rollupByKecamatan(baseKel).map((r) => [r.kecamatan, r]));

    const query = kecamatanSearch.trim().toLowerCase();
    const rows = varKec
      .filter((r) => !query || r.kecamatan.toLowerCase().includes(query))
      .map((vRow) => {
        const bRow = baseByKec.get(vRow.kecamatan);
        const deltaMin = bRow
          ? Math.round((vRow.avg_travel_min - bRow.avg_travel_min) * 10) / 10
          : 0;
        const deltaCost = bRow ? vRow.avg_cost_idr - bRow.avg_cost_idr : 0;
        const deltaStuck = vRow.stuck_count - (bRow?.stuck_count ?? 0);
        return {
          kecamatan: vRow.kecamatan,
          residents: vRow.residents,
          base_min: bRow?.avg_travel_min ?? null,
          var_min: vRow.avg_travel_min,
          delta_min: bRow ? deltaMin : null,
          base_cost: bRow?.avg_cost_idr ?? null,
          var_cost: vRow.avg_cost_idr,
          delta_cost: bRow ? deltaCost : null,
          base_stuck: bRow?.stuck_count ?? null,
          var_stuck: vRow.stuck_count,
          sortScore:
            Math.abs(deltaStuck) * 5000 + Math.abs(deltaMin) * 1000 + Math.abs(deltaCost),
        };
      });
    if (comparison) {
      rows.sort((a, b) => b.sortScore - a.sortScore || a.kecamatan.localeCompare(b.kecamatan));
    } else {
      rows.sort((a, b) => b.residents - a.residents || a.kecamatan.localeCompare(b.kecamatan));
    }
    return rows;
  }, [comparison, metrics, kecamatanSearch]);

  // Only kelurahan with >= 10 residents (MIN_AREA_RESIDENTS)
  const kelurahanMajorRows = useMemo(() => {
    const varKel = comparison?.variant?.by_kelurahan || metrics?.by_kelurahan || [];
    const baseByKel = new Map(
      (comparison?.base?.by_kelurahan || []).map((row) => [row.kelurahan, row])
    );
    return varKel
      .filter((r) => (r.residents ?? 0) >= MIN_AREA_RESIDENTS)
      .map((vRow) => {
        const bRow = baseByKel.get(vRow.kelurahan);
        const deltaMin = bRow
          ? Math.round((vRow.avg_travel_min - bRow.avg_travel_min) * 10) / 10
          : null;
        return {
          kelurahan: vRow.kelurahan,
          kecamatan: KELURAHAN_TO_KECAMATAN[vRow.kelurahan] || "",
          residents: vRow.residents ?? 0,
          base_min: bRow?.avg_travel_min ?? null,
          var_min: vRow.avg_travel_min,
          delta_min: deltaMin,
          base_cost: bRow?.avg_cost_idr ?? null,
          var_cost: vRow.avg_cost_idr,
          var_stuck: vRow.stuck_count,
        };
      });
  }, [comparison, metrics]);

  const effectiveCompareBaseId =
    compareBaseOverride !== ""
      ? compareBaseOverride
      : activeScenario?.base_scenario_id || "";

  const baseScenarioObj = useMemo(
    () => scenarios.find((s) => s.scenario_id === comparison?.base?.scenario_id),
    [scenarios, comparison]
  );

  // Cached helpers for persona profile & decision evidence chain
  const getPersonaCached = useCallback(async (personaId: string): Promise<Persona | null> => {
    if (personaCacheRef.current.has(personaId)) {
      return personaCacheRef.current.get(personaId) ?? null;
    }
    const p = await fetchPersona(personaId).catch(() => null);
    if (p) personaCacheRef.current.set(personaId, p);
    return p;
  }, []);

  const getDecisionCached = useCallback(
    async (
      scenarioId: string,
      personaId: string
    ): Promise<PersonaDecisionRecord | null> => {
      const key = `${scenarioId}::${personaId}`;
      if (decisionCacheRef.current.has(key)) {
        return decisionCacheRef.current.get(key) ?? null;
      }
      const d = await fetchPersonaDecisions(scenarioId, personaId).catch(() => null);
      if (d && d.decisions?.length) decisionCacheRef.current.set(key, d);
      return d;
    },
    []
  );

  const quickPickResidents = useMemo(() => {
    if (isLargeScaleScenario || selectedScenarioId === SCALE_5000_SCENARIO_ID) {
      return FEATURED_SCALE_5000_RESIDENTS;
    }
    const ids = currentTickData?.persona_ids || [];
    const modes = currentTickData?.mode || [];
    return ids.slice(0, 3).map((id, idx) => {
      const modeName = MODE_LABELS[modes[idx] || ""] || modes[idx] || "Resident";
      return { id, tag: `${id} (${modeName})` };
    });
  }, [isLargeScaleScenario, selectedScenarioId, currentTickData]);

  // Prefetch quick-pick residents so clicking in the UI is instant
  useEffect(() => {
    if (!selectedScenarioId || quickPickResidents.length === 0) return;
    const timer = setTimeout(() => {
      for (const item of quickPickResidents) {
        getPersonaCached(item.id);
        getDecisionCached(selectedScenarioId, item.id);
        if (effectiveCompareBaseId && effectiveCompareBaseId !== selectedScenarioId) {
          getDecisionCached(effectiveCompareBaseId, item.id);
        }
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [
    selectedScenarioId,
    effectiveCompareBaseId,
    quickPickResidents,
    getPersonaCached,
    getDecisionCached,
  ]);

  // Load selected persona profile + scenario decision evidence chain when selectedPersonaId changes
  useEffect(() => {
    if (!selectedPersonaId || !selectedScenarioId) {
      setSelectedPersona(null);
      setSelectedDecision(null);
      setSelectedBaseDecision(null);
      return;
    }
    let cancelled = false;
    setLoadingDecision(true);
    Promise.all([
      getPersonaCached(selectedPersonaId),
      getDecisionCached(selectedScenarioId, selectedPersonaId),
      effectiveCompareBaseId && effectiveCompareBaseId !== selectedScenarioId
        ? getDecisionCached(effectiveCompareBaseId, selectedPersonaId)
        : Promise.resolve(null),
    ])
      .then(([personaDoc, decDoc, baseDecDoc]) => {
        if (cancelled) return;
        setSelectedPersona(personaDoc);
        setSelectedDecision(decDoc);
        setSelectedBaseDecision(baseDecDoc);
      })
      .finally(() => {
        if (!cancelled) setLoadingDecision(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    selectedPersonaId,
    selectedScenarioId,
    effectiveCompareBaseId,
    getPersonaCached,
    getDecisionCached,
  ]);

  const handleSelectResident = useCallback(
    (personaId: string, flyTo = false) => {
      setSelectedPersonaId(personaId);
      setResidentSearchFeedback(null);
      if (flyTo && currentTickData?.persona_ids) {
        const idx = currentTickData.persona_ids.indexOf(personaId);
        if (idx >= 0) {
          const lat = currentTickData.lat[idx];
          const lng = currentTickData.lng[idx];
          if (typeof lat === "number" && typeof lng === "number") {
            mapRef.current?.flyTo({
              center: [lng, lat],
              zoom: Math.max(mapRef.current.getZoom(), 12.0),
              offset: [70, 0],
              duration: 600,
            });
          }
        }
      }
    },
    [currentTickData]
  );

  const handleFindResident = (e: React.FormEvent) => {
    e.preventDefault();
    const raw = residentSearchInput.trim();
    if (!raw) return;
    const query = raw.toLowerCase().replace(/^#/, "");
    const ids = currentTickData?.persona_ids || [];

    let matched =
      ids.find((id) => id.toLowerCase() === query) ||
      ids.find((id) => id.toLowerCase().endsWith(`_${query.padStart(5, "0")}`)) ||
      ids.find((id) => id.toLowerCase().includes(query));

    if (!matched && /^\d+$/.test(query)) {
      const popId =
        activeScenario?.population_id ||
        `pop_s${activeScenario?.seed || 2026}_n${activeScenario?.population_size || 1000}_r2`;
      const prefix = popId.replace(/^pop_/, "p_");
      matched = `${prefix}_${query.padStart(5, "0")}`;
    } else if (!matched && query.startsWith("p_")) {
      matched = raw;
    }

    if (matched) {
      handleSelectResident(matched, true);
    } else {
      setResidentSearchFeedback(
        `No resident matching "${raw}". Enter a persona ID or 5-digit index (e.g. 00001).`
      );
    }
  };

  const handleResetView = () => {
    mapRef.current?.flyTo({
      center: [APP_CONFIG.jakartaCenter.lng, APP_CONFIG.jakartaCenter.lat],
      zoom: APP_CONFIG.jakartaCenter.zoom,
      pitch: 0,
      bearing: 0,
      duration: 900,
    });
  };

  const handleCreateScenario = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreatingScenario(true);
    setCreateErrorMessage(null);
    try {
      const policies =
        Math.abs(Number(newParkingRatio)) > 1e-6
          ? [
              {
                type: "parking_tariff" as const,
                zone: "central",
                change_ratio: Number(newParkingRatio),
              },
            ]
          : [];
      const created = await createScenario({
        name: newName.trim() || "Custom Scenario",
        base_scenario_id: newBaseId || null,
        seed: 42,
        population_size: newPopSize,
        policies,
        events: includeFlood
          ? [
              {
                type: "flood",
                area_id: "jakarta_utara",
                start_tick: 12,
                end_tick: 72,
                depth_cm: 45,
              },
            ]
          : [],
      });
      await refreshScenarioList(false);
      setSelectedScenarioId(created.scenario_id);
      setShowCreateModal(false);
    } catch {
      setCreateErrorMessage(
        "Unable to create scenario right now. Please check your connection and try again."
      );
    } finally {
      setCreatingScenario(false);
    }
  };

  return (
    <div className="map-shell">
      {/* Top HUD Bar */}
      <header className="hud-header">
        <div className="hud-brand">
          <span className="status-dot" aria-hidden="true" />
          <div>
            <h1>Shadow City</h1>
            <p className="subtitle">
              Jakarta Policy &amp; Flood Simulator &middot; AI Builder Cup 2026
            </p>
          </div>
        </div>

        <div className="hud-controls">
          <label className="scenario-picker-label">
            <span>Scenario:</span>
            <select
              className="scenario-select"
              value={selectedScenarioId}
              onChange={(e) => setSelectedScenarioId(e.target.value)}
              aria-label="Select scenario"
            >
              {scenarios.length === 0 && (
                <option value={APP_CONFIG.defaultScenarioId}>
                  Loading scenarios...
                </option>
              )}
              {scenarios.some((s) => s.scenario_id in DEMO_SCENARIO_PRIORITY) ? (
                <>
                  <optgroup label="Demo Scenarios">
                    {scenarios
                      .filter((s) => s.scenario_id in DEMO_SCENARIO_PRIORITY)
                      .map((s) => (
                        <option key={s.scenario_id} value={s.scenario_id}>
                          {formatScenarioPickerLabel(s)}
                        </option>
                      ))}
                  </optgroup>
                  {scenarios.some(
                    (s) => s.scenario_id in V1_UNIFORM_SCENARIO_PRIORITY
                  ) && (
                    <optgroup label="v1 (uniform population)">
                      {scenarios
                        .filter((s) => s.scenario_id in V1_UNIFORM_SCENARIO_PRIORITY)
                        .map((s) => (
                          <option key={s.scenario_id} value={s.scenario_id}>
                            {formatScenarioPickerLabel(s)}
                          </option>
                        ))}
                    </optgroup>
                  )}
                  <optgroup label="Earlier Validation & Test Runs">
                    {scenarios
                      .filter(
                        (s) =>
                          !(s.scenario_id in DEMO_SCENARIO_PRIORITY) &&
                          !(s.scenario_id in V1_UNIFORM_SCENARIO_PRIORITY) &&
                          (s.status !== "failed" || s.scenario_id === selectedScenarioId)
                      )
                      .map((s) => (
                        <option key={s.scenario_id} value={s.scenario_id}>
                          {formatScenarioPickerLabel(s)}
                        </option>
                      ))}
                  </optgroup>
                </>
              ) : (
                scenarios.map((s) => (
                  <option key={s.scenario_id} value={s.scenario_id}>
                    {formatScenarioPickerLabel(s)}
                  </option>
                ))
              )}
            </select>
          </label>

          {activeScenario && (
            <span className={`status-pill status-${activeScenario.status}`}>
              Status: {formatScenarioStatus(activeScenario.status)} &middot;{" "}
              {activeScenario.population_size.toLocaleString()} residents
            </span>
          )}

          <button
            type="button"
            className="hud-button"
            onClick={() => {
              loadScenarioBundle(
                selectedScenarioId,
                compareBaseOverride || undefined,
                true
              );
              loadBacktestData();
            }}
            disabled={loadingScenario}
          >
            {loadingScenario ? "Syncing..." : "Refresh"}
          </button>

          <button
            type="button"
            className="hud-button"
            onClick={() => {
              setCreateErrorMessage(null);
              setShowCreateModal(true);
            }}
          >
            + New Scenario
          </button>

          <button
            type="button"
            className={`hud-button ${showZones ? "active" : ""}`}
            onClick={() => setShowZones((prev) => !prev)}
            disabled={!mapReady}
          >
            {showZones ? "Zones: Visible" : "Zones: Hidden"}
          </button>

          <button
            type="button"
            className={`hud-button ${showReportDrawer ? "active" : ""}`}
            onClick={() => setShowReportDrawer((prev) => !prev)}
          >
            {showReportDrawer ? "Hide Analysis Panel" : "Comparison & Report"}
          </button>

          <button type="button" className="hud-button" onClick={handleResetView}>
            Recenter Map
          </button>
        </div>
      </header>

      {errorMessage && (
        <div className="error-banner" role="alert">
          <span>{errorMessage}</span>
          <button
            type="button"
            className="hud-button"
            onClick={() =>
              loadScenarioBundle(selectedScenarioId, compareBaseOverride || undefined, true)
            }
          >
            Retry
          </button>
        </div>
      )}

      {/* Map Canvas */}
      <div ref={containerRef} className="map-canvas" role="region" aria-label="Map of Jakarta" />

      {/* Left Mode, Zone & Resident Search Legend */}
      <aside className="mode-legend" aria-label="Transport Mode and Policy Zone Legend">
        <div className="legend-title">Commute Transport Modes</div>
        <div className="mode-grid">
          {Object.entries(MODE_LABELS).map(([key, label]) => (
            <div key={key} className="mode-chip">
              <span
                className="mode-dot"
                style={{ backgroundColor: MODE_COLORS[key] }}
              />
              <span>{label}</span>
            </div>
          ))}
        </div>
        {showZones && (
          <div className="zone-legend-inline">
            <div className="legend-title">Policy &amp; Flood Areas on Map</div>
            <div className="legend-item">
              <span className="swatch swatch-central" />
              <div>
                <strong>Central Parking Zone (+100% tariff)</strong>
                <div className="zone-subtext">
                  Gambir, Menteng, Tanah Abang, Setiabudi
                </div>
              </div>
            </div>
            <div className="legend-item">
              <span className="swatch swatch-north" />
              <div>
                <strong>North Jakarta Tidal Flood Area</strong>
                <div className="zone-subtext">
                  Penjaringan, Pademangan, Tanjung Priok, Koja, Cilincing
                </div>
              </div>
            </div>
          </div>
        )}
        <div className="resident-picker-inline">
          <div className="legend-title">Find Resident (Decision Evidence)</div>
          <form onSubmit={handleFindResident} className="resident-find-form">
            <input
              type="text"
              value={residentSearchInput}
              onChange={(e) => {
                setResidentSearchInput(e.target.value);
                if (residentSearchFeedback) setResidentSearchFeedback(null);
              }}
              placeholder="Persona ID or index (e.g. 00001)"
              className="resident-find-input"
              aria-label="Find resident by persona ID"
            />
            <button type="submit" className="resident-find-btn">
              Find
            </button>
          </form>
          {residentSearchFeedback && (
            <div className="resident-search-feedback">{residentSearchFeedback}</div>
          )}
          <div className="resident-hint">
            Quick-pick resident (hover to highlight on map):
          </div>
          <div className="resident-pill-group">
            {quickPickResidents.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`resident-pill-btn ${
                  selectedPersonaId === item.id ? "active" : ""
                }`}
                onMouseEnter={() => setHoveredPersonaId(item.id)}
                onMouseLeave={() => setHoveredPersonaId(null)}
                onClick={() => handleSelectResident(item.id, true)}
              >
                {item.tag}
              </button>
            ))}
          </div>
        </div>
      </aside>

      {/* Resident Decision Evidence Chain Panel (CONTRACT.md v1.5 §4.5) */}
      {selectedPersonaId && (
        <aside className="decision-card" aria-label="Resident Decision Evidence Chain">
          {(() => {
            const decEntry = selectedDecision?.decisions?.[0] || null;
            const baseDecEntry = selectedBaseDecision?.decisions?.[0] || null;
            const homeKel = selectedPersona?.home?.kelurahan || "";
            const workKel = selectedPersona?.work?.kelurahan || "";
            const homeKec = KELURAHAN_TO_KECAMATAN[homeKel] || "";
            const workKec = KELURAHAN_TO_KECAMATAN[workKel] || "";

            const optionRows = decEntry
              ? Object.keys(decEntry.options_detail || {})
                  .map((mode) => ({
                    mode,
                    label: MODE_LABELS[mode] || mode,
                    color: MODE_COLORS[mode] || "#64748b",
                    detail: decEntry.options_detail[mode],
                    prob: decEntry.probabilities?.[mode] ?? 0,
                    isChosen: decEntry.chosen === mode,
                  }))
                  .sort((a, b) => b.prob - a.prob)
              : [];

            return (
              <>
                <div className="decision-card-header">
                  <div>
                    <div className="decision-eyebrow">
                      Resident Commute Decision &middot; Evidence Chain
                    </div>
                    <h3 className="decision-persona-id">{selectedPersonaId}</h3>
                  </div>
                  <div className="decision-header-right">
                    {decEntry?.decided_by && (
                      <span className="hud-badge">
                        Decided by: {formatDecidedBy(decEntry.decided_by)}
                      </span>
                    )}
                    <button
                      type="button"
                      className="decision-close-btn"
                      onClick={() => setSelectedPersonaId(null)}
                      aria-label="Close resident decision panel"
                    >
                      &times;
                    </button>
                  </div>
                </div>

                {loadingDecision ? (
                  <div className="state-box loading-state-box">
                    Loading resident profile and decision evidence chain...
                  </div>
                ) : (
                  <>
                    {selectedPersona ? (
                      <div className="decision-profile-box">
                        <div className="decision-meta-row">
                          <span className="decision-badge">
                            {selectedPersona.occupation} ({selectedPersona.age} yrs)
                          </span>
                          <span className="decision-badge">
                            Income: {formatIncomeBand(selectedPersona.income_band)}
                          </span>
                        </div>
                        <div className="decision-route-line">
                          Home: <strong>{homeKel}</strong>
                          {homeKec ? ` (${homeKec})` : ""} &rarr; Work:{" "}
                          <strong>{workKel}</strong>
                          {workKec ? ` (${workKec})` : ""}
                        </div>
                        <p className="decision-profile-summary">
                          {selectedPersona.profile_summary}
                        </p>
                      </div>
                    ) : (
                      <div className="state-box empty-state-box">
                        Resident profile details unavailable for {selectedPersonaId}.
                      </div>
                    )}

                    {decEntry ? (
                      <>
                        {decEntry.shared_from && (
                          <div className="decision-shared-box">
                            <span className="decision-shared-text">
                              Shared from <code>{decEntry.shared_from}</code>
                              {decEntry.shared_from === selectedPersonaId
                                ? " (cluster representative)"
                                : " (cluster group decision)"}
                            </span>
                            {decEntry.shared_from !== selectedPersonaId && (
                              <button
                                type="button"
                                className="decision-shared-link"
                                onClick={() =>
                                  handleSelectResident(decEntry.shared_from!, true)
                                }
                              >
                                Inspect rep &rarr;
                              </button>
                            )}
                          </div>
                        )}

                        <div className="decision-mode-strip">
                          <div className="decision-mode-cell">
                            <span className="metric-label">Usual mode</span>
                            <span className="decision-mode-val">
                              <span
                                className="mode-dot"
                                style={{
                                  backgroundColor:
                                    MODE_COLORS[selectedPersona?.usual_mode || ""] || "#64748b",
                                }}
                              />
                              {MODE_LABELS[selectedPersona?.usual_mode || ""] ||
                                selectedPersona?.usual_mode ||
                                "—"}
                            </span>
                          </div>

                          {baseDecEntry && (
                            <div className="decision-mode-cell">
                              <span className="metric-label">Baseline mode</span>
                              <span className="decision-mode-val">
                                <span
                                  className="mode-dot"
                                  style={{
                                    backgroundColor:
                                      MODE_COLORS[baseDecEntry.chosen] || "#64748b",
                                  }}
                                />
                                {MODE_LABELS[baseDecEntry.chosen] || baseDecEntry.chosen}
                              </span>
                            </div>
                          )}

                          <div className="decision-mode-cell highlight">
                            <span className="metric-label">
                              Today&apos;s chosen mode ({tickToLocalTime(decEntry.tick)})
                            </span>
                            <strong className="decision-mode-val">
                              <span
                                className="mode-dot"
                                style={{
                                  backgroundColor: MODE_COLORS[decEntry.chosen] || "#38bdf8",
                                }}
                              />
                              {MODE_LABELS[decEntry.chosen] || decEntry.chosen}
                            </strong>
                          </div>
                        </div>

                        <div className="decision-reason-box">
                          <div className="metric-label">
                            Why this resident chose {MODE_LABELS[decEntry.chosen] || decEntry.chosen}
                          </div>
                          <p>&ldquo;{decEntry.reason_short}&rdquo;</p>
                        </div>

                        <div className="decision-options-block">
                          <div className="section-caption">
                            All Mode Options, Route Flood Status &amp; Model Probabilities
                          </div>
                          <table className="compact-table decision-table">
                            <thead>
                              <tr>
                                <th>Mode option</th>
                                <th>Travel time</th>
                                <th>Cost</th>
                                <th>Probability</th>
                              </tr>
                            </thead>
                            <tbody>
                              {optionRows.map((opt) => (
                                <tr
                                  key={opt.mode}
                                  className={opt.isChosen ? "chosen-option-row" : ""}
                                >
                                  <td>
                                    <span className="mode-compare-name">
                                      <span
                                        className="mode-dot"
                                        style={{ backgroundColor: opt.color }}
                                      />
                                      <b>{opt.label}</b>
                                      {opt.isChosen && (
                                        <span className="chosen-tag">CHOSEN</span>
                                      )}
                                    </span>
                                  </td>
                                  <td>
                                    {opt.detail?.est_minutes} min{" "}
                                    {opt.detail?.flooded_on_route ? (
                                      <span
                                        className="flood-tag"
                                        title="Route crosses North Jakarta flood area"
                                      >
                                        Flooded route
                                      </span>
                                    ) : (
                                      <span className="clear-route-tag">Clear route</span>
                                    )}
                                  </td>
                                  <td>Rp {(opt.detail?.cost_idr ?? 0).toLocaleString()}</td>
                                  <td>
                                    <div className="prob-cell">
                                      <div className="prob-bar-track">
                                        <div
                                          className="prob-bar-fill"
                                          style={{
                                            width: `${Math.round(opt.prob * 100)}%`,
                                            backgroundColor: opt.color,
                                          }}
                                        />
                                      </div>
                                      <span>{Math.round(opt.prob * 100)}%</span>
                                    </div>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </>
                    ) : (
                      <div className="state-box empty-state-box">
                        Decision details available once the scenario completes.
                      </div>
                    )}
                  </>
                )}
              </>
            );
          })()}
        </aside>
      )}

      {/* Right Analyst Report & Baseline vs. Variant Comparison Drawer */}
      {showReportDrawer && (
        <aside className="summary-drawer" aria-label="Scenario Comparison and Result Summary">
          <div className="drawer-header">
            <div>
              <h2>
                {selectedScenarioId === SCALE_5000_SCENARIO_ID || isLargeScaleScenario
                  ? "Scale: 5,000 residents (clustered)"
                  : comparison
                  ? "Comparison vs. Baseline"
                  : "Scenario Summary"}
              </h2>
              <p className="drawer-subtitle">
                {activeScenario?.name || selectedScenarioId}
              </p>
            </div>
            <span className="hud-badge">System Two &middot; Gemini</span>
          </div>

          {(selectedScenarioId === SCALE_5000_SCENARIO_ID || isLargeScaleScenario) && (
            <div className="scale-cost-card" aria-label="Scale and cost summary">
              <div className="scale-cost-title">Scale &amp; cost</div>
              <p className="scale-cost-text">
                5,000 residents &middot; 377 clusters &middot; 377 model calls instead of
                5,000 (&minus;92.5%) &middot; ~2 minutes end to end &middot; $0.72 in Gemini
                calls &middot; replay from cache: $0
              </p>
            </div>
          )}

          {/* Compare against Baseline selector */}
          <div className="compare-bar">
            <label className="compare-select-label">
              <span>Compare vs. baseline:</span>
              <select
                className="scenario-select compare-select"
                value={effectiveCompareBaseId}
                onChange={(e) => handleBaseOverrideChange(e.target.value)}
              >
                <option value="">None (Single scenario view)</option>
                {scenarios
                  .filter(
                    (s) =>
                      s.scenario_id !== selectedScenarioId &&
                      s.status === "completed"
                  )
                  .map((s) => (
                    <option key={s.scenario_id} value={s.scenario_id}>
                      {s.name} ({s.population_size.toLocaleString()} residents)
                    </option>
                  ))}
              </select>
            </label>
          </div>

          {/* Citywide Metrics: Side-by-Side Comparison when `comparison` exists, else single strip */}
          {loadingScenario && !metrics ? (
            <div className="state-box loading-state-box">
              Loading citywide metrics and comparison vs. baseline...
            </div>
          ) : comparison ? (
            <div className="compare-citywide-grid">
              <div className="compare-card">
                <span className="metric-label">Avg travel time</span>
                <div className="compare-values">
                  <span className="base-val" title="Baseline">
                    {comparison.base.citywide.avg_travel_min} min
                  </span>
                  <span className="arrow-sep">&rarr;</span>
                  <strong className="var-val" title="Current Scenario">
                    {comparison.variant.citywide.avg_travel_min} min
                  </strong>
                </div>
                <span
                  className={`delta-badge ${
                    comparison.variant.citywide.avg_travel_min -
                      comparison.base.citywide.avg_travel_min <=
                    0
                      ? "delta-good"
                      : "delta-warn"
                  }`}
                >
                  &Delta; vs baseline:{" "}
                  {formatSignedDelta(
                    comparison.variant.citywide.avg_travel_min -
                      comparison.base.citywide.avg_travel_min,
                    1,
                    " min"
                  )}
                </span>
              </div>

              <div className="compare-card">
                <span className="metric-label">Avg commute cost</span>
                <div className="compare-values">
                  <span className="base-val" title="Baseline">
                    Rp {(comparison.base.citywide.avg_cost_idr ?? 0).toLocaleString()}
                  </span>
                  <span className="arrow-sep">&rarr;</span>
                  <strong className="var-val" title="Current Scenario">
                    Rp {(comparison.variant.citywide.avg_cost_idr ?? 0).toLocaleString()}
                  </strong>
                </div>
                <span
                  className={`delta-badge ${
                    (comparison.variant.citywide.avg_cost_idr ?? 0) -
                      (comparison.base.citywide.avg_cost_idr ?? 0) <=
                    0
                      ? "delta-good"
                      : "delta-warn"
                  }`}
                >
                  &Delta; vs baseline:{" "}
                  {formatSignedIdr(
                    (comparison.variant.citywide.avg_cost_idr ?? 0) -
                      (comparison.base.citywide.avg_cost_idr ?? 0)
                  )}
                </span>
              </div>

              <div className="compare-card">
                <span className="metric-label">Residents stuck in flood</span>
                <div className="compare-values">
                  <span className="base-val" title="Baseline">
                    {comparison.base.citywide.stuck_count ?? 0}
                  </span>
                  <span className="arrow-sep">&rarr;</span>
                  <strong className="var-val" title="Current Scenario">
                    {comparison.variant.citywide.stuck_count ?? 0}
                  </strong>
                </div>
                <span
                  className={`delta-badge ${
                    (comparison.variant.citywide.stuck_count ?? 0) -
                      (comparison.base.citywide.stuck_count ?? 0) <=
                    0
                      ? "delta-good"
                      : "delta-warn"
                  }`}
                >
                  &Delta; vs baseline:{" "}
                  {formatSignedDelta(
                    (comparison.variant.citywide.stuck_count ?? 0) -
                      (comparison.base.citywide.stuck_count ?? 0),
                    0,
                    " residents"
                  )}
                </span>
              </div>
            </div>
          ) : metrics ? (
            <div className="metrics-strip">
              <div className="metric-card">
                <span className="metric-label">Avg travel time</span>
                <strong className="metric-value">
                  {metrics.citywide.avg_travel_min} min
                </strong>
              </div>
              {typeof metrics.citywide.avg_cost_idr === "number" && (
                <div className="metric-card">
                  <span className="metric-label">Avg commute cost</span>
                  <strong className="metric-value">
                    Rp {metrics.citywide.avg_cost_idr.toLocaleString()}
                  </strong>
                </div>
              )}
              <div className="metric-card">
                <span className="metric-label">Residents stuck in flood</span>
                <strong className="metric-value">
                  {metrics.citywide.stuck_count ?? 0} residents
                </strong>
              </div>
            </div>
          ) : (
            <div className="state-box empty-state-box">
              Citywide metrics available once the scenario completes.
            </div>
          )}

          {/* Mode Share Section: Side-by-Side when `comparison` exists */}
          {comparison ? (
            <div className="mode-share-section">
              <div className="section-caption">
                Mode Share Shift (&Delta; vs baseline:{" "}
                {baseScenarioObj?.name || "Baseline weekday"})
              </div>

              <div className="stacked-bar-row">
                <span className="bar-tag">Baseline</span>
                <div className="mode-share-bar">
                  {comparedModes.map((row) =>
                    row.basePct > 0 ? (
                      <div
                        key={`base-${row.mode}`}
                        style={{
                          width: `${Math.max(2, row.basePct)}%`,
                          backgroundColor: row.color,
                        }}
                        title={`Baseline ${row.label}: ${row.basePct.toFixed(1)}%`}
                      />
                    ) : null
                  )}
                </div>
              </div>

              <div className="stacked-bar-row">
                <span className="bar-tag">Scenario</span>
                <div className="mode-share-bar">
                  {comparedModes.map((row) =>
                    row.varPct > 0 ? (
                      <div
                        key={`var-${row.mode}`}
                        style={{
                          width: `${Math.max(2, row.varPct)}%`,
                          backgroundColor: row.color,
                        }}
                        title={`Scenario ${row.label}: ${row.varPct.toFixed(1)}%`}
                      />
                    ) : null
                  )}
                </div>
              </div>

              <div className="mode-compare-table">
                {comparedModes.map((row) => (
                  <div key={row.mode} className="mode-compare-row">
                    <span className="mode-compare-name">
                      <span
                        className="mode-dot"
                        style={{ backgroundColor: row.color }}
                      />
                      {row.label}
                    </span>
                    <span className="mode-compare-nums">
                      {row.basePct.toFixed(1)}% &rarr; <b>{row.varPct.toFixed(1)}%</b>
                    </span>
                    <span
                      className={`mode-delta ${
                        Math.abs(row.deltaPp) < 0.05
                          ? "neutral"
                          : row.deltaPp > 0
                          ? "up"
                          : "down"
                      }`}
                    >
                      &Delta; {formatSignedDelta(row.deltaPp, 1, " pp")}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            metrics?.citywide?.mode_share && (
              <div className="mode-share-section">
                <div className="section-caption">Citywide Mode Share</div>
                <div className="mode-share-bar">
                  {Object.entries(metrics.citywide.mode_share).map(([m, share]) => (
                    <div
                      key={m}
                      style={{
                        width: `${Math.max(4, Math.round(share * 100))}%`,
                        backgroundColor: MODE_COLORS[m] || "#64748b",
                      }}
                      title={`${MODE_LABELS[m] || m}: ${(share * 100).toFixed(1)}%`}
                    />
                  ))}
                </div>
                <div className="mode-share-labels">
                  {Object.entries(metrics.citywide.mode_share).map(([m, share]) => (
                    <span key={m} className="share-pill">
                      <span
                        className="mode-dot"
                        style={{ backgroundColor: MODE_COLORS[m] || "#64748b" }}
                      />
                      {MODE_LABELS[m] || m}: <b>{(share * 100).toFixed(1)}%</b>
                    </span>
                  ))}
                </div>
              </div>
            )
          )}

          {/* Drawer Tabs: Analyst Report vs. Verification vs. Backtest vs. Per-Kecamatan & Income Breakdown */}
          <div className="drawer-tabs four-tabs">
            <button
              type="button"
              className={`tab-btn ${drawerTab === "report" ? "active" : ""}`}
              onClick={() => setDrawerTab("report")}
            >
              Analyst Report
            </button>
            <button
              type="button"
              className={`tab-btn ${drawerTab === "verification" ? "active" : ""}`}
              onClick={() => setDrawerTab("verification")}
            >
              Verification{" "}
              {verification ? `(${verification.overall.toUpperCase()})` : ""}
            </button>
            <button
              type="button"
              className={`tab-btn ${drawerTab === "backtest" ? "active" : ""}`}
              onClick={() => setDrawerTab("backtest")}
            >
              Backtest{" "}
              {backtest?.direction_match === true
                ? "(Yes)"
                : backtest?.direction_match === false
                ? "(No)"
                : ""}
            </button>
            <button
              type="button"
              className={`tab-btn ${drawerTab === "breakdown" ? "active" : ""}`}
              onClick={() => setDrawerTab("breakdown")}
            >
              Income &amp; Area ({kecamatanComparisonRows.length})
            </button>
          </div>

          {drawerTab === "report" ? (
            <div className="report-body">
              {loadingReport ? (
                <div className="state-box loading-state-box">
                  Generating Analyst Report (comparing scenario against baseline)...
                </div>
              ) : report ? (
                <>
                  {report.base_scenario_id && (
                    <div className="compared-against-tag">
                      Comparison vs. baseline:{" "}
                      <strong>
                        {scenarios.find((s) => s.scenario_id === report.base_scenario_id)
                          ?.name || report.base_scenario_id}
                      </strong>
                    </div>
                  )}
                  <div className="report-headline">{report.headline}</div>

                  {report.winners?.length > 0 && (
                    <div className="report-section">
                      <h3 className="sec-winners">Who Benefits (Winners)</h3>
                      <ul>
                        {report.winners.map((item, idx) => (
                          <li key={idx}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {report.losers?.length > 0 && (
                    <div className="report-section">
                      <h3 className="sec-losers">Who Is Affected Most (Losers)</h3>
                      <ul>
                        {report.losers.map((item, idx) => (
                          <li key={idx}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {report.recommendations?.length > 0 && (
                    <div className="report-section">
                      <h3 className="sec-recs">Policy Recommendations</h3>
                      <ul>
                        {report.recommendations.map((item, idx) => (
                          <li key={idx}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {report.caveats?.length > 0 && (
                    <div className="report-caveats">
                      {report.caveats.map((c, idx) => (
                        <div key={idx}>&bull; {c}</div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <div className="state-box empty-state-box">
                  Report available once the scenario completes.
                </div>
              )}
            </div>
          ) : drawerTab === "verification" ? (
            <div className="verification-body">
              {loadingVerification ? (
                <div className="state-box loading-state-box">
                  Running verification checks (first call takes up to 30 seconds)...
                </div>
              ) : verification ? (
                <>
                  {(() => {
                    const passCount = verification.checks.filter(
                      (c) => c.status === "pass"
                    ).length;
                    const warnCount = verification.checks.filter(
                      (c) => c.status === "warn"
                    ).length;
                    const failCount = verification.checks.filter(
                      (c) => c.status === "fail"
                    ).length;
                    return (
                      <div className={`verification-overall vstatus-${verification.overall}`}>
                        <div>
                          <div className="metric-label">Verifier Overall Result</div>
                          <strong className="verification-overall-text">
                            Overall status: {verification.overall.toUpperCase()}
                          </strong>
                          <div className="verification-summary-counts">
                            {passCount} Passed &middot; {warnCount} Reference Warnings &middot;{" "}
                            {failCount} Failed
                          </div>
                        </div>
                        <span className={`vstatus-badge vstatus-${verification.overall}`}>
                          Status: {verification.overall.toUpperCase()}
                        </span>
                      </div>
                    );
                  })()}

                  <div className="verification-checks-list">
                    {verification.checks.map((chk) => (
                      <div key={chk.name} className="verification-check-card">
                        <div className="verification-check-header">
                          <div>
                            <div className="verification-check-title">
                              {formatVerificationCheckName(chk.name)}
                            </div>
                          </div>
                          <span className={`vstatus-badge vstatus-${chk.status}`}>
                            Status: {chk.status.toUpperCase()}
                          </span>
                        </div>
                        <p className="verification-check-detail">{chk.detail}</p>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="state-box empty-state-box">
                  Verification report available once the scenario completes.
                </div>
              )}
            </div>
          ) : drawerTab === "backtest" ? (
            <div className="backtest-body">
              {loadingBacktest ? (
                <div className="state-box loading-state-box">
                  Loading backtest result (GET /v1/backtests/b_0001)...
                </div>
              ) : backtest ? (
                (() => {
                  const matchText =
                    backtest.direction_match === true
                      ? "Yes"
                      : backtest.direction_match === false
                      ? "No"
                      : "Pending";
                  const matchStatusClass =
                    backtest.direction_match === true
                      ? "vstatus-pass"
                      : backtest.direction_match === false
                      ? "vstatus-fail"
                      : "vstatus-warn";
                  const parsedSource = parseReferenceSource(backtest.reference_source);
                  const btScenarioId = RP1_BACKTEST_SCENARIO_ID;

                  return (
                    <>
                      <div className={`verification-overall ${matchStatusClass}`}>
                        <div>
                          <div className="metric-label">
                            Backtest {backtest.backtest_id} &middot; Historical Event Check
                          </div>
                          <strong className="verification-overall-text">
                            Direction match: {matchText}
                          </strong>
                        </div>
                        <span className={`vstatus-badge ${matchStatusClass}`}>
                          Direction match: {matchText}
                        </span>
                      </div>

                      {backtest.description && (
                        <div className="backtest-card">
                          <div className="metric-label">Backtest description</div>
                          <div className="backtest-description">
                            {backtest.description}
                          </div>
                        </div>
                      )}

                      <div className="backtest-grid">
                        <div className="backtest-card">
                          <div className="metric-label">
                            Simulated change in transit share (Transjakarta + MRT + KRL)
                          </div>
                          <strong className="backtest-val">
                            {backtest.simulated_value !== null
                              ? `${formatSignedDelta(
                                  backtest.simulated_value,
                                  1,
                                  " pp"
                                )}`
                              : "Pending"}
                          </strong>
                          <div className="backtest-sub">
                            Simulated direction:{" "}
                            <b>{backtest.simulated_direction || "pending"}</b>
                          </div>
                        </div>

                        <div className="backtest-card">
                          <div className="metric-label">
                            Reported direction &amp; magnitude
                          </div>
                          <strong className="backtest-val">
                            Reported direction:{" "}
                            {backtest.reference_direction || "increase"}
                          </strong>
                          <div className="backtest-sub">
                            Magnitude: reference pending (no official daily ridership
                            published)
                          </div>
                        </div>
                      </div>

                      <div className="backtest-card">
                        <div className="metric-label">Reference source</div>
                        <p className="backtest-source-text">{parsedSource.text}</p>
                        {parsedSource.url && (
                          <a
                            href={parsedSource.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="backtest-source-link"
                          >
                            Read ANTARA report (24 April 2026) &rarr;
                          </a>
                        )}
                      </div>

                      {backtest.notes && (
                        <div className="backtest-card">
                          <div className="metric-label">Notes &amp; scope</div>
                          <p className="backtest-notes-text">{backtest.notes}</p>
                        </div>
                      )}

                      {selectedScenarioId !== btScenarioId && (
                        <button
                          type="button"
                          className="hud-button active backtest-load-btn"
                          onClick={() => setSelectedScenarioId(btScenarioId)}
                        >
                          View Rp1 fare day (24 April 2026) scenario on map &rarr;
                        </button>
                      )}
                    </>
                  );
                })()
              ) : (
                <div className="state-box empty-state-box">
                  Backtest result will appear once the Rp1 fare day scenario completes.
                </div>
              )}
            </div>
          ) : (
            <div className="breakdown-body">
              {loadingScenario && !metrics ? (
                <div className="state-box loading-state-box">
                  Loading income and kecamatan breakdown...
                </div>
              ) : !metrics ? (
                <div className="state-box empty-state-box">
                  Income and kecamatan breakdown available once the scenario completes.
                </div>
              ) : (
                <>
                  {/* By Income Band Table */}
                  <div className="breakdown-block">
                    <div className="section-caption">
                      By Income Group {comparison ? "(Δ vs baseline)" : ""}
                    </div>
                    <table className="compact-table">
                      <thead>
                        <tr>
                          <th>Income group</th>
                          <th>Avg travel time</th>
                          <th>Avg commute cost</th>
                          <th>Residents stuck in flood</th>
                        </tr>
                      </thead>
                      <tbody>
                        {incomeComparisonRows.map((row) => (
                          <tr key={row.income_band}>
                            <td>
                              <b>{formatIncomeBand(row.income_band)}</b>
                            </td>
                            <td>
                              {row.base_min !== null ? (
                                <>
                                  {row.base_min}m &rarr; <b>{row.var_min}m</b>{" "}
                                  <span className="inline-delta">
                                    (&Delta; {formatSignedDelta(row.delta_min ?? 0, 1, "m")})
                                  </span>
                                </>
                              ) : (
                                <b>{row.var_min} min</b>
                              )}
                            </td>
                            <td>
                              {row.base_cost !== null ? (
                                <>
                                  {(row.base_cost / 1000).toFixed(1)}k &rarr;{" "}
                                  <b>{(row.var_cost / 1000).toFixed(1)}k</b>
                                </>
                              ) : (
                                <b>Rp {row.var_cost.toLocaleString()}</b>
                              )}
                            </td>
                            <td>
                              {row.base_stuck !== null && row.base_stuck !== row.var_stuck
                                ? `${row.base_stuck} → ${row.var_stuck}`
                                : row.var_stuck}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* Per-Kecamatan Resident-Weighted Table */}
                  <div className="breakdown-block">
                    <div className="kelurahan-header-row">
                      <span className="section-caption">
                        By Kecamatan &middot; Resident-Weighted{" "}
                        {comparison ? "(Δ vs baseline)" : ""}
                      </span>
                      <input
                        type="text"
                        placeholder="Filter kecamatan..."
                        value={kecamatanSearch}
                        onChange={(e) => setKecamatanSearch(e.target.value)}
                        className="kelurahan-filter-input"
                      />
                    </div>
                    <div className="kelurahan-scroll">
                      <table className="compact-table">
                        <thead>
                          <tr>
                            <th>Kecamatan</th>
                            <th>Residents</th>
                            <th>Avg travel time</th>
                            <th>Avg cost (IDR)</th>
                            <th>Stuck in flood</th>
                          </tr>
                        </thead>
                        <tbody>
                          {kecamatanComparisonRows.length === 0 ? (
                            <tr>
                              <td colSpan={5} className="empty-table-cell">
                                No kecamatan matches &ldquo;{kecamatanSearch}&rdquo;.
                              </td>
                            </tr>
                          ) : (
                            kecamatanComparisonRows.map((row) => (
                              <tr key={row.kecamatan}>
                                <td>
                                  <b>{row.kecamatan}</b>
                                </td>
                                <td>{row.residents}</td>
                                <td>
                                  {row.base_min !== null ? (
                                    <>
                                      {row.base_min}m &rarr; <b>{row.var_min}m</b>{" "}
                                      <span className="inline-delta">
                                        (&Delta; {formatSignedDelta(row.delta_min ?? 0, 1, "m")})
                                      </span>
                                    </>
                                  ) : (
                                    <b>{row.var_min} min</b>
                                  )}
                                </td>
                                <td>
                                  {row.base_cost !== null ? (
                                    <>
                                      {(row.base_cost / 1000).toFixed(1)}k &rarr;{" "}
                                      <b>{(row.var_cost / 1000).toFixed(1)}k</b>
                                    </>
                                  ) : (
                                    <b>{row.var_cost.toLocaleString()}</b>
                                  )}
                                </td>
                                <td>
                                  {row.base_stuck !== null && row.base_stuck !== row.var_stuck
                                    ? `${row.base_stuck} → ${row.var_stuck}`
                                    : row.var_stuck}
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                    <div className="area-rollup-note">
                      Kelurahan with fewer than {MIN_AREA_RESIDENTS} residents are aggregated
                      into their kecamatan, weighted by resident count.
                    </div>
                  </div>

                  {kelurahanMajorRows.length > 0 && (
                    <div className="breakdown-block">
                      <div className="section-caption">
                        Kelurahan with &ge; {MIN_AREA_RESIDENTS} Residents
                      </div>
                      <table className="compact-table">
                        <thead>
                          <tr>
                            <th>Kelurahan</th>
                            <th>Residents</th>
                            <th>Avg travel time</th>
                            <th>Avg cost (IDR)</th>
                          </tr>
                        </thead>
                        <tbody>
                          {kelurahanMajorRows.map((row) => (
                            <tr key={row.kelurahan}>
                              <td>
                                <b>{row.kelurahan}</b>{" "}
                                <span className="inline-delta">({row.kecamatan})</span>
                              </td>
                              <td>{row.residents}</td>
                              <td>
                                {row.base_min !== null ? (
                                  <>
                                    {row.base_min}m &rarr; <b>{row.var_min}m</b>
                                  </>
                                ) : (
                                  <b>{row.var_min} min</b>
                                )}
                              </td>
                              <td>
                                {row.base_cost !== null ? (
                                  <>
                                    {(row.base_cost / 1000).toFixed(1)}k &rarr;{" "}
                                    <b>{(row.var_cost / 1000).toFixed(1)}k</b>
                                  </>
                                ) : (
                                  <b>{row.var_cost.toLocaleString()}</b>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </aside>
      )}

      {/* Bottom Timeline Playback Bar */}
      <footer className="timeline-bar" aria-label="Simulation Timeline">
        <div className="timeline-controls">
          <button
            type="button"
            className="play-button"
            onClick={() => setIsPlaying((prev) => !prev)}
          >
            {isPlaying ? "Pause" : "Play"}
          </button>
          <div className="speed-group">
            {[1, 2, 4].map((spd) => (
              <button
                key={spd}
                type="button"
                className={`speed-btn ${playbackSpeed === spd ? "active" : ""}`}
                onClick={() => setPlaybackSpeed(spd)}
              >
                {spd}&times;
              </button>
            ))}
          </div>
          <div className="clock-readout">
            <strong>{tickToLocalTime(currentTick)} WIB</strong>
            <span>
              Tick {String(currentTick).padStart(4, "0")} / 0203
            </span>
          </div>
        </div>

        <input
          type="range"
          min={0}
          max={Math.max(0, (ticks.length || 204) - 1)}
          value={currentTick}
          onChange={(e) => {
            setIsPlaying(false);
            setCurrentTick(Number(e.target.value));
          }}
          className="tick-slider"
          aria-label="Simulation Tick"
        />

        <div className="status-counters">
          <span className="counter-chip">
            At home: <b>{statusCounts.at_home}</b>
          </span>
          <span className="counter-chip traveling">
            Traveling: <b>{statusCounts.traveling}</b>
          </span>
          <span className={`counter-chip ${statusCounts.stuck > 0 ? "stuck" : ""}`}>
            Residents stuck in flood: <b>{statusCounts.stuck}</b>
          </span>
          <span className="counter-chip at-work">
            At work: <b>{statusCounts.at_work}</b>
          </span>
        </div>
      </footer>

      {/* Create Scenario Modal */}
      {showCreateModal && (
        <div className="modal-backdrop" onClick={() => setShowCreateModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <h3>Create Policy / Flood Scenario</h3>
            {createErrorMessage && (
              <div className="state-box empty-state-box" role="alert">
                {createErrorMessage}
              </div>
            )}
            <form onSubmit={handleCreateScenario} className="scenario-form">
              <label>
                Scenario Name
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  required
                />
              </label>
              <label>
                Baseline Scenario to Compare Against (optional)
                <select
                  className="scenario-select"
                  value={newBaseId}
                  onChange={(e) => setNewBaseId(e.target.value)}
                >
                  <option value="">None (Standalone baseline)</option>
                  {scenarios
                    .filter((s) => s.status === "completed")
                    .map((s) => (
                      <option key={s.scenario_id} value={s.scenario_id}>
                        {s.name} ({s.scenario_id})
                      </option>
                    ))}
                </select>
              </label>
              <label>
                Population Size (Seed 42)
                <select
                  className="scenario-select"
                  value={newPopSize}
                  onChange={(e) => setNewPopSize(Number(e.target.value))}
                >
                  <option value={1000}>1,000 Residents (Demo Standard)</option>
                  <option value={50}>50 Residents (Fast Smoke Test)</option>
                </select>
              </label>
              <label>
                Central Parking Tariff Change Ratio (e.g., 1.0 = +100%, 0 = No policy)
                <input
                  type="number"
                  step="0.25"
                  min="-0.8"
                  max="5.0"
                  value={newParkingRatio}
                  onChange={(e) => setNewParkingRatio(Number(e.target.value))}
                />
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={includeFlood}
                  onChange={(e) => setIncludeFlood(e.target.checked)}
                />
                <span>Include North Jakarta Tidal Flood (45 cm, ticks 12–72)</span>
              </label>
              <div className="modal-actions">
                <button
                  type="button"
                  className="hud-button"
                  onClick={() => setShowCreateModal(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="hud-button active"
                  disabled={creatingScenario}
                >
                  {creatingScenario ? "Creating..." : "Create Scenario"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
