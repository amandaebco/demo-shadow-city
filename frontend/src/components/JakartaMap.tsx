"use client";

import React, { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { APP_CONFIG } from "@/lib/config";

export default function JakartaMap() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [showZones, setShowZones] = useState<boolean>(false);
  const [mapReady, setMapReady] = useState<boolean>(false);

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
          visibility: "none",
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
          "fill-opacity": 0.25,
        },
      });

      map.addLayer({
        id: "zones-outline",
        type: "line",
        source: "shadow-city-zones",
        layout: {
          visibility: "none",
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
          "line-width": 2,
        },
      });

      setMapReady(true);
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

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

  const handleResetView = () => {
    mapRef.current?.flyTo({
      center: [APP_CONFIG.jakartaCenter.lng, APP_CONFIG.jakartaCenter.lat],
      zoom: APP_CONFIG.jakartaCenter.zoom,
      pitch: 0,
      bearing: 0,
      duration: 900,
    });
  };

  return (
    <div className="map-shell">
      <header className="hud-header">
        <div className="hud-brand">
          <span className="status-dot" aria-hidden="true" />
          <div>
            <h1>Shadow City</h1>
            <p className="subtitle">Jakarta Policy Simulator &middot; Layer 0 (Foundation)</p>
          </div>
        </div>

        <div className="hud-controls">
          <span className="hud-badge">
            GCP: <code>{APP_CONFIG.gcpProjectId}</code>
          </span>
          <span className="hud-badge">
            Firestore: <code>{APP_CONFIG.firestoreDatabase}</code>
          </span>
          <button
            type="button"
            className={`hud-button ${showZones ? "active" : ""}`}
            onClick={() => setShowZones((prev) => !prev)}
            disabled={!mapReady}
          >
            {showZones ? "Hide Policy & Flood Zones" : "Preview Policy & Flood Zones"}
          </button>
          <button type="button" className="hud-button" onClick={handleResetView}>
            Recenter Jakarta
          </button>
        </div>
      </header>

      <div ref={containerRef} className="map-canvas" role="region" aria-label="Map of Jakarta" />

      {showZones && (
        <aside className="zone-legend" aria-label="Zone Legend">
          <div className="legend-item">
            <span className="swatch swatch-central" />
            <div>
              <strong>central</strong> (<code>parking_zone</code>)
              <div className="legend-sub">Gambir, Menteng, Tanah Abang, Setiabudi</div>
            </div>
          </div>
          <div className="legend-item">
            <span className="swatch swatch-north" />
            <div>
              <strong>jakarta_utara</strong> (<code>flood_area</code>)
              <div className="legend-sub">Penjaringan, Pademangan, Tanjung Priok, Koja, Cilincing</div>
            </div>
          </div>
        </aside>
      )}
    </div>
  );
}

