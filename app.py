import os
import re
import json
import uuid
import base64
import shutil
import subprocess
import tempfile
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string, send_file
from flask_cors import CORS
from google import genai

app = Flask(__name__)
CORS(app)

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
MAX_REPAIR_ATTEMPTS = int(os.getenv("MAX_REPAIR_ATTEMPTS", "4"))
SIM_TIMEOUT_SECONDS = int(os.getenv("SIM_TIMEOUT_SECONDS", "20"))
JOB_ROOT = Path(os.getenv("JOB_ROOT", "/tmp/rtl_ai_jobs"))
JOB_ROOT.mkdir(parents=True, exist_ok=True)

API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY) if API_KEY else None

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
    const d=await r.json();
    if(!r.ok){document.getElementById('status').innerHTML='<p class="bad">'+(d.error||'Build failed')+'</p>';return;}
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
  }catch(e){document.getElementById('status').innerHTML='<p class="bad">'+esc(String(e))+'</p>';}
}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
</script>
</body>
</html>
"""

def require_client():
    if client is None:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

def gemini_text(prompt):
    require_client()
    response = client.models.generate_content(model=MODEL, contents=prompt)
    return (getattr(response, "text", "") or "").strip()

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
    try:
        cp = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=SIM_TIMEOUT_SECONDS)
    except FileNotFoundError:
        return {"pass": False, "stage": "compile", "log": "iverilog is not installed."}
    except subprocess.TimeoutExpired:
        return {"pass": False, "stage": "compile", "log": "Compilation timed out."}

    if cp.returncode != 0:
        return {"pass": False, "stage": "compile", "log": cp.stdout + "\n" + cp.stderr}

    try:
        rp = subprocess.run(["vvp", str(out)], cwd=workdir, capture_output=True,
                            text=True, timeout=SIM_TIMEOUT_SECONDS)
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
    subprocess.run(["dot", "-Tsvg", str(dot_file), "-o", str(path)],
                   capture_output=True, text=True, timeout=10, check=True)

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

    spec = requirement_agent(user_request)
    arch = architecture_agent(spec)
    plan = verification_plan_agent(spec, arch)
    rtl = rtl_agent(spec, arch)
    tb = tb_agent(spec, arch, plan, rtl)

    sim = None
    repair_history = []

    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        sim = simulate(rtl, tb, job_dir)
        repair_history.append({"attempt": attempt, "simulation": sim})

        if sim["pass"]:
            break

        if attempt >= MAX_REPAIR_ATTEMPTS:
            break

        repair = debug_agent(spec, arch, plan, rtl, tb, sim)
        rtl = repair.get("corrected_rtl") or rtl
        tb = repair.get("corrected_testbench") or tb

    critic = verification_critic(spec, arch, plan, rtl, tb, sim)

    dot = diagram_agent(spec, arch)
    svg_path = job_dir / "diagram.svg"
    try:
        render_svg(dot, svg_path)
    except Exception as e:
        svg_path.write_text(
            "<svg xmlns='http://www.w3.org/2000/svg' width='900' height='120'>"
            "<text x='20' y='60'>Diagram rendering failed: "
            + str(e).replace("&","&amp;").replace("<","&lt;")
            + "</text></svg>", encoding="utf-8"
        )

    (job_dir / "design.sv").write_text(rtl, encoding="utf-8")
    (job_dir / "testbench.sv").write_text(tb, encoding="utf-8")
    (job_dir / "spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    (job_dir / "architecture.json").write_text(json.dumps(arch, indent=2), encoding="utf-8")
    (job_dir / "verification_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    (job_dir / "verification_critic.json").write_text(json.dumps(critic, indent=2), encoding="utf-8")
    (job_dir / "repair_history.json").write_text(json.dumps(repair_history, indent=2), encoding="utf-8")
    (job_dir / "simulation.log").write_text(sim.get("log",""), encoding="utf-8")
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
        "repair_history": repair_history
    }

@app.get("/")
def home():
    return render_template_string(HTML)

@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "gemini_configured": client is not None,
        "iverilog": shutil.which("iverilog") is not None,
        "graphviz": shutil.which("dot") is not None
    })

@app.post("/api/build")
def api_build():
    try:
        data = request.get_json(force=True)
        user_request = (data.get("request") or "").strip()
        if not user_request:
            return jsonify({"error": "Missing hardware requirement."}), 400
        if len(user_request) > 12000:
            return jsonify({"error": "Requirement is too long."}), 400
        return jsonify(run_pipeline(user_request))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
