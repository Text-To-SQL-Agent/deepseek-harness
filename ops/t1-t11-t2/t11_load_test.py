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
DSH_HOME = Path.home() / "dsh-t11-home"
WORKSPACE = ROOT / "ops/t1-t11-t2/workspace"
RESULT_DIR = ROOT / "ops/t1-t11-t2/results"

CONCURRENCY_LEVELS = [1, 5, 10, 20]

# 가상 사용자 한 명이 순차적으로 보내는 요청 수
REQUESTS_PER_USER = 5

EXPECTED_RESPONSE = "T11 mock response OK"


def percentile(values: list[float], p: float) -> float:
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


def find_harness_rss_mib() -> float:
    """
    현재 sdk-minimal Harness Runtime과 자식 프로세스의 RSS 합계를 구한다.
    """
    total = 0
    seen: set[int] = set()

    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            cmd = " ".join(cmdline)

            if (
                "apps/cli/src/bin.ts" in cmd
                and "--profile" in cmd
                and "sdk-minimal" in cmd
            ):
                targets = [proc]

                try:
                    targets += proc.children(recursive=True)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

                for target in targets:
                    if target.pid in seen:
                        continue

                    seen.add(target.pid)

                    try:
                        total += target.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return total / (1024 * 1024)


def start_monitor(stop_event: threading.Event, samples: list[dict]) -> None:
    # 첫 cpu_percent 호출은 기준점 생성용
    psutil.cpu_percent(interval=None)

    while not stop_event.is_set():
        cpu = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()

        samples.append(
            {
                "cpu_percent": cpu,
                "memory_percent": memory.percent,
                "memory_available_mib": memory.available / (1024 * 1024),
                "harness_rss_mib": find_harness_rss_mib(),
            }
        )


def run_level(harness: DeepSeekHarness, concurrency: int) -> dict:
    results: list[dict] = []
    result_lock = threading.Lock()

    # 모든 가상 사용자가 가능한 한 동시에 시작하도록 맞춘다.
    barrier = threading.Barrier(concurrency)

    monitor_samples: list[dict] = []
    monitor_stop = threading.Event()

    monitor_thread = threading.Thread(
        target=start_monitor,
        args=(monitor_stop, monitor_samples),
        daemon=True,
    )

    def user_worker(user_index: int) -> None:
        session_id = f"t11-c{concurrency:03d}-u{user_index:03d}"
        session = harness.start_session(session_id)

        barrier.wait()

        for request_index in range(REQUESTS_PER_USER):
            started = time.perf_counter()

            success = False
            error = ""
            finish_reason = None
            response = ""

            try:
                result = session.run(
                    f"T11 load test. user={user_index}, request={request_index}"
                )

                finish_reason = result.finish_reason
                response = result.final_response.strip()

                success = (
                    finish_reason == "completed"
                    and response == EXPECTED_RESPONSE
                )

                if not success:
                    error = (
                        f"unexpected result: "
                        f"finish_reason={finish_reason}, response={response!r}"
                    )

            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            latency_ms = (time.perf_counter() - started) * 1000

            with result_lock:
                results.append(
                    {
                        "concurrency": concurrency,
                        "user": user_index,
                        "request": request_index,
                        "session_id": session_id,
                        "success": success,
                        "latency_ms": latency_ms,
                        "finish_reason": finish_reason or "",
                        "response": response,
                        "error": error,
                    }
                )

    print()
    print(f"=== concurrency={concurrency} START ===")

    monitor_thread.start()

    wall_started = time.perf_counter()

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(user_worker, user_index)
            for user_index in range(concurrency)
        ]

        for future in futures:
            future.result()

    wall_seconds = time.perf_counter() - wall_started

    monitor_stop.set()
    monitor_thread.join(timeout=2)

    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    latencies = [r["latency_ms"] for r in successful]

    total_requests = len(results)
    success_count = len(successful)

    cpu_values = [s["cpu_percent"] for s in monitor_samples]
    memory_values = [s["memory_percent"] for s in monitor_samples]
    rss_values = [s["harness_rss_mib"] for s in monitor_samples]

    summary = {
        "concurrency": concurrency,
        "requests_per_user": REQUESTS_PER_USER,
        "total_requests": total_requests,
        "success": success_count,
        "failed": len(failed),
        "success_rate_percent": (
            success_count / total_requests * 100
            if total_requests
            else 0
        ),
        "wall_seconds": wall_seconds,
        "throughput_rps": (
            total_requests / wall_seconds
            if wall_seconds
            else 0
        ),
        "latency_avg_ms": (
            statistics.mean(latencies)
            if latencies
            else 0
        ),
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "latency_p99_ms": percentile(latencies, 99),
        "latency_max_ms": max(latencies) if latencies else 0,
        "system_cpu_avg_percent": (
            statistics.mean(cpu_values)
            if cpu_values
            else 0
        ),
        "system_cpu_peak_percent": (
            max(cpu_values)
            if cpu_values
            else 0
        ),
        "system_memory_peak_percent": (
            max(memory_values)
            if memory_values
            else 0
        ),
        "harness_rss_peak_mib": (
            max(rss_values)
            if rss_values
            else 0
        ),
    }

    print(
        f"requests={total_requests} "
        f"success={success_count} "
        f"failed={len(failed)}"
    )
    print(
        f"success_rate={summary['success_rate_percent']:.1f}% "
        f"wall={wall_seconds:.3f}s "
        f"throughput={summary['throughput_rps']:.2f} req/s"
    )
    print(
        f"latency avg={summary['latency_avg_ms']:.2f} ms "
        f"p50={summary['latency_p50_ms']:.2f} ms "
        f"p95={summary['latency_p95_ms']:.2f} ms "
        f"p99={summary['latency_p99_ms']:.2f} ms "
        f"max={summary['latency_max_ms']:.2f} ms"
    )
    print(
        f"CPU avg={summary['system_cpu_avg_percent']:.1f}% "
        f"peak={summary['system_cpu_peak_percent']:.1f}%"
    )
    print(
        f"Harness RSS peak="
        f"{summary['harness_rss_peak_mib']:.1f} MiB"
    )

    if failed:
        print("FAILURES:")
        for row in failed[:5]:
            print(
                f"  {row['session_id']} "
                f"request={row['request']} "
                f"{row['error']}"
            )

    return {
        "summary": summary,
        "details": results,
    }


def main() -> None:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    DSH_HOME.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    summaries: list[dict] = []
    details: list[dict] = []

    with DeepSeekHarness(
        dsh_bin=str(DSH_BIN),
        dsh_home=str(DSH_HOME),
        cwd=str(WORKSPACE),
        runtime_cwd=str(ROOT),
        profile="sdk-minimal",
        provider="deepseek-official",
        model="deepseek-v4-flash",
        base_url="http://127.0.0.1:8000/v1",
        api_key="mock-key",
        request_timeout_seconds=60,
    ) as harness:

        print("=== WARM-UP ===")

        warmup = harness.run(
            "T11 warm-up",
            session_id=f"t11-warmup-{timestamp}",
        )

        print(
            "warmup:",
            warmup.finish_reason,
            warmup.final_response.strip(),
        )

        for concurrency in CONCURRENCY_LEVELS:
            output = run_level(harness, concurrency)
            summaries.append(output["summary"])
            details.extend(output["details"])

    summary_path = RESULT_DIR / f"t11_mock_summary_{timestamp}.csv"
    detail_path = RESULT_DIR / f"t11_mock_details_{timestamp}.csv"

    with summary_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(summaries[0].keys()),
        )
        writer.writeheader()
        writer.writerows(summaries)

    with detail_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(details[0].keys()),
        )
        writer.writeheader()
        writer.writerows(details)

    print()
    print("=== T11 MOCK TEST COMPLETE ===")
    print("summary:", summary_path)
    print("details:", detail_path)


if __name__ == "__main__":
    main()
