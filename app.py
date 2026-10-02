import os
import re
import json
import html
import uuid
import time
import shutil
import subprocess
from pathlib import Path

from flask import Flask, request, jsonify, render_template_string, send_file
from flask_cors import CORS
from google import genai
from google.genai import types

app = Flask(__name__)
CORS(app)

# ============================================================
# RTL FORGE — GENERAL ECE DIGITAL HARDWARE WORKBENCH
# ============================================================
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
FALLBACK_MODELS = [
    x.strip() for x in os.getenv(
        "GEMINI_FALLBACK_MODELS",
        "gemini-3.5-flash-lite,gemini-3.1-flash-lite"
    ).split(",") if x.strip()
]
REQUEST_TIMEOUT = max(10, min(30, float(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "15"))))
MAX_REPAIR_ATTEMPTS = max(0, min(1, int(os.getenv("MAX_REPAIR_ATTEMPTS", "1"))))
SIM_TIMEOUT = max(3, min(15, int(os.getenv("SIM_TIMEOUT_SECONDS", "10"))))
MAX_BUILD_SECONDS = max(45, min(90, int(os.getenv("MAX_BUILD_SECONDS", "75"))))
DIAGRAM_TIMEOUT = max(2, min(15, int(os.getenv("DIAGRAM_TIMEOUT_SECONDS", "8"))))
API_KEY = os.getenv("GEMINI_API_KEY")
JOB_ROOT = Path(os.getenv("JOB_ROOT", "/tmp/rtl_ai_jobs"))
JOB_ROOT.mkdir(parents=True, exist_ok=True)

client = None
if API_KEY:
    try:
        client = genai.Client(
            api_key=API_KEY,
            http_options=types.HttpOptions(
                timeout=int(REQUEST_TIMEOUT * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
    except Exception:
        client = None

# ============================================================
# FRONTEND
# ============================================================
HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#05090b">
<title>RTL Forge — ECE Hardware Workbench</title>
<style>
:root{
 --bg:#040709;--bg2:#071015;--panel:#091116;--panel2:#0b151a;--line:#193039;
 --line2:#29434d;--text:#e8f3f5;--muted:#78939d;--dim:#4e6973;
 --cyan:#57e6ff;--green:#61e5a4;--amber:#efc56f;--red:#ff7084;--violet:#a79aff;
 --shadow:0 35px 100px rgba(0,0,0,.48)
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:radial-gradient(circle at 50% -10%,rgba(87,230,255,.07),transparent 30%),radial-gradient(circle at 90% 48%,rgba(167,154,255,.055),transparent 25%),var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow-x:hidden}
body:before{content:"";position:fixed;inset:0;z-index:-3;pointer-events:none;background-image:linear-gradient(rgba(120,170,185,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(120,170,185,.035) 1px,transparent 1px);background-size:48px 48px;mask-image:linear-gradient(#000,transparent 85%)}
body:after{content:"";position:fixed;inset:0;z-index:50;pointer-events:none;background:linear-gradient(transparent 0%,rgba(87,230,255,.018) 50%,transparent 100%);height:12%;animation:scan 11s linear infinite}
button,textarea{font:inherit}.shell{width:min(1380px,calc(100% - 28px));margin:auto;padding-bottom:100px}

/* NAV */
.nav{height:58px;margin-top:12px;position:sticky;top:10px;z-index:40;display:flex;align-items:center;justify-content:space-between;padding:0 13px;border:1px solid var(--line);border-radius:12px;background:rgba(4,8,10,.78);backdrop-filter:blur(20px);box-shadow:0 15px 50px rgba(0,0,0,.28)}
.brand{display:flex;gap:10px;align-items:center}.brandmark{width:32px;height:32px;border:1px solid rgba(87,230,255,.4);border-radius:8px;display:grid;place-items:center;color:var(--cyan);font:900 9px ui-monospace,monospace;background:#091a20;box-shadow:inset 0 0 15px rgba(87,230,255,.08)}.brand b{display:block;font-size:11px;letter-spacing:.08em}.brand small{display:block;color:#58727b;font:700 7px ui-monospace,monospace;letter-spacing:.14em;margin-top:2px}.navRight{display:flex;align-items:center;gap:8px;color:#607a83;font:800 8px ui-monospace,monospace;letter-spacing:.12em}.dotLive{width:6px;height:6px;border-radius:50%;background:var(--green);box-shadow:0 0 12px var(--green);animation:pulse 1.7s infinite}

/* HERO */
.hero{min-height:650px;display:grid;place-items:center;text-align:center;position:relative;overflow:hidden}.heroGrid{position:absolute;width:620px;height:620px;border:1px solid rgba(87,230,255,.06);border-radius:50%;box-shadow:0 0 0 90px rgba(87,230,255,.012),0 0 0 180px rgba(87,230,255,.008);animation:rotate 24s linear infinite}.heroGrid:before,.heroGrid:after{content:"";position:absolute;inset:18%;border:1px dashed rgba(87,230,255,.08);border-radius:50%;animation:rotateReverse 18s linear infinite}.heroGrid:after{inset:37%;border-style:solid}.heroCore{position:absolute;width:95px;height:95px;border:1px solid rgba(87,230,255,.25);transform:rotate(45deg);box-shadow:0 0 50px rgba(87,230,255,.07);animation:core 4s ease-in-out infinite}.heroContent{position:relative;z-index:2;max-width:920px;padding-top:50px}.eyebrow{display:inline-flex;align-items:center;gap:8px;padding:7px 10px;border:1px solid #20404a;border-radius:999px;background:rgba(8,25,31,.65);color:#a3d8e0;font:900 8px ui-monospace,monospace;letter-spacing:.16em}.hero h1{margin:25px 0 18px;font-size:clamp(54px,8vw,106px);line-height:.86;letter-spacing:-.075em}.hero h1 em{font-style:normal;background:linear-gradient(100deg,#fff 15%,#67eaff 54%,#a79aff 90%);color:transparent;background-clip:text;-webkit-background-clip:text}.hero p{max-width:720px;margin:auto;color:#8099a2;font-size:14px;line-height:1.8}.heroTags{display:flex;justify-content:center;gap:7px;flex-wrap:wrap;margin-top:22px}.tag{padding:6px 9px;border:1px solid #1b3038;border-radius:6px;color:#637d86;background:#071014;font:800 8px ui-monospace,monospace}.scrollCue{margin-top:55px;color:#4d6871;font:900 8px ui-monospace,monospace;letter-spacing:.2em}.scrollCue i{display:block;width:7px;height:12px;border-right:1px solid var(--cyan);border-bottom:1px solid var(--cyan);transform:rotate(45deg);margin:12px auto;animation:bob 1.5s infinite}

/* ENGINEERING IMAGE FILM */
.section{margin-top:30px}.sectionHead{display:flex;justify-content:space-between;align-items:end;gap:30px;margin:0 2px 16px}.kicker{color:#5b7780;font:900 8px ui-monospace,monospace;letter-spacing:.17em}.sectionHead h2{font-size:clamp(27px,4vw,48px);letter-spacing:-.055em;margin:7px 0 0}.sectionHead p{max-width:480px;color:#718991;font-size:12px;line-height:1.7;margin:0}.film{display:grid;grid-template-columns:1.15fr .9fr 1fr;gap:10px}.shot{height:310px;position:relative;overflow:hidden;border:1px solid #1a3038;border-radius:14px;background:#080e12}.shot.large{height:380px}.shot img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:saturate(.55) contrast(1.2) brightness(.62);transform:scale(1.02);transition:1s cubic-bezier(.2,.7,.2,1)}.shot:hover img{transform:scale(1.1);filter:saturate(.9) contrast(1.12) brightness(.8)}.shot:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,transparent 40%,rgba(2,5,7,.92));pointer-events:none}.shot label{position:absolute;z-index:2;left:13px;right:13px;bottom:12px;display:flex;justify-content:space-between;color:#d7eef2;font:900 8px ui-monospace,monospace;letter-spacing:.1em}.shot label b{color:var(--cyan)}

/* SCHEMATIC STRIP */
.schematicGrid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.schematic{border:1px solid #193039;border-radius:14px;background:linear-gradient(145deg,#091217,#05090b);padding:13px;overflow:hidden;transition:.35s;box-shadow:0 18px 50px rgba(0,0,0,.18)}.schematic:hover{transform:translateY(-5px);border-color:#31515c}.schematicTop{display:flex;justify-content:space-between;color:#59757e;font:800 7px ui-monospace,monospace;letter-spacing:.13em}.schematicTop b{color:#a3cbd3}.schematic svg{width:100%;height:auto;margin-top:10px;display:block;color:#60818a;transition:.4s}.schematic:hover svg{color:#8fd9e5}

/* WORKBENCH */
.workbench{margin-top:42px;border:1px solid #1b333c;border-radius:18px;background:linear-gradient(145deg,rgba(9,17,22,.98),rgba(4,8,10,.98));box-shadow:var(--shadow);overflow:hidden;position:relative}.workbench:before{content:"";position:absolute;top:0;left:8%;right:8%;height:1px;background:linear-gradient(90deg,transparent,var(--cyan),transparent);opacity:.7}.workTop{padding:19px 20px;border-bottom:1px solid #172b33;display:flex;justify-content:space-between;gap:15px}.workTop h2{font-size:17px;margin:5px 0 0;letter-spacing:-.025em}.mode{border:1px solid #223a43;border-radius:6px;padding:6px 8px;color:#66808a;font:800 7px ui-monospace,monospace;height:max-content}.workBody{padding:18px}.editor{border:1px solid #203740;border-radius:12px;overflow:hidden;background:#04080a}.editorBar{height:32px;padding:0 11px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #15272e;color:#526e77;font:800 7px ui-monospace,monospace}.traffic{display:flex;gap:4px}.traffic i{width:5px;height:5px;border-radius:50%;background:#2c4048}.editor textarea{width:100%;height:175px;min-height:130px;max-height:430px;resize:vertical;border:0;outline:0;background:transparent;color:#d8eaee;padding:17px;font:12px/1.75 ui-monospace,SFMono-Regular,Consolas,monospace}.editor textarea::placeholder{color:#3d5861}.editorFoot{display:flex;justify-content:space-between;border-top:1px solid #15272e;padding:7px 10px;color:#48636c;font:800 7px ui-monospace,monospace}.examples{display:flex;gap:6px;flex-wrap:wrap;margin:11px 0}.chip{border:1px solid #1b3038;border-radius:6px;background:#071014;color:#718991;padding:7px 9px;cursor:pointer;font:800 7px ui-monospace,monospace;transition:.2s}.chip:hover{transform:translateY(-2px);border-color:#3b626e;color:#b9f2f8}.controls{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:13px}.hint{color:#4e6871;font:800 8px ui-monospace,monospace}.generate{border:1px solid rgba(87,230,255,.45);border-radius:8px;background:#0b222a;color:#d1faff;padding:11px 15px;cursor:pointer;font-weight:950;font-size:10px;box-shadow:0 0 30px rgba(87,230,255,.05);transition:.25s}.generate:hover{transform:translateY(-2px);border-color:var(--cyan);box-shadow:0 0 35px rgba(87,230,255,.11)}.generate:disabled{opacity:.5;cursor:not-allowed;transform:none}.status{min-height:43px;padding-top:12px}.notice{padding:10px 12px;border:1px solid #1c343d;border-radius:8px;color:#89a1a9;background:#071014;font-size:10px}.notice.ok{border-color:rgba(97,229,164,.3);color:#7be7ae;background:rgba(97,229,164,.04)}.notice.err{border-color:rgba(255,112,132,.3);color:#ff93a3;background:rgba(255,112,132,.04)}

/* LIVE STAGE RAIL */
.stageRail{display:grid;grid-template-columns:repeat(6,1fr);gap:5px;margin-top:7px}.stage{position:relative;border:1px solid #172a32;background:#060c0f;border-radius:7px;padding:10px 6px;text-align:center;color:#435d66;font:900 7px ui-monospace,monospace;letter-spacing:.1em;transition:.3s}.stage span{display:block;font-size:6px;color:#334c55;margin-bottom:4px}.stage.active{color:#b9f5fb;border-color:rgba(87,230,255,.55);background:rgba(87,230,255,.035);box-shadow:0 0 22px rgba(87,230,255,.06)}.stage.active:after{content:"";position:absolute;left:12%;right:12%;bottom:0;height:2px;background:var(--cyan);box-shadow:0 0 10px var(--cyan);animation:progress 1.2s infinite}.stage.done{color:#76dca5;border-color:rgba(97,229,164,.28);background:rgba(97,229,164,.025)}

/* RESULT */
.result{margin-top:20px;border:1px solid #1b343d;border-radius:18px;background:#060b0e;overflow:hidden;animation:rise .55s both}.resultHeader{padding:17px 19px;border-bottom:1px solid #172b33;display:flex;justify-content:space-between;gap:15px;align-items:center;flex-wrap:wrap}.resultIdentity{display:flex;gap:10px;align-items:center}.statusIcon{width:31px;height:31px;border-radius:8px;display:grid;place-items:center;border:1px solid rgba(87,230,255,.25);color:var(--cyan);background:#08161b}.statusIcon.pass{color:var(--green);border-color:rgba(97,229,164,.3);background:rgba(97,229,164,.04)}.statusIcon.fail{color:var(--red);border-color:rgba(255,112,132,.3);background:rgba(255,112,132,.04)}.resultIdentity b{font-size:13px}.resultIdentity small{display:block;color:#59727b;font-size:8px;margin-top:3px}.actions{display:flex;gap:5px;flex-wrap:wrap}.smallbtn{border:1px solid #263d46;border-radius:6px;background:#081115;color:#9bb0b7;padding:7px 9px;cursor:pointer;font:900 7px ui-monospace,monospace}.smallbtn:hover{color:#e1f2f5;border-color:#4a6873}.artifactGrid{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:12px}.artifact{border:1px solid #172d35;border-radius:11px;background:#04080a;overflow:hidden;min-width:0}.artifact.full{grid-column:1/-1}.artifactHead{height:31px;display:flex;align-items:center;justify-content:space-between;padding:0 10px;border-bottom:1px solid #14272e;color:#56717a;font:900 7px ui-monospace,monospace}.artifactHead b{color:#86a8b1}.codeWrap{position:relative;overflow:auto;max-height:530px}.codeWrap pre{margin:0;padding:15px 17px;white-space:pre-wrap;overflow-wrap:anywhere;word-break:normal;color:#d8e9ed;font:12px/1.7 ui-monospace,SFMono-Regular,Consolas,monospace;tab-size:4;min-width:0}.codeWrap pre::selection{background:rgba(87,230,255,.18)}.artifactHint{padding:10px 11px;color:#5c757e;font-size:9px;line-height:1.6;border-bottom:1px solid #14272e}.verifyBox{margin:0 12px 12px;padding:11px;border:1px solid rgba(97,229,164,.25);border-radius:8px;background:rgba(97,229,164,.035);color:#78929b;font-size:9px;line-height:1.65}.verifyBox strong{color:#76e5a8}.verifyBox.fail{border-color:rgba(255,112,132,.28);background:rgba(255,112,132,.035)}.verifyBox.fail strong{color:#ff8b9b}.visualBox{padding:11px;overflow:auto;min-height:190px}.visualBox svg{display:block;width:100%;height:auto;min-width:620px}.emptyVisual{min-height:180px;display:grid;place-items:center;border:1px dashed #203840;border-radius:8px;color:#4c6871;font:800 8px ui-monospace,monospace;letter-spacing:.08em;text-align:center;padding:20px}.artifact.full .visualBox{min-height:220px}

/* ENGINEERING NOTES */
.notes{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:15px}.note{border:1px solid #172d35;border-radius:11px;padding:15px;background:#071014;min-height:125px}.note b{font-size:10px}.note p{color:#607982;font-size:9px;line-height:1.7}.trace{height:2px;background:#14282f;margin-top:12px;overflow:hidden}.trace i{display:block;width:30%;height:100%;background:var(--cyan);box-shadow:0 0 12px var(--cyan);animation:trace 2.6s linear infinite}
.footer{margin:45px 0 0;text-align:center;color:#3e5962;font:800 7px ui-monospace,monospace;letter-spacing:.14em}
.reveal{opacity:0;transform:translateY(25px);transition:opacity .8s ease,transform .8s ease}.reveal.visible{opacity:1;transform:none}
.spinner{display:inline-block;width:10px;height:10px;border:2px solid #24434c;border-top-color:var(--cyan);border-radius:50%;animation:spin .65s linear infinite;vertical-align:-2px}

@keyframes pulse{50%{opacity:.3;transform:scale(.65)}}@keyframes spin{to{transform:rotate(360deg)}}@keyframes rotate{to{transform:rotate(360deg)}}@keyframes rotateReverse{to{transform:rotate(-360deg)}}@keyframes core{50%{transform:rotate(135deg) scale(1.08);box-shadow:0 0 70px rgba(87,230,255,.12)}}@keyframes bob{50%{transform:translateY(5px) rotate(45deg)}}@keyframes scan{from{transform:translateY(-120%)}to{transform:translateY(900%)}}@keyframes progress{50%{opacity:.3}}@keyframes rise{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:none}}@keyframes trace{to{transform:translateX(340%)}}
@media(max-width:900px){.film{grid-template-columns:1fr}.shot,.shot.large{height:270px}.schematicGrid{grid-template-columns:1fr}.artifactGrid{grid-template-columns:1fr}.artifact.full{grid-column:auto}.notes{grid-template-columns:1fr}.stageRail{grid-template-columns:repeat(3,1fr)}.sectionHead{display:block}.sectionHead p{margin-top:10px}.controls{align-items:stretch;flex-direction:column}.generate{width:100%}.navRight{display:none}}
@media(max-width:600px){.shell{width:calc(100% - 14px)}.hero{min-height:570px}.heroGrid{width:430px;height:430px}.hero h1{font-size:52px}.hero p{font-size:12px}.workTop,.workBody{padding:13px}.stageRail{grid-template-columns:repeat(2,1fr)}.artifactGrid{padding:8px}.codeWrap pre{font-size:11px}.shot{height:230px}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation-duration:.001ms!important;animation-iteration-count:1!important;scroll-behavior:auto!important;transition-duration:.001ms!important}}
</style>
</head>
<body>
<div class="shell">
<nav class="nav">
 <div class="brand"><div class="brandmark">RF</div><div><b>RTL FORGE</b><small>ECE HARDWARE WORKBENCH</small></div></div>
 <div class="navRight"><span class="dotLive"></span> LOCAL SIMULATION READY</div>
</nav>

<section class="hero">
 <div class="heroGrid"></div><div class="heroCore"></div>
 <div class="heroContent">
  <div class="eyebrow"><span class="dotLive"></span> SYNTHESIS / SIMULATION / VERIFICATION</div>
  <h1>Build the hardware.<br><em>Inspect every signal.</em></h1>
  <p>Describe any digital ECE design in engineering language. RTL Forge turns the specification into synthesizable SystemVerilog, an independent testbench, a functional schematic and an actual simulation waveform.</p>
  <div class="heroTags"><span class="tag">SYSTEMVERILOG</span><span class="tag">Icarus Verilog</span><span class="tag">SELF-CHECKING TB</span><span class="tag">GRAPHVIZ</span><span class="tag">AUTO REPAIR</span></div>
  <div class="scrollCue">SCROLL INTO THE WORKBENCH<i></i></div>
 </div>
</section>

<section class="section reveal">
 <div class="sectionHead"><div><div class="kicker">01 / HARDWARE FILMSTRIP</div><h2>Silicon, boards, signals.</h2></div><p>Physical electronics references surround the digital workspace so the product feels like an engineering instrument, not a generic chat interface.</p></div>
 <div class="film">
  <figure class="shot large"><img loading="lazy" src="https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1500&q=88" alt="Close-up electronics board"><label><b>01</b><span>PCB / ROUTING</span></label></figure>
  <figure class="shot"><img loading="lazy" src="https://images.unsplash.com/photo-1592659762303-90081d34b277?auto=format&fit=crop&w=1200&q=88" alt="Circuit board detail"><label><b>02</b><span>COMPONENT FIELD</span></label></figure>
  <figure class="shot large"><img loading="lazy" src="https://images.unsplash.com/photo-1553406830-ef2513450d76?auto=format&fit=crop&w=1500&q=88" alt="Electronics laboratory"><label><b>03</b><span>ENGINEERING LAB</span></label></figure>
 </div>
</section>

<section class="section reveal">
 <div class="sectionHead"><div><div class="kicker">02 / DIGITAL DESIGN FIELD</div><h2>Signals. States. Structure.</h2></div><p>These schematic panels are generated UI artwork: multiplexing, state transitions and timing relationships are visible before the generated project is even opened.</p></div>
 <div class="schematicGrid">
  <div class="schematic"><div class="schematicTop"><span>COMBINATIONAL</span><b>4:1 SELECT PATH</b></div><svg viewBox="0 0 600 220" fill="none"><g stroke="currentColor" stroke-width="3"><path d="M20 35H190L350 100H570"/><path d="M20 85H190L350 100"/><path d="M20 135H190L350 100"/><path d="M20 185H190L350 100"/><path d="M350 100l55-55v110z"/></g><g fill="currentColor"><circle cx="20" cy="35" r="5"/><circle cx="20" cy="85" r="5"/><circle cx="20" cy="135" r="5"/><circle cx="20" cy="185" r="5"/><circle cx="570" cy="100" r="5"/></g></svg></div>
  <div class="schematic"><div class="schematicTop"><span>SEQUENTIAL</span><b>STATE MACHINE</b></div><svg viewBox="0 0 600 220" fill="none"><g stroke="currentColor" stroke-width="2"><circle cx="115" cy="110" r="45"/><circle cx="300" cy="55" r="45"/><circle cx="300" cy="165" r="45"/><circle cx="485" cy="110" r="45"/><path d="M160 95L255 65M160 125L255 155M345 55h95M345 165h95M440 92l-90-37M440 128l-90 37"/><path d="M70 78q-55-35 0-70M530 152q55 35 0 70"/></g><g fill="currentColor" font-family="monospace" font-size="16" text-anchor="middle"><text x="115" y="115">IDLE</text><text x="300" y="60">LOAD</text><text x="300" y="170">RUN</text><text x="485" y="115">DONE</text></g></svg></div>
  <div class="schematic"><div class="schematicTop"><span>VERIFICATION</span><b>WAVEFORM TRACE</b></div><svg viewBox="0 0 600 220" fill="none"><g stroke="#29414a" stroke-width="1"><path d="M10 35H590M10 85H590M10 135H590M10 185H590"/></g><path d="M10 60H80V20H150V60H220V20H290V60H360V20H430V60H500V20H590" stroke="#57e6ff" stroke-width="4"/><path d="M10 150H55V110H120V150H180V110H250V150H320V110H390V150H460V110H530V150H590" stroke="#61e5a4" stroke-width="4"/></svg></div>
 </div>
</section>

<section id="workbench" class="workbench reveal">
 <div class="workTop"><div><div class="kicker">03 / HARDWARE SPECIFICATION</div><h2>Describe the circuit you want to build</h2></div><div class="mode">GENERAL ECE / SYSTEMVERILOG</div></div>
 <div class="workBody">
  <div class="editor"><div class="editorBar"><span><span class="traffic"><i></i><i></i><i></i></span>&nbsp;&nbsp;hardware_requirement.txt</span><span>NATURAL LANGUAGE</span></div><textarea id="req" maxlength="5000" placeholder="Example: Design a dual-clock asynchronous FIFO with 8-bit data, 16 entries, Gray-coded pointers, synchronized status flags, active-low resets, and an independent self-checking testbench."></textarea><div class="editorFoot"><span>PLAN → RTL → TESTBENCH → SIMULATE → VERIFY</span><span id="count">0 / 5000</span></div></div>
  <div class="examples"><button class="chip" onclick="usePrompt('Design a UART transmitter and receiver with configurable baud divider, 8N1 framing and an independent self-checking testbench.')">UART</button><button class="chip" onclick="usePrompt('Design a synchronous FIFO, 16 entries x 8-bit, with full, empty, almost-full and almost-empty flags.')">SYNC FIFO</button><button class="chip" onclick="usePrompt('Design an SPI master supporting 8-bit transfers, CPOL/CPHA mode selection, programmable clock divider and busy/done status.')">SPI MASTER</button><button class="chip" onclick="usePrompt('Design an 8-bit ALU supporting ADD, SUB, AND, OR, XOR, shifts, zero flag and carry flag.')">8-BIT ALU</button><button class="chip" onclick="usePrompt('Design a PWM controller with programmable period and duty cycle, synchronous enable and clean reset behavior.')">PWM</button><button class="chip" onclick="usePrompt('Design a CRC-8 streaming calculator with valid input, start/reset control and an independent reference-model testbench.')">CRC-8</button></div>
  <div class="controls"><div class="hint"><span>⌘ / CTRL</span> + <span>ENTER</span> TO BUILD</div><button id="generate" class="generate" onclick="build()">GENERATE &amp; VERIFY HDL →</button></div>
  <div id="status" class="status"></div>
  <div id="stageRail" class="stageRail hidden"><div id="s1" class="stage"><span>01</span>SPECIFY</div><div id="s2" class="stage"><span>02</span>ARCHITECT</div><div id="s3" class="stage"><span>03</span>GENERATE RTL</div><div id="s4" class="stage"><span>04</span>COMPILE</div><div id="s5" class="stage"><span>05</span>SIMULATE</div><div id="s6" class="stage"><span>06</span>VERIFY</div></div>
 </div>
</section>

<section id="result" class="result hidden reveal">
 <div class="resultHeader"><div class="resultIdentity"><div id="statusIcon" class="statusIcon">⌁</div><div><b id="resultHeading">Generated Design</b><small id="resultSub">RTL • testbench • circuit schematic • simulation waveform</small></div></div><div class="actions"><button class="smallbtn" onclick="downloadCode()">DOWNLOAD RTL</button><button class="smallbtn" onclick="downloadTB()">DOWNLOAD TB</button><button class="smallbtn" onclick="copyCode()">COPY RTL</button><span id="copied" style="color:var(--green);font:800 7px ui-monospace"></span></div></div>
 <div class="artifactGrid">
  <article class="artifact"><div class="artifactHead"><span>01 / RTL</span><b>generated_design.sv</b></div><div class="codeWrap"><pre id="rtl"></pre></div></article>
  <article class="artifact"><div class="artifactHead"><span>02 / TESTBENCH</span><b>testbench.sv</b></div><div class="codeWrap"><pre id="tbcode"></pre></div></article>
  <article class="artifact"><div class="artifactHead"><span>03 / CIRCUIT DESIGN</span><b>GRAPHVIZ SVG</b></div><div id="diagram" class="visualBox"><div class="emptyVisual">SCHEMATIC WILL APPEAR AFTER GENERATION</div></div></article>
  <article class="artifact"><div class="artifactHead"><span>04 / WAVEFORM</span><b>wave.vcd → SVG</b></div><div id="waveform" class="visualBox"><div class="emptyVisual">WAVEFORM WILL APPEAR AFTER SIMULATION</div></div></article>
  <article class="artifact full"><div class="artifactHead"><span>05 / VERIFICATION CONSOLE</span><b>Icarus objective result</b></div><div class="artifactHint">The status below is based on the actual compiler and simulator process. A failed result is never presented as verified.</div><div id="verify" class="verifyBox"><strong>Waiting for result</strong><br>Build a design to inspect objective verification.</div></article>
 </div>
</section>

<section class="notes reveal">
 <div class="note"><b>Hardware-first workflow</b><p>The product is organized around specification, RTL, verification and physical signal relationships — not a chat transcript.</p><div class="trace"><i></i></div></div>
 <div class="note"><b>Independent verification</b><p>The testbench is requested separately from the DUT and must calculate expected behavior rather than simply echoing the implementation.</p></div>
 <div class="note"><b>Bounded recovery</b><p>Compile or simulation failures can trigger one focused repair attempt. There is no endless retry loop.</p></div>
</section>
<div class="footer">RTL FORGE / ECE DIGITAL HARDWARE WORKBENCH / ENGINEER • SIMULATE • VERIFY</div>
</div>
<script>
let generated='', generatedTB='', timer=null, stageTimer=null;
const req=document.getElementById('req');
req.addEventListener('input',()=>document.getElementById('count').textContent=req.value.length+' / 5000');
req.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key==='Enter'){e.preventDefault();build()}});
function usePrompt(t){req.value=t;document.getElementById('count').textContent=t.length+' / 5000';document.getElementById('workbench').scrollIntoView({behavior:'smooth',block:'center'});setTimeout(()=>req.focus(),350)}
function stages(n){for(let i=1;i<=6;i++){const el=document.getElementById('s'+i);el.classList.toggle('active',i===n);el.classList.toggle('done',i<n)}}
function startStages(){document.getElementById('stageRail').classList.remove('hidden');let n=1;stages(n);clearInterval(stageTimer);stageTimer=setInterval(()=>{if(n<5){n++;stages(n)}},900)}
function finishStages(ok){clearInterval(stageTimer);stages(ok?6:5)}
function setStatus(kind,msg){document.getElementById('status').innerHTML='<div class="notice '+kind+'">'+msg+'</div>'}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function putVisual(id,value,empty){const el=document.getElementById(id);if(value&&String(value).includes('<svg'))el.innerHTML=value;else el.innerHTML='<div class="emptyVisual">'+esc(empty)+'</div>'}
async function build(){
 const text=req.value.trim(),btn=document.getElementById('generate');
 if(!text){setStatus('err','Enter a hardware requirement first.');req.focus();return}
 btn.disabled=true;btn.innerHTML='<span class="spinner"></span>&nbsp; BUILDING HARDWARE…';
 document.getElementById('result').classList.add('hidden');
 setStatus('', '<span class="spinner"></span>&nbsp; Engineering pipeline running — specification → RTL → compile → simulation → verification');
 startStages();
 try{
  const r=await fetch('/api/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request:text})});
  const raw=await r.text();let d={};try{d=raw?JSON.parse(raw):{}}catch(_){throw new Error('Server returned a non-JSON response. Check the Render deployment logs.')}
  if(!r.ok)throw new Error(d.message||d.error||'Hardware build failed.');
  generated=d.rtl||'';generatedTB=d.testbench||'';
  document.getElementById('rtl').textContent=generated;
  document.getElementById('tbcode').textContent=generatedTB;
  putVisual('diagram',d.diagram_svg,'No functional circuit schematic was produced.');
  putVisual('waveform',d.waveform_svg,'No waveform was captured. The testbench may not have reached simulation.');
  const v=d.verification||{};
  const icon=document.getElementById('statusIcon');
  const verify=document.getElementById('verify');
  if(v.passed){
   finishStages(true);icon.className='statusIcon pass';icon.textContent='✓';
   document.getElementById('resultHeading').textContent='Verified Design';
   document.getElementById('resultSub').textContent=(d.design_name||'ECE design')+' • RTL • testbench • schematic • waveform';
   setStatus('ok','✓ DESIGN VERIFIED — compile and self-checking simulation passed.');
   verify.className='verifyBox';verify.innerHTML='<strong>✓ Verification passed</strong><br>Icarus compiled the project and the independent testbench reported <b>TEST_RESULT: PASS</b>.'+(d.repair_attempted?' One bounded repair pass was used.':'');
  }else{
   finishStages(false);icon.className='statusIcon fail';icon.textContent='!';
   document.getElementById('resultHeading').textContent='Generated Design — Not Verified';
   document.getElementById('resultSub').textContent=(d.design_name||'ECE design')+' • inspect RTL, testbench, schematic and simulator output';
   setStatus('err','⚠ RTL generated, but objective verification did not pass.');
   let log=(v.log||'').trim().split('\n').filter(Boolean).slice(-8).map(esc).join('<br>');
   verify.className='verifyBox fail';verify.innerHTML='<strong>⚠ Verification did not pass</strong><br>Stage: '+esc(v.stage||'unknown')+'. The artifacts are shown for inspection only.'+(log?'<br><span style="color:#637b84">'+log+'</span>':'');
  }
  const result=document.getElementById('result');result.classList.remove('hidden');result.classList.add('visible');
  requestAnimationFrame(()=>result.scrollIntoView({behavior:'smooth',block:'start'}));
 }catch(e){clearInterval(stageTimer);setStatus('err','✕ '+esc(e.message||String(e)));document.getElementById('stageRail').classList.add('hidden')}
 finally{btn.disabled=false;btn.textContent='GENERATE & VERIFY HDL →'}
}
async function copyCode(){if(!generated)return;try{await navigator.clipboard.writeText(generated);document.getElementById('copied').textContent='COPIED';setTimeout(()=>document.getElementById('copied').textContent='',1300)}catch(_){document.getElementById('copied').textContent='COPY FAILED'}}
function saveText(text,name){if(!text)return;const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type:'text/plain'}));a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
function downloadCode(){saveText(generated,'generated_design.sv')}function downloadTB(){saveText(generatedTB,'testbench.sv')}
const observer=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting)e.target.classList.add('visible')}),{threshold:.1});document.querySelectorAll('.reveal').forEach(x=>observer.observe(x));
</script>
</body>
</html>'''

# ============================================================
# SAFE / MODEL HELPERS
# ============================================================
def clean_code(text):
    if not isinstance(text, str):
        return ''
    m = re.search(r"```(?:systemverilog|verilog|sv|json)?\s*(.*?)```", text, re.I | re.S)
    code = (m.group(1) if m else text).strip()
    if code.count('\n') < 2 and code.count('\\n') >= 3:
        code = code.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\t', '\t')
    return code.strip()

def unsafe_reason(code):
    if not isinstance(code, str) or not code.strip():
        return 'empty HDL output'
    rules = [
        (r'\$system\b', '$system host command'),
        (r'\$popen\b', '$popen host process'),
        (r'\$fopen\b|\$fclose\b|\$fwrite\b|\$fdisplay\b|\$fscanf\b|\$fread\b', 'host file I/O'),
        (r'\$writemem\b', '$writemem host file access'),
        (r'DPI-C', 'DPI-C external code'),
        (r'\bimport\s+"', 'external DPI/import code'),
    ]
    for pattern, label in rules:
        if re.search(pattern, code, re.I):
            return label
    return None

def json_from(text):
    text = clean_code(text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r'\{.*\}', text, re.S)
        if not m:
            raise ValueError('Model returned invalid JSON.')
        return json.loads(m.group(0))

def api_code(exc):
    for a in ('code', 'status_code', 'http_status'):
        v = getattr(exc, a, None)
        try:
            if v is not None:
                return int(v)
        except Exception:
            pass
    m = re.search(r'\b(400|401|403|404|408|429|500|502|503|504)\b', str(exc))
    return int(m.group(1)) if m else None

def model_list():
    return list(dict.fromkeys([MODEL] + FALLBACK_MODELS))[:3]

DESIGN_SCHEMA = {
    'type':'object',
    'properties':{
        'design_name':{'type':'string'},
        'rtl':{'type':'string'},
        'testbench':{'type':'string'},
        'diagram_dot':{'type':'string'},
    },
    'required':['design_name','rtl','testbench','diagram_dot']
}

REPAIR_SCHEMA = {
    'type':'object',
    'properties':{
        'rtl':{'type':'string'},
        'testbench':{'type':'string'},
        'diagram_dot':{'type':'string'},
    },
    'required':['rtl','testbench','diagram_dot']
}

def gemini_call(prompt, repair=False):
    if client is None:
        raise RuntimeError('Gemini API key is not configured on the server.')
    errors=[]
    for model in model_list():
        try:
            response=client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=14000,
                    response_mime_type='application/json',
                    response_schema=REPAIR_SCHEMA if repair else DESIGN_SCHEMA,
                ),
            )
            text=(getattr(response,'text',None) or '').strip()
            if text:
                return text
            errors.append(f'{model}:empty')
        except Exception as exc:
            code=api_code(exc)
            errors.append(f'{model}:{code or "error"}')
            if code in (401,403):
                raise RuntimeError('Gemini authentication/permission failed. Check GEMINI_API_KEY and model access.')
    raise RuntimeError('Gemini generation is temporarily unavailable across the configured models. Attempt summary: '+', '.join(errors))

# ============================================================
# GENERAL ECE PROMPTS
# ============================================================
def prompt_for_design(req_text):
    return f'''
You are a senior digital ECE RTL engineer. The user can request ANY digital
hardware circuit or subsystem. Never limit the task to examples from a website.

Return exactly one JSON object containing:
1. design_name
2. rtl
3. testbench
4. diagram_dot

RTL:
- Complete synthesizable SystemVerilog DUT.
- Use conservative constructs compatible with iverilog -g2012.
- Preserve exact requested widths, reset polarity, clocking, latency and interfaces.
- No host-control, shell, network, DPI or arbitrary file I/O in the DUT.
- Do not put testbench logic inside the DUT.

TESTBENCH:
- Top module MUST be named tb.
- Instantiate the DUT exactly.
- Independently calculate expected behavior; do not simply copy DUT equations.
- Test normal cases plus important boundaries/corner cases.
- For sequential logic test reset, clocking, state transitions and latency.
- Print mismatch details.
- Print TEST_RESULT: PASS only if every check passes.
- Print TEST_RESULT: FAIL if any check fails.
- Include exactly these waveform commands in the testbench:
  initial begin
    $dumpfile("wave.vcd");
    $dumpvars(0, tb);
  end
- Do not use $system, $popen, $fopen, $fwrite, DPI or host filesystem control.
- Keep simulation reasonably short.

DIAGRAM:
- Return valid Graphviz DOT beginning with digraph.
- Show actual functional blocks and signal/data/control flow.
- Label clock/reset, data buses, enables and important outputs where applicable.
- Keep under 12000 characters.

Before returning, mentally inspect syntax balance and module interfaces.

USER REQUIREMENT:
{req_text}
'''

def repair_prompt(req_text, rtl, tb, log, diagram=''):
    return f'''
You are the senior digital RTL debug and verification engineer.

The following arbitrary ECE hardware project failed an objective Icarus Verilog
compile or simulation. Return one JSON object with rtl, testbench and diagram_dot.
Return COMPLETE replacement files, never fragments or "unchanged" placeholders.

The simulator/compiler log is authoritative. Diagnose the actual failure and fix it.
Preserve the requested hardware behavior and verification strength. Never delete
checks just to obtain PASS. Make the testbench independently self-checking.

The testbench top module MUST be tb and MUST contain:
initial begin
  $dumpfile("wave.vcd");
  $dumpvars(0, tb);
end

Use conservative SystemVerilog compatible with iverilog -g2012. Avoid host-control,
shell, network, DPI and arbitrary file I/O. Carefully inspect widths, signedness,
part-selects, parameter expressions, reset behavior, clock-domain crossings,
reference models and race conditions.

USER REQUIREMENT:
{req_text}

CURRENT RTL:
```systemverilog
{rtl}
```

CURRENT TESTBENCH:
```systemverilog
{tb}
```

FAILURE LOG:
{log[-16000:]}

CURRENT DIAGRAM:
{diagram[:12000]}
'''

# ============================================================
# WAVEFORM / DIAGRAM
# ============================================================
def ensure_wave_dump(tb):
    if '$dumpfile' not in tb:
        tb='''\ninitial begin\n  $dumpfile("wave.vcd");\n  $dumpvars(0, tb);\nend\n''' + tb
    elif '$dumpvars' not in tb:
        tb='''\ninitial begin\n  $dumpvars(0, tb);\nend\n''' + tb
    return tb

def render_diagram(dot_text):
    if not dot_text or not dot_text.strip().lower().startswith('digraph'):
        return ''
    dot_text=dot_text[:12000]
    try:
        cp=subprocess.run(['dot','-Tsvg'],input=dot_text,capture_output=True,text=True,timeout=DIAGRAM_TIMEOUT)
        if cp.returncode!=0 or '<svg' not in cp.stdout:
            return ''
        svg=re.sub(r'^\s*<\?xml[^>]*>\s*','',cp.stdout)
        svg=re.sub(r'<!DOCTYPE[^>]*>\s*','',svg,flags=re.I)
        # Remove script/style tags from model-produced SVG before embedding.
        svg=re.sub(r'<script\b[^>]*>.*?</script>','',svg,flags=re.I|re.S)
        return svg
    except (FileNotFoundError,subprocess.TimeoutExpired,OSError):
        return ''

def esc_svg(v):
    return html.escape(str(v),quote=True)

def waveform_svg(vcd_path,max_signals=10,max_changes=180):
    path=Path(vcd_path)
    if not path.exists():
        return ''
    try:
        lines=path.read_text(encoding='utf-8',errors='ignore').splitlines()
    except OSError:
        return ''
    vars_by_id={};scope=[];defs=True;now=0;changes={}
    for line in lines:
        line=line.strip()
        if not line: continue
        if line.startswith('$scope'):
            p=line.split();
            if len(p)>=3: scope.append(p[2])
        elif line.startswith('$upscope'):
            if scope: scope.pop()
        elif line.startswith('$var'):
            p=line.split()
            if len(p)>=5:
                width=int(p[2]) if p[2].isdigit() else 1
                vars_by_id[p[3]]=(width,'.'.join(scope+[p[4]]))
        elif line.startswith('$enddefinitions'):
            defs=False
        elif not defs:
            if line.startswith('#'):
                try: now=int(line[1:])
                except ValueError: pass
                continue
            val=None;ident=None
            if len(line)>1 and line[0] in '01xXzZ': val=line[0];ident=line[1:]
            elif line.startswith('b'):
                p=line.split()
                if len(p)>=2: val=p[0][1:];ident=p[1]
            if ident in vars_by_id:
                changes.setdefault(ident,[]).append((now,val))
    chosen=[]
    for ident,(width,name) in vars_by_id.items():
        if changes.get(ident): chosen.append((ident,width,name,changes[ident]))
    chosen=chosen[:max_signals]
    if not chosen: return ''
    max_time=max((p[-1][0] for *_,p in chosen if p),default=1) or 1
    W=1100;left=225;right=20;plot=W-left-right;row=54;H=35+row*len(chosen)
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}"><rect width="100%" height="100%" fill="#04080a"/>']
    for i,(_,width,name,pts) in enumerate(chosen):
        y=22+i*row
        out.append(f'<line x1="{left}" y1="{y+29}" x2="{W-right}" y2="{y+29}" stroke="#173039"/>')
        out.append(f'<text x="12" y="{y+33}" fill="#a1b7be" font-family="monospace" font-size="11">{esc_svg(name)}</text>')
        compact=[]
        for t,v in pts:
            if compact and compact[-1][1]==v: continue
            compact.append((t,v))
        if len(compact)>max_changes:
            step=max(1,len(compact)//max_changes);compact=compact[::step]
        if width==1:
            d=[];last_y=y+29
            for j,(t,v) in enumerate(compact):
                x=left+plot*(t/max_time)
                yy=y+13 if str(v).lower()=='1' else y+39
                if str(v).lower() not in ('0','1'): yy=y+26
                if j==0:d.append(f'M{x:.1f} {yy:.1f}')
                else:d.append(f'L{x:.1f} {last_y:.1f} L{x:.1f} {yy:.1f}')
                last_y=yy
            if compact:d.append(f'L{W-right:.1f} {last_y:.1f}')
            out.append(f'<path d="{" ".join(d)}" fill="none" stroke="#57e6ff" stroke-width="2"/>')
        else:
            for j,(t,v) in enumerate(compact):
                t2=compact[j+1][0] if j+1<len(compact) else max_time
                x1=left+plot*(t/max_time);x2=left+plot*(t2/max_time)
                label=str(v);label=label if len(label)<=16 else label[:13]+'…'
                out.append(f'<rect x="{x1:.1f}" y="{y+12}" width="{max(1,x2-x1):.1f}" height="28" rx="3" fill="#0a171d" stroke="#29444e"/>')
                if x2-x1>38:out.append(f'<text x="{(x1+x2)/2:.1f}" y="{y+30}" text-anchor="middle" fill="#8eddea" font-family="monospace" font-size="9">{esc_svg(label)}</text>')
    out.append(f'<text x="{left}" y="{H-6}" fill="#526c75" font-family="monospace" font-size="9">0</text><text x="{W-right}" y="{H-6}" text-anchor="end" fill="#526c75" font-family="monospace" font-size="9">{max_time}</text></svg>')
    return ''.join(out)

# ============================================================
# OBJECTIVE SIMULATION
# ============================================================
def simulate(rtl,tb,job,deadline):
    job=Path(job);dut=job/'design.sv';bench=job/'testbench.sv';out=job/'sim.out'
    dut.write_text(rtl,encoding='utf-8');bench.write_text(ensure_wave_dump(tb),encoding='utf-8')
    def remaining(default):
        left=deadline-time.monotonic()
        return max(0,min(float(default),left))
    ct=remaining(SIM_TIMEOUT)
    if ct<=0:return {'passed':False,'stage':'compile','log':'Build deadline reached before compilation.'}
    try:
        cp=subprocess.run(['iverilog','-g2012','-s','tb','-o',str(out),str(dut),str(bench)],capture_output=True,text=True,timeout=ct)
    except FileNotFoundError:return {'passed':False,'stage':'compile','log':'iverilog is not installed on the Render service.'}
    except subprocess.TimeoutExpired:return {'passed':False,'stage':'compile','log':'Compilation timed out.'}
    if cp.returncode!=0:
        return {'passed':False,'stage':'compile','log':((cp.stdout or '')+'\n'+(cp.stderr or ''))[-18000:]}
    st=remaining(SIM_TIMEOUT)
    if st<=0:return {'passed':False,'stage':'simulation','log':'Build deadline reached before simulation.'}
    try:
        sp=subprocess.run(['vvp',str(out)],cwd=job,capture_output=True,text=True,timeout=st)
    except subprocess.TimeoutExpired:return {'passed':False,'stage':'simulation','log':'Simulation timed out.'}
    log=(sp.stdout or '')+'\n'+(sp.stderr or '')
    passed=sp.returncode==0 and 'TEST_RESULT: PASS' in log and 'TEST_RESULT: FAIL' not in log
    if sp.returncode!=0 and 'Assertion' in log:
        log='VVP RUNTIME FAILURE detected. This is a simulator/runtime failure, not a PASS.\n'+log
    return {'passed':passed,'stage':'simulation','log':log[-18000:]}

# ============================================================
# BUILD PIPELINE
# ============================================================
def build_project(user_request):
    started=time.monotonic();deadline=started+MAX_BUILD_SECONDS
    job=JOB_ROOT/uuid.uuid4().hex[:12];job.mkdir(parents=True,exist_ok=True)
    def budget(msg):
        if time.monotonic()>=deadline: raise TimeoutError(msg)
    try:
        budget('Build deadline reached before generation.')
        data=json_from(gemini_call(prompt_for_design(user_request)))
        rtl=clean_code(data.get('rtl',''));tb=clean_code(data.get('testbench',''));dot=clean_code(data.get('diagram_dot',''))
        name=str(data.get('design_name','General ECE RTL design')).strip() or 'General ECE RTL design'
        tb=ensure_wave_dump(tb)
        repair=False
        issue=unsafe_reason(rtl) or unsafe_reason(tb)
        if issue:
            if MAX_REPAIR_ATTEMPTS<=0: raise RuntimeError(f'Generated HDL contains blocked construct ({issue}).')
            repair=True;budget('Build deadline reached before safety repair.')
            fixed=json_from(gemini_call(repair_prompt(user_request,rtl,tb,'SAFETY VALIDATION: '+issue,dot),repair=True))
            rtl=clean_code(fixed.get('rtl',''));tb=ensure_wave_dump(clean_code(fixed.get('testbench','')));dot=clean_code(fixed.get('diagram_dot',dot))
            issue=unsafe_reason(rtl) or unsafe_reason(tb)
            if issue: raise RuntimeError(f'Repaired HDL still contains blocked construct ({issue}).')
        if not rtl or not tb: raise RuntimeError('Gemini did not return complete RTL and testbench artifacts.')
        budget('Build deadline reached before simulation.')
        sim=simulate(rtl,tb,job,deadline)
        # One bounded objective repair. This also handles vvp assertion/runtime failures.
        if not sim['passed'] and MAX_REPAIR_ATTEMPTS>0 and not repair:
            repair=True;budget('Build deadline reached before repair.')
            fixed=json_from(gemini_call(repair_prompt(user_request,rtl,tb,sim.get('log',''),dot),repair=True))
            rtl2=clean_code(fixed.get('rtl',''));tb2=ensure_wave_dump(clean_code(fixed.get('testbench','')));dot2=clean_code(fixed.get('diagram_dot',dot))
            issue=unsafe_reason(rtl2) or unsafe_reason(tb2)
            if issue: raise RuntimeError(f'Repair generated blocked construct ({issue}).')
            if not rtl2 or not tb2: raise RuntimeError('Repair response did not contain complete RTL and testbench.')
            rtl,tb,dot=rtl2,tb2,dot2
            budget('Build deadline reached before repaired simulation.')
            sim=simulate(rtl,tb,job,deadline)
        (job/'design.sv').write_text(rtl,encoding='utf-8')
        (job/'testbench.sv').write_text(tb,encoding='utf-8')
        (job/'simulation.log').write_text(sim.get('log',''),encoding='utf-8')
        (job/'request.txt').write_text(user_request,encoding='utf-8')
        diagram=render_diagram(dot)
        wave=waveform_svg(job/'wave.vcd')
        return {'rtl':rtl,'testbench':tb,'verification':sim,'design_name':name,'job_id':job.name,'repair_attempted':repair,'general_purpose':True,'diagram_svg':diagram,'waveform_svg':wave}
    except Exception:
        shutil.rmtree(job,ignore_errors=True)
        raise

# ============================================================
# ROUTES
# ============================================================
@app.get('/')
def home():
    return render_template_string(HTML)

@app.get('/health')
def health():
    return jsonify({
        'status':'ok','gemini_configured':client is not None,'gemini_model':MODEL,
        'gemini_fallback_models':FALLBACK_MODELS,'gemini_request_timeout_seconds':REQUEST_TIMEOUT,
        'max_build_seconds':MAX_BUILD_SECONDS,'max_repair_attempts':MAX_REPAIR_ATTEMPTS,
        'sim_timeout_seconds':SIM_TIMEOUT,'diagram_timeout_seconds':DIAGRAM_TIMEOUT,
        'iverilog':shutil.which('iverilog') is not None,'vvp':shutil.which('vvp') is not None,
        'graphviz':shutil.which('dot') is not None,'general_purpose':True,
        'hardcoded_demo_fallback':False,'version':'rtl-forge-general-ece-6.0'
    })

@app.post('/api/build')
def api_build():
    data=request.get_json(silent=True) or {}
    user_request=str(data.get('request','')).strip()
    if not user_request:
        return jsonify({'error':'Please provide a hardware requirement.','message':'Please provide a hardware requirement.'}),400
    if len(user_request)>5000:
        return jsonify({'error':'Hardware requirement is too long.','message':'Hardware requirement is limited to 5000 characters.'}),400
    try:
        return jsonify(build_project(user_request))
    except TimeoutError as exc:
        msg=str(exc);return jsonify({'error':msg,'message':msg,'code':'build_timeout','verification':{'passed':False,'stage':'deadline','log':msg}}),504
    except Exception as exc:
        msg=str(exc);return jsonify({'error':msg,'message':msg,'code':'build_failed','verification':{'passed':False}}),503

@app.get('/api/download/<job_id>/<artifact>')
def download_artifact(job_id,artifact):
    names={'rtl':'design.sv','testbench':'testbench.sv','log':'simulation.log'}
    if artifact not in names:return jsonify({'error':'Unknown artifact.'}),400
    path=JOB_ROOT/job_id/names[artifact]
    if not path.exists():return jsonify({'error':'Build artifact not found.'}),404
    return send_file(path,as_attachment=True,download_name=names[artifact])

@app.errorhandler(404)
def not_found(_):
    return jsonify({'error':'Not found.','message':'Not found.'}),404

@app.errorhandler(Exception)
def unexpected(_):
    return jsonify({'error':'Server error. Please try the build again.','message':'Server error. Please try the build again.'}),500

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))
