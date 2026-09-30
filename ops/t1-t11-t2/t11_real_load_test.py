from __future__ import annotations

import csv
import math
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import psutil
from deepseek_harness import DeepSeekHarness


ROOT = Path(__file__).resolve().parents[2]
DSH_BIN = ROOT / "ops/t1-t11-t2/dsh-source.sh"
DSH_HOME = Path.home() / "dsh-t11-real-home"
WORKSPACE = ROOT / "ops/t1-t11-t2/workspace"
RESULT_DIR = ROOT / "ops/t1-t11-t2/results"

MODEL = "deepseek/deepseek-v4-flash-0731"

CONCURRENCY_LEVELS = [1, 5]
REQUESTS_PER_USER = 2
EXPECTED_RESPONSE = "T11 REAL OK"


def percentile(values, p):
    if not values:
        return 0.0

    values = sorted(values)

    if len(values) == 1:
        return values[0]

    k = (len(values) - 1) * (p / 100)
    f = math.floor(k)
    c = math.ceil(k)

    if f == c:
        return values[int(k)]

    return values[f] * (c - k) + values[c] * (k - f)


def monitor(stop_event, samples):
    psutil.cpu_percent(interval=None)

    while not stop_event.is_set():
        memory = psutil.virtual_memory()

        samples.append({
            "cpu": psutil.cpu_percent(interval=0.2),
            "memory_percent": memory.percent,
            "memory_available_mib": memory.available / (1024 * 1024),
        })


def run_level(harness, concurrency):
    rows = []
    lock = threading.Lock()
    barrier = threading.Barrier(concurrency)

    samples = []
    stop_event = threading.Event()

    monitor_thread = threading.Thread(
        target=monitor,
        args=(stop_event, samples),
        daemon=True,
    )

    def worker(user_index):
        session_id = (
            f"t11-real-c{concurrency}-u{user_index}-"
            f"{datetime.now().strftime('%H%M%S%f')}"
        )

        session = harness.start_session(session_id)

        barrier.wait()

        for request_index in range(REQUESTS_PER_USER):
            started = time.perf_counter()

            success = False
            exact_match = False
            error = ""
            response = ""
            finish_reason = ""

            try:
                result = session.run(
                    "Reply with exactly: T11 REAL OK"
                )

                finish_reason = result.finish_reason or ""
                response = result.final_response.strip()

                success = (
                    finish_reason == "completed"
                    and bool(response)
                )

                exact_match = response == EXPECTED_RESPONSE

                if not success:
                    error = (
                        f"finish_reason={finish_reason}, "
                        f"response={response!r}"
                    )

            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            latency = time.perf_counter() - started

            with lock:
                rows.append({
                    "concurrency": concurrency,
                    "user": user_index,
                    "request": request_index,
                    "session_id": session_id,
                    "success": success,
                    "exact_match": exact_match,
                    "latency_seconds": latency,
                    "finish_reason": finish_reason,
                    "response": response,
                    "error": error,
                })

    print()
    print(f"=== REAL concurrency={concurrency} START ===")

    monitor_thread.start()
    wall_start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(worker, i)
            for i in range(concurrency)
        ]

        for future in futures:
            future.result()

    wall = time.perf_counter() - wall_start

    stop_event.set()
    monitor_thread.join(timeout=2)

    successful = [x for x in rows if x["success"]]
    latencies = [x["latency_seconds"] for x in successful]

    total = len(rows)
    success_count = len(successful)
    exact_count = sum(x["exact_match"] for x in rows)

    cpu_values = [x["cpu"] for x in samples]

    summary = {
        "concurrency": concurrency,
        "requests_per_user": REQUESTS_PER_USER,
        "total_requests": total,
        "success": success_count,
        "failed": total - success_count,
        "success_rate_percent": (
            success_count / total * 100 if total else 0
        ),
        "exact_match": exact_count,
        "wall_seconds": wall,
        "throughput_rps": total / wall if wall else 0,
        "latency_avg_seconds": (
            statistics.mean(latencies) if latencies else 0
        ),
        "latency_p50_seconds": percentile(latencies, 50),
        "latency_p95_seconds": percentile(latencies, 95),
        "latency_max_seconds": max(latencies) if latencies else 0,
        "system_cpu_avg_percent": (
            statistics.mean(cpu_values) if cpu_values else 0
        ),
        "system_cpu_peak_percent": (
            max(cpu_values) if cpu_values else 0
        ),
    }

    print(
        f"requests={total} "
        f"success={success_count} "
        f"failed={total-success_count} "
        f"exact={exact_count}"
    )

    print(
        f"success_rate={summary['success_rate_percent']:.1f}% "
        f"wall={wall:.2f}s "
        f"throughput={summary['throughput_rps']:.3f} req/s"
    )

    print(
        f"latency avg={summary['latency_avg_seconds']:.2f}s "
        f"p50={summary['latency_p50_seconds']:.2f}s "
        f"p95={summary['latency_p95_seconds']:.2f}s "
        f"max={summary['latency_max_seconds']:.2f}s"
    )

    print(
        f"CPU avg={summary['system_cpu_avg_percent']:.1f}% "
        f"peak={summary['system_cpu_peak_percent']:.1f}%"
    )

    failures = [x for x in rows if not x["success"]]

    for failure in failures:
        print(
            "FAIL:",
            failure["session_id"],
            failure["error"],
        )

    return summary, rows


def main():
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    summaries = []
    details = []

    with DeepSeekHarness(
        dsh_bin=str(DSH_BIN),
        dsh_home=str(DSH_HOME),
        cwd=str(WORKSPACE),
        runtime_cwd=str(ROOT),
        profile="sdk-minimal",
        provider="deepseek-official",
        model=MODEL,
        max_tokens=64,
        request_timeout_seconds=120,
    ) as harness:

        for concurrency in CONCURRENCY_LEVELS:
            summary, rows = run_level(harness, concurrency)
            summaries.append(summary)
            details.extend(rows)

    summary_path = (
        RESULT_DIR / f"t11_real_summary_{timestamp}.csv"
    )

    detail_path = (
        RESULT_DIR / f"t11_real_details_{timestamp}.csv"
    )

    with summary_path.open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(summaries[0].keys()),
        )
        writer.writeheader()
        writer.writerows(summaries)

    with detail_path.open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(details[0].keys()),
        )
        writer.writeheader()
        writer.writerows(details)

    print()
    print("=== T11 REAL TEST COMPLETE ===")
    print("summary:", summary_path)
    print("details:", detail_path)


if __name__ == "__main__":
    main()
