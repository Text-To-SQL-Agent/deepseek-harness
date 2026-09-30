from pathlib import Path
from datetime import datetime

from deepseek_harness import DeepSeekHarness

ROOT = Path(__file__).resolve().parents[2]
DSH_BIN = ROOT / "ops/t1-t11-t2/dsh-source.sh"
DSH_HOME = Path.home() / "dsh-t11-real-home"
WORKSPACE = ROOT / "ops/t1-t11-t2/workspace"

DSH_HOME.mkdir(parents=True, exist_ok=True)

session_id = f"t11-real-smoke-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

with DeepSeekHarness(
    dsh_bin=str(DSH_BIN),
    dsh_home=str(DSH_HOME),
    cwd=str(WORKSPACE),
    runtime_cwd=str(ROOT),
    profile="sdk-minimal",
    provider="deepseek-official",
    model="deepseek/deepseek-v4-flash-0731",
    max_tokens=64,
    request_timeout_seconds=120,
) as harness:
    result = harness.run(
        "Reply with exactly: T11 REAL OK",
        session_id=session_id,
    )

print("=== T11 REAL SMOKE RESULT ===")
print("session_id:", result.session_id)
print("finish_reason:", result.finish_reason)
print("response:", result.final_response)
print("events:", len(result.events))
