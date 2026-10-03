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
<meta name="theme-color" content="#090b0c">
<title>RTL Forge — Digital Hardware Workstation</title>
<style>
:root{--bg:#090b0c;--panel:#111516;--panel2:#151a1a;--line:#303938;--line2:#4a5551;--text:#edf1ed;--muted:#929b98;--dim:#69736f;--lime:#c7ff4d;--cyan:#6ee7e0;--orange:#ffad5c;--red:#ff6f72;--blue:#8fb8ff;--shadow:0 28px 80px rgba(0,0,0,.4)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 12% 5%,rgba(199,255,77,.05),transparent 25%),radial-gradient(circle at 88% 20%,rgba(110,231,224,.045),transparent 25%),linear-gradient(180deg,#080a0b,#0b0e0f 50%,#080a0b);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow-x:hidden}body:before{content:"";position:fixed;inset:0;pointer-events:none;z-index:-2;background-image:linear-gradient(rgba(255,255,255,.022) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.022) 1px,transparent 1px);background-size:36px 36px;mask-image:linear-gradient(#000,transparent 82%)}body:after{content:"";position:fixed;top:-15%;left:0;width:100%;height:15%;pointer-events:none;z-index:60;background:linear-gradient(transparent,rgba(199,255,77,.035),transparent);animation:scan 13s linear infinite}button,textarea{font:inherit}.shell{width:min(1420px,calc(100% - 34px));margin:auto;padding-bottom:90px}#scrollProgress{position:fixed;left:0;top:0;width:0;height:2px;background:var(--lime);box-shadow:0 0 12px rgba(199,255,77,.55);z-index:100}
.nav{height:64px;margin-top:12px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:50;background:rgba(9,11,12,.88);backdrop-filter:blur(16px)}.brand{display:flex;align-items:center;gap:11px}.brandmark{width:34px;height:34px;border:1px solid var(--line2);background:#151919;display:grid;place-items:center;color:var(--lime);font:900 10px ui-monospace,monospace;position:relative}.brandmark:after{content:"";position:absolute;right:-4px;bottom:-4px;width:7px;height:7px;background:var(--lime)}.brand b{font-size:12px;letter-spacing:.1em}.brand small{display:block;color:var(--dim);font:800 7px ui-monospace,monospace;letter-spacing:.18em;margin-top:3px}.navlinks{display:flex;gap:18px}.navlinks a{color:#737d79;text-decoration:none;font:800 8px ui-monospace,monospace;letter-spacing:.12em}.navlinks a:hover{color:var(--lime)}.health{display:flex;gap:7px;align-items:center;color:#7f8985;font:800 8px ui-monospace,monospace}.health i{width:6px;height:6px;border-radius:50%;background:var(--lime);box-shadow:0 0 12px rgba(199,255,77,.7);animation:pulse 1.8s infinite}
.hero{min-height:700px;display:grid;grid-template-columns:1.05fr .95fr;align-items:center;gap:30px}.heroCopy{padding:70px 0}.eyebrow{display:inline-flex;gap:8px;align-items:center;border:1px solid var(--line2);padding:7px 9px;background:#111516;color:#aab4b0;font:900 8px ui-monospace,monospace;letter-spacing:.15em}.eyebrow b{color:var(--lime)}.hero h1{font-size:clamp(55px,7.5vw,101px);line-height:.86;letter-spacing:-.075em;margin:24px 0 20px;max-width:850px}.hero h1 span{display:block;color:#737b78}.hero h1 em{font-style:normal;color:var(--lime)}.hero p{max-width:680px;color:#919b97;line-height:1.8;font-size:14px}.heroStats{display:flex;margin-top:30px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);width:max-content}.stat{padding:13px 20px 12px 0;margin-right:20px;border-right:1px solid var(--line)}.stat:last-child{border-right:0}.stat b{display:block;font-size:14px}.stat span{color:#65706d;font:800 7px ui-monospace,monospace;letter-spacing:.12em}.scrollCue{margin-top:42px;color:#626d69;font:900 8px ui-monospace,monospace;letter-spacing:.16em}.scrollCue:after{content:"↓";display:inline-block;margin-left:10px;color:var(--lime);animation:bob 1.4s infinite}.heroVisual{height:550px;position:relative;display:grid;place-items:center;perspective:1100px;transition:transform .15s linear}.board3d{width:min(510px,90%);aspect-ratio:1.35/1;border:1px solid #46514d;background:linear-gradient(135deg,#181d1c,#0d1111 52%,#171c19);transform:rotateX(58deg) rotateZ(-28deg);box-shadow:30px 45px 0 rgba(0,0,0,.22),0 80px 100px rgba(0,0,0,.4),inset 0 0 60px rgba(199,255,77,.035);position:relative;animation:boardFloat 7s ease-in-out infinite;overflow:hidden}.board3d:before{content:"";position:absolute;inset:22px;background:repeating-linear-gradient(90deg,transparent 0 31px,rgba(199,255,77,.09) 32px,transparent 33px),repeating-linear-gradient(0deg,transparent 0 25px,rgba(110,231,224,.08) 26px,transparent 27px)}.board3d:after{content:"";position:absolute;width:120px;height:120px;border:1px solid rgba(199,255,77,.25);background:#111716;left:42%;top:35%;box-shadow:0 0 0 12px rgba(199,255,77,.025),0 0 35px rgba(199,255,77,.08);animation:chipPulse 3s ease-in-out infinite}.traceLine{position:absolute;height:1px;background:var(--lime);box-shadow:0 0 8px rgba(199,255,77,.5);transform-origin:left center}.t1{width:170px;left:4%;top:27%;transform:rotate(7deg)}.t2{width:220px;right:2%;top:65%;transform:rotate(-8deg);background:var(--cyan)}.t3{width:150px;left:12%;bottom:17%;transform:rotate(-12deg);background:var(--orange)}.node{position:absolute;width:7px;height:7px;border:1px solid #0a0c0d;background:var(--lime);z-index:2}.n1{left:9%;top:26%}.n2{right:8%;top:64%;background:var(--cyan)}.n3{left:18%;bottom:16%;background:var(--orange)}.floatCard{position:absolute;border:1px solid var(--line2);background:rgba(17,22,22,.88);backdrop-filter:blur(12px);padding:12px;box-shadow:var(--shadow);font:800 8px ui-monospace,monospace;color:#a0aaa6;animation:cardFloat 5s ease-in-out infinite}.floatCard b{display:block;color:var(--lime);font-size:11px;margin-bottom:5px}.fc1{top:15%;right:2%}.fc2{bottom:14%;left:4%;animation-delay:-2s}
.section{padding:72px 0 18px}.sectionHead{display:flex;justify-content:space-between;align-items:end;gap:35px;margin-bottom:22px}.kicker{color:#68736f;font:900 8px ui-monospace,monospace;letter-spacing:.18em}.sectionHead h2{font-size:clamp(30px,4vw,56px);letter-spacing:-.065em;margin:7px 0 0}.sectionHead p{max-width:470px;color:#77817e;font-size:12px;line-height:1.75;margin:0}.visualRail{display:grid;grid-template-columns:1.15fr .85fr 1fr;gap:12px}.techShot{height:330px;position:relative;overflow:hidden;border:1px solid #303938;background:#111515}.techShot.tall{height:390px}.techShot img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:grayscale(.25) saturate(.6) contrast(1.12) brightness(.56);transform:scale(1.02);transition:1s cubic-bezier(.2,.7,.2,1)}.techShot:hover img{transform:scale(1.1);filter:grayscale(.05) saturate(.9) contrast(1.08) brightness(.73)}.techShot:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,transparent 44%,rgba(5,7,7,.95));pointer-events:none}.techShot figcaption{position:absolute;z-index:2;left:15px;right:15px;bottom:13px;display:flex;justify-content:space-between;color:#dfe5e1;font:900 8px ui-monospace,monospace;letter-spacing:.1em}.techShot figcaption b{color:var(--lime)}
.motifGrid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.motif{border:1px solid #303938;background:#101415;min-height:220px;padding:14px;position:relative;overflow:hidden}.motif:hover{border-color:#56615d}.motifTop{display:flex;justify-content:space-between;color:#6c7773;font:900 7px ui-monospace,monospace;letter-spacing:.14em}.motifTop b{color:var(--lime)}.motif svg{width:100%;height:155px;margin-top:10px}
.workstation:before{content:"";display:block;height:2px;background:linear-gradient(90deg,transparent,var(--lime),var(--cyan),transparent);opacity:.55}.workstation{margin-top:28px;margin-bottom:12px;border:1px solid #38413f;background:#101415;box-shadow:var(--shadow)}.stationHead{display:grid;grid-template-columns:1fr auto;border-bottom:1px solid #303938;padding:18px 20px;background:#131819}.stationTitle h2{margin:6px 0 0;font-size:19px;letter-spacing:-.03em}.stationMeta{align-self:center;border:1px solid #3a4542;padding:7px 9px;color:#929b97;font:900 7px ui-monospace,monospace}.stationBody{padding:18px 20px 20px}.inputPanel{border:1px solid #394441;background:#0b0f10}.panelBar{height:34px;border-bottom:1px solid #303938;display:flex;justify-content:space-between;align-items:center;padding:0 11px;color:#7c8783;font:900 7px ui-monospace,monospace}.traffic{display:inline-flex;gap:4px;margin-right:7px}.traffic i{width:5px;height:5px;border-radius:50%;background:#4b5552}.inputPanel textarea{display:block;width:100%;min-height:210px;max-height:440px;resize:vertical;border:0;outline:0;background:#080b0c;color:#e2e8e4;padding:18px;font:13px/1.75 ui-monospace,SFMono-Regular,Consolas,monospace}.inputPanel textarea::placeholder{color:#59635f}.inputFoot{display:flex;justify-content:space-between;border-top:1px solid #303938;padding:7px 11px;color:#606b67;font:800 7px ui-monospace,monospace}.promptStrip{display:flex;gap:7px;flex-wrap:wrap;margin:12px 0}.prompt{border:1px solid #394441;background:#151a1a;color:#a1aaa6;padding:7px 9px;cursor:pointer;font:900 7px ui-monospace,monospace}.prompt:hover{color:#dfffa5;border-color:#6d7b73}.stationControls{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:13px}.buildHint{color:#69736f;font:800 8px ui-monospace,monospace}.buildBtn{border:1px solid #819347;background:#c7ff4d;color:#10130d;padding:12px 16px;font-size:9px;font-weight:950;cursor:pointer;box-shadow:0 8px 30px rgba(199,255,77,.1);transition:.2s}.buildBtn:hover{transform:translateY(-2px);box-shadow:0 12px 35px rgba(199,255,77,.18)}.buildBtn:disabled{opacity:.5;cursor:not-allowed;transform:none}.status{min-height:40px;padding-top:13px}.notice{border:1px solid #394441;background:#0b0f10;padding:10px 12px;color:#9da6a2;font-size:10px}.notice.ok{border-color:#566e3a;color:#c6e98a}.notice.err{border-color:#6c3e40;color:#ff9b9d}.notice.wait{color:#a8c2c0}.stageRail{display:grid;grid-template-columns:repeat(6,1fr);gap:4px;margin-top:10px;border-top:1px solid #303938;padding-top:12px}.stage{position:relative;border:1px solid #303938;background:#0b0f10;padding:10px 7px;color:#58625e;font:900 7px ui-monospace,monospace;text-align:center;letter-spacing:.1em}.stage small{display:block;color:#444d4a;font-size:6px;margin-bottom:5px}.stage.active{color:var(--lime);border-color:#6f7e48;background:#141a12}.stage.active:after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:2px;background:var(--lime);animation:stagePulse 1s infinite}.stage.done{color:#90a77b;border-color:#4c5a3c}
.result{margin-top:28px;border:1px solid #38413f;background:#0e1213}.resultHead{display:flex;justify-content:space-between;align-items:center;gap:15px;padding:15px 17px;border-bottom:1px solid #303938;background:#121718}.resultIdentity{display:flex;gap:10px;align-items:center}.resultIcon{width:30px;height:30px;border:1px solid #4a5652;display:grid;place-items:center;color:#909a96;font:900 13px ui-monospace,monospace}.resultIcon.pass{color:var(--lime);border-color:#657d3c}.resultIcon.fail{color:var(--red);border-color:#754547}.resultIdentity b{font-size:13px}.resultIdentity small{display:block;color:#65706d;font:700 7px ui-monospace,monospace;margin-top:4px}.actions{display:flex;gap:5px;flex-wrap:wrap}.toolBtn{border:1px solid #3c4744;background:#171c1c;color:#b1bbb7;padding:7px 9px;cursor:pointer;font:900 7px ui-monospace,monospace}.toolBtn:hover{color:#e9f0ec;border-color:#707b76}.artifactGrid{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px}.artifact{border:1px solid #303938;background:#090d0e;min-width:0}.artifact.full{grid-column:1/-1}.artifactHead{height:34px;border-bottom:1px solid #303938;display:flex;justify-content:space-between;align-items:center;padding:0 11px;color:#69736f;font:900 7px ui-monospace,monospace}.artifactHead b{color:#aab3af}.codeWindow{display:grid;grid-template-columns:44px minmax(0,1fr);max-height:560px;overflow:auto;background:#070a0b}.lineNums{padding:15px 8px 15px 0;text-align:right;color:#3e4845;border-right:1px solid #222b29;font:11px/1.72 ui-monospace,SFMono-Regular,Consolas,monospace;user-select:none}.code{margin:0;padding:15px 16px;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;color:#dbe2de;font:11px/1.72 ui-monospace,SFMono-Regular,Consolas,monospace;tab-size:4}.code .kw{color:#c7ff4d}.code .str{color:#ffbf79}.code .num{color:#8fb8ff}.code .com{color:#65716c}.visual{padding:12px;overflow:auto;min-height:230px;background:#070a0b}.visual svg{display:block;width:100%;height:auto;min-width:650px}.empty{min-height:205px;border:1px dashed #35403d;display:grid;place-items:center;text-align:center;color:#5d6864;font:900 8px ui-monospace,monospace;letter-spacing:.1em}.console{padding:13px}.verify{border:1px solid #3b4945;background:#0a0e0f;padding:13px;color:#85918c;font-size:9px;line-height:1.75}.verify.pass{border-color:#53693a}.verify.pass strong{color:var(--lime)}.verify.fail{border-color:#673e40}.verify.fail strong{color:#ff9a9b}.log{margin-top:9px;border-top:1px solid #303938;padding-top:9px;white-space:pre-wrap;overflow:auto;max-height:260px;color:#6e7975;font:9px/1.65 ui-monospace,SFMono-Regular,Consolas,monospace}.resultNote{padding:11px 13px;border-top:1px solid #303938;color:#66716d;font-size:8px;line-height:1.7}.infoGrid{display:grid;grid-template-columns:1.2fr .8fr .8fr;gap:12px;margin-top:35px}.infoCard{border:1px solid #303938;background:#101415;padding:17px;min-height:145px;position:relative;overflow:hidden}.infoCard b{font-size:11px}.infoCard p{color:#737e7a;font-size:9px;line-height:1.7}.infoCard:after{content:"";position:absolute;width:120px;height:120px;border:1px solid rgba(199,255,77,.08);right:-45px;bottom:-55px;transform:rotate(45deg)}.footer{margin-top:45px;color:#515c58;text-align:center;font:900 7px ui-monospace,monospace;letter-spacing:.16em}.reveal{opacity:0;transform:translateY(34px);transition:opacity .8s ease,transform .8s cubic-bezier(.2,.7,.2,1)}.reveal.visible{opacity:1;transform:none}.spinner{display:inline-block;width:10px;height:10px;border:2px solid #34433d;border-top-color:var(--lime);border-radius:50%;animation:spin .65s linear infinite;vertical-align:-2px}
@keyframes pulse{50%{opacity:.25;transform:scale(.65)}}@keyframes spin{to{transform:rotate(360deg)}}@keyframes scan{to{transform:translateY(720%)}}@keyframes boardFloat{0%,100%{transform:rotateX(58deg) rotateZ(-28deg) translateY(0)}50%{transform:rotateX(58deg) rotateZ(-28deg) translateY(-15px)}}@keyframes chipPulse{50%{box-shadow:0 0 0 18px rgba(199,255,77,.02),0 0 50px rgba(199,255,77,.12)}}@keyframes cardFloat{50%{transform:translateY(-9px)}}@keyframes bob{50%{transform:translateY(5px)}}@keyframes stagePulse{50%{opacity:.35}}
@media(max-width:980px){.hero{grid-template-columns:1fr;min-height:850px}.heroCopy{padding-top:80px}.heroVisual{height:400px}.navlinks{display:none}.visualRail{grid-template-columns:1fr}.techShot,.techShot.tall{height:300px}.motifGrid{grid-template-columns:1fr}.infoGrid{grid-template-columns:1fr}.artifactGrid{grid-template-columns:1fr}.artifact.full{grid-column:auto}.stageRail{grid-template-columns:repeat(3,1fr)}}
@media(max-width:620px){.shell{width:calc(100% - 18px)}.hero h1{font-size:55px}.heroStats{width:100%}.stat{padding-right:10px;margin-right:10px}.heroVisual{height:300px}.board3d{width:88%}.floatCard{display:none}.stationHead{grid-template-columns:1fr}.stationMeta{width:max-content;margin-top:10px}.stationControls{flex-direction:column;align-items:stretch}.buildBtn{width:100%}.stageRail{grid-template-columns:repeat(2,1fr)}.codeWindow{grid-template-columns:34px minmax(0,1fr)}.code,.lineNums{font-size:10px}.artifactGrid{padding:8px}.section{padding-top:50px}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation-duration:.001ms!important;animation-iteration-count:1!important;scroll-behavior:auto!important;transition-duration:.001ms!important}}
</style>
</head>
<body>
<div id="scrollProgress"></div>
<div class="shell">
<nav class="nav"><div class="brand"><div class="brandmark">RF</div><div><b>RTL FORGE</b><small>DIGITAL HARDWARE WORKSTATION</small></div></div><div class="navlinks"><a href="#visuals">HARDWARE</a><a href="#workstation">WORKSTATION</a><a href="#results">OUTPUT</a></div><div class="health"><i></i> LOCAL SIMULATION READY</div></nav>
<section id="workstation" class="workstation reveal"><div class="stationHead"><div class="stationTitle"><div class="kicker">01 / ENGINEERING WORKSTATION</div><h2>Specify the hardware. The pipeline handles the rest.</h2></div><div class="stationMeta">GENERAL-PURPOSE ECE / NO DEMO LIMIT</div></div><div class="stationBody"><div class="inputPanel"><div class="panelBar"><span><span class="traffic"><i></i><i></i><i></i></span> hardware_requirement.txt</span><span>NATURAL LANGUAGE</span></div><textarea id="req" maxlength="5000" placeholder="Describe any digital ECE circuit: interface, widths, clocks, resets, timing, state behavior, corner cases, and verification expectations."></textarea><div class="inputFoot"><span>SPECIFICATION → RTL → TESTBENCH → COMPILE → SIMULATE → VERIFY</span><span id="count">0 / 5000</span></div></div><div class="promptStrip"><button class="prompt" onclick="usePrompt('Design a UART transmitter and receiver with configurable baud divider, 8N1 framing, status signals and an independent self-checking testbench.')">UART</button><button class="prompt" onclick="usePrompt('Design a synchronous FIFO, 16 entries x 8-bit, with full, empty, almost-full and almost-empty flags and a self-checking testbench.')">SYNC FIFO</button><button class="prompt" onclick="usePrompt('Design an SPI master supporting 8-bit transfers, CPOL/CPHA modes, programmable clock divider, busy and done status.')">SPI</button><button class="prompt" onclick="usePrompt('Design an I2C master controller with start, stop, write, read, acknowledge handling and a conservative synthesizable interface.')">I2C</button><button class="prompt" onclick="usePrompt('Design an 8-bit ALU supporting ADD, SUB, AND, OR, XOR, shifts, zero flag and carry flag.')">ALU</button><button class="prompt" onclick="usePrompt('Design a PWM controller with programmable period and duty cycle, synchronous enable and reset behavior.')">PWM</button><button class="prompt" onclick="usePrompt('Design a CRC-8 streaming calculator with valid input, start control and an independent reference-model testbench.')">CRC-8</button></div><div class="stationControls"><div class="buildHint">⌘ / CTRL + ENTER &nbsp;•&nbsp; OBJECTIVE BUILD</div><button id="generate" class="buildBtn" onclick="build()">BUILD &amp; VERIFY →</button></div><div id="status" class="status"></div><div id="stageRail" class="stageRail hidden"><div id="s1" class="stage"><small>01</small>SPECIFY</div><div id="s2" class="stage"><small>02</small>ARCHITECT</div><div id="s3" class="stage"><small>03</small>GENERATE RTL</div><div id="s4" class="stage"><small>04</small>COMPILE</div><div id="s5" class="stage"><small>05</small>SIMULATE</div><div id="s6" class="stage"><small>06</small>VERIFY</div></div></div></section>

<section class="hero"><div class="heroCopy reveal"><div class="eyebrow"><b>02</b> DIGITAL HARDWARE / RTL WORKSTATION</div><h1>Build circuits.<br><span>Read the <em>signals.</em></span></h1><p>Turn an engineering requirement into synthesizable SystemVerilog, an independent self-checking testbench, a functional schematic and a real simulation waveform. One workstation for arbitrary digital ECE designs.</p><div class="heroStats"><div class="stat"><b>ANY ECE</b><span>NO CIRCUIT CATALOGUE</span></div><div class="stat"><b>SV / 2012</b><span>RTL TARGET</span></div><div class="stat"><b>Icarus</b><span>OBJECTIVE SIM</span></div></div><div class="scrollCue">SCROLL THROUGH THE DESIGN FIELD</div></div><div class="heroVisual" id="heroVisual"><div class="board3d"><span class="traceLine t1"></span><span class="traceLine t2"></span><span class="traceLine t3"></span><i class="node n1"></i><i class="node n2"></i><i class="node n3"></i></div><div class="floatCard fc1"><b>RTL / 01</b>syn · compile · inspect</div><div class="floatCard fc2"><b>TRACE / 04</b>VCD signal history</div></div></section>
<section id="visuals" class="section reveal"><div class="sectionHead"><div><div class="kicker">03 / HARDWARE REFERENCES</div><h2>Boards, silicon, instruments.</h2></div><p>Physical electronics imagery sits beside generated engineering diagrams. The visual language stays grounded in hardware instead of generic AI graphics.</p></div><div class="visualRail"><figure class="techShot tall"><img loading="lazy" src="https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1400&q=88" alt="Close-up printed circuit board with integrated circuits"><figcaption><b>01</b><span>PCB / COPPER ROUTING</span></figcaption></figure><figure class="techShot"><img loading="lazy" src="https://images.unsplash.com/photo-1555664424-778a690220e1?auto=format&fit=crop&w=1200&q=88" alt="Electronic circuit board components and traces"><figcaption><b>02</b><span>IC / SIGNAL ROUTING</span></figcaption></figure><figure class="techShot tall"><img loading="lazy" src="https://images.unsplash.com/photo-1581092160607-ee22621dd758?auto=format&fit=crop&w=1400&q=88" alt="Electronics engineering laboratory equipment"><figcaption><b>03</b><span>LAB / INSTRUMENTATION</span></figcaption></figure></div></section>
<section class="section reveal"><div class="sectionHead"><div><div class="kicker">04 / DIGITAL DESIGN LANGUAGE</div><h2>Logic. States. Timing.</h2></div><p>Interface-native engineering motifs: combinational paths, finite-state control and signal timing. These are visual context, not fake simulation output.</p></div><div class="motifGrid"><article class="motif"><div class="motifTop"><span>COMBINATIONAL</span><b>DATA PATH</b></div><svg viewBox="0 0 600 210" fill="none"><g stroke="currentColor" stroke-width="3"><path d="M20 30H170L330 105H570"/><path d="M20 80H170L330 105"/><path d="M20 130H170L330 105"/><path d="M20 180H170L330 105"/><path d="M330 105l55-50v100z"/></g><g fill="currentColor"><circle cx="20" cy="30" r="5"/><circle cx="20" cy="80" r="5"/><circle cx="20" cy="130" r="5"/><circle cx="20" cy="180" r="5"/><circle cx="570" cy="105" r="5"/></g></svg></article><article class="motif"><div class="motifTop"><span>SEQUENTIAL</span><b>FSM CONTROL</b></div><svg viewBox="0 0 600 210" fill="none"><g stroke="currentColor" stroke-width="2"><circle cx="105" cy="105" r="38"/><circle cx="300" cy="55" r="38"/><circle cx="300" cy="155" r="38"/><circle cx="495" cy="105" r="38"/><path d="M143 92L262 65M143 118L262 145M338 55h119M338 155h119M457 92l-80-25M457 118l-80 25"/></g><g fill="currentColor" font-family="monospace" font-size="14" text-anchor="middle"><text x="105" y="110">IDLE</text><text x="300" y="60">LOAD</text><text x="300" y="160">RUN</text><text x="495" y="110">DONE</text></g></svg></article><article class="motif"><div class="motifTop"><span>VERIFICATION</span><b>WAVEFORM</b></div><svg viewBox="0 0 600 210" fill="none"><g stroke="#394744" stroke-width="1"><path d="M10 35H590M10 85H590M10 135H590M10 185H590"/></g><path d="M10 58H80V20H150V58H220V20H290V58H360V20H430V58H500V20H590" stroke="#c7ff4d" stroke-width="4"/><path d="M10 150H55V110H120V150H180V110H250V150H320V110H390V150H460V110H530V150H590" stroke="#6ee7e0" stroke-width="4"/></svg></article></div></section>

<section id="results" class="result hidden reveal"><div class="resultHead"><div class="resultIdentity"><div id="resultIcon" class="resultIcon">·</div><div><b id="resultHeading">Generated Design</b><small id="resultSub">RTL / TESTBENCH / SCHEMATIC / WAVEFORM</small></div></div><div class="actions"><button class="toolBtn" onclick="downloadArtifact('rtl')">DOWNLOAD RTL</button><button class="toolBtn" onclick="downloadArtifact('testbench')">DOWNLOAD TB</button><button class="toolBtn" onclick="copyCode('rtl')">COPY RTL</button></div></div><div class="artifactGrid"><article class="artifact"><div class="artifactHead"><span>01 / RTL MODULE</span><b>generated_design.sv</b></div><div class="codeWindow"><div id="rtlLines" class="lineNums"></div><pre id="rtl" class="code"></pre></div></article><article class="artifact"><div class="artifactHead"><span>02 / TESTBENCH</span><b>testbench.sv</b></div><div class="codeWindow"><div id="tbLines" class="lineNums"></div><pre id="tbcode" class="code"></pre></div></article><article class="artifact"><div class="artifactHead"><span>03 / CIRCUIT DESIGN</span><b>GRAPHVIZ / FUNCTIONAL VIEW</b></div><div id="diagram" class="visual"><div class="empty">SCHEMATIC APPEARS AFTER GENERATION</div></div></article><article class="artifact"><div class="artifactHead"><span>04 / SIMULATION WAVEFORM</span><b>VCD / ACTUAL TRACE</b></div><div id="waveform" class="visual"><div class="empty">WAVEFORM APPEARS AFTER A SUCCESSFUL SIMULATION</div></div></article><article class="artifact full"><div class="artifactHead"><span>05 / VERIFICATION CONSOLE</span><b>ICARUS / VVP OBJECTIVE RESULT</b></div><div class="console"><div id="verify" class="verify"><strong>Waiting for build</strong><br>Generate a design to inspect objective compilation and simulation.</div><pre id="log" class="log"></pre></div><div class="resultNote">A design is marked <b>VERIFIED</b> only when Icarus compilation succeeds, VVP exits successfully and the testbench prints TEST_RESULT: PASS.</div></article></div></section>
<section class="infoGrid reveal"><article class="infoCard"><b>General ECE engine</b><p>No fixed circuit whitelist. The request can describe combinational logic, sequential logic, memories, buses, communication interfaces, DSP, processors, control logic or an unusual digital architecture.</p></article><article class="infoCard"><b>Independent verification</b><p>The testbench is generated separately from the DUT and is instructed to calculate expected behavior rather than mirror the implementation.</p></article><article class="infoCard"><b>Bounded recovery</b><p>Compile and simulation failures can trigger one focused repair. The system never turns a failed simulation into a fake PASS.</p></article></section>
<div class="footer">RTL FORGE / DIGITAL HARDWARE WORKSTATION / ENGINEER • COMPILE • SIMULATE • VERIFY</div>
</div>
<script>
let generated='',generatedTB='',currentJob='',stageTimer=null;const req=document.getElementById('req');req.addEventListener('input',()=>document.getElementById('count').textContent=req.value.length+' / 5000');req.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key==='Enter'){e.preventDefault();build()}});
function usePrompt(t){req.value=t;document.getElementById('count').textContent=t.length+' / 5000';document.getElementById('workstation').scrollIntoView({behavior:'smooth',block:'start'});setTimeout(()=>req.focus(),300)}
function stages(n){for(let i=1;i<=6;i++){const e=document.getElementById('s'+i);e.classList.toggle('active',i===n);e.classList.toggle('done',i<n)}}function startStages(){document.getElementById('stageRail').classList.remove('hidden');let n=1;stages(n);clearInterval(stageTimer);stageTimer=setInterval(()=>{if(n<5){n++;stages(n)}},950)}function finishStages(ok){clearInterval(stageTimer);stages(ok?6:5)}
function setStatus(kind,msg){document.getElementById('status').innerHTML='<div class="notice '+kind+'">'+msg+'</div>'}function esc(s){return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function codeHTML(s){
  // Deliberately render HDL as TEXT, not model-generated HTML.
  // This prevents malformed tokens such as "kw"> or injected <span> markup
  // from ever appearing in the source viewer.
  return esc(String(s||''));
}
function renderCode(id,lineId,text){
  const clean=String(text||'').replace(/\r\n/g,'\n').replace(/\r/g,'\n');
  document.getElementById(id).textContent=clean;
  const n=Math.max(1,clean.split('\n').length);
  document.getElementById(lineId).textContent=Array.from({length:n},(_,i)=>String(i+1)).join('\n');
}
function empty(id,msg){document.getElementById(id).innerHTML='<div class="empty">'+esc(msg)+'</div>'}
async function build(){const text=req.value.trim();if(!text){setStatus('err','Enter a hardware requirement before building.');req.focus();return}const btn=document.getElementById('generate');btn.disabled=true;btn.innerHTML='<span class="spinner"></span> BUILDING';setStatus('wait','<span class="spinner"></span> Running specification → RTL → compile → simulation → verification.');startStages();document.getElementById('results').classList.add('hidden');try{const r=await fetch('/api/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request:text})});const d=await r.json().catch(()=>({error:'Server returned an invalid response.'}));if(!r.ok)throw new Error(d.message||d.error||'Build failed.');generated=d.rtl||'';generatedTB=d.testbench||'';currentJob=d.job_id||'';document.getElementById('results').classList.remove('hidden');document.getElementById('resultHeading').textContent=(d.verification&&d.verification.passed?'Verified — ':'Generated — ')+(d.design_name||'Digital design');const icon=document.getElementById('resultIcon');icon.className='resultIcon '+(d.verification&&d.verification.passed?'pass':'fail');icon.textContent=d.verification&&d.verification.passed?'✓':'!';renderCode('rtl','rtlLines',generated);renderCode('tbcode','tbLines',generatedTB);if(d.diagram_svg)document.getElementById('diagram').innerHTML=d.diagram_svg;else empty('diagram','NO FUNCTIONAL SCHEMATIC RETURNED');if(d.waveform_svg)document.getElementById('waveform').innerHTML=d.waveform_svg;else empty('waveform','NO WAVEFORM — SIMULATION DID NOT COMPLETE');const v=d.verification||{};document.getElementById('log').textContent=v.log||'';if(v.passed){document.getElementById('verify').className='verify pass';document.getElementById('verify').innerHTML='<strong>✓ VERIFIED</strong><br>Icarus compilation succeeded, VVP simulation completed and the independent testbench reported TEST_RESULT: PASS.';setStatus('ok','✓ Hardware generated and objectively verified.');finishStages(true)}else{document.getElementById('verify').className='verify fail';document.getElementById('verify').innerHTML='<strong>⚠ NOT VERIFIED</strong><br>Artifacts are available for inspection, but the objective build did not pass. Stage: '+esc(v.stage||'unknown')+'.';setStatus('err','⚠ Generated artifacts returned, but verification did not pass.');finishStages(false)}document.getElementById('results').scrollIntoView({behavior:'smooth',block:'start'})}catch(e){finishStages(false);setStatus('err','⚠ '+esc(e.message));document.getElementById('results').classList.add('hidden')}finally{btn.disabled=false;btn.textContent='BUILD & VERIFY →'}}
function copyCode(which){const t=which==='tb'?generatedTB:generated;if(!t)return;navigator.clipboard?.writeText(t);setStatus('ok','Copied '+(which==='tb'?'testbench':'RTL')+' to clipboard.')}function downloadArtifact(k){if(currentJob)location.href='/api/download/'+encodeURIComponent(currentJob)+'/'+k}
window.addEventListener('scroll',()=>{const h=document.documentElement.scrollHeight-innerHeight;document.getElementById('scrollProgress').style.width=(h>0?(scrollY/h)*100:0)+'%'});
const observer=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting)e.target.classList.add('visible')}),{threshold:.12});document.querySelectorAll('.reveal').forEach(e=>observer.observe(e));const hv=document.getElementById('heroVisual');window.addEventListener('pointermove',e=>{if(!hv)return;const x=(e.clientX/innerWidth-.5)*8,y=(e.clientY/innerHeight-.5)*6;hv.style.transform='translate3d('+x+'px,'+y+'px,0)'},{passive:true});
</script>
</body></html>'''

# ============================================================
# SAFE / MODEL HELPERS
# ============================================================
def clean_code(text):
    if not isinstance(text, str):
        return ''
    text = html.unescape(text)
    text = re.sub(r'<span\b[^>]*>', '', text, flags=re.I)
    text = re.sub(r'</span\s*>', '', text, flags=re.I)
    text = re.sub(r'<(?:div|pre|code)\b[^>]*>', '', text, flags=re.I)
    text = re.sub(r'</(?:div|pre|code)\s*>', '', text, flags=re.I)
    marker = r"(?i)(?:[\"']?)(?:kw|com|str|num)(?:[\"']?)\s*>"
    text = re.sub(marker, '', text)
    text = text.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\t', '\t')
    m = re.search(r"```(?:systemverilog|verilog|sv|json)?\s*(.*?)```", text, re.I | re.S)
    code = (m.group(1) if m else text).strip()
    return re.sub(marker, '', code).strip()

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
    """Parse Gemini JSON robustly, including JSON strings containing raw newlines/tabs.

    Gemini structured output can occasionally return a JSON object whose string
    fields contain literal control characters instead of JSON-escaped \n/\t.
    Python's normal json.loads() rejects those with `Invalid control character`.
    JSONDecoder(strict=False) is deliberately used here because the values are
    immediately treated as data and subsequently cleaned before HDL execution.
    """
    if not isinstance(text, str):
        raise ValueError('Model returned a non-text response.')

    text = html.unescape(text).strip()
    text = re.sub(r'^\s*```(?:json)?\s*', '', text, flags=re.I)
    text = re.sub(r'\s*```\s*$', '', text)
    text = text.strip()

    # First try the normal strict parser.
    try:
        return json.loads(text)
    except json.JSONDecodeError as first_error:
        strict_error = first_error

    # Then allow literal control characters inside JSON strings. This directly
    # handles errors such as: Invalid control character at line 3 column 113.
    decoder = json.JSONDecoder(strict=False)
    starts = [m.start() for m in re.finditer(r'\{', text)]
    for start in starts:
        try:
            value, _ = decoder.raw_decode(text[start:])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue

    # Last attempt: locate the outer object while respecting quoted strings,
    # escaped quotes, and nested braces. This avoids the old greedy regex.
    start = text.find('{')
    if start >= 0:
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == '\\':
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate, strict=False)
                    except json.JSONDecodeError:
                        break

    raise ValueError(
        f'Model returned invalid JSON: {strict_error.msg} at line '
        f'{strict_error.lineno} column {strict_error.colno}.'
    )

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
                    max_output_tokens=18000,
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
- This is a HUMAN-READABLE FUNCTIONAL BLOCK DIAGRAM, not a raw netlist and not a cloud/AI architecture diagram.
- Use rankdir=LR and 3 to 8 meaningful rectangular blocks.
- Put the DUT's external inputs on the left, processing/control blocks in the middle, and outputs on the right.
- Group related logic into understandable blocks such as Input Interface, Controller/FSM, Datapath, CRC Engine, FIFO Memory, Synchronizer, Counter, Register Bank, ALU, UART TX/RX, etc., depending on the actual design.
- Show important signal names on arrows. Group clock/reset separately when appropriate.
- Do NOT draw every RTL statement, every register, or every wire.
- Add a clear graph label containing the design function.
- Use readable node labels with short descriptions.
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

DIAGRAM REQUIREMENT:
Return a HUMAN-READABLE Graphviz functional block diagram beginning with digraph.
Use rankdir=LR, 3 to 8 meaningful rectangular blocks, left-to-right signal flow,
short labels, and important signal names on arrows. Do not create a raw netlist.

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
        # Keep model-provided graph semantics, but make the rendered schematic
        # readable inside the dark engineering workstation.
        svg=re.sub(r'<svg([^>]*)>', r'<svg\1 style="background:#070b0d;border:1px solid #243238;border-radius:12px">', svg, count=1, flags=re.I)
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
    return {'passed':passed,'stage':'simulation','return_code':sp.returncode,'log':log[-18000:]}

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
        'hardcoded_demo_fallback':False,'version':'rtl-forge-general-ece-6.1','source_cleanup':'plain_hdl_sanitizer_v2'
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
