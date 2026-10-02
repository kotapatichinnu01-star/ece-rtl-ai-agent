import os, re, json, uuid, time, random, subprocess, tempfile, shutil
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string, send_file
from flask_cors import CORS
from google import genai
from google.genai import types

app = Flask(__name__)
CORS(app)

# -----------------------------
# Runtime configuration
# -----------------------------
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
FALLBACK_MODELS = [x.strip() for x in os.getenv(
    "GEMINI_FALLBACK_MODELS", "gemini-3.7-flash,gemini-3.5-flash-lite"
).split(",") if x.strip()]
REQUEST_TIMEOUT = max(10, min(15, float(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "12"))))
MAX_REPAIR_ATTEMPTS = max(0, int(os.getenv("MAX_REPAIR_ATTEMPTS", "1")))
# Keep each compile/simulation short so a repair cycle still fits inside the request budget.
SIM_TIMEOUT = max(2, min(10, int(os.getenv("SIM_TIMEOUT_SECONDS", "8"))))
API_KEY = os.getenv("GEMINI_API_KEY")
# Hard wall for one /api/build request. Must include generation + simulation + one repair + re-simulation.
MAX_BUILD_SECONDS = max(30, min(60, int(os.getenv("MAX_BUILD_SECONDS", "60"))))
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

# -----------------------------
# UI
# -----------------------------
HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#05080b">
<title>RTL Forge — ECE Hardware Workbench</title>
<style>
:root{--bg:#05080b;--bg2:#080d12;--panel:#0b1117;--panel2:#0d151c;--line:#1a2933;--line2:#263943;--text:#edf7fa;--muted:#78909c;--cyan:#55e5ff;--green:#54e39b;--amber:#f4c76d;--red:#ff687e;--purple:#9c8cff;--shadow:0 30px 90px rgba(0,0,0,.48)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:var(--text);background:radial-gradient(circle at 50% -10%,rgba(85,229,255,.08),transparent 34%),radial-gradient(circle at 85% 35%,rgba(156,140,255,.07),transparent 28%),var(--bg);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow-x:hidden}
body:before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.28;background-image:linear-gradient(rgba(130,170,185,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(130,170,185,.045) 1px,transparent 1px);background-size:42px 42px;mask-image:linear-gradient(#000,transparent 88%);z-index:-2}
body:after{content:"";position:fixed;left:0;right:0;top:-20%;height:35%;pointer-events:none;background:linear-gradient(transparent,rgba(85,229,255,.025),transparent);animation:scan 9s linear infinite;z-index:20}
button,textarea{font:inherit}.wrap{width:min(1280px,calc(100% - 36px));margin:auto;padding-bottom:100px}.hidden{display:none!important}
.nav{height:62px;margin-top:16px;position:sticky;top:12px;z-index:30;display:flex;align-items:center;justify-content:space-between;padding:0 16px;border:1px solid var(--line);border-radius:16px;background:rgba(5,9,12,.78);backdrop-filter:blur(22px);box-shadow:0 15px 50px rgba(0,0,0,.28)}
.brand{display:flex;align-items:center;gap:12px}.brandmark{width:36px;height:36px;border:1px solid rgba(85,229,255,.35);border-radius:10px;display:grid;place-items:center;background:linear-gradient(145deg,#0c252d,#101526);box-shadow:inset 0 0 18px rgba(85,229,255,.08),0 0 25px rgba(85,229,255,.08);font:800 10px ui-monospace,monospace;color:var(--cyan)}.brand b{font-size:14px;letter-spacing:.04em}.brand small{display:block;color:#617883;font-size:9px;letter-spacing:.17em;text-transform:uppercase;margin-top:2px}.navright{display:flex;align-items:center;gap:16px;color:#6e858f;font:700 9px ui-monospace,monospace;letter-spacing:.12em}.pulse{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 14px var(--green);animation:pulse 1.8s infinite}
.hero{min-height:700px;position:relative;display:grid;place-items:center;padding:80px 0 55px;text-align:center;overflow:hidden}.hero:before{content:"";position:absolute;width:600px;height:600px;border-radius:50%;border:1px solid rgba(85,229,255,.07);box-shadow:0 0 0 80px rgba(85,229,255,.018),0 0 0 160px rgba(85,229,255,.012);animation:orbit 18s linear infinite}.hero:after{content:"";position:absolute;width:300px;height:300px;border-radius:50%;background:radial-gradient(circle,rgba(85,229,255,.12),transparent 68%);filter:blur(15px);animation:float 6s ease-in-out infinite}.heroContent{position:relative;z-index:1}.eyebrow{display:inline-flex;gap:9px;align-items:center;border:1px solid rgba(85,229,255,.18);border-radius:999px;padding:8px 12px;color:#9cd8e2;background:rgba(85,229,255,.035);font:800 9px ui-monospace,monospace;letter-spacing:.15em;text-transform:uppercase}.hero h1{font-size:clamp(48px,7vw,92px);line-height:.93;letter-spacing:-.065em;margin:25px auto 20px;max-width:1000px}.hero h1 span{background:linear-gradient(100deg,#f5fbfc 10%,#55e5ff 48%,#a69aff 86%);color:transparent;background-clip:text;-webkit-background-clip:text}.hero p{max-width:700px;margin:auto;color:#82979f;line-height:1.75;font-size:16px}.heroMeta{display:flex;justify-content:center;gap:8px;flex-wrap:wrap;margin-top:26px}.spec{padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.02);color:#71878f;font:700 9px ui-monospace,monospace}.scroll{margin-top:70px;color:#506770;font:700 9px ui-monospace,monospace;letter-spacing:.18em;text-transform:uppercase}.scroll i{display:block;width:7px;height:12px;border-right:1px solid var(--cyan);border-bottom:1px solid var(--cyan);transform:rotate(45deg);margin:11px auto;animation:bob 1.7s infinite}
.workbench{position:relative;border:1px solid var(--line);border-radius:24px;background:linear-gradient(145deg,rgba(12,19,25,.97),rgba(6,10,14,.96));box-shadow:var(--shadow);overflow:hidden}.workbench:before{content:"";position:absolute;left:0;top:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--cyan),transparent);opacity:.55}.workhead{padding:22px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:flex-start;gap:15px}.sectionnum{color:#5c737c;font:800 9px ui-monospace,monospace;letter-spacing:.16em}.workhead h2{font-size:19px;margin:6px 0 0;letter-spacing:-.025em}.mode{color:#6e858e;border:1px solid var(--line);padding:7px 9px;border-radius:8px;font:700 8px ui-monospace,monospace}.workbody{padding:24px}.editor{border:1px solid #1d3039;border-radius:16px;background:#060a0d;overflow:hidden;transition:.25s}.editor:focus-within{border-color:rgba(85,229,255,.4);box-shadow:0 0 0 3px rgba(85,229,255,.035)}.editorbar{height:35px;border-bottom:1px solid #14242b;display:flex;align-items:center;justify-content:space-between;padding:0 12px;background:#080d11}.traffic{display:flex;gap:5px}.traffic i{width:6px;height:6px;border-radius:50%;background:#33434a}.editorfile{color:#546c75;font:700 9px ui-monospace,monospace}.editorlang{color:#4d6670;font:800 8px ui-monospace,monospace;letter-spacing:.13em}textarea{width:100%;height:180px;resize:vertical;min-height:130px;max-height:420px;padding:20px;background:transparent;border:0;outline:0;color:#dcebf0;font:14px/1.7 ui-monospace,SFMono-Regular,Consolas,monospace}textarea::placeholder{color:#3f565e}.editorfoot{display:flex;justify-content:space-between;border-top:1px solid #14242b;padding:8px 12px;color:#4e666f;font:700 9px ui-monospace,monospace}
.exampleLabel{width:100%;color:#405760;font:800 8px ui-monospace,monospace;letter-spacing:.14em;margin:8px 2px 0}.examples{display:flex;gap:7px;flex-wrap:wrap;margin:12px 0}.chip{border:1px solid #1a2a31;border-radius:8px;background:#0a1116;color:#789099;padding:8px 10px;cursor:pointer;font:700 9px ui-monospace,monospace;transition:.2s}.chip:hover{color:#b9f4fb;border-color:#31515c;transform:translateY(-2px);background:#0c171c}.controls{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:16px;flex-wrap:wrap}.shortcut{color:#506771;font:700 9px ui-monospace,monospace}.key{border:1px solid #253740;border-radius:5px;padding:2px 5px;color:#82979f}.generate{border:1px solid rgba(85,229,255,.32);border-radius:10px;padding:12px 16px;background:linear-gradient(145deg,#15313a,#102029);color:#c9f9ff;cursor:pointer;font-weight:900;box-shadow:inset 0 0 22px rgba(85,229,255,.05),0 10px 35px rgba(0,0,0,.25);transition:.22s}.generate:hover{transform:translateY(-2px);border-color:rgba(85,229,255,.65);box-shadow:0 0 30px rgba(85,229,255,.08)}.generate:disabled{opacity:.5;cursor:not-allowed;transform:none}.status{min-height:48px;padding-top:15px}.notice{display:flex;align-items:center;gap:9px;padding:10px 12px;border:1px solid #1c2d34;border-radius:10px;color:#8aa0a8;background:#091116;font-size:11px}.notice.ok{border-color:rgba(84,227,155,.22);color:#78e8ad;background:rgba(84,227,155,.035)}.notice.err{border-color:rgba(255,104,126,.24);color:#ff91a1;background:rgba(255,104,126,.035)}.spinner{width:13px;height:13px;border:2px solid #29434b;border-top-color:var(--cyan);border-radius:50%;animation:spin .7s linear infinite}.pipeline{display:grid;grid-template-columns:repeat(6,1fr);gap:7px;margin-top:10px}.stage{position:relative;padding:12px 8px;text-align:center;border:1px solid #17272e;border-radius:9px;background:#080e12;color:#4e656d;font:800 8px ui-monospace,monospace;letter-spacing:.12em;transition:.35s}.stage.active{border-color:rgba(85,229,255,.3);color:#a8edf5;box-shadow:inset 0 0 20px rgba(85,229,255,.035)}.stage.done{border-color:rgba(84,227,155,.2);color:#70dca4}
.result{margin-top:22px;border:1px solid var(--line);border-radius:22px;background:#080d11;overflow:hidden;animation:up .55s both}.resultHead{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:18px 20px;border-bottom:1px solid var(--line);flex-wrap:wrap}.resultTitle{display:flex;align-items:center;gap:10px}.okmark{width:30px;height:30px;border-radius:8px;display:grid;place-items:center;border:1px solid rgba(84,227,155,.2);color:var(--green);background:rgba(84,227,155,.04)}.resultTitle b{font-size:14px}.resultTitle small{display:block;color:#536b74;font-size:9px;margin-top:3px}.actions{display:flex;align-items:center;gap:7px}.smallbtn{border:1px solid #263740;border-radius:8px;background:#0b1217;color:#9db0b7;padding:8px 10px;cursor:pointer;font:800 9px ui-monospace,monospace}.smallbtn:hover{border-color:#38535d;color:#d4e9ed}.copied{color:var(--green);font:700 9px ui-monospace,monospace}.code{margin:14px;border:1px solid #182830;border-radius:14px;overflow:hidden;background:#040709}.codebar{height:33px;display:flex;align-items:center;justify-content:space-between;padding:0 11px;border-bottom:1px solid #15242b;color:#4e656d;font:700 8px ui-monospace,monospace}.code pre{margin:0;padding:18px;max-height:620px;overflow:auto;color:#d8e9ed;font:12px/1.7 ui-monospace,SFMono-Regular,Consolas,monospace;tab-size:4}.verify{margin:0 14px 16px;padding:13px;border:1px solid rgba(84,227,155,.18);border-radius:11px;background:rgba(84,227,155,.03);color:#718991;font-size:11px;line-height:1.65}.verify strong{color:#79e4a9}.verify.fail{border-color:rgba(255,104,126,.2);background:rgba(255,104,126,.025)}.verify.fail strong{color:#ff8c9d}
.engine{margin-top:24px;display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:10px}.card{border:1px solid var(--line);border-radius:16px;background:#090f13;padding:18px;min-height:135px;position:relative;overflow:hidden}.card:after{content:"";position:absolute;width:90px;height:90px;border-radius:50%;right:-30px;bottom:-40px;background:rgba(85,229,255,.035);filter:blur(2px)}.card b{font-size:12px}.card p{color:#617982;font-size:10px;line-height:1.65;margin:8px 0 0}.trace{margin-top:16px;height:3px;background:#14242a;position:relative;overflow:hidden}.trace:before{content:"";position:absolute;width:35%;height:100%;background:var(--cyan);box-shadow:0 0 12px var(--cyan);animation:trace 2.8s linear infinite}.footer{margin-top:50px;text-align:center;color:#40555e;font:700 8px ui-monospace,monospace;letter-spacing:.13em;text-transform:uppercase}
@keyframes pulse{50%{opacity:.35;transform:scale(.7)}}@keyframes spin{to{transform:rotate(360deg)}}@keyframes orbit{to{transform:rotate(360deg)}}@keyframes float{50%{transform:translateY(-15px) scale(1.03)}}@keyframes bob{50%{transform:translateY(5px)}}@keyframes scan{to{transform:translateY(300%)}}@keyframes up{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:none}}@keyframes trace{to{transform:translateX(360%)}}@media(max-width:800px){.galleryIntro{display:block}.galleryIntro p{margin-top:12px}.imageRail{grid-template-columns:1fr}.techImage,.techImage.tall{min-height:250px}.wrap{width:calc(100% - 18px)}.hero{min-height:610px}.hero h1{font-size:51px}.navright{display:none}.workhead,.workbody{padding:16px}.engine{grid-template-columns:1fr}.pipeline{grid-template-columns:repeat(3,1fr)}.controls{align-items:stretch}.generate{width:100%}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation-duration:.001ms!important;animation-iteration-count:1!important;scroll-behavior:auto!important;transition-duration:.001ms!important}}

.gallery{padding:20px 0 55px;position:relative}.galleryIntro{display:flex;align-items:end;justify-content:space-between;gap:30px;margin:0 4px 20px}.galleryIntro>span{color:#5d7780;font:800 9px ui-monospace,monospace;letter-spacing:.16em}.galleryIntro h2{font-size:clamp(28px,4vw,48px);letter-spacing:-.045em;margin:7px 0 0}.galleryIntro p{max-width:470px;color:#728891;line-height:1.7;font-size:13px;margin:0}.imageRail{display:grid;grid-template-columns:1.05fr .8fr 1fr;gap:12px}.techImage{position:relative;min-height:270px;margin:0;overflow:hidden;border:1px solid #1b2b32;border-radius:18px;background:#080d11;box-shadow:0 25px 70px rgba(0,0,0,.28)}.techImage.tall{min-height:340px}.techImage img{width:100%;height:100%;position:absolute;inset:0;object-fit:cover;filter:saturate(.72) contrast(1.08) brightness(.72);transform:scale(1.04);transition:transform .8s cubic-bezier(.2,.7,.2,1),filter .5s}.techImage:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,transparent 40%,rgba(3,7,10,.88) 100%)}.techImage:hover img{transform:scale(1.11);filter:saturate(.95) contrast(1.08) brightness(.86)}.techImage figcaption{position:absolute;z-index:2;left:15px;right:15px;bottom:14px;display:flex;justify-content:space-between;align-items:center;color:#d6eef2;font:800 9px ui-monospace,monospace;letter-spacing:.1em}.techImage figcaption b{color:var(--cyan)}
.signalField{padding:25px 0 55px}.signalHeader{display:flex;justify-content:space-between;align-items:end;gap:25px;margin:0 4px 18px}.signalHeader>div>span{color:#5d7780;font:800 9px ui-monospace,monospace;letter-spacing:.16em}.signalHeader h2{font-size:clamp(28px,4vw,48px);letter-spacing:-.045em;margin:7px 0 0}.signalHeader p{max-width:460px;color:#728891;font-size:13px;line-height:1.7;margin:0}.signalGrid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.schematicCard{border:1px solid #1a2b32;border-radius:18px;background:linear-gradient(145deg,#090f13,#070b0e);padding:15px;overflow:hidden;box-shadow:0 25px 70px rgba(0,0,0,.22)}.schematicTop{display:flex;justify-content:space-between;gap:10px;color:#607780;font:800 8px ui-monospace,monospace;letter-spacing:.12em}.schematicTop b{color:#9cc5cd}.schematicCard svg{width:100%;height:auto;display:block;margin:13px 0;color:#65818b}.schematicCard:hover svg{color:#8baeb7}.signalFoot{padding-top:10px;border-top:1px solid #14242b;color:#4d6871;font:800 8px ui-monospace,monospace;letter-spacing:.1em}@media(max-width:800px){.signalHeader{display:block}.signalHeader p{margin-top:10px}.signalGrid{grid-template-columns:1fr}}
.reveal{opacity:0;transform:translateY(28px);transition:opacity .8s ease,transform .8s ease}.reveal.visible{opacity:1;transform:none}
</style>
</head>
<body>
<div class="wrap">
<nav class="nav"><div class="brand"><div class="brandmark">RF</div><div><b>RTL FORGE</b><small>ECE hardware workbench</small></div></div><div class="navright"><span class="pulse"></span>LOCAL SIMULATION READY</div></nav>
<section class="hero"><div class="heroContent"><div class="eyebrow"><span class="pulse"></span> SYNTHESIS / SIMULATION / VERIFICATION</div><h1>Engineer the circuit.<br><span>Not the interface.</span></h1><p>Describe the digital hardware you need. RTL Forge generates synthesizable SystemVerilog, runs an independent simulation, and returns a clean engineering artifact.</p><div class="heroMeta"><span class="spec">SYSTEMVERILOG</span><span class="spec">IVERILOG</span><span class="spec">SELF-CHECKING TB</span><span class="spec">AUTO REPAIR</span></div><div class="scroll">ENTER WORKBENCH<i></i></div></div></section>
<section class="gallery reveal" id="visuals">
<div class="galleryIntro"><div><span>01 / HARDWARE VISUAL FIELD</span><h2>From gates to silicon.</h2></div><p>Real engineering references frame the workspace: circuit boards, digital hardware, FPGA development and physical electronics.</p></div>
<div class="imageRail">
<figure class="techImage tall"><img loading="lazy" src="https://images.unsplash.com/photo-1592659762303-90081d34b277?auto=format&fit=crop&w=1400&q=85" alt="Electronics circuit board"><figcaption><b>01</b><span>PCB / SIGNAL PATHS</span></figcaption></figure>
<figure class="techImage"><img loading="lazy" src="https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1400&q=85" alt="Electronic components"><figcaption><b>02</b><span>DIGITAL HARDWARE</span></figcaption></figure>
<figure class="techImage tall"><img loading="lazy" src="https://images.unsplash.com/photo-1519389950473-47ba0277781c?auto=format&fit=crop&w=1200&q=82" alt="Engineering workstation"><figcaption><b>03</b><span>ENGINEERING LAB</span></figcaption></figure>
</div></section>
<section class="signalField reveal">
<div class="signalHeader"><div><span>02 / DIGITAL DESIGN FIELD</span><h2>Signals. States. Structure.</h2></div><p>Static engineering visuals make the workspace feel like a hardware lab rather than a chat application.</p></div>
<div class="signalGrid">
<div class="schematicCard"><div class="schematicTop"><span>COMBINATIONAL</span><b>4:1 SELECT PATH</b></div><svg viewBox="0 0 520 180" role="img" aria-label="Multiplexer schematic"><g fill="none" stroke="currentColor" stroke-width="2"><path d="M25 30H160M25 70H160M25 110H160M25 150H160"/><path d="M360 90H500"/><path d="M160 30L280 58M160 70L280 72M160 110L280 88M160 150L280 102"/><path d="M280 58L360 90M280 72L360 90M280 88L360 90M280 102L360 90"/><path d="M280 58L330 150M280 102L330 30"/></g><path d="M280 58L360 90" stroke="var(--cyan)" stroke-width="5"/><rect x="270" y="45" width="75" height="90" rx="8" fill="rgba(85,229,255,.035)" stroke="rgba(85,229,255,.4)"/><text x="292" y="95" fill="currentColor" stroke="none" font-size="12" font-family="monospace">MUX</text></svg><div class="signalFoot">A0 · A1 · A2 · A3 → Y</div></div>
<div class="schematicCard"><div class="schematicTop"><span>SEQUENTIAL</span><b>STATE MACHINE</b></div><svg viewBox="0 0 520 180" role="img" aria-label="Finite state machine diagram"><g fill="rgba(255,255,255,.02)" stroke="currentColor" stroke-width="2"><circle cx="110" cy="90" r="40"/><circle cx="270" cy="45" r="40"/><circle cx="270" cy="135" r="40"/><circle cx="430" cy="90" r="40"/></g><g fill="currentColor" stroke="none" font-size="11" font-family="monospace" text-anchor="middle"><text x="110" y="94">IDLE</text><text x="270" y="49">LOAD</text><text x="270" y="139">RUN</text><text x="430" y="94">DONE</text></g><g fill="none" stroke="var(--cyan)" stroke-width="2"><path d="M145 72L232 54M145 108L232 126M310 45H392M310 135L392 105"/><path d="M430 50C480 10 500 150 430 130"/></g></svg><div class="signalFoot">CLOCK · RESET · ENABLE · TRANSITIONS</div></div>
<div class="schematicCard"><div class="schematicTop"><span>VERIFICATION</span><b>WAVEFORM TRACE</b></div><svg viewBox="0 0 520 180" role="img" aria-label="Digital waveform"><g stroke="#22353d" stroke-width="1"><path d="M0 30H520M0 75H520M0 120H520M0 165H520"/><path d="M40 0V180M100 0V180M160 0V180M220 0V180M280 0V180M340 0V180M400 0V180M460 0V180"/></g><path d="M0 48H50V15H110V48H170V15H230V48H290V15H350V48H410V15H470V48H520" fill="none" stroke="var(--cyan)" stroke-width="4"/><path d="M0 130H90V100H180V130H270V100H360V130H450V100H520" fill="none" stroke="var(--green)" stroke-width="3"/></svg><div class="signalFoot">CLK / DATA · EDGE · LATENCY · PASS</div></div>
</div></section>
<section id="workbench" class="workbench">
<div class="workhead"><div><div class="sectionnum">01 / HARDWARE SPECIFICATION</div><h2>Describe the circuit you want to build</h2></div><div class="mode">VERILOG • SYSTEMVERILOG</div></div>
<div class="workbody"><div class="editor"><div class="editorbar"><div class="traffic"><i></i><i></i><i></i></div><div class="editorfile">hardware_requirement.txt</div><div class="editorlang">NATURAL LANGUAGE</div></div><textarea id="req" maxlength="5000" placeholder="Describe ANY digital ECE hardware: UART, SPI, I2C, FIFO, FSM, RAM, ALU, PWM, DSP block, processor datapath, custom controller…"></textarea><div class="editorfoot"><span>PLAIN LANGUAGE → RTL</span><span><span id="count">0</span> / 5000</span></div></div>
<div class="examples"><span class="exampleLabel">REFERENCE BUILDS — NOT LIMITS</span><button class="chip" onclick="usePrompt('Design a UART transmitter with configurable baud divider, 8-N-1 framing and tx_busy status.')">UART TX</button><button class="chip" onclick="usePrompt('Design a synchronous FIFO with 16 entries, 8-bit data, full and empty flags, and safe simultaneous read/write behavior.')">16×8 FIFO</button><button class="chip" onclick="usePrompt('Design an SPI master with configurable clock divider, CPOL/CPHA mode, 8-bit transfers and chip-select control.')">SPI MASTER</button><button class="chip" onclick="usePrompt('Design an 8-bit ALU supporting ADD, SUB, AND, OR and XOR with zero and carry flags.')">8-BIT ALU</button><button class="chip" onclick="usePrompt('Design a parameterized PWM generator with programmable period and duty cycle, synchronous reset and an enable input.')">PWM</button></div>
<div class="controls"><div class="shortcut"><span class="key">⌘</span> + <span class="key">ENTER</span> TO GENERATE</div><button id="generate" class="generate" onclick="build()">GENERATE & VERIFY HDL&nbsp; →</button></div>
<div id="status" class="status"></div><div id="pipeline" class="pipeline hidden"><div class="stage" id="s1">SPECIFY</div><div class="stage" id="s2">ARCHITECT</div><div class="stage" id="s3">GENERATE RTL</div><div class="stage" id="s4">COMPILE</div><div class="stage" id="s5">SIMULATE</div><div class="stage" id="s6">VERIFY</div></div></div></section>
<section id="result" class="result hidden"><div class="resultHead"><div class="resultTitle"><div class="okmark">✓</div><div><b id="resultHeading">Verified RTL</b><small>clean engineering output • internal reasoning hidden</small></div></div><div class="actions"><button class="smallbtn" onclick="downloadCode()">DOWNLOAD .SV</button><button class="smallbtn" onclick="copyCode()">COPY</button><span id="copied" class="copied"></span></div></div><div class="code"><div class="codebar"><span>generated_design.sv</span><span>SYSTEMVERILOG</span></div><pre id="rtl"></pre></div><div id="verify" class="verify"><strong>Verification</strong><br>Waiting for result.</div></section>
<section class="engine"><div class="card"><b>Hardware-first workflow</b><p>Natural-language requirements are translated into a DUT and a separate self-checking verification environment. The interface exposes the engineering result rather than an AI chat transcript.</p><div class="trace"></div></div><div class="card"><b>Local objective check</b><p>Icarus Verilog compiles the generated project and runs the testbench before the result is marked verified.</p></div><div class="card"><b>Bounded recovery</b><p>If simulation fails, the backend can make one focused repair attempt instead of entering a long multi-agent retry loop.</p></div></section>
<div class="footer">RTL FORGE • ECE RTL ENGINEERING WORKBENCH</div>
</div>
<script>
let generated='';let timer=null;const req=document.getElementById('req');
req.addEventListener('input',()=>document.getElementById('count').textContent=req.value.length);
req.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key==='Enter'){e.preventDefault();build()}});
function usePrompt(t){req.value=t;document.getElementById('count').textContent=t.length;document.getElementById('workbench').scrollIntoView({behavior:'smooth',block:'center'});setTimeout(()=>req.focus(),400)}
function stages(n){for(let i=1;i<=6;i++){const x=document.getElementById('s'+i);x.classList.toggle('active',i===n);x.classList.toggle('done',i<n)}}
function start(){document.getElementById('pipeline').classList.remove('hidden');stages(1);let n=1;clearInterval(timer);timer=setInterval(()=>{if(n<6){n++;stages(n)}},1300)}
function stop(ok){clearInterval(timer);stages(ok?6:1)}
function setStatus(kind,msg){document.getElementById('status').innerHTML='<div class="notice '+kind+'">'+msg+'</div>'}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function build(){const text=req.value.trim(),btn=document.getElementById('generate');if(!text){setStatus('err','Enter a hardware requirement first.');req.focus();return}btn.disabled=true;btn.innerHTML='<span class="spinner"></span>&nbsp; SYNTHESIZING…';document.getElementById('result').classList.add('hidden');setStatus('', '<span class="spinner"></span>&nbsp; Running engineering stages — RTL → compile → simulation → verification…');start();try{const r=await fetch('/api/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request:text})});const raw=await r.text();let d={};try{d=raw?JSON.parse(raw):{}}catch(_){throw new Error('The server returned an invalid response. Check the Render deploy logs.')}if(!r.ok)throw new Error(d.message||d.error||'Hardware generation failed.');generated=d.rtl||'';document.getElementById('rtl').textContent=generated;const v=d.verification||{};if(v.passed){setStatus('ok','✓ DESIGN VERIFIED — compilation and self-checking simulation passed.');document.getElementById('verify').className='verify';document.getElementById('verify').innerHTML='<strong>✓ Verification passed</strong><br>Icarus compiled the RTL and the independent testbench reported TEST_RESULT: PASS.'+(d.repair_attempted?' <span style="color:#7aa1aa">One bounded repair pass was used.</span>':'');document.getElementById('resultHeading').textContent='Verified RTL';stop(true)}else{setStatus('err','⚠ RTL generated, but verification did not pass.');document.getElementById('verify').className='verify fail';const detail = v.stage ? (' Stage: '+esc(v.stage)+'.') : '';
const logText = v.log ? String(v.log).trim().split('\\n').filter(Boolean).slice(-3).map(esc).join('<br>') : '';
document.getElementById('verify').innerHTML='<strong>⚠ Verification did not pass</strong><br>The RTL is shown for inspection, but it should not be treated as verified.'+detail+(logText?'<br><span style="color:#617982">'+logText+'</span>':'');document.getElementById('resultHeading').textContent='Generated RTL';stop(false)}document.getElementById('result').classList.remove('hidden');requestAnimationFrame(()=>document.getElementById('result').scrollIntoView({behavior:'smooth',block:'start'}))}catch(e){clearInterval(timer);setStatus('err','✕ '+esc(e.message||String(e)));document.getElementById('pipeline').classList.add('hidden')}finally{btn.disabled=false;btn.textContent='GENERATE & VERIFY HDL  →'}}
async function copyCode(){if(!generated)return;try{await navigator.clipboard.writeText(generated);document.getElementById('copied').textContent='COPIED';setTimeout(()=>document.getElementById('copied').textContent='',1400)}catch(_){document.getElementById('copied').textContent='COPY FAILED'}}
function downloadCode(){if(!generated)return;const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([generated],{type:'text/plain'}));a.download='generated_design.sv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
const observer=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting)e.target.classList.add('visible')}),{threshold:.12});document.querySelectorAll('.reveal').forEach(el=>observer.observe(el));
</script>
</body></html>'''

# -----------------------------
# Safe helpers
# -----------------------------
def clean_code(text):
    if not isinstance(text,str): return ''
    m=re.search(r"```(?:systemverilog|verilog|sv)?\s*(.*?)```",text,re.I|re.S)
    return (m.group(1) if m else text).strip()

def unsafe_reason(code):
    if not isinstance(code, str) or not code.strip():
        return "empty HDL output"
    rules = [
        (r"\$system\b", "$system host command"),
        (r"\$popen\b", "$popen host process"),
        (r"\$fopen\b|\$fclose\b|\$fwrite\b|\$fdisplay\b|\$fscanf\b|\$fread\b", "host file I/O"),
        (r"\$writemem\b", "$writemem host file access"),
        (r"DPI-C", "DPI-C external code"),
        (r"\bimport\s+\"", "external DPI/import code"),
    ]
    for pattern, label in rules:
        if re.search(pattern, code, re.I):
            return label
    return None

def safe_hdl(code):
    return unsafe_reason(code) is None

def json_from(text):
    text=clean_code(text)
    try:return json.loads(text)
    except Exception:
        m=re.search(r"\{.*\}",text,re.S)
        if not m: raise ValueError("Model returned invalid JSON")
        return json.loads(m.group(0))

def model_list():
    return list(dict.fromkeys([MODEL]+FALLBACK_MODELS))

def api_code(exc):
    for a in ('code','status_code','http_status'):
        v=getattr(exc,a,None)
        try:
            if v is not None:return int(v)
        except Exception:pass
    m=re.search(r'\b(400|401|403|404|408|429|500|502|503|504)\b',str(exc))
    return int(m.group(1)) if m else None

def gemini_call(prompt):
    """Bounded Gemini call: at most one request per configured model.

    This is deliberately short-lived because Render must receive a JSON response
    before its proxy/worker timeout. A provider outage must never turn into a
    long retry storm.
    """
    if client is None:
        raise RuntimeError('Gemini API key is not configured on the server.')

    errors = []
    started = time.monotonic()
    models = model_list()[:3]

    for model in models:
        if time.monotonic() - started >= MAX_BUILD_SECONDS:
            break
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(max_output_tokens=12000),
            )
            text = (getattr(response, 'text', None) or '').strip()
            if text:
                return text
            errors.append((model, None, 'empty response'))
        except Exception as exc:
            code = api_code(exc)
            errors.append((model, code, str(exc)))
            if code in (401, 403):
                raise RuntimeError(
                    'Gemini API authentication/permission failed. Check GEMINI_API_KEY and project/model access.'
                )
            # Never retry the same model here. Move directly to the next model.
            continue

    summary = ', '.join(f'{m}:{c or "error"}' for m, c, _ in errors)
    if errors and all((c in (408, 429, 500, 502, 503, 504) or c is None) for _, c, _ in errors):
        raise RuntimeError(
            'Gemini is temporarily unavailable across the configured models. '
            'No HDL was fabricated or executed. Retry the build shortly. Attempt summary: ' + summary
        )
    raise RuntimeError(
        'Gemini generation failed across the configured models. Check API key, model access, and quota. '
        'Attempt summary: ' + summary
    )

def prompt_for_design(user_request):
    return f'''You are a senior digital RTL engineer. Convert the user's hardware requirement into ONE complete JSON object.
Return ONLY JSON, no markdown.
Keys:
rtl: synthesizable SystemVerilog DUT code

testbench: independent self-checking SystemVerilog testbench

design_name: concise name

Rules:
- Infer the architecture from the natural-language requirement; do not restrict yourself to examples.
- RTL must be synthesizable SystemVerilog and must compile under Icarus Verilog -g2012.
- Testbench must instantiate the DUT exactly and independently calculate expected behavior.
- Testbench must exercise reset/clock behavior when applicable, boundary cases, and normal cases.
- Testbench must print exactly TEST_RESULT: PASS only if every check passes; otherwise TEST_RESULT: FAIL.
- Do not weaken tests to make them pass.
- No shell, filesystem, network, DPI, or vendor-specific constructs.
- Prefer straightforward robust RTL over clever code.
- Include a module named tb in the testbench.
- Return useful mismatch messages.

USER REQUIREMENT:
{user_request}'''

def repair_prompt(user_request,rtl,tb,log):
    return f'''You are a senior RTL debug engineer. Repair the following SystemVerilog project after an objective Icarus compile/simulation failure.
Return ONLY JSON with keys rtl and testbench.
Keep the intended behavior. Do not remove checks or weaken the testbench merely to obtain PASS. Fix interface, reset, timing, syntax, or expected-model mistakes as appropriate.
The testbench must still independently verify the DUT and print TEST_RESULT: PASS only when all checks pass.

REQUIREMENT:
{user_request}

RTL:
```systemverilog
{rtl}
```

TESTBENCH:
```systemverilog
{tb}
```

FAILURE LOG:
{log[-12000:]}'''

# -----------------------------
# General-purpose ECE RTL build pipeline
# -----------------------------
def simulate(rtl, tb, job, deadline=None):
    """Compile and simulate with a hard per-process and overall build deadline."""
    job = Path(job)
    dut = job / 'design.sv'
    bench = job / 'testbench.sv'
    out = job / 'sim.out'
    dut.write_text(rtl, encoding='utf-8')
    bench.write_text(tb, encoding='utf-8')

    def remaining(default):
        if deadline is None:
            return default
        left = deadline - time.monotonic()
        if left <= 0:
            return 0
        return min(float(default), left)

    compile_timeout = remaining(SIM_TIMEOUT)
    if compile_timeout <= 0:
        return {'passed': False, 'stage': 'compile', 'log': 'Build deadline reached before compilation.'}

    try:
        cp = subprocess.run(
            ['iverilog', '-g2012', '-s', 'tb', '-o', str(out), str(dut), str(bench)],
            capture_output=True, text=True, timeout=compile_timeout
        )
    except FileNotFoundError:
        return {'passed': False, 'stage': 'compile', 'log': 'iverilog is not installed on the server.'}
    except subprocess.TimeoutExpired:
        return {'passed': False, 'stage': 'compile', 'log': 'Compilation timed out before the build deadline.'}

    if cp.returncode != 0:
        return {
            'passed': False,
            'stage': 'compile',
            'log': (cp.stdout + '\n' + cp.stderr)[-16000:]
        }

    sim_timeout = remaining(SIM_TIMEOUT)
    if sim_timeout <= 0:
        return {'passed': False, 'stage': 'simulation', 'log': 'Build deadline reached before simulation.'}

    try:
        sp = subprocess.run(
            ['vvp', str(out)],
            cwd=job,
            capture_output=True,
            text=True,
            timeout=sim_timeout
        )
    except subprocess.TimeoutExpired:
        return {'passed': False, 'stage': 'simulation', 'log': 'Simulation timed out before the build deadline.'}

    log = (sp.stdout or '') + '\n' + (sp.stderr or '')
    passed = (
        sp.returncode == 0
        and 'TEST_RESULT: PASS' in log
        and 'TEST_RESULT: FAIL' not in log
    )
    return {'passed': passed, 'stage': 'simulation', 'log': log[-16000:]}


# This schema is deliberately general: there is no fixed circuit catalogue.
DESIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "design_name": {"type": "string"},
        "rtl": {"type": "string"},
        "testbench": {"type": "string"}
    },
    "required": ["design_name", "rtl", "testbench"]
}


def prompt_for_design(user_request):
    return f"""
You are the GENERAL-PURPOSE ECE DIGITAL RTL ENGINEER for an autonomous hardware
engineering workbench.

The user may request ANY digital electronic circuit or digital hardware subsystem.
There is NO fixed circuit catalogue and NO whitelist of supported designs.

You must handle, when applicable:
- combinational and sequential logic
- arithmetic/datapath units
- FSMs and controllers
- counters, timers and pulse generators
- registers and register files
- RAM/ROM/memories/FIFOs
- UART, SPI, I2C and other digital communication blocks
- bus peripherals and register interfaces
- ALUs, multipliers, dividers and pipelines
- encoders/decoders, mux/demux and arbiters
- CRC, parity and error-detection logic
- PWM, digital filters and DSP-oriented blocks
- clock/reset/control logic
- processor/datapath components
- parameterized and configurable RTL
- FPGA/ASIC-oriented synthesizable digital blocks
- unusual or novel digital architectures described by the user

The examples in the website UI are ONLY examples. Never restrict the user's
request to those examples.

ENGINEERING PROCESS:
1. Parse the natural-language requirement.
2. Infer a reasonable hardware architecture.
3. Identify inputs, outputs, parameters, clocking, reset semantics, latency,
   state behavior and corner cases.
4. Generate synthesizable SystemVerilog.
5. Generate an INDEPENDENT self-checking SystemVerilog testbench.
6. The testbench must determine expected behavior from the stated specification,
   not by duplicating the DUT implementation.
7. Make the testbench strong enough to detect realistic RTL mistakes.
8. Make the project compile with Icarus Verilog -g2012.
9. If sequential logic is required, correctly model clock, reset, latency and
   state transitions.
10. If the requirement is underspecified, choose a reasonable engineering
    default and make the interface/behavior internally consistent.

RTL REQUIREMENTS:
- Return complete synthesizable SystemVerilog.
- No vendor-specific primitives unless explicitly requested.
- No shell, filesystem, network, DPI or simulator-control constructs in the DUT.
- No testbench code inside the DUT.
- Use clear module/port declarations.
- Do not invent features not requested unless necessary to make the design coherent.
- Preserve exact requested widths, active levels and timing behavior.
- Parameterize the design when the requirement calls for configurability.

TESTBENCH REQUIREMENTS:
- The top-level testbench module MUST be named `tb`.
- Instantiate the generated DUT exactly.
- Build an independent reference/expected model.
- Exercise normal operation and important boundary/corner cases.
- Exercise reset and clock behavior when applicable.
- Use exhaustive tests for small state/input spaces when practical.
- Otherwise use directed and/or constrained randomized tests.
- Print useful mismatch information.
- Print exactly `TEST_RESULT: PASS` only when all checks pass.
- Print `TEST_RESULT: FAIL` if any check fails.
- Do not weaken or remove checks just to obtain PASS.
- Do not simply copy the DUT's equations into the expected model.
- Avoid unnecessary long-running simulations.

SAFETY:
- Do not generate $system, $popen, $fopen, $fwrite, $fdisplay, $fscanf, $fread,
  file-writing, network access, DPI-C, shell commands, or other host-control mechanisms.
- `$readmemh`/`$readmemb` are permitted only when genuinely needed for ROM/memory
  initialization; never use arbitrary paths or external user-controlled files.
- Keep generated artifacts self-contained.

IMPORTANT:
Do not explain your reasoning.
Return ONLY the requested structured object.

USER HARDWARE REQUIREMENT:
{user_request}
"""


def repair_prompt(user_request, rtl, tb, log):
    return f"""
You are the GENERAL-PURPOSE ECE RTL DEBUG AND REPAIR ENGINEER.

A digital hardware design generated from the user's requirement failed objective
Icarus compilation or simulation.

Repair the project while preserving the user's intended hardware behavior.
This is NOT a fixed-circuit repair task. The design may be any digital ECE block.

Diagnose the failure using the original requirement, RTL, testbench, and objective
compiler/simulation log.

Correct syntax, module interfaces, widths, signedness, reset behavior, clocking,
state transitions, latency assumptions, reference-model mistakes, race conditions,
or other genuine issues as appropriate.

Rules:
- Return ONLY JSON with `rtl` and `testbench`.
- Keep the intended functionality.
- Do NOT delete verification checks just to make the test pass.
- Do NOT weaken the expected model.
- The testbench must remain independently self-checking.
- The testbench top module must remain `tb`.
- RTL must remain synthesizable SystemVerilog.
- Do not add shell, filesystem, network, DPI or host-control constructs.
- Make the corrected project compile under Icarus Verilog -g2012.

USER REQUIREMENT:
{user_request}

RTL:
```systemverilog
{rtl}
```

TESTBENCH:
```systemverilog
{tb}
```

OBJECTIVE FAILURE LOG:
{log[-16000:]}
"""


def build_project(user_request):
    build_started = time.monotonic()
    deadline = build_started + MAX_BUILD_SECONDS
    job = JOB_ROOT / uuid.uuid4().hex[:12]
    job.mkdir(parents=True, exist_ok=True)

    def ensure_budget(message):
        if time.monotonic() >= deadline:
            raise TimeoutError(message)

    try:
        # One generation call for arbitrary ECE designs.
        ensure_budget('Build safety deadline reached before generation.')
        data = json_from(gemini_call(prompt_for_design(user_request)))
        rtl = clean_code(data.get('rtl', ''))
        tb = clean_code(data.get('testbench', ''))
        name = str(data.get('design_name', 'General ECE RTL design')).strip() or 'General ECE RTL design'

        repair_attempted = False
        safety_issue = unsafe_reason(rtl) or unsafe_reason(tb)

        # Safety violations are repaired by the same bounded repair channel.
        if safety_issue:
            if MAX_REPAIR_ATTEMPTS <= 0:
                raise RuntimeError(
                    f'Generated HDL contains a blocked construct ({safety_issue}) and no safety repair is enabled. Nothing was executed.'
                )
            repair_attempted = True
            ensure_budget('Build safety deadline reached before safety repair.')
            safety_log = f"SAFETY VALIDATION FAILURE: {safety_issue}"
            repaired = json_from(gemini_call(repair_prompt(user_request, rtl, tb, safety_log)))
            rtl2 = clean_code(repaired.get('rtl', ''))
            tb2 = clean_code(repaired.get('testbench', ''))
            second_issue = unsafe_reason(rtl2) or unsafe_reason(tb2)
            if second_issue:
                raise RuntimeError(
                    f'Generated HDL still contains a blocked construct ({second_issue}) after the bounded safety repair. '
                    'Nothing was executed.'
                )
            rtl, tb = rtl2, tb2

        if not rtl or not tb:
            raise RuntimeError('Gemini did not return both RTL and a testbench.')

        ensure_budget('Build safety deadline reached before simulation.')
        sim = simulate(rtl, tb, job, deadline)

        # At most one objective repair call. The repair and re-simulation share the same hard deadline.
        if not sim['passed'] and MAX_REPAIR_ATTEMPTS > 0 and not repair_attempted:
            repair_attempted = True
            ensure_budget('Build safety deadline reached before repair.')
            repaired = json_from(gemini_call(repair_prompt(user_request, rtl, tb, sim['log'])))
            rtl2 = clean_code(repaired.get('rtl', ''))
            tb2 = clean_code(repaired.get('testbench', ''))

            second_issue = unsafe_reason(rtl2) or unsafe_reason(tb2)
            if second_issue:
                raise RuntimeError(
                    f'Repair generated a blocked construct ({second_issue}). The repaired project was not executed.'
                )

            if not rtl2 or not tb2:
                raise RuntimeError('Repair response did not contain both RTL and a testbench.')

            rtl, tb = rtl2, tb2
            ensure_budget('Build safety deadline reached before repaired simulation.')
            sim = simulate(rtl, tb, job, deadline)

        (job / 'design.sv').write_text(rtl, encoding='utf-8')
        (job / 'testbench.sv').write_text(tb, encoding='utf-8')
        (job / 'simulation.log').write_text(sim.get('log', ''), encoding='utf-8')
        (job / 'request.txt').write_text(user_request, encoding='utf-8')

        return {
            'rtl': rtl,
            'verification': sim,
            'design_name': name,
            'job_id': job.name,
            'repair_attempted': repair_attempted,
            'general_purpose': True
        }

    except Exception:
        shutil.rmtree(job, ignore_errors=True)
        raise


# -----------------------------
# Routes
# -----------------------------
@app.get('/')
def home():return render_template_string(HTML)

@app.get('/health')
def health():
    return jsonify({'status':'ok','gemini_configured':client is not None,'gemini_model':MODEL,'gemini_fallback_models':FALLBACK_MODELS,'max_repair_attempts':MAX_REPAIR_ATTEMPTS,'gemini_request_timeout_seconds':REQUEST_TIMEOUT,'max_build_seconds':MAX_BUILD_SECONDS,'max_gemini_models_per_call':3,'iverilog':shutil.which('iverilog') is not None,'vvp':shutil.which('vvp') is not None,'version':'rtl-forge-general-ece-5.1','general_purpose':True,'hardcoded_demo_fallback':False})

@app.post('/api/build')
def api_build():
    data=request.get_json(silent=True) or {};user_request=str(data.get('request','')).strip()
    if not user_request:return jsonify({'error':'Please provide a hardware requirement.','message':'Please provide a hardware requirement.'}),400
    if len(user_request)>5000:return jsonify({'error':'Hardware requirement is too long.','message':'Hardware requirement is limited to 5000 characters.'}),400
    try:
        result=build_project(user_request)
        return jsonify(result)
    except TimeoutError as exc:
        msg = str(exc)
        return jsonify({
            'error': msg,
            'message': msg,
            'code': 'build_timeout',
            'verification': {'passed': False, 'stage': 'deadline'}
        }), 504
    except Exception as exc:
        msg=str(exc)
        # Never leak stack traces or HTML to the frontend.
        return jsonify({
            'error':msg,
            'message':msg,
            'code':getattr(exc,'code','build_failed'),
            'verification':{'passed':False}
        }), 503

@app.get('/api/download/<job_id>')
def download(job_id):
    path=JOB_ROOT/job_id/'design.sv'
    if not path.exists():return jsonify({'error':'Build artifact not found.'}),404
    return send_file(path,as_attachment=True,download_name='generated_design.sv')

@app.errorhandler(Exception)
def handle_unexpected(exc):
    return jsonify({'error':'Server error. Please try the build again.','message':'Server error. Please try the build again.'}),500

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))
