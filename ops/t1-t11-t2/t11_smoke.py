from pathlib import Path
from deepseek_harness import DeepSeekHarness

ROOT = Path(__file__).resolve().parents[2]
DSH_BIN = ROOT / "ops/t1-t11-t2/dsh-source.sh"
DSH_HOME = Path.home() / "dsh-t11-home"
WORKSPACE = ROOT / "ops/t1-t11-t2/workspace"

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
    result = harness.run(
        "T11 smoke test입니다. 짧게 응답하세요.",
        session_id="t11-smoke-001",
    )

print("=== T11 SMOKE RESULT ===")
print("session_id:", result.session_id)
print("finish_reason:", result.finish_reason)
print("response:", result.final_response)
print("events:", len(result.events))
