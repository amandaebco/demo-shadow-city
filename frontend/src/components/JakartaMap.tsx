"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { APP_CONFIG } from "@/lib/config";
import {
  AnalystReport,
  createScenario,
  fetchScenario,
  fetchScenarioMetrics,
  fetchScenarioReport,
  fetchScenarios,
  loadScenarioTicks,
  Scenario,
  ScenarioMetrics,
  TickData,
  tickToLocalTime,
} from "@/lib/api";

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

function buildResidentsGeoJSON(tickData: TickData | undefined): GeoJSON.FeatureCollection {
  if (!tickData || !tickData.persona_ids) {
    return { type: "FeatureCollection", features: [] };
  }
  const features: GeoJSON.Feature[] = [];
  const count = tickData.persona_ids.length;
  for (let i = 0; i < count; i++) {
    const lat = tickData.lat[i];
    const lng = tickData.lng[i];
    if (typeof lat !== "number" || typeof lng !== "number") continue;
    features.push({
      type: "Feature",
      properties: {
        persona_id: tickData.persona_ids[i],
        mode: tickData.mode[i] || "motorcycle",
        status: tickData.status[i] || "at_home",
      },
      geometry: {
        type: "Point",
        coordinates: [lng, lat],
      },
    });
  }
  return { type: "FeatureCollection", features };
}

export default function JakartaMap() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);

  const [mapReady, setMapReady] = useState<boolean>(false);
  const [showZones, setShowZones] = useState<boolean>(true);
  const [showReportDrawer, setShowReportDrawer] = useState<boolean>(true);
  const [showCreateModal, setShowCreateModal] = useState<boolean>(false);

  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>(
    APP_CONFIG.defaultScenarioId
  );
  const [activeScenario, setActiveScenario] = useState<Scenario | null>(null);
  const [metrics, setMetrics] = useState<ScenarioMetrics | null>(null);
  const [report, setReport] = useState<AnalystReport | null>(null);
  const [ticks, setTicks] = useState<TickData[]>([]);
  const [currentTick, setCurrentTick] = useState<number>(22);
  const [isPlaying, setIsPlaying] = useState<boolean>(true);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(2);
  const [loadingScenario, setLoadingScenario] = useState<boolean>(false);
  const [loadingReport, setLoadingReport] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // New scenario form state
  const [newName, setNewName] = useState<string>("Central Parking +100% (50 Personas)");
  const [newParkingRatio, setNewParkingRatio] = useState<number>(1.0);
  const [includeFlood, setIncludeFlood] = useState<boolean>(false);
  const [creatingScenario, setCreatingScenario] = useState<boolean>(false);

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
          "fill-opacity": 0.16,
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
            "#fbbf24",
            "jakarta_utara",
            "#0ea5e9",
            "#cbd5e1",
          ],
          "line-width": 1.8,
          "line-dasharray": [2, 2],
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
            11,
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
            0.5,
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
            6,
            "stuck",
            7,
            4.5,
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
          "circle-stroke-width": 1.5,
          "circle-stroke-color": [
            "match",
            ["get", "status"],
            "stuck",
            "#fef08a",
            "#0f172a",
          ],
        },
      });

      map.on("mouseenter", "residents-circle", (e) => {
        map.getCanvas().style.cursor = "pointer";
        const feat = e.features?.[0];
        if (!feat || feat.geometry.type !== "Point") return;
        const coords = feat.geometry.coordinates.slice() as [number, number];
        const props = feat.properties || {};
        const modeLabel = MODE_LABELS[props.mode] || props.mode;
        popup
          .setLngLat(coords)
          .setHTML(
            `<div style="color:#0f172a;font-size:12px;line-height:1.4">
              <strong>${props.persona_id}</strong><br/>
              Mode: <b>${modeLabel}</b><br/>
              Status: <code>${props.status}</code>
            </div>`
          )
          .addTo(map);
      });

      map.on("mouseleave", "residents-circle", () => {
        map.getCanvas().style.cursor = "";
        popup.remove();
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
    if (map.getLayer("zones-fill")) {
      map.setLayoutProperty("zones-fill", "visibility", visibility);
    }
    if (map.getLayer("zones-outline")) {
      map.setLayoutProperty("zones-outline", "visibility", visibility);
    }
  }, [showZones, mapReady]);

  // Load scenario list on mount
  const refreshScenarioList = useCallback(async () => {
    try {
      const list = await fetchScenarios();
      setScenarios(list);
    } catch (err) {
      console.warn("Could not list scenarios:", err);
    }
  }, []);

  useEffect(() => {
    refreshScenarioList();
  }, [refreshScenarioList]);

  // Load selected scenario details, ticks, metrics, and analyst report
  const loadScenarioBundle = useCallback(async (scenarioId: string) => {
    if (!scenarioId) return;
    setLoadingScenario(true);
    setErrorMessage(null);
    try {
      const scen = await fetchScenario(scenarioId);
      setActiveScenario(scen);

      const scenMetrics = await fetchScenarioMetrics(scenarioId);
      setMetrics(scenMetrics);

      const loadedTicks = await loadScenarioTicks(scen, scenMetrics);
      setTicks(loadedTicks);

      if (scen.status === "completed" || scenMetrics) {
        setLoadingReport(true);
        try {
          const rep = await fetchScenarioReport(scenarioId);
          setReport(rep);
        } catch {
          setReport(null);
        } finally {
          setLoadingReport(false);
        }
      } else {
        setReport(null);
      }
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to load scenario");
    } finally {
      setLoadingScenario(false);
    }
  }, []);

  useEffect(() => {
    loadScenarioBundle(selectedScenarioId);
  }, [selectedScenarioId, loadScenarioBundle]);

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

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const src = map.getSource("residents-source") as maplibregl.GeoJSONSource | undefined;
    if (src) {
      src.setData(buildResidentsGeoJSON(currentTickData));
    }
  }, [currentTickData, mapReady]);

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
    try {
      const created = await createScenario({
        name: newName.trim() || "Custom Layer 1 Scenario",
        base_scenario_id: null,
        seed: 42,
        population_size: 50,
        policies: [
          {
            type: "parking_tariff",
            zone: "central",
            change_ratio: Number(newParkingRatio),
          },
        ],
        events: includeFlood
          ? [
              {
                type: "flood",
                area_id: "jakarta_utara",
                start_tick: 16,
                end_tick: 80,
                depth_cm: 40,
              },
            ]
          : [],
      });
      await refreshScenarioList();
      setSelectedScenarioId(created.scenario_id);
      setShowCreateModal(false);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to create scenario");
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
            <p className="subtitle">Jakarta Policy Simulator &middot; Layer 1 (Gemini MVP)</p>
          </div>
        </div>

        <div className="hud-controls">
          <label className="scenario-picker-label">
            <span>Scenario:</span>
            <select
              className="scenario-select"
              value={selectedScenarioId}
              onChange={(e) => setSelectedScenarioId(e.target.value)}
            >
              {scenarios.length === 0 && (
                <option value={APP_CONFIG.defaultScenarioId}>
                  {APP_CONFIG.defaultScenarioId}
                </option>
              )}
              {scenarios.map((s) => (
                <option key={s.scenario_id} value={s.scenario_id}>
                  {s.name} ({s.status})
                </option>
              ))}
            </select>
          </label>

          {activeScenario && (
            <span className={`status-pill status-${activeScenario.status}`}>
              {activeScenario.status} &middot; {activeScenario.population_size} residents
            </span>
          )}

          <button
            type="button"
            className="hud-button"
            onClick={() => loadScenarioBundle(selectedScenarioId)}
            disabled={loadingScenario}
          >
            {loadingScenario ? "Syncing..." : "Refresh"}
          </button>

          <button
            type="button"
            className="hud-button"
            onClick={() => setShowCreateModal(true)}
          >
            + New Scenario
          </button>

          <button
            type="button"
            className={`hud-button ${showZones ? "active" : ""}`}
            onClick={() => setShowZones((prev) => !prev)}
            disabled={!mapReady}
          >
            {showZones ? "Zones: On" : "Zones: Off"}
          </button>

          <button
            type="button"
            className={`hud-button ${showReportDrawer ? "active" : ""}`}
            onClick={() => setShowReportDrawer((prev) => !prev)}
          >
            {showReportDrawer ? "Hide Summary" : "Result Summary"}
          </button>

          <button type="button" className="hud-button" onClick={handleResetView}>
            Recenter
          </button>
        </div>
      </header>

      {errorMessage && <div className="error-banner">{errorMessage}</div>}

      {/* Map Canvas */}
      <div ref={containerRef} className="map-canvas" role="region" aria-label="Map of Jakarta" />

      {/* Left Mode & Zone Legend */}
      <aside className="mode-legend" aria-label="Transport Mode Legend">
        <div className="legend-title">Resident Transport Modes</div>
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
            <div className="legend-item">
              <span className="swatch swatch-central" />
              <div>
                <strong>central</strong> (<code>parking_zone</code>)
              </div>
            </div>
            <div className="legend-item">
              <span className="swatch swatch-north" />
              <div>
                <strong>jakarta_utara</strong> (<code>flood_area</code>)
              </div>
            </div>
          </div>
        )}
      </aside>

      {/* Right Analyst Report & Metrics Drawer */}
      {showReportDrawer && (
        <aside className="summary-drawer" aria-label="Scenario Result Summary">
          <div className="drawer-header">
            <div>
              <h2>Result Summary</h2>
              <p className="drawer-subtitle">
                {activeScenario?.name || selectedScenarioId}
              </p>
            </div>
            <span className="hud-badge">
              <code>gemini-system-two</code>
            </span>
          </div>

          {metrics && (
            <div className="metrics-strip">
              <div className="metric-card">
                <span className="metric-label">Avg Travel Time</span>
                <strong className="metric-value">
                  {metrics.citywide.avg_travel_min} min
                </strong>
              </div>
              {typeof metrics.citywide.avg_cost_idr === "number" && (
                <div className="metric-card">
                  <span className="metric-label">Avg Commute Cost</span>
                  <strong className="metric-value">
                    Rp {metrics.citywide.avg_cost_idr.toLocaleString()}
                  </strong>
                </div>
              )}
              <div className="metric-card">
                <span className="metric-label">Modes Used</span>
                <strong className="metric-value">
                  {Object.keys(metrics.citywide.mode_share || {}).length}
                </strong>
              </div>
            </div>
          )}

          {metrics?.citywide?.mode_share && (
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
                    {MODE_LABELS[m] || m}: <b>{(share * 100).toFixed(0)}%</b>
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="report-body">
            {loadingReport ? (
              <p className="muted-note">Generating Gemini analyst report...</p>
            ) : report ? (
              <>
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
              <p className="muted-note">
                Analyst report is generated once the simulation worker writes{" "}
                <code>metrics/summary</code> for this scenario.
              </p>
            )}
          </div>
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
            At Home: <b>{statusCounts.at_home}</b>
          </span>
          <span className="counter-chip traveling">
            Traveling: <b>{statusCounts.traveling}</b>
          </span>
          {statusCounts.stuck > 0 && (
            <span className="counter-chip stuck">
              Flood Delayed: <b>{statusCounts.stuck}</b>
            </span>
          )}
          <span className="counter-chip at-work">
            At Work: <b>{statusCounts.at_work}</b>
          </span>
        </div>
      </footer>

      {/* Create Scenario Modal */}
      {showCreateModal && (
        <div className="modal-backdrop" onClick={() => setShowCreateModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <h3>Create Layer 1 Scenario (50 Personas)</h3>
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
                Central Parking Tariff Change Ratio (e.g., 1.0 = +100%)
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
                <span>Include North Jakarta Tidal Flood (40 cm, ticks 16–80)</span>
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
