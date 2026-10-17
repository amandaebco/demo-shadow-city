"""Centralized model assumptions for the Shadow City Layer 2 simulation engine.

IMPORTANT (AGENTS.md & Track A Layer 2 rules):
All constants in this module are MODEL ASSUMPTIONS, not measured empirical data.
Never present these numbers as measured statistics. Every assumption is tagged
with a TODO indicating the empirical or regulatory source needed for calibration.
"""

from __future__ import annotations

# Canonical ordering of transport options for byte-for-byte request determinism
# (CONTRACT.md section 4.2 & section 5 decision_cache).
CANONICAL_MODES: tuple[str, ...] = (
    "motorcycle",
    "car",
    "transjakarta",
    "krl",
    "mrt",
    "ojol",
    "walk",
)

# ---------------------------------------------------------------------------
# 1. Station catchment & active-mobility distance assumptions (km)
# ---------------------------------------------------------------------------
# MODEL ASSUMPTION — TODO: Replace with cited Jakarta MRT feeder/access catchment
# survey (e.g. ITDP Indonesia / PT MRT Jakarta passenger access study).
MRT_CATCHMENT_KM: float = 2.5

# MODEL ASSUMPTION — TODO: Replace with cited Jabodetabek KRL station access radius
# study (e.g. JUTPI / PT KAI Commuter passenger origin-to-station survey).
KRL_CATCHMENT_KM: float = 3.5

# MODEL ASSUMPTION — TODO: Replace with cited Jakarta active-mobility maximum
# walking commute threshold (e.g. ITDP Jakarta pedestrian survey).
MAX_WALK_COMMUTE_KM: float = 4.0

# MODEL ASSUMPTION — Fallback urban road detour factor used only if road graph
# vertices are disconnected. TODO: Calibrate against OSM network circuity index.
FALLBACK_URBAN_DETOUR_FACTOR: float = 1.25

# MODEL ASSUMPTION — Straight-line station-to-station to rail track distance factor.
# TODO: Replace with exact OSM rail track polyline distances between stations.
RAIL_TRACK_DETOUR_FACTOR: float = 1.15

# ---------------------------------------------------------------------------
# 2. Access/egress walking and waiting time assumptions (minutes)
# ---------------------------------------------------------------------------
# MODEL ASSUMPTION — 12.5 min/km (~4.8 km/h walking speed).
# TODO: Cite empirical pedestrian walking speed study in tropical urban conditions.
WALK_MINUTES_PER_KM: float = 12.5

# MODEL ASSUMPTION — Average waiting time for MRT Jakarta (minutes).
# TODO: Cite official PT MRT Jakarta peak/off-peak headway schedule (5-10 min headway).
MRT_WAIT_MIN: int = 6

# MODEL ASSUMPTION — Average waiting time for KRL Commuterline (minutes).
# TODO: Cite official PT KAI Commuter Jabodetabek line headway schedule.
KRL_WAIT_MIN: int = 10

# MODEL ASSUMPTION — Average waiting + transfer time for TransJakarta BRT (minutes).
# TODO: Cite PT Transportasi Jakarta corridor headway and boarding delay statistics.
TRANSJAKARTA_WAIT_MIN: int = 8

# MODEL ASSUMPTION — Average dispatch and pickup waiting time for ojol (minutes).
# TODO: Cite ride-hailing dispatch latency survey in DKI Jakarta.
OJOL_WAIT_MIN: int = 5

# MODEL ASSUMPTION — Parking access/egress time for private motorcycles (minutes).
# TODO: Cite urban building parking access time survey.
MOTORCYCLE_PARKING_EGRESS_MIN: int = 5

# MODEL ASSUMPTION — Parking search and egress time for private cars (minutes).
# TODO: Cite Jakarta CBD off-street parking search/egress time study.
CAR_PARKING_EGRESS_MIN: int = 8

# ---------------------------------------------------------------------------
# 3. In-vehicle travel pace assumptions (minutes per km, base conditions)
# ---------------------------------------------------------------------------
# MODEL ASSUMPTION — Base in-vehicle pace by mode in minutes per kilometer.
# TODO: Calibrate road and transit speeds against Dishub DKI Jakarta / JUTPI
# travel-time surveys and official MRT/KRL commercial speed specifications.
MOTORCYCLE_MINUTES_PER_KM: float = 2.15
CAR_MINUTES_PER_KM: float = 2.95
OJOL_MINUTES_PER_KM: float = 2.25
TRANSJAKARTA_MINUTES_PER_KM: float = 2.45
MRT_IN_VEHICLE_MINUTES_PER_KM: float = 1.65
KRL_IN_VEHICLE_MINUTES_PER_KM: float = 1.90

# Minimum total door-to-door trip duration assumptions (minutes) by mode.
# MODEL ASSUMPTION — TODO: Calibrate minimum short-trip overhead from travel diaries.
MIN_TRIP_MINUTES: dict[str, int] = {
    "walk": 5,
    "motorcycle": 8,
    "car": 12,
    "transjakarta": 15,
    "krl": 20,
    "mrt": 16,
    "ojol": 10,
}

# ---------------------------------------------------------------------------
# 4. Peak-hour road capacity & congestion multiplier assumptions
# ---------------------------------------------------------------------------
# Ticks 12..48 correspond to 06:00..09:00; ticks 132..168 correspond to 16:00..19:00.
# MODEL ASSUMPTION — TODO: Replace step peak multipliers with calibrated BPR
# volume-delay curves using Dishub DKI Jakarta hourly traffic count data.
MORNING_PEAK_TICK_RANGE: tuple[int, int] = (12, 48)
EVENING_PEAK_TICK_RANGE: tuple[int, int] = (132, 168)

PEAK_CONGESTION_MULTIPLIER: dict[str, float] = {
    "car": 1.25,
    "motorcycle": 1.12,
    "ojol": 1.12,
    "transjakarta": 1.08,
    "walk": 1.0,
    "mrt": 1.0,
    "krl": 1.0,
}

# ---------------------------------------------------------------------------
# 5. Monetary cost & tariff assumptions (IDR)
# ---------------------------------------------------------------------------
# MODEL ASSUMPTION — Private motorcycle fuel and daily parking costs (IDR).
# TODO: Cite Pertalite fuel economy data and DKI Jakarta Pergub parking tariffs.
MOTORCYCLE_FUEL_IDR_PER_KM: float = 650.0
MOTORCYCLE_PARKING_CENTRAL_IDR: int = 8000
MOTORCYCLE_PARKING_NON_CENTRAL_IDR: int = 3000

# MODEL ASSUMPTION — Private car fuel/toll and daily parking costs (IDR).
# TODO: Cite passenger car fuel + toll cost study and DKI Jakarta Pergub CBD parking tariffs.
CAR_FUEL_AND_TOLL_IDR_PER_KM: float = 2200.0
CAR_PARKING_CENTRAL_IDR: int = 25000
CAR_PARKING_NON_CENTRAL_IDR: int = 10000

# MODEL ASSUMPTION — Public transit & ride-hailing fare parameters (IDR).
# TODO: Cite official TransJakarta flat fare, KAI Commuter distance tariff,
# MRT Jakarta station fare matrix, and Kemenhub Zona II ojol tariff regulation.
TRANSJAKARTA_BASE_FARE_IDR: int = 3500
KRL_BASE_FARE_IDR: int = 3000
KRL_DISTANCE_THRESHOLD_KM: float = 10.0
KRL_INCREMENT_STEP_KM: float = 10.0
KRL_INCREMENT_FARE_IDR: int = 1000

MRT_BASE_FARE_IDR: int = 4000
MRT_MAX_FARE_IDR: int = 14000
MRT_INCREMENT_STEP_KM: float = 3.0
MRT_INCREMENT_FARE_IDR: int = 1000

OJOL_BASE_FARE_IDR: int = 4000
OJOL_MIN_FARE_IDR: int = 12000
OJOL_IDR_PER_KM: float = 2800.0

# ---------------------------------------------------------------------------
# 6. Flood delay impact assumptions
# ---------------------------------------------------------------------------
# MODEL ASSUMPTION — Additional delay (minutes per cm of flood depth) when route
# edges intersect an active flood zone.
# TODO: Cite empirical flood depth vs. road speed reduction study in Jakarta
# (e.g. BPBD DKI Jakarta / Deltares flood disruption model).
FLOOD_DELAY_ROAD_MIN_PER_CM: float = 0.55
FLOOD_DELAY_BRT_MIN_PER_CM: float = 0.30

