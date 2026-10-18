#!/usr/bin/env python3
"""Read-only end-to-end check of the live demo, through the public URL judges use.

Usage: python3 infra/smoke_test.py [--base https://shadow-city.web.app]
Exit code 0 when every check passes.
"""

import argparse
import json
import time
import urllib.error
import urllib.request

DEMO = {
    "baseline": "s_baseline_weekday_c4d9d5",
    "parking": "s_central_parking_100_3aeda8",
    "parking_flood": "s_central_parking_100_with_north_jakarta_t_fe362a",
    "scale_5000": "s_layer_6_clustered_baseline_run_a_n_5000__0388aa",
}
FIRESTORE = "https://firestore.googleapis.com/v1/projects/ebc-cloud-dev-03/databases/shadow-city/documents"


def fetch(url: str) -> tuple[int, object, float]:
    started = time.time()
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            body = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        body, status = exc.read(), exc.code
    elapsed = time.time() - started
    try:
        return status, json.loads(body), elapsed
    except ValueError:
        return status, body.decode("utf-8", "replace"), elapsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="https://shadow-city.web.app")
    args = parser.parse_args()
    api = args.base.rstrip("/") + "/v1"
    checks = []

    def check(name, url, ok):
        status, body, elapsed = fetch(url)
        try:
            passed = bool(status == 200 and ok(body))
        except Exception:
            passed = False
        checks.append(passed)
        print(f"{'PASS' if passed else 'FAIL'}  {elapsed:5.1f}s  {name}" + ("" if passed else f"  -> {status} {str(body)[:160]}"))

    check("frontend loads", args.base, lambda b: "<html" in str(b).lower())
    check("orchestrator health", f"{api}/health", lambda b: b["status"] == "ok")
    for label, sid in DEMO.items():
        check(f"{label}: scenario completed", f"{api}/scenarios/{sid}", lambda b: b["status"] == "completed")
        check(f"{label}: metrics", f"{api}/scenarios/{sid}/metrics", lambda b: b["citywide"]["avg_travel_min"] > 0)
    for label in ("baseline", "parking", "parking_flood"):
        sid = DEMO[label]
        check(f"{label}: analyst report", f"{api}/scenarios/{sid}/report", lambda b: len(b["headline"]) > 20)
        check(f"{label}: verification", f"{api}/scenarios/{sid}/verification",
              lambda b: b["overall"] in ("pass", "warn", "fail") and len(b["checks"]) >= 5)
    for label in ("parking", "parking_flood"):
        check(f"{label}: compare vs baseline", f"{api}/scenarios/{DEMO[label]}/compare",
              lambda b: "base" in b and "variant" in b)
    check("persona p_s2026_n1000_r2_00747", f"{api}/personas/p_s2026_n1000_r2_00747", lambda b: b["usual_mode"])
    check("video resident decision (KRL)",
          f"{FIRESTORE}/scenarios/{DEMO['parking_flood']}/decisions/p_s2026_n1000_r2_00747",
          lambda b: b["fields"]["decisions"]["arrayValue"]["values"][0]["mapValue"]["fields"]["chosen"]["stringValue"] == "krl")
    check("live ticks readable (tick 0100)", f"{FIRESTORE}/scenarios/{DEMO['baseline']}/ticks/0100",
          lambda b: "fields" in b)
    check("backtest b_0001", f"{api}/backtests/b_0001", lambda b: b["backtest_id"] == "b_0001")

    print(f"\n{sum(checks)}/{len(checks)} checks passed")
    raise SystemExit(0 if all(checks) else 1)


if __name__ == "__main__":
    main()
