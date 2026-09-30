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

DSH_HOME = Path.home() / "dsh-t2-home"
WORKSPACE = ROOT / "ops/t1-t11-t2/workspace"
RESULT_DIR = ROOT / "ops/t1-t11-t2/results"

TARGET_SESSION_COUNTS = [100, 500, 1000]

# T11怨?寃뱀튂吏 ?딅룄濡??숈떆?깆? 怨좎젙
CONCURRENCY = 10

EXPECTED_RESPONSE = "T2 mock response OK"


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


def directory_size_bytes(path: Path) -> int:
    total = 0

    if not path.exists():
        return 0

    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            pass

    return total


def count_files(path: Path) -> int:
    if not path.exists():
        return 0

    return sum(
        1
        for item in path.rglob("*")
        if item.is_file()
    )


def find_harness_rss_mib() -> float:
    """
    sdk-minimal Harness Runtime怨??먯떇 ?꾨줈?몄뒪??RSS ?⑷퀎.
    Mock LLM ?꾨줈?몄뒪???쒖쇅?쒕떎.
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


def monitor_resources(
    stop_event: threading.Event,
    samples: list[dict],
) -> None:
    psutil.cpu_percent(interval=None)

    while not stop_event.is_set():
        cpu = psutil.cpu_percent(interval=0.2)
        memory = psutil.virtual_memory()

        samples.append(
            {
                "cpu_percent": cpu,
                "system_memory_percent": memory.percent,
                "system_available_mib": (
                    memory.available / (1024 * 1024)
                ),
                "harness_rss_mib": find_harness_rss_mib(),
            }
        )


def run_session(
    harness: DeepSeekHarness,
    session_number: int,
) -> dict:
    session_id = f"t2-scale-{session_number:05d}"

    started = time.perf_counter()

    success = False
    exact_match = False
    finish_reason = ""
    response = ""
    error = ""

    try:
        result = harness.run(
            "T2 scale test. Reply with exactly: T2 mock response OK",
            session_id=session_id,
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

    latency_ms = (time.perf_counter() - started) * 1000

    return {
        "session_number": session_number,
        "session_id": session_id,
        "success": success,
        "exact_match": exact_match,
        "latency_ms": latency_ms,
        "finish_reason": finish_reason,
        "response": response,
        "error": error,
    }


def run_stage(
    harness: DeepSeekHarness,
    start_session: int,
    end_session: int,
) -> tuple[dict, list[dict]]:

    new_sessions = end_session - start_session

    print()
    print(
        f"=== T2 SCALE {start_session} -> "
        f"{end_session} sessions START ==="
    )
    print(
        f"new_sessions={new_sessions}, "
        f"concurrency={CONCURRENCY}"
    )

    resource_samples: list[dict] = []
    stop_event = threading.Event()

    monitor_thread = threading.Thread(
        target=monitor_resources,
        args=(stop_event, resource_samples),
        daemon=True,
    )

    before_rss = find_harness_rss_mib()
    before_home_bytes = directory_size_bytes(DSH_HOME)

    monitor_thread.start()

    stage_started = time.perf_counter()

    rows: list[dict] = []

    with ThreadPoolExecutor(
        max_workers=CONCURRENCY
    ) as executor:

        futures = [
            executor.submit(
                run_session,
                harness,
                session_number,
            )
            for session_number in range(
                start_session + 1,
                end_session + 1,
            )
        ]

        for future in futures:
            rows.append(future.result())

    wall_seconds = time.perf_counter() - stage_started

    stop_event.set()
    monitor_thread.join(timeout=2)

    # ?붿껌??紐⑤몢 ?앸궃 ??議곌툑 湲곕떎?ㅼ꽌
    # steady-state 硫붾え由щ룄 痢≪젙
    time.sleep(2)

    after_rss = find_harness_rss_mib()
    after_home_bytes = directory_size_bytes(DSH_HOME)
    home_files = count_files(DSH_HOME)

    successful = [
        row for row in rows
        if row["success"]
    ]

    failures = [
        row for row in rows
        if not row["success"]
    ]

    latencies = [
        row["latency_ms"]
        for row in successful
    ]

    cpu_values = [
        sample["cpu_percent"]
        for sample in resource_samples
    ]

    rss_values = [
        sample["harness_rss_mib"]
        for sample in resource_samples
    ]

    system_memory_values = [
        sample["system_memory_percent"]
        for sample in resource_samples
    ]

    total = len(rows)
    success_count = len(successful)

    summary = {
        "target_sessions": end_session,
        "new_sessions_this_stage": new_sessions,
        "concurrency": CONCURRENCY,

        "requests": total,
        "success": success_count,
        "failed": len(failures),
        "success_rate_percent": (
            success_count / total * 100
            if total
            else 0
        ),

        "exact_match": sum(
            row["exact_match"]
            for row in rows
        ),

        "wall_seconds": wall_seconds,

        "throughput_rps": (
            total / wall_seconds
            if wall_seconds
            else 0
        ),

        "latency_avg_ms": (
            statistics.mean(latencies)
            if latencies
            else 0
        ),

        "latency_p50_ms": percentile(
            latencies, 50
        ),

        "latency_p95_ms": percentile(
            latencies, 95
        ),

        "latency_p99_ms": percentile(
            latencies, 99
        ),

        "latency_max_ms": (
            max(latencies)
            if latencies
            else 0
        ),

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
            max(system_memory_values)
            if system_memory_values
            else 0
        ),

        "harness_rss_before_mib": before_rss,

        "harness_rss_peak_mib": (
            max(rss_values)
            if rss_values
            else after_rss
        ),

        "harness_rss_after_mib": after_rss,

        "harness_rss_growth_mib": (
            after_rss - before_rss
        ),

        "dsh_home_before_mib": (
            before_home_bytes / (1024 * 1024)
        ),

        "dsh_home_after_mib": (
            after_home_bytes / (1024 * 1024)
        ),

        "dsh_home_growth_mib": (
            (after_home_bytes - before_home_bytes)
            / (1024 * 1024)
        ),

        "dsh_home_file_count": home_files,
    }

    print(
        f"requests={total} "
        f"success={success_count} "
        f"failed={len(failures)}"
    )

    print(
        f"success_rate="
        f"{summary['success_rate_percent']:.1f}% "
        f"exact={summary['exact_match']}/{total}"
    )

    print(
        f"wall={wall_seconds:.2f}s "
        f"throughput="
        f"{summary['throughput_rps']:.2f} req/s"
    )

    print(
        f"latency avg="
        f"{summary['latency_avg_ms']:.2f} ms "
        f"p50={summary['latency_p50_ms']:.2f} ms "
        f"p95={summary['latency_p95_ms']:.2f} ms "
        f"p99={summary['latency_p99_ms']:.2f} ms "
        f"max={summary['latency_max_ms']:.2f} ms"
    )

    print(
        f"Harness RSS: "
        f"before={before_rss:.1f} MiB "
        f"peak={summary['harness_rss_peak_mib']:.1f} MiB "
        f"after={after_rss:.1f} MiB "
        f"growth={summary['harness_rss_growth_mib']:.1f} MiB"
    )

    print(
        f"DSH_HOME: "
        f"{summary['dsh_home_after_mib']:.2f} MiB "
        f"files={home_files}"
    )

    if failures:
        print("FAILURES:")

        for row in failures[:10]:
            print(
                row["session_id"],
                row["error"],
            )

    return summary, rows


def main() -> None:
    RESULT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    WORKSPACE.mkdir(
        parents=True,
        exist_ok=True,
    )

    DSH_HOME.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    summaries: list[dict] = []
    details: list[dict] = []

    with DeepSeekHarness(
        dsh_bin=str(DSH_BIN),
        dsh_home=str(DSH_HOME),
        cwd=str(WORKSPACE),

        # dsh-source.sh媛 repo ?곷?寃쎈줈瑜??ъ슜?섎?濡?        # Runtime? repo root?먯꽌 ?ㅽ뻾
        runtime_cwd=str(ROOT),

        profile="sdk-minimal",

        provider="deepseek-official",
        model="deepseek-v4-flash",

        base_url="http://127.0.0.1:8000/v1",
        api_key="mock-key",

        max_tokens=64,
        request_timeout_seconds=60,
    ) as harness:

        print("=== T2 WARM-UP ===")

        warmup = harness.run(
            "Reply with exactly: T2 mock response OK",
            session_id=f"t2-warmup-{timestamp}",
        )

        print(
            "warmup:",
            warmup.finish_reason,
            warmup.final_response.strip(),
        )

        previous_target = 0

        for target in TARGET_SESSION_COUNTS:
            summary, rows = run_stage(
                harness,
                previous_target,
                target,
            )

            summaries.append(summary)
            details.extend(rows)

            previous_target = target

    summary_path = (
        RESULT_DIR
        / f"t2_scale_summary_{timestamp}.csv"
    )

    detail_path = (
        RESULT_DIR
        / f"t2_scale_details_{timestamp}.csv"
    )

    with summary_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=list(
                summaries[0].keys()
            ),
        )

        writer.writeheader()
        writer.writerows(summaries)

    with detail_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=list(
                details[0].keys()
            ),
        )

        writer.writeheader()
        writer.writerows(details)

    print()
    print("=== T2 SCALE TEST COMPLETE ===")
    print("summary:", summary_path)
    print("details:", detail_path)


if __name__ == "__main__":
    main()

