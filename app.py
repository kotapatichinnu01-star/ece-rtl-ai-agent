import os
import re
import json
import uuid
import base64
import shutil
import subprocess
import tempfile
import time
import random
from contextvars import ContextVar
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string, send_file
from flask_cors import CORS
from google import genai
from google.genai import types

app = Flask(__name__)
CORS(app)

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
FALLBACK_MODELS = [m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash,gemini-3.1-flash-lite").split(",") if m.strip()]
GEMINI_RETRY_ATTEMPTS = max(1, int(os.getenv("GEMINI_RETRY_ATTEMPTS", "3")))
GEMINI_INITIAL_BACKOFF = max(0.1, float(os.getenv("GEMINI_INITIAL_BACKOFF", "2")))
GEMINI_MAX_BACKOFF = max(GEMINI_INITIAL_BACKOFF, float(os.getenv("GEMINI_MAX_BACKOFF", "8")))
GEMINI_429_RETRIES = max(0, int(os.getenv("GEMINI_429_RETRIES", "1")))
GEMINI_REQUEST_TIMEOUT_SECONDS = max(5, float(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "15")))
MAX_PIPELINE_SECONDS = max(20, float(os.getenv("MAX_PIPELINE_SECONDS", "105")))
MAX_REPAIR_ATTEMPTS = int(os.getenv("MAX_REPAIR_ATTEMPTS", "4"))
SIM_TIMEOUT_SECONDS = int(os.getenv("SIM_TIMEOUT_SECONDS", "20"))
JOB_ROOT = Path(os.getenv("JOB_ROOT", "/tmp/rtl_ai_jobs"))
JOB_ROOT.mkdir(parents=True, exist_ok=True)

API_KEY = os.getenv("GEMINI_API_KEY")

if API_KEY:
    # Disable the SDK's own retry loop. We do bounded retries ourselves so that
    # quota errors do not trigger long hidden waits before our fallback logic runs.
    client = genai.Client(
        api_key=API_KEY,
        http_options=types.HttpOptions(
            timeout=int(GEMINI_REQUEST_TIMEOUT_SECONDS * 1000),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
else:
    client = None


HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ECE RTL AI Engineer</title>
<style>
body{font-family:Arial,sans-serif;background:#0b0d10;color:#eee;margin:0}
.wrap{max-width:1200px;margin:auto;padding:28px}
h1{margin-bottom:6px}
.sub{color:#aab1bb}
textarea{width:100%;min-height:150px;background:#15191f;color:#fff;border:1px solid #343b45;border-radius:12px;padding:14px;font-size:16px;box-sizing:border-box}
button{margin-top:12px;background:#d7b35a;border:0;border-radius:10px;padding:12px 20px;font-weight:700;cursor:pointer}
.card{background:#12161b;border:1px solid #29313b;border-radius:14px;padding:18px;margin-top:18px}
pre{white-space:pre-wrap;overflow:auto;background:#090b0e;padding:14px;border-radius:10px}
img{max-width:100%;background:white;border-radius:10px}
.badge{display:inline-block;padding:5px 9px;border-radius:8px;background:#26303a}
.ok{background:#123d2a}.bad{background:#4b1f24}
small{color:#9ca5b1}
</style>
</head>
<body>
<div class="wrap">
<h1>ECE RTL AI Engineer</h1>
<div class="sub">Natural language → architecture → Verilog/SystemVerilog → testbench → simulation → repair → verification → diagram</div>
<div class="card">
<textarea id="req" placeholder="Example: Design a parameterized synchronous FIFO with configurable depth and data width, active-low reset, full/empty flags, and safe read/write behavior."></textarea>
<button onclick="build()">Build & Verify</button>
<div id="status"></div>
</div>
<div id="out"></div>
</div>
<script>
async function build(){
  const req=document.getElementById('req').value.trim();
  if(!req){alert('Enter a hardware requirement.');return;}
  document.getElementById('status').innerHTML='<p>Agent is designing and verifying...</p>';
  document.getElementById('out').innerHTML='';
  try{
    const r=await fetch('/api/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request:req})});
    const raw=await r.text();
    let d=null;
    try{d=raw?JSON.parse(raw):{};}catch(parseError){
      const snippet=raw.replace(/\s+/g,' ').slice(0,220);
      throw new Error('Server returned a non-JSON response (HTTP '+r.status+'). '+snippet);
    }
    if(!r.ok){document.getElementById('status').innerHTML='<p class="bad">'+esc(d.error||'Build failed')+'</p>';return;}
    const sim=d.simulation||{};
    const badge=sim.pass?'<span class="badge ok">SIMULATION PASS</span>':'<span class="badge bad">SIMULATION NOT VERIFIED</span>';
    document.getElementById('status').innerHTML='<p>'+badge+' &nbsp; Job: '+d.job_id+'</p>';
    document.getElementById('out').innerHTML=
      '<div class="card"><h2>Specification</h2><pre>'+esc(JSON.stringify(d.spec,null,2))+'</pre></div>'+
      '<div class="card"><h2>Architecture Plan</h2><pre>'+esc(JSON.stringify(d.architecture,null,2))+'</pre></div>'+
      '<div class="card"><h2>Verification Plan</h2><pre>'+esc(JSON.stringify(d.verification_plan,null,2))+'</pre></div>'+
      '<div class="card"><h2>RTL</h2><pre>'+esc(d.rtl)+'</pre></div>'+
      '<div class="card"><h2>Testbench</h2><pre>'+esc(d.testbench)+'</pre></div>'+
      '<div class="card"><h2>Simulation Log</h2><pre>'+esc(d.simulation.log||'')+'</pre></div>'+
      '<div class="card"><h2>Diagram</h2><img src="/api/jobs/'+d.job_id+'/diagram.svg"><p><a href="/api/jobs/'+d.job_id+'/download">Download project ZIP</a></p></div>';
  }catch(e){document.getElementById('status').innerHTML='<p class="bad">'+esc(e?.message||String(e))+'</p>';}
}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
</script>
</body>
</html>
"""

def require_client():
    if client is None:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

TRANSIENT_GEMINI_CODES = {408, 500, 502, 503, 504}

class GeminiServiceError(RuntimeError):
    """Clean, API-safe Gemini failure that can be returned as JSON."""
    def __init__(self, message, *, code="gemini_error", status=503, retryable=False, details=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.retryable = retryable
        self.details = details or {}

class GeminiQuotaError(GeminiServiceError):
    def __init__(self, models):
        names = ", ".join(models)
        super().__init__(
            f"Gemini API quota is exhausted for the configured models ({names}). "
            "No more automatic retries will be made for this build. Check the Gemini API quota/billing or use a project with available quota.",
            code="gemini_quota_exhausted",
            status=429,
            retryable=False,
            details={"models": models},
        )

class GeminiUnavailableError(GeminiServiceError):
    def __init__(self, message, details=None):
        super().__init__(
            message,
            code="gemini_service_unavailable",
            status=503,
            retryable=True,
            details=details,
        )

class PipelineTimeoutError(GeminiServiceError):
    def __init__(self):
        super().__init__(
            "The hardware build exceeded the server safety time limit. "
            "The request was stopped before the Render worker timeout.",
            code="build_timeout",
            status=504,
            retryable=True,
        )

def _exception_code(exc):
    for attr in ("code", "status_code", "http_status"):
        value = getattr(exc, attr, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    m = re.search(r"\b(400|401|403|404|408|409|429|500|502|503|504)\b", str(exc))
    return int(m.group(1)) if m else None

def _is_quota_exhausted(exc):
    text = str(exc).lower()
    quota_markers = (
        "resource_exhausted",
        "quota exceeded",
        "exceeded your current quota",
        "current quota",
        "generaterequestsperday",
        "perday",
        "free_tier_requests",
        "quota failure",
        "quota_value",
        "daily quota",
    )
    return _exception_code(exc) == 429 and any(marker in text for marker in quota_markers)

def _retry_delay(exc, attempt):
    # For 503/5xx use bounded exponential backoff with jitter.
    delay = min(GEMINI_MAX_BACKOFF, GEMINI_INITIAL_BACKOFF * (2 ** max(0, attempt - 1)))

    # Gemini may include "retry in 19.9s" for rate limiting. Never wait that
    # long inside a synchronous Render request; the caller has a hard deadline.
    m = re.search(r"retry(?: in| after)\s+([0-9]+(?:\.[0-9]+)?)\s*s", str(exc), re.I)
    if m:
        try:
            delay = min(delay, max(0.0, float(m.group(1))))
        except ValueError:
            pass

    jitter = random.uniform(0, min(1.0, delay * 0.25)) if delay > 0 else 0
    return delay + jitter

def _model_sequence():
    models = [MODEL]
    for model in FALLBACK_MODELS:
        if model and model not in models:
            models.append(model)
    return models

def _friendly_gemini_error(exc, model):
    code = _exception_code(exc)
    if _is_quota_exhausted(exc):
        return f"Gemini API quota is exhausted for model '{model}'."
    if code == 429:
        return f"Gemini model '{model}' is temporarily rate-limited (429)."
    if code == 503:
        return f"Gemini model '{model}' is temporarily unavailable (503)."
    if code in (408, 500, 502, 504):
        return f"Gemini model '{model}' returned a temporary service error ({code})."
    if code == 401:
        return "Gemini API authentication failed (401). Check GEMINI_API_KEY in Render."
    if code == 403:
        return "Gemini API access was denied (403). Check the API key/project permissions and model access."
    if code == 404:
        return f"Gemini model '{model}' was not found (404). Check GEMINI_MODEL/fallback model names."
    return f"Gemini request failed for model '{model}': {exc}"

PIPELINE_DEADLINE = ContextVar("pipeline_deadline", default=None)

def _pipeline_deadline():
    return PIPELINE_DEADLINE.get()

def _set_pipeline_deadline(value):
    return PIPELINE_DEADLINE.set(value)

def _reset_pipeline_deadline(token):
    PIPELINE_DEADLINE.reset(token)

def _ensure_pipeline_time():
    deadline = _pipeline_deadline()
    if deadline is not None and time.monotonic() >= deadline:
        raise PipelineTimeoutError()
    return deadline

def gemini_text(prompt):
    require_client()
    deadline = _ensure_pipeline_time()
    models = _model_sequence()
    errors = []
    quota_models = []

    for model_index, model in enumerate(models):
        _ensure_pipeline_time()
        model_saw_quota = False

        # 503/408/5xx: bounded exponential retries.
        transient_attempts = GEMINI_RETRY_ATTEMPTS
        # Ordinary 429 rate limiting gets at most a small bounded retry.
        rate_limit_attempts = GEMINI_429_RETRIES + 1

        attempt = 1
        while attempt <= transient_attempts:
            _ensure_pipeline_time()
            try:
                remaining = None
                deadline = _pipeline_deadline()
                if deadline is not None:
                    remaining = max(1.0, deadline - time.monotonic())
                timeout_ms = int(1000 * min(GEMINI_REQUEST_TIMEOUT_SECONDS, remaining)) if remaining is not None else int(GEMINI_REQUEST_TIMEOUT_SECONDS * 1000)

                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={"http_options": {"timeout": timeout_ms}},
                )
                result = (getattr(response, "text", "") or "").strip()
                if not result:
                    raise RuntimeError(f"Gemini returned an empty response from model '{model}'.")
                return result
            except Exception as exc:
                code = _exception_code(exc)
                errors.append((model, code, exc))

                if _is_quota_exhausted(exc):
                    model_saw_quota = True
                    quota_models.append(model)
                    print(f"[Gemini] quota exhausted for model={model}; switching without retry", flush=True)
                    break

                if code == 429:
                    if attempt >= rate_limit_attempts:
                        print(f"[Gemini] rate limit exhausted for model={model}; switching fallback", flush=True)
                        break
                    delay = min(5.0, _retry_delay(exc, attempt))
                    deadline = _pipeline_deadline()
                    if deadline is not None:
                        delay = min(delay, max(0.0, deadline - time.monotonic() - 1.0))
                    if delay > 0:
                        print(f"[Gemini] rate limited model={model}; retrying once in {delay:.2f}s", flush=True)
                        time.sleep(delay)
                    attempt += 1
                    continue

                if code in TRANSIENT_GEMINI_CODES:
                    if attempt >= transient_attempts:
                        print(f"[Gemini] transient retries exhausted model={model} code={code}; switching fallback", flush=True)
                        break
                    delay = _retry_delay(exc, attempt)
                    deadline = _pipeline_deadline()
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 1.0:
                            raise PipelineTimeoutError()
                        delay = min(delay, remaining - 1.0)
                    print(f"[Gemini] transient error model={model} code={code} attempt={attempt}/{transient_attempts}; retrying in {delay:.2f}s", flush=True)
                    time.sleep(max(0.0, delay))
                    attempt += 1
                    continue

                # Invalid/missing model: move directly to fallback.
                if code == 404:
                    print(f"[Gemini] model '{model}' not found; switching fallback", flush=True)
                    break

                # Authentication/permission and other deterministic failures should
                # fail immediately instead of burning time on retries.
                raise GeminiServiceError(
                    _friendly_gemini_error(exc, model),
                    code="gemini_request_failed",
                    status=code if code in (401, 403) else 502,
                    retryable=False,
                    details={"model": model, "http_code": code},
                ) from exc

        if model_saw_quota:
            continue
        if model_index < len(models) - 1:
            print(f"[Gemini] switching from '{model}' to fallback '{models[model_index + 1]}'", flush=True)

    if quota_models and len(quota_models) == len(models):
        raise GeminiQuotaError(quota_models)

    # If every model failed with temporary errors, return a clean 503.
    temporary = [(m, c, e) for m, c, e in errors if c in TRANSIENT_GEMINI_CODES or c == 429]
    if temporary:
        summary = "; ".join(f"{m}:{c}" for m, c, _ in temporary[-len(models):])
        raise GeminiUnavailableError(
            "All configured Gemini models were temporarily unavailable after bounded retries/fallbacks. Please try again shortly.",
            {"attempts": summary, "models": models},
        )

    raise GeminiServiceError(
        "Gemini could not produce a response from any configured model.",
        code="gemini_request_failed",
        status=502,
        retryable=False,
        details={"models": models},
    )

def extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError("Gemini did not return valid JSON.")
        return json.loads(m.group(0))

def extract_code(text, languages=("verilog","systemverilog","sv")):
    for lang in languages:
        m = re.search(rf"```{lang}\s*(.*?)```", text, re.I|re.S)
        if m:
            return m.group(1).strip()
    m = re.search(r"```[^\n]*\s*(.*?)```", text, re.S)
    if m:
        return m.group(1).strip()
    return text.strip()

def extract_dot(text):
    m = re.search(r"```(?:dot|graphviz)?\s*(.*?)```", text, re.I|re.S)
    if m:
        return m.group(1).strip()
    start = text.find("digraph")
    if start >= 0:
        return text[start:].strip()
    return text.strip()

def safe_hdl(code):
    forbidden = [
        r"\$system\b", r"\$popen\b", r"\$fopen\b", r"\$fwrite\b",
        r"\$readmem", r"\$writemem", r"\bimport\s+\"", r"\bDPI-C\b"
    ]
    return not any(re.search(p, code, re.I) for p in forbidden)

def requirement_agent(user_request):
    prompt = f"""
You are the REQUIREMENT ANALYZER for an autonomous digital-ECE RTL engineering agent.

The user can request ANY digital hardware design, not only textbook examples.
Do not match against a fixed circuit list. Infer the engineering problem from the request.

Return ONLY valid JSON with:
design_name, problem_statement, domain, architecture_style, language,
parameters, ports, clocking, reset, functional_requirements,
corner_cases, assumptions, verification_strategy.

domain may include:
combinational, sequential, fsm, arithmetic, memory, fifo, communication,
processor, bus, dsp, timing, control, fpga, asic, mixed_digital,
or another precise digital-RTL category.

If a detail is missing, choose a reasonable engineering default and put it in assumptions.
Language must be SystemVerilog unless the request explicitly requires Verilog.

USER REQUEST:
{user_request}
"""
    return extract_json(gemini_text(prompt))

def architecture_agent(spec):
    prompt = f"""
You are the HARDWARE ARCHITECT.

Create an implementation-independent architecture plan for this digital RTL requirement.
Think like a senior ECE/VLSI engineer. Do not assume the design is one of a fixed set.

Return ONLY JSON:
{{
  "architecture_summary": "...",
  "blocks": [{{"name":"...", "purpose":"...", "inputs":[...], "outputs":[...]}}],
  "state_elements": [...],
  "data_path": [...],
  "control_path": [...],
  "timing_behavior": [...],
  "corner_case_behavior": [...],
  "implementation_notes": [...],
  "diagram_edges": [{{"from":"...", "to":"...", "label":"..."}}]
}}

SPEC:
{json.dumps(spec, indent=2)}
"""
    return extract_json(gemini_text(prompt))

def verification_plan_agent(spec, arch):
    prompt = f"""
You are the VERIFICATION ARCHITECT.

Design a self-checking simulation strategy for arbitrary digital RTL.
The testbench must independently determine expected behavior; do not simply duplicate
the DUT's internal equations.

Return ONLY JSON:
{{
  "strategy": "exhaustive|directed|random|mixed",
  "test_categories": [...],
  "reset_tests": [...],
  "corner_cases": [...],
  "expected_model": "...",
  "coverage_goals": [...],
  "pass_rule": "The testbench must print TEST_RESULT: PASS only when all checks pass."
}}

SPEC:
{json.dumps(spec, indent=2)}

ARCHITECTURE:
{json.dumps(arch, indent=2)}
"""
    return extract_json(gemini_text(prompt))

def rtl_agent(spec, arch):
    prompt = f"""
You are the RTL ENGINEER.

Generate production-style synthesizable SystemVerilog for the requirement below.
This is a general-purpose agent: infer the correct architecture rather than using a
hard-coded circuit template.

Rules:
- Return ONLY SystemVerilog code, no explanation.
- Use exactly the interface defined in the specification.
- Use synthesizable constructs for the DUT.
- Avoid vendor-specific primitives unless explicitly requested.
- Make reset/clock behavior match the specification.
- Parameterize only when requested or clearly useful.
- Do not include testbench code.
- Do not use system/file/network commands.

SPEC:
{json.dumps(spec, indent=2)}

ARCHITECTURE:
{json.dumps(arch, indent=2)}
"""
    code = extract_code(gemini_text(prompt))
    if not safe_hdl(code):
        raise ValueError("Generated RTL contains a forbidden simulation/system construct.")
    return code

def tb_agent(spec, arch, plan, rtl):
    prompt = f"""
You are the TESTBENCH ENGINEER.

Generate a self-checking SystemVerilog testbench for the DUT below.

Rules:
- Instantiate the DUT exactly according to its module/ports.
- Create clock/reset when required.
- Build an INDEPENDENT expected/reference model from the specification.
- Use exhaustive testing when the input/state space is small enough.
- Otherwise use directed plus randomized tests covering corner cases.
- Check outputs and relevant status flags.
- For sequential designs, test reset, legal transitions, boundary conditions,
  back-to-back operations and relevant latency.
- End with exactly either "TEST_RESULT: PASS" or "TEST_RESULT: FAIL".
- Print useful mismatch details.
- Include $dumpfile/$dumpvars for waveform generation when practical.
- Do not use shell/file/network system commands.
- Return ONLY SystemVerilog code.

SPEC:
{json.dumps(spec, indent=2)}

ARCHITECTURE:
{json.dumps(arch, indent=2)}

VERIFICATION PLAN:
{json.dumps(plan, indent=2)}

DUT RTL:
```systemverilog
{rtl}
```
"""
    code = extract_code(gemini_text(prompt))
    if not safe_hdl(code):
        raise ValueError("Generated testbench contains a forbidden system construct.")
    return code

def simulate(rtl, tb, workdir):
    workdir = Path(workdir)
    dut = workdir / "design.sv"
    bench = workdir / "testbench.sv"
    out = workdir / "sim.out"
    wave = workdir / "wave.vcd"
    dut.write_text(rtl, encoding="utf-8")
    bench.write_text(tb, encoding="utf-8")

    compile_cmd = ["iverilog", "-g2012", "-s", "tb", "-o", str(out), str(dut), str(bench)]
    deadline = _pipeline_deadline()
    compile_timeout = SIM_TIMEOUT_SECONDS
    if deadline is not None:
        compile_timeout = max(0.5, min(SIM_TIMEOUT_SECONDS, deadline - time.monotonic()))
    try:
        cp = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=compile_timeout)
    except FileNotFoundError:
        return {"pass": False, "stage": "compile", "log": "iverilog is not installed."}
    except subprocess.TimeoutExpired:
        return {"pass": False, "stage": "compile", "log": "Compilation timed out."}

    if cp.returncode != 0:
        return {"pass": False, "stage": "compile", "log": cp.stdout + "\n" + cp.stderr}

    deadline = _pipeline_deadline()
    sim_timeout = SIM_TIMEOUT_SECONDS
    if deadline is not None:
        sim_timeout = max(0.5, min(SIM_TIMEOUT_SECONDS, deadline - time.monotonic()))
    try:
        rp = subprocess.run(["vvp", str(out)], cwd=workdir, capture_output=True,
                            text=True, timeout=sim_timeout)
    except subprocess.TimeoutExpired:
        return {"pass": False, "stage": "simulation", "log": "Simulation timed out."}

    log = (rp.stdout or "") + "\n" + (rp.stderr or "")
    passed = rp.returncode == 0 and "TEST_RESULT: PASS" in log and "TEST_RESULT: FAIL" not in log
    return {
        "pass": passed,
        "stage": "simulation",
        "log": log,
        "waveform": str(wave) if wave.exists() else None
    }

def debug_agent(spec, arch, plan, rtl, tb, sim):
    prompt = f"""
You are the DEBUG/REPAIR ENGINEER.

A generated RTL project failed objective compilation or simulation.
Determine whether the fault is in RTL, testbench, interface assumptions, timing/reset,
or the verification model.

Return ONLY JSON:
{{
  "diagnosis": "...",
  "target": "rtl|testbench|both",
  "corrected_rtl": "...",
  "corrected_testbench": "..."
}}

Keep unchanged code unchanged where possible.
Do not weaken tests just to make them pass.
Do not remove checks to hide a failure.
The final testbench must remain genuinely self-checking.

SPEC:
{json.dumps(spec, indent=2)}

ARCHITECTURE:
{json.dumps(arch, indent=2)}

VERIFICATION PLAN:
{json.dumps(plan, indent=2)}

RTL:
```systemverilog
{rtl}
```

TESTBENCH:
```systemverilog
{tb}
```

SIMULATION RESULT:
{json.dumps(sim, indent=2)}
"""
    result = extract_json(gemini_text(prompt))
    if result.get("corrected_rtl") and not safe_hdl(result["corrected_rtl"]):
        raise ValueError("Repair agent produced unsafe RTL.")
    if result.get("corrected_testbench") and not safe_hdl(result["corrected_testbench"]):
        raise ValueError("Repair agent produced unsafe testbench.")
    return result

def verification_critic(spec, arch, plan, rtl, tb, sim):
    prompt = f"""
You are an INDEPENDENT VERIFICATION CRITIC.

Review the generated project. Do not override objective simulator results.
Identify weak verification such as a TB that merely repeats DUT logic, missing
corner cases, missing reset testing, wrong latency assumptions, or tests that
can pass without exercising the design.

Return ONLY JSON:
{{
  "simulation_pass": {str(bool(sim.get("pass"))).lower()},
  "verification_quality": "strong|moderate|weak|failed",
  "issues": [...],
  "recommendation": "accept|regenerate_testbench|repair_rtl_and_testbench"
}}

SPEC:
{json.dumps(spec, indent=2)}
ARCHITECTURE:
{json.dumps(arch, indent=2)}
PLAN:
{json.dumps(plan, indent=2)}
RTL:
{rtl}
TESTBENCH:
{tb}
SIMULATION:
{json.dumps(sim, indent=2)}
"""
    return extract_json(gemini_text(prompt))

def diagram_agent(spec, arch):
    prompt = f"""
Create a Graphviz DOT architecture diagram for the digital design.
Use ONLY blocks and connections supported by the architecture plan.
Do not invent gates or internal signals that are not supported.
Keep it readable.

Return ONLY DOT beginning with digraph.

SPEC:
{json.dumps(spec, indent=2)}

ARCHITECTURE:
{json.dumps(arch, indent=2)}
"""
    dot = extract_dot(gemini_text(prompt))
    if not dot.startswith("digraph"):
        raise ValueError("Diagram agent did not return Graphviz DOT.")
    return dot

def render_svg(dot, path):
    path = Path(path)
    dot_file = path.with_suffix(".dot")
    dot_file.write_text(dot, encoding="utf-8")
    timeout = 10
    deadline = _pipeline_deadline()
    if deadline is not None:
        timeout = max(0.5, min(timeout, deadline - time.monotonic()))
    subprocess.run(["dot", "-Tsvg", str(dot_file), "-o", str(path)],
                   capture_output=True, text=True, timeout=timeout, check=True)

def make_zip(job_dir):
    job_dir = Path(job_dir)
    zip_path = job_dir / "rtl_ai_project.zip"
    with __import__("zipfile").ZipFile(zip_path, "w") as z:
        for p in job_dir.iterdir():
            if p.is_file() and p.name != zip_path.name:
                z.write(p, arcname=p.name)
    return zip_path

def run_pipeline(user_request):
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOB_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    deadline_token = _set_pipeline_deadline(time.monotonic() + MAX_PIPELINE_SECONDS)

    try:
        _ensure_pipeline_time()
        spec = requirement_agent(user_request)
        _ensure_pipeline_time()
        arch = architecture_agent(spec)
        _ensure_pipeline_time()
        plan = verification_plan_agent(spec, arch)
        _ensure_pipeline_time()
        rtl = rtl_agent(spec, arch)
        _ensure_pipeline_time()
        tb = tb_agent(spec, arch, plan, rtl)

        sim = None
        repair_history = []

        for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
            _ensure_pipeline_time()
            sim = simulate(rtl, tb, job_dir)
            repair_history.append({"attempt": attempt, "simulation": sim})

            if sim["pass"]:
                break

            if attempt >= MAX_REPAIR_ATTEMPTS:
                break

            _ensure_pipeline_time()
            repair = debug_agent(spec, arch, plan, rtl, tb, sim)
            rtl = repair.get("corrected_rtl") or rtl
            tb = repair.get("corrected_testbench") or tb

        _ensure_pipeline_time()
        critic = verification_critic(spec, arch, plan, rtl, tb, sim)

        _ensure_pipeline_time()
        dot = diagram_agent(spec, arch)
        svg_path = job_dir / "diagram.svg"
        try:
            render_svg(dot, svg_path)
        except Exception as e:
            svg_path.write_text(
                "<svg xmlns='http://www.w3.org/2000/svg' width='900' height='120'>"
                "<text x='20' y='60'>Diagram rendering failed: "
                + str(e).replace("&", "&amp;").replace("<", "&lt;")
                + "</text></svg>", encoding="utf-8"
            )

        (job_dir / "design.sv").write_text(rtl, encoding="utf-8")
        (job_dir / "testbench.sv").write_text(tb, encoding="utf-8")
        (job_dir / "spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
        (job_dir / "architecture.json").write_text(json.dumps(arch, indent=2), encoding="utf-8")
        (job_dir / "verification_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
        (job_dir / "verification_critic.json").write_text(json.dumps(critic, indent=2), encoding="utf-8")
        (job_dir / "repair_history.json").write_text(json.dumps(repair_history, indent=2), encoding="utf-8")
        (job_dir / "simulation.log").write_text(sim.get("log", ""), encoding="utf-8")
        make_zip(job_dir)

        return {
            "job_id": job_id,
            "spec": spec,
            "architecture": arch,
            "verification_plan": plan,
            "rtl": rtl,
            "testbench": tb,
            "simulation": sim,
            "verification_critic": critic,
            "repair_history": repair_history,
        }
    finally:
        _reset_pipeline_deadline(deadline_token)

@app.get("/")
def home():
    return render_template_string(HTML)

@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "gemini_configured": client is not None,
        "gemini_model": MODEL,
        "gemini_fallback_models": FALLBACK_MODELS,
        "gemini_retry_attempts": GEMINI_RETRY_ATTEMPTS,
        "gemini_429_retries": GEMINI_429_RETRIES,
        "gemini_request_timeout_seconds": GEMINI_REQUEST_TIMEOUT_SECONDS,
        "max_pipeline_seconds": MAX_PIPELINE_SECONDS,
        "max_repair_attempts": MAX_REPAIR_ATTEMPTS,
        "iverilog": shutil.which("iverilog") is not None,
        "graphviz": shutil.which("dot") is not None,
    })

@app.post("/api/build")
def api_build():
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({
                "error": "Request body must be JSON.",
                "error_type": "invalid_request",
                "retryable": False,
            }), 400

        user_request = (data.get("request") or "").strip()
        if not user_request:
            return jsonify({
                "error": "Missing hardware requirement.",
                "error_type": "invalid_request",
                "retryable": False,
            }), 400
        if len(user_request) > 12000:
            return jsonify({
                "error": "Requirement is too long. Keep it under 12,000 characters.",
                "error_type": "invalid_request",
                "retryable": False,
            }), 400

        return jsonify(run_pipeline(user_request)), 200

    except GeminiServiceError as e:
        app.logger.warning("Build stopped: %s", e)
        return jsonify({
            "error": str(e),
            "error_type": e.code,
            "retryable": e.retryable,
            "details": e.details,
        }), e.status

    except ValueError as e:
        app.logger.warning("Build validation failed: %s", e)
        return jsonify({
            "error": str(e),
            "error_type": "validation_error",
            "retryable": False,
        }), 422

    except Exception as e:
        app.logger.exception("Build failed")
        return jsonify({
            "error": "The hardware build failed unexpectedly.",
            "details": str(e),
            "error_type": "internal_error",
            "retryable": False,
        }), 500

@app.get("/api/jobs/<job_id>/diagram.svg")
def job_diagram(job_id):
    path = JOB_ROOT / job_id / "diagram.svg"
    if not path.exists():
        return "Not found", 404
    return send_file(path, mimetype="image/svg+xml")

@app.get("/api/jobs/<job_id>/download")
def job_download(job_id):
    path = JOB_ROOT / job_id / "rtl_ai_project.zip"
    if not path.exists():
        return "Not found", 404
    return send_file(path, as_attachment=True, download_name="rtl_ai_project.zip")

if __name__ == "__main__":
    port = int(os.getenv("PORT", "7860"))
    app.run(host="0.0.0.0", port=port, debug=False)
