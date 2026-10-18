"""Unit tests for sim-worker Layer 0, Layer 1, and Layer 2 engine, road graph, physics, and config.

Compatible with both `python -m unittest` and `pytest`.
"""

from __future__ import annotations

import copy
import json
import os
import unittest
from typing import Any
from unittest.mock import patch

import networkx as nx

from sim_worker.assumptions import (
    CANONICAL_MODES,
    KRL_WAIT_MIN,
    MRT_CATCHMENT_KM,
    MRT_WAIT_MIN,
    WALK_MINUTES_PER_KM,
)
from sim_worker.config import (
    END_TICK,
    EXPECTED_FIRESTORE_DATABASE,
    EXPECTED_GCP_PROJECT_ID,
    START_TICK,
    TOTAL_TICKS,
    WorkerConfig,
)
from sim_worker.engine import (
    FROZEN_DEMO_SCENARIO_IDS,
    flood_signature,
    format_tick_id,
    make_decision_rng,
    make_tick_rng,
    normalize_member_probabilities,
    persona_hash,
    run_placeholder_tick_loop,
    sample_mode_choice,
    simulate_scenario_layer1,
    simulate_scenario_layer2,
    tick_to_local_time,
)
from sim_worker.physics import ZoneIndex, compute_options_detail, haversine_km
from sim_worker.road_graph import JakartaNetwork


class FakeDecisionProvider:
    """Deterministic fake System One provider for unit tests."""

    def __init__(self, forced_mode: str | None = None) -> None:
        self.forced_mode = forced_mode
        self.last_items: list[dict[str, Any]] = []

    def decide_batch(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.last_items = copy.deepcopy(items)
        out: list[dict[str, Any]] = []
        for item in items:
            opts = item["options"]
            chosen = self.forced_mode if (self.forced_mode in opts) else opts[0]
            out.append(
                {
                    "request_id": item["request_id"],
                    "decision_id": f"d_{item['request_id']}",
                    "probabilities": {o: (1.0 if o == chosen else 0.0) for o in opts},
                    "chosen": chosen,
                    "reason_short": f"Chose {chosen} in test.",
                    "decided_by": "rule-fallback",
                    "model_version": "test-fake-v0",
                    "latency_ms": 1,
                }
            )
        return out


class TestSimWorkerLayer0To2(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = WorkerConfig.from_env()
        cls.zones = ZoneIndex.from_file(cls.cfg.zones_geojson_path)
        cls.network = JakartaNetwork.from_file(cls.cfg.network_json_path)

    def test_worker_config_defaults(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("GCP_PROJECT_ID", "FIRESTORE_DATABASE")
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = WorkerConfig.from_env()
            self.assertEqual(cfg.gcp_project_id, EXPECTED_GCP_PROJECT_ID)
            self.assertEqual(cfg.firestore_database, EXPECTED_FIRESTORE_DATABASE)
            self.assertEqual(cfg.gcp_region, "asia-southeast2")

    def test_worker_config_rejects_wrong_project(self) -> None:
        with patch.dict(os.environ, {"GCP_PROJECT_ID": "wrong-project-id"}):
            with self.assertRaisesRegex(ValueError, "ebc-cloud-dev-03"):
                WorkerConfig.from_env()

    def test_worker_config_rejects_wrong_firestore_db(self) -> None:
        with patch.dict(os.environ, {"FIRESTORE_DATABASE": "(default)"}):
            with self.assertRaisesRegex(ValueError, "shadow-city"):
                WorkerConfig.from_env()

    def test_tick_formatting_and_simulated_time(self) -> None:
        self.assertEqual(format_tick_id(START_TICK), "0000")
        self.assertEqual(format_tick_id(84), "0084")
        self.assertEqual(format_tick_id(END_TICK), "0203")

        self.assertEqual(tick_to_local_time(0), "05:00")
        self.assertEqual(tick_to_local_time(12), "06:00")
        self.assertEqual(tick_to_local_time(203), "21:55")

    def test_placeholder_tick_loop_is_deterministic(self) -> None:
        states_a = run_placeholder_tick_loop(scenario_id="s_baseline_weekday", seed=42)
        states_b = run_placeholder_tick_loop(scenario_id="s_baseline_weekday", seed=42)

        self.assertEqual(len(states_a), TOTAL_TICKS)
        self.assertEqual(states_a, states_b)
        self.assertEqual(states_a[0].tick_id, "0000")
        self.assertEqual(states_a[-1].tick_id, "0203")
        self.assertEqual(
            states_a[84].to_firestore_dict(),
            {
                "scenario_id": "s_baseline_weekday",
                "tick": 84,
                "persona_ids": [],
                "lat": [],
                "lng": [],
                "mode": [],
                "status": [],
            },
        )

    def test_make_tick_rng_reproducibility(self) -> None:
        rng1 = make_tick_rng(seed=42, tick=84, salt="p_00421")
        rng2 = make_tick_rng(seed=42, tick=84, salt="p_00421")
        rng_diff = make_tick_rng(seed=43, tick=84, salt="p_00421")

        seq1 = [rng1.random() for _ in range(5)]
        seq2 = [rng2.random() for _ in range(5)]
        seq_diff = [rng_diff.random() for _ in range(5)]

        self.assertEqual(seq1, seq2)
        self.assertNotEqual(seq1, seq_diff)

    def test_zones_geojson_matches_contract(self) -> None:
        self.assertTrue(self.cfg.zones_geojson_path.exists(), f"Missing {self.cfg.zones_geojson_path}")
        fc = json.loads(self.cfg.zones_geojson_path.read_text(encoding="utf-8"))
        self.assertEqual(fc["type"], "FeatureCollection")
        by_id = {f["properties"]["zone_id"]: f for f in fc["features"]}
        self.assertEqual(set(by_id.keys()), {"central", "jakarta_utara"})

        central = by_id["central"]
        self.assertEqual(central["properties"]["type"], "parking_zone")
        self.assertEqual(
            central["properties"]["kecamatan"],
            ["Gambir", "Menteng", "Tanah Abang", "Setiabudi"],
        )
        self.assertIn(central["geometry"]["type"], ("Polygon", "MultiPolygon"))

        north = by_id["jakarta_utara"]
        self.assertEqual(north["properties"]["type"], "flood_area")
        self.assertEqual(
            north["properties"]["kecamatan"],
            ["Penjaringan", "Pademangan", "Tanjung Priok", "Koja", "Cilincing"],
        )
        self.assertIn(north["geometry"]["type"], ("Polygon", "MultiPolygon"))

    def test_jakarta_osm_network_and_operational_stations(self) -> None:
        self.assertTrue(self.cfg.network_json_path.exists(), f"Missing {self.cfg.network_json_path}")
        self.assertEqual(len(self.network.mrt_stations), 13)
        # Verify no MRT Phase 2 stations north of Bundaran HI are included
        for st in self.network.mrt_stations:
            self.assertLessEqual(float(st["lat"]), -6.1905)
        self.assertGreaterEqual(len(self.network.krl_stations), 40)
        krl_names = {s["name"].lower() for s in self.network.krl_stations}
        self.assertNotIn("gambir", krl_names)
        self.assertNotIn("jakarta gudang", krl_names)

        self.assertGreater(self.network.graph.number_of_nodes(), 5000)
        self.assertTrue(nx.is_connected(self.network.graph))

    def test_mrt_and_krl_station_reachability_gating(self) -> None:
        # 1. Persona along the MRT North-South corridor (Cipete -> Setiabudi)
        persona_mrt_corridor = {
            "persona_id": "p_mrt_yes",
            "home": {"kelurahan": "Cipete Selatan", "lat": -6.2780, "lng": 106.7980},
            "work": {"kelurahan": "Karet Kuningan", "lat": -6.2095, "lng": 106.8220},
            "vehicles": ["motorcycle"],
            "usual_mode": "motorcycle",
            "usual_departure_tick": 24,
        }
        opts_mrt, detail_mrt, _, _ = compute_options_detail(
            persona=persona_mrt_corridor,
            tick=24,
            policies=[],
            events=[],
            zones=self.zones,
            network=self.network,
        )
        self.assertIn("mrt", opts_mrt)
        # MRT time must include access walk + MRT_WAIT_MIN + in-vehicle + egress walk
        self.assertGreaterEqual(detail_mrt["mrt"]["est_minutes"], 16)

        # 2. Persona in Penjaringan (North Jakarta) -> Cakung (East Jakarta), far from MRT
        persona_no_mrt = {
            "persona_id": "p_mrt_no",
            "home": {"kelurahan": "Penjaringan", "lat": -6.1260, "lng": 106.7960},
            "work": {"kelurahan": "Cakung Barat", "lat": -6.1724, "lng": 106.9341},
            "vehicles": ["motorcycle"],
            "usual_mode": "motorcycle",
            "usual_departure_tick": 24,
        }
        opts_no_mrt, _, _, _ = compute_options_detail(
            persona=persona_no_mrt,
            tick=24,
            policies=[],
            events=[],
            zones=self.zones,
            network=self.network,
        )
        self.assertNotIn("mrt", opts_no_mrt)
        self.assertNotIn("krl", opts_no_mrt)

        # 3. Persona near Pasar Minggu KRL -> Gondangdia KRL (Gambir)
        persona_krl_corridor = {
            "persona_id": "p_krl_yes",
            "home": {"kelurahan": "Pasar Minggu", "lat": -6.2871, "lng": 106.8439},
            "work": {"kelurahan": "Gambir", "lat": -6.1772, "lng": 106.8249},
            "vehicles": ["car"],
            "usual_mode": "car",
            "usual_departure_tick": 24,
        }
        opts_krl, detail_krl, _, _ = compute_options_detail(
            persona=persona_krl_corridor,
            tick=24,
            policies=[],
            events=[],
            zones=self.zones,
            network=self.network,
        )
        self.assertIn("krl", opts_krl)
        self.assertNotIn("mrt", opts_krl)  # Pasar Minggu is >4.5 km from Fatmawati MRT (> 2.5 km catchment)
        self.assertGreaterEqual(detail_krl["krl"]["est_minutes"], 20)

    def test_physics_options_detail_and_parking_policy(self) -> None:
        persona = {
            "persona_id": "p_s42_n50_00000",
            "cluster_id": "c_s42_n50_00000",
            "home": {"kelurahan": "Penjaringan", "lat": -6.1260, "lng": 106.7960},
            "work": {"kelurahan": "Gambir", "lat": -6.1750, "lng": 106.8230},
            "vehicles": ["car", "motorcycle"],
            "usual_mode": "car",
            "usual_departure_tick": 20,
            "cost_sensitivity": 0.5,
            "time_sensitivity": 0.7,
        }
        dist = haversine_km(
            persona["home"]["lat"],
            persona["home"]["lng"],
            persona["work"]["lat"],
            persona["work"]["lng"],
        )
        self.assertGreater(dist, 5.0)
        self.assertLess(dist, 10.0)

        opts_base, detail_base, pol_base, ev_base = compute_options_detail(
            persona=persona,
            tick=20,
            policies=[],
            events=[],
            zones=self.zones,
            network=self.network,
        )
        opts_pol, detail_pol, pol_str, ev_str = compute_options_detail(
            persona=persona,
            tick=20,
            policies=[{"type": "parking_tariff", "zone": "central", "change_ratio": 1.0}],
            events=[
                {
                    "type": "flood",
                    "area_id": "jakarta_utara",
                    "start_tick": 10,
                    "end_tick": 40,
                    "depth_cm": 40,
                }
            ],
            zones=self.zones,
            network=self.network,
        )

        self.assertEqual(opts_base, opts_pol)
        # Verify canonical mode order
        self.assertEqual(opts_pol, [m for m in CANONICAL_MODES if m in opts_pol])
        for opt in opts_pol:
            self.assertIn(opt, detail_pol)
        self.assertGreater(detail_pol["car"]["cost_idr"], detail_base["car"]["cost_idr"])
        self.assertTrue(detail_pol["car"]["flooded_on_route"])
        self.assertEqual(pol_str, ["parking_tariff:central:+100%"])
        self.assertEqual(ev_str, ["flood:jakarta_utara"])

    def test_layer2_road_routing_and_two_run_determinism(self) -> None:
        personas_run1 = [
            {
                "persona_id": "p_00002",
                "cluster_id": "c_00002",
                "population_id": "pop_s42_n2",
                "home": {"kelurahan": "Penjaringan", "lat": -6.1214, "lng": 106.7923},
                "work": {"kelurahan": "Setiabudi", "lat": -6.2088, "lng": 106.8302},
                "income_band": "middle",
                "vehicles": ["motorcycle"],
                "usual_mode": "motorcycle",
                "usual_departure_tick": 24,
                "cost_sensitivity": 0.7,
                "time_sensitivity": 0.6,
                "profile_summary": "Worker commuting to Setiabudi.",
                "memory": ["Prior memory 1"],
            },
            {
                "persona_id": "p_00001",
                "cluster_id": "c_00001",
                "population_id": "pop_s42_n2",
                "home": {"kelurahan": "Pasar Minggu", "lat": -6.2871, "lng": 106.8439},
                "work": {"kelurahan": "Gambir", "lat": -6.1772, "lng": 106.8249},
                "income_band": "high",
                "vehicles": ["car"],
                "usual_mode": "car",
                "usual_departure_tick": 20,
                "cost_sensitivity": 0.2,
                "time_sensitivity": 0.8,
                "profile_summary": "Advisor commuting to Gambir.",
                "memory": [],
            },
        ]
        # Reverse persona order and policy order in run 2 to verify deterministic sorting
        personas_run2 = copy.deepcopy(list(reversed(personas_run1)))

        scenario_1 = {
            "scenario_id": "s_test_det_1",
            "seed": 42,
            "population_size": 2,
            "population_id": "pop_s42_n2",
            "policies": [
                {"type": "parking_tariff", "zone": "central", "change_ratio": 1.0},
                {"type": "transit_fare", "zone": "all", "change_ratio": -0.3},
            ],
            "events": [
                {
                    "type": "flood",
                    "area_id": "jakarta_utara",
                    "start_tick": 15,
                    "end_tick": 60,
                    "depth_cm": 35,
                }
            ],
        }
        scenario_2 = {
            "scenario_id": "s_test_det_2",
            "seed": 42,
            "population_size": 2,
            "population_id": "pop_s42_n2",
            "policies": list(reversed(scenario_1["policies"])),
            "events": copy.deepcopy(scenario_1["events"]),
        }

        fake_1 = FakeDecisionProvider(forced_mode="transjakarta")
        fake_2 = FakeDecisionProvider(forced_mode="transjakarta")

        res_1 = simulate_scenario_layer2(
            scenario=scenario_1,
            personas=personas_run1,
            zones=self.zones,
            decision_provider=fake_1,
            network=self.network,
        )
        res_2 = simulate_scenario_layer2(
            scenario=scenario_2,
            personas=personas_run2,
            zones=self.zones,
            decision_provider=fake_2,
            network=self.network,
        )

        # 1. Verify input persona.memory was NOT mutated
        self.assertEqual(personas_run1[0]["memory"], ["Prior memory 1"])
        self.assertEqual(personas_run1[1]["memory"], [])
        # While scenario_memories captured the scenario-scoped memory (max 5, newest last)
        self.assertEqual(len(res_1.scenario_memories["p_00002"]), 2)
        self.assertEqual(len(res_1.scenario_memories["p_00001"]), 1)

        # 2. Verify System One request items are byte-for-byte identical (excluding request_id & scenario_id)
        self.assertEqual(len(fake_1.last_items), len(fake_2.last_items))
        for item1, item2 in zip(fake_1.last_items, fake_2.last_items):
            c1 = {k: v for k, v in item1.items() if k not in ("request_id", "scenario_id")}
            c2 = {k: v for k, v in item2.items() if k not in ("request_id", "scenario_id")}
            self.assertEqual(
                json.dumps(c1, sort_keys=False),
                json.dumps(c2, sort_keys=False),
            )

        # 3. Verify all 204 tick documents are identical across both runs
        self.assertEqual(len(res_1.tick_states), TOTAL_TICKS)
        self.assertEqual(len(res_2.tick_states), TOTAL_TICKS)
        for t1, t2 in zip(res_1.tick_states, res_2.tick_states):
            d1 = {k: v for k, v in t1.to_firestore_dict().items() if k != "scenario_id"}
            d2 = {k: v for k, v in t2.to_firestore_dict().items() if k != "scenario_id"}
            self.assertEqual(d1, d2)

        # 4. Verify metrics/summary is identical across both runs and includes residents in by_kelurahan
        m1 = {k: v for k, v in res_1.metrics_summary.items() if k != "scenario_id"}
        m2 = {k: v for k, v in res_2.metrics_summary.items() if k != "scenario_id"}
        self.assertEqual(m1, m2)
        for kel_row in res_1.metrics_summary["by_kelurahan"]:
            self.assertEqual(kel_row["residents"], 1)

        # 5. Verify persona_decisions matches CONTRACT.md v1.5 §4.5
        self.assertEqual(res_1.persona_decisions, res_2.persona_decisions)
        for pid in ("p_00001", "p_00002"):
            self.assertIn(pid, res_1.persona_decisions)
            self.assertEqual(len(res_1.persona_decisions[pid]), 1)
            dec = res_1.persona_decisions[pid][0]
            self.assertEqual(
                set(dec.keys()),
                {"tick", "options_detail", "probabilities", "chosen", "reason_short", "decided_by"},
            )
            self.assertEqual(dec["chosen"], "transjakarta")
            self.assertEqual(dec["decided_by"], "rule-fallback")

    def test_layer6_cluster_decision_sharing_and_flood_split(self) -> None:
        """Verify CONTRACT.md v1.7 §4.6:
        1. Split cluster members by flood signature.
        2. Send 1 request per group (representative if in group, else lowest persona_id).
        3. Each member samples its own chosen from probabilities restricted & rescaled to its options
           using RNG seeded by seed + tick + persona_hash(member).
        4. Member decision records include shared_from.
        """
        # Three members in cluster c_001:
        # - p_00001: in North Jakarta (flooded route during flood), not representative
        # - p_00002: in North Jakarta (flooded route during flood), IS cluster representative
        # - p_00003: in South Jakarta (dry route during flood), not representative (lowest id in dry group)
        clustered_personas = [
            {
                "persona_id": "p_00001",
                "cluster_id": "c_001",
                "is_cluster_representative": False,
                "population_id": "pop_s42_n3",
                "home": {"kelurahan": "Penjaringan", "lat": -6.1214, "lng": 106.7923},
                "work": {"kelurahan": "Setiabudi", "lat": -6.2088, "lng": 106.8302},
                "income_band": "middle",
                "vehicles": ["motorcycle"],
                "usual_mode": "motorcycle",
                "usual_departure_tick": 20,
                "cost_sensitivity": 0.7,
                "time_sensitivity": 0.6,
                "profile_summary": "Member 1 in North Jakarta.",
                "memory": [],
            },
            {
                "persona_id": "p_00002",
                "cluster_id": "c_001",
                "is_cluster_representative": True,
                "population_id": "pop_s42_n3",
                "home": {"kelurahan": "Pademangan Barat", "lat": -6.1320, "lng": 106.8350},
                "work": {"kelurahan": "Setiabudi", "lat": -6.2088, "lng": 106.8302},
                "income_band": "middle",
                "vehicles": ["motorcycle"],
                "usual_mode": "motorcycle",
                "usual_departure_tick": 24,
                "cost_sensitivity": 0.65,
                "time_sensitivity": 0.6,
                "profile_summary": "Representative in North Jakarta.",
                "memory": [],
            },
            {
                "persona_id": "p_00003",
                "cluster_id": "c_001",
                "is_cluster_representative": False,
                "population_id": "pop_s42_n3",
                "home": {"kelurahan": "Cipete Selatan", "lat": -6.2780, "lng": 106.7980},
                "work": {"kelurahan": "Karet Kuningan", "lat": -6.2095, "lng": 106.8220},
                "income_band": "middle",
                "vehicles": ["motorcycle"],
                "usual_mode": "motorcycle",
                "usual_departure_tick": 22,
                "cost_sensitivity": 0.7,
                "time_sensitivity": 0.6,
                "profile_summary": "Member 3 in South Jakarta (MRT corridor, dry).",
                "memory": [],
            },
        ]

        class MixedProbProvider:
            def __init__(self) -> None:
                self.last_items: list[dict[str, Any]] = []

            def decide_batch(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
                self.last_items = copy.deepcopy(items)
                out: list[dict[str, Any]] = []
                for item in items:
                    probs = {o: (0.6 if o == "transjakarta" else 0.4 / max(1, len(item["options"]) - 1)) for o in item["options"]}
                    out.append(
                        {
                            "request_id": item["request_id"],
                            "decision_id": f"d_{item['request_id']}",
                            "probabilities": probs,
                            "chosen": "transjakarta",
                            "reason_short": "Shared cluster decision reason.",
                            "decided_by": "gemini-system-two",
                            "model_version": "gemini-3.8-flash",
                            "latency_ms": 10,
                        }
                    )
                return out

        # Case A: Baseline (no flood) -> all 3 members have empty flood signature -> 1 group total,
        # sent using representative p_00002's context.
        prov_no_flood = MixedProbProvider()
        res_no_flood = simulate_scenario_layer2(
            scenario={"scenario_id": "s_layer6_base", "seed": 42, "policies": [], "events": []},
            personas=clustered_personas,
            zones=self.zones,
            decision_provider=prov_no_flood,
            network=self.network,
        )
        self.assertEqual(len(prov_no_flood.last_items), 1)
        self.assertEqual(prov_no_flood.last_items[0]["persona_id"], "p_00002")
        for pid in ("p_00001", "p_00002", "p_00003"):
            dec = res_no_flood.persona_decisions[pid][0]
            self.assertEqual(dec["shared_from"], "p_00002")
            self.assertEqual(dec["reason_short"], "Shared cluster decision reason.")
            # Probabilities restricted to member's own options and sum to 1
            self.assertAlmostEqual(sum(dec["probabilities"].values()), 1.0, places=3)

        # Case B: Active North Jakarta flood -> cluster c_001 splits into 2 flood-signature groups:
        # - Flooded group (p_00001, p_00002) -> uses representative p_00002
        # - Dry group (p_00003) -> representative not in group, uses lowest persona_id p_00003
        prov_flood = MixedProbProvider()
        res_flood = simulate_scenario_layer2(
            scenario={
                "scenario_id": "s_layer6_flood",
                "seed": 42,
                "policies": [],
                "events": [
                    {
                        "type": "flood",
                        "area_id": "jakarta_utara",
                        "start_tick": 10,
                        "end_tick": 60,
                        "depth_cm": 45,
                    }
                ],
            },
            personas=clustered_personas,
            zones=self.zones,
            decision_provider=prov_flood,
            network=self.network,
        )
        self.assertEqual(len(prov_flood.last_items), 2)
        sent_pids = {item["persona_id"] for item in prov_flood.last_items}
        self.assertEqual(sent_pids, {"p_00002", "p_00003"})
        self.assertEqual(res_flood.persona_decisions["p_00001"][0]["shared_from"], "p_00002")
        self.assertEqual(res_flood.persona_decisions["p_00002"][0]["shared_from"], "p_00002")
        self.assertEqual(res_flood.persona_decisions["p_00003"][0]["shared_from"], "p_00003")

        # Verify Frozen Demo Scenario leaves clustering off by default
        demo_id = next(iter(FROZEN_DEMO_SCENARIO_IDS))
        prov_demo = MixedProbProvider()
        res_demo = simulate_scenario_layer2(
            scenario={"scenario_id": demo_id, "seed": 42, "policies": [], "events": []},
            personas=clustered_personas,
            zones=self.zones,
            decision_provider=prov_demo,
            network=self.network,
        )
        self.assertEqual(len(prov_demo.last_items), 3)
        self.assertNotIn("shared_from", res_demo.persona_decisions["p_00001"][0])

    def test_layer7_transit_fare_modes_filter_rp1_day(self) -> None:
        """Verify CONTRACT.md v1.8 §2.2:
        - transit_fare with modes: ['transjakarta', 'mrt'] and change_ratio: -0.9997
          discounts Transjakarta and MRT to Rp 1 while leaving KRL at its normal fare.
        - transit_fare without modes discounts all transit modes (including KRL).
        """
        # Persona near Kebayoran KRL & Blok M MRT -> Sudirman KRL & Dukuh Atas MRT
        persona_both_rail = {
            "persona_id": "p_rail_both",
            "home": {"kelurahan": "Kramat Pela", "lat": -6.2440, "lng": 106.7980},
            "work": {"kelurahan": "Kebon Melati", "lat": -6.2008, "lng": 106.8228},
            "vehicles": ["motorcycle"],
            "usual_mode": "motorcycle",
            "usual_departure_tick": 24,
        }
        opts_base, detail_base, _, _ = compute_options_detail(
            persona=persona_both_rail,
            tick=24,
            policies=[],
            events=[],
            zones=self.zones,
            network=self.network,
        )
        self.assertIn("transjakarta", opts_base)
        self.assertIn("mrt", opts_base)
        self.assertIn("krl", opts_base)

        # Rp1 day policy: modes = ["transjakarta", "mrt"], KRL not discounted
        rp1_policies = [
            {
                "type": "transit_fare",
                "zone": "all",
                "change_ratio": -0.9997,
                "modes": ["transjakarta", "mrt"],
            }
        ]
        _, detail_rp1, pol_str_rp1, _ = compute_options_detail(
            persona=persona_both_rail,
            tick=24,
            policies=rp1_policies,
            events=[],
            zones=self.zones,
            network=self.network,
        )
        self.assertEqual(detail_rp1["transjakarta"]["cost_idr"], 1)
        self.assertEqual(detail_rp1["mrt"]["cost_idr"], 1)
        self.assertEqual(detail_rp1["krl"]["cost_idr"], detail_base["krl"]["cost_idr"])
        self.assertGreaterEqual(detail_rp1["krl"]["cost_idr"], 3000)
        self.assertEqual(pol_str_rp1, ["transit_fare:mrt,transjakarta:-100%"])

        # Absent modes = applies to every transit mode (including KRL)
        all_transit_policies = [
            {"type": "transit_fare", "zone": "all", "change_ratio": -0.5}
        ]
        _, detail_all, pol_str_all, _ = compute_options_detail(
            persona=persona_both_rail,
            tick=24,
            policies=all_transit_policies,
            events=[],
            zones=self.zones,
            network=self.network,
        )
        self.assertLess(detail_all["transjakarta"]["cost_idr"], detail_base["transjakarta"]["cost_idr"])
        self.assertLess(detail_all["mrt"]["cost_idr"], detail_base["mrt"]["cost_idr"])
        self.assertLess(detail_all["krl"]["cost_idr"], detail_base["krl"]["cost_idr"])
        self.assertEqual(pol_str_all, ["transit_fare:all:-50%"])


if __name__ == "__main__":
    unittest.main()
