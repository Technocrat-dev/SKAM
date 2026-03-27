#!/usr/bin/env python3
"""
SKAM Demo Scenarios — end-to-end demonstrations of the self-healing loop.

Each scenario:
  1. Starts background load
  2. Waits for baseline metrics
  3. Injects a specific fault via the chaos engine
  4. Monitors the anomaly detector for detection
  5. Monitors the decision engine for recovery
  6. Reports results

Usage:
  python demo_scenarios.py scenario1       # Single service failure + restart
  python demo_scenarios.py scenario2       # Cascading latency
  python demo_scenarios.py scenario3       # Memory pressure + auto-scale
  python demo_scenarios.py scenario4       # CPU saturation healing
  python demo_scenarios.py scenario5       # Full chaos: multi-fault injection
  python demo_scenarios.py all             # Run all scenarios
"""

import asyncio
import argparse
import time

import aiohttp

CHAOS_URL = "http://localhost:8000"
ANOMALY_URL = "http://localhost:8001"
DECISION_URL = "http://localhost:8002"
GATEWAY_URL = "http://localhost:8080"


async def inject_fault(session, fault_type, target_service, duration=30, params=None):
    body = {
        "name": f"demo-{fault_type}-{target_service}-{int(time.time())}",
        "fault_type": fault_type,
        "target": {"namespace": "default", "label_selector": f"app={target_service}"},
        "duration_seconds": duration,
        "parameters": params or {},
    }
    async with session.post(f"{CHAOS_URL}/api/experiments", json=body) as r:
        data = await r.json()
        print(f"  [chaos] injected {fault_type} on {target_service} ({duration}s) -> {data.get('id', 'ok')}")
        return data


async def wait_for_anomaly(session, target_service, timeout=90):
    print(f"  [detect] waiting for anomaly on {target_service}...")
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            async with session.get(f"{ANOMALY_URL}/api/scores") as r:
                data = await r.json()
                for s in data.get("scores", []):
                    if s["service"] == target_service and s.get("is_anomaly"):
                        elapsed = time.monotonic() - start
                        print(f"  [detect] anomaly detected! score={s['ensemble_score']:.3f} ({elapsed:.1f}s)")
                        return s
        except Exception:
            pass
        await asyncio.sleep(3)
    print(f"  [detect] timeout after {timeout}s — no anomaly detected")
    return None


async def wait_for_recovery(session, timeout=120):
    print(f"  [heal] waiting for recovery action...")
    start = time.monotonic()
    seen_ids = set()
    while time.monotonic() - start < timeout:
        try:
            async with session.get(f"{DECISION_URL}/api/events?limit=5") as r:
                data = await r.json()
                for evt in data.get("events", []):
                    if evt["id"] not in seen_ids and evt["status"] in ("completed", "executing"):
                        seen_ids.add(evt["id"])
                        elapsed = time.monotonic() - start
                        print(f"  [heal] {evt['action']} on {evt['service']} ({evt['status']}) ({elapsed:.1f}s)")
                        if evt["status"] == "completed":
                            return evt
        except Exception:
            pass
        await asyncio.sleep(3)
    print(f"  [heal] timeout after {timeout}s — no recovery observed")
    return None


def header(name, desc):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"  {desc}")
    print(f"{'='*60}\n")


async def scenario1(session):
    """Single service failure → pod restart healing"""
    header("Scenario 1", "Pod Kill → Anomaly Detection → Auto Restart")

    print("[1/3] Injecting pod_kill on user-service...")
    await inject_fault(session, "pod_kill", "user-service", duration=30)

    print("[2/3] Monitoring anomaly detector...")
    anomaly = await wait_for_anomaly(session, "user-service")

    print("[3/3] Monitoring decision engine...")
    recovery = await wait_for_recovery(session)

    return {"anomaly_detected": anomaly is not None, "recovery_completed": recovery is not None}


async def scenario2(session):
    """Cascading latency → detection across dependent services"""
    header("Scenario 2", "Latency Injection → Cascading Detection → Scale Up")

    print("[1/3] Injecting latency on order-service (500ms)...")
    await inject_fault(session, "latency_injection", "order-service", duration=45,
                       params={"delay_ms": 500})

    print("[2/3] Monitoring for cascading anomalies...")
    anomaly = await wait_for_anomaly(session, "order-service", timeout=60)

    print("[3/3] Monitoring decision engine...")
    recovery = await wait_for_recovery(session)

    return {"anomaly_detected": anomaly is not None, "recovery_completed": recovery is not None}


async def scenario3(session):
    """Memory pressure → memory limit increase"""
    header("Scenario 3", "Memory Pressure → Detection → Memory Limit Adjustment")

    print("[1/3] Injecting memory_pressure on payment-service...")
    await inject_fault(session, "memory_pressure", "payment-service", duration=40)

    print("[2/3] Monitoring anomaly detector...")
    anomaly = await wait_for_anomaly(session, "payment-service")

    print("[3/3] Monitoring decision engine...")
    recovery = await wait_for_recovery(session)

    return {"anomaly_detected": anomaly is not None, "recovery_completed": recovery is not None}


async def scenario4(session):
    """CPU saturation → auto-scale"""
    header("Scenario 4", "CPU Stress → Detection → Horizontal Scale Up")

    print("[1/3] Injecting cpu_stress on product-service...")
    await inject_fault(session, "cpu_stress", "product-service", duration=45)

    print("[2/3] Monitoring anomaly detector...")
    anomaly = await wait_for_anomaly(session, "product-service")

    print("[3/3] Monitoring decision engine...")
    recovery = await wait_for_recovery(session)

    return {"anomaly_detected": anomaly is not None, "recovery_completed": recovery is not None}


async def scenario5(session):
    """Multi-fault chaos → multiple healings"""
    header("Scenario 5", "Multi-Fault Injection → Concurrent Detection & Healing")

    print("[1/4] Injecting pod_kill on cart-service...")
    await inject_fault(session, "pod_kill", "cart-service", duration=30)

    print("[2/4] Injecting network_partition on notification-service...")
    await inject_fault(session, "network_partition", "notification-service", duration=30)

    print("[3/4] Monitoring for anomalies on both services...")
    a1 = await wait_for_anomaly(session, "cart-service", timeout=60)
    a2 = await wait_for_anomaly(session, "notification-service", timeout=60)

    print("[4/4] Monitoring decision engine for recovery actions...")
    r1 = await wait_for_recovery(session, timeout=90)

    return {
        "cart_anomaly": a1 is not None,
        "notif_anomaly": a2 is not None,
        "recovery_completed": r1 is not None,
    }


SCENARIOS = {
    "scenario1": scenario1,
    "scenario2": scenario2,
    "scenario3": scenario3,
    "scenario4": scenario4,
    "scenario5": scenario5,
}


async def run(names):
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        results = {}
        for name in names:
            fn = SCENARIOS.get(name)
            if not fn:
                print(f"Unknown scenario: {name}")
                continue
            try:
                result = await fn(session)
                results[name] = result
                status = "PASS" if all(result.values()) else "PARTIAL"
                print(f"\n  Result: {status} — {result}")
            except Exception as e:
                print(f"\n  Result: FAIL — {e}")
                results[name] = {"error": str(e)}

        print(f"\n{'='*60}")
        print("  Summary")
        print(f"{'='*60}")
        for name, result in results.items():
            marker = "OK" if isinstance(result, dict) and all(v for v in result.values() if isinstance(v, bool)) else "!!"
            print(f"  [{marker}] {name}: {result}")


def main():
    parser = argparse.ArgumentParser(description="SKAM demo scenarios")
    parser.add_argument("scenarios", nargs="+", help="scenario1..scenario5 or 'all'")
    parser.add_argument("--chaos-url", default=CHAOS_URL)
    parser.add_argument("--anomaly-url", default=ANOMALY_URL)
    parser.add_argument("--decision-url", default=DECISION_URL)
    args = parser.parse_args()

    global CHAOS_URL, ANOMALY_URL, DECISION_URL
    CHAOS_URL = args.chaos_url
    ANOMALY_URL = args.anomaly_url
    DECISION_URL = args.decision_url

    names = list(SCENARIOS.keys()) if "all" in args.scenarios else args.scenarios
    asyncio.run(run(names))


if __name__ == "__main__":
    main()
