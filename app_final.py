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

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
FALLBACK_MODELS = [m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite,gemini-3.8-flash").split(",") if m.strip()]
GEMINI_RETRY_ATTEMPTS = max(1, int(os.getenv("GEMINI_RETRY_ATTEMPTS", "1")))
GEMINI_INITIAL_BACKOFF = max(0.1, float(os.getenv("GEMINI_INITIAL_BACKOFF", "2")))
GEMINI_MAX_BACKOFF = max(GEMINI_INITIAL_BACKOFF, float(os.getenv("GEMINI_MAX_BACKOFF", "8")))
GEMINI_429_RETRIES = max(0, int(os.getenv("GEMINI_429_RETRIES", "0")))
# Gemini 3.x can spend noticeable time thinking. 15s was too aggressive for
# a multi-stage RTL agent and caused httpx read timeouts on fallback models.
GEMINI_REQUEST_TIMEOUT_SECONDS = max(10, float(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "30")))
GEMINI_TIMEOUT_RETRIES = max(0, int(os.getenv("GEMINI_TIMEOUT_RETRIES", "0")))
GEMINI_THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "low").strip().lower()
if GEMINI_THINKING_LEVEL not in {"minimal", "low", "medium", "high"}:
    GEMINI_THINKING_LEVEL = "low"
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
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#05070b">
<title>ECE RTL AI Engineer</title>
<style>
:root{
  --bg:#05070b;--bg2:#080c13;--panel:rgba(12,17,25,.72);--panel2:rgba(7,11,17,.88);
  --border:rgba(142,163,190,.16);--border2:rgba(105,231,255,.26);--text:#eef7ff;--muted:#8fa2b8;
  --cyan:#62e6ff;--violet:#9b7cff;--green:#49e6a5;--red:#ff647c;--gold:#e5c76a;
  --shadow:0 24px 80px rgba(0,0,0,.45)
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:radial-gradient(circle at 15% 5%,rgba(98,230,255,.09),transparent 28%),radial-gradient(circle at 85% 15%,rgba(155,124,255,.11),transparent 30%),var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow-x:hidden}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(255,255,255,.018) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);background-size:44px 44px;mask-image:linear-gradient(to bottom,black,transparent 82%);z-index:-3}
body:after{content:"";position:fixed;inset:0;pointer-events:none;background:linear-gradient(180deg,transparent 0%,rgba(98,230,255,.025) 50%,transparent 100%);background-size:100% 7px;opacity:.35;z-index:10}
button,textarea{font:inherit}.hidden{display:none!important}
.wrap{width:min(1240px,calc(100% - 34px));margin:auto;padding:18px 0 90px}
.topbar{height:58px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:12px;z-index:20;padding:0 15px;border:1px solid var(--border);border-radius:18px;background:rgba(5,8,13,.72);backdrop-filter:blur(18px);box-shadow:0 12px 45px rgba(0,0,0,.24)}
.brand{display:flex;align-items:center;gap:11px;font-weight:850;letter-spacing:.02em}.brand-mark{width:32px;height:32px;border-radius:10px;display:grid;place-items:center;background:linear-gradient(135deg,var(--cyan),var(--violet));color:#031018;box-shadow:0 0 28px rgba(98,230,255,.22);font-size:14px}.brand small{display:block;color:var(--muted);font-size:10px;font-weight:700;letter-spacing:.16em;text-transform:uppercase}.live{display:flex;align-items:center;gap:8px;color:#a9bbce;font-size:12px}.dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 14px var(--green);animation:pulse 1.8s infinite}
.hero{min-height:590px;display:grid;place-items:center;text-align:center;padding:90px 10px 55px;position:relative}.orb{position:absolute;width:420px;height:420px;border-radius:50%;background:radial-gradient(circle,rgba(98,230,255,.13),rgba(155,124,255,.07) 34%,transparent 68%);filter:blur(10px);animation:float 7s ease-in-out infinite;z-index:-1}.hero-kicker{display:inline-flex;align-items:center;gap:8px;border:1px solid rgba(98,230,255,.22);background:rgba(98,230,255,.055);padding:8px 12px;border-radius:999px;color:#aeeeff;font-size:12px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;animation:rise .7s ease both}.hero h1{font-size:clamp(44px,7vw,82px);line-height:.98;letter-spacing:-.055em;margin:22px 0 18px;font-weight:900;max-width:900px}.gradient{background:linear-gradient(100deg,#f5fbff 5%,var(--cyan) 43%,#b7a3ff 75%,#fff 100%);-webkit-background-clip:text;background-clip:text;color:transparent}.hero p{max-width:690px;margin:0 auto;color:#91a5bb;font-size:17px;line-height:1.75}.hero-actions{display:flex;justify-content:center;gap:10px;flex-wrap:wrap;margin-top:30px}.scroll-cue{margin-top:55px;color:#667b92;font-size:11px;letter-spacing:.16em;text-transform:uppercase;animation:bob 2s infinite}.chev{display:block;margin:8px auto 0;width:8px;height:8px;border-right:1px solid var(--cyan);border-bottom:1px solid var(--cyan);transform:rotate(45deg)}
.panel{position:relative;background:linear-gradient(145deg,rgba(16,23,34,.84),rgba(6,10,16,.78));border:1px solid var(--border);border-radius:26px;box-shadow:var(--shadow);backdrop-filter:blur(18px);overflow:hidden}.panel:before{content:"";position:absolute;inset:0;background:linear-gradient(110deg,rgba(98,230,255,.045),transparent 32%,rgba(155,124,255,.035));pointer-events:none}.workbench{padding:25px}.section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:15px;margin-bottom:20px}.eyebrow{color:#6e849b;font-size:10px;letter-spacing:.18em;text-transform:uppercase;font-weight:800}.section-title{margin:6px 0 0;font-size:21px;letter-spacing:-.02em}.mini-status{font-size:11px;color:#7f94aa;border:1px solid var(--border);padding:7px 10px;border-radius:999px;background:rgba(255,255,255,.025)}
.input-shell{position:relative;border:1px solid rgba(116,145,175,.2);border-radius:20px;background:rgba(3,7,12,.62);transition:.25s;overflow:hidden}.input-shell:focus-within{border-color:rgba(98,230,255,.52);box-shadow:0 0 0 4px rgba(98,230,255,.055),0 0 50px rgba(98,230,255,.07)}textarea{display:block;width:100%;min-height:180px;resize:vertical;background:transparent;color:#f4f8fc;border:0;outline:0;padding:22px 22px 58px;font-size:16px;line-height:1.65}.input-footer{position:absolute;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:space-between;padding:10px 13px;border-top:1px solid rgba(255,255,255,.05);background:rgba(0,0,0,.16);color:#687e94;font-size:11px}.counter{font-variant-numeric:tabular-nums}
.prompt-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.chip{border:1px solid rgba(125,149,175,.17);background:rgba(255,255,255,.025);color:#8da1b7;border-radius:999px;padding:8px 11px;font-size:11px;cursor:pointer;transition:.2s}.chip:hover{border-color:rgba(98,230,255,.36);color:#c8f7ff;transform:translateY(-2px);background:rgba(98,230,255,.045)}
.primary{position:relative;display:inline-flex;align-items:center;justify-content:center;gap:9px;border:0;border-radius:13px;padding:13px 20px;background:linear-gradient(110deg,#6de8ff,#8e7cff);color:#041018;font-weight:900;cursor:pointer;box-shadow:0 12px 34px rgba(98,230,255,.14);transition:.22s;overflow:hidden}.primary:before{content:"";position:absolute;inset:-30%;background:linear-gradient(100deg,transparent 35%,rgba(255,255,255,.42),transparent 65%);transform:translateX(-100%);transition:.7s}.primary:hover:before{transform:translateX(100%)}.primary:hover{transform:translateY(-2px);box-shadow:0 17px 40px rgba(98,230,255,.2)}.primary:disabled{opacity:.55;cursor:not-allowed;transform:none}.secondary{border:1px solid var(--border);border-radius:11px;padding:10px 13px;background:rgba(255,255,255,.035);color:#d7e5f2;font-weight:750;cursor:pointer;transition:.2s}.secondary:hover{border-color:rgba(98,230,255,.35);background:rgba(98,230,255,.05)}
.action-row{display:flex;align-items:center;justify-content:space-between;gap:15px;flex-wrap:wrap;margin-top:17px}.hint{font-size:11px;color:#657a90}.kbd{border:1px solid var(--border);border-bottom-color:#38495a;border-radius:5px;padding:2px 5px;color:#93a8bc;background:rgba(255,255,255,.03)}
.status-area{min-height:44px;margin-top:16px}.badge{display:inline-flex;align-items:center;gap:8px;padding:9px 12px;border-radius:11px;font-size:12px;font-weight:800;border:1px solid transparent;animation:rise .35s ease}.ok{background:rgba(73,230,165,.075);border-color:rgba(73,230,165,.22);color:#70efb5}.bad{background:rgba(255,100,124,.07);border-color:rgba(255,100,124,.23);color:#ff8a9c}.neutral{background:rgba(125,149,175,.07);border-color:var(--border);color:#a7b7c8}.spinner{width:14px;height:14px;border:2px solid rgba(255,255,255,.18);border-top-color:var(--cyan);border-radius:50%;display:inline-block;animation:spin .8s linear infinite}
.pipeline{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:19px}.stage{position:relative;padding:13px 10px;border:1px solid var(--border);border-radius:13px;background:rgba(255,255,255,.018);color:#61758b;text-align:center;font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;transition:.35s}.stage.active{color:#c8f8ff;border-color:rgba(98,230,255,.32);background:rgba(98,230,255,.055);box-shadow:inset 0 0 24px rgba(98,230,255,.04)}.stage.done{color:#72e9b5;border-color:rgba(73,230,165,.2)}
.output{margin-top:22px;animation:reveal .65s cubic-bezier(.2,.8,.2,1) both}.result-top{display:flex;align-items:center;justify-content:space-between;gap:15px;flex-wrap:wrap;padding:21px 23px;border-bottom:1px solid var(--border)}.result-name{display:flex;align-items:center;gap:12px}.shield{width:35px;height:35px;border-radius:11px;display:grid;place-items:center;background:rgba(73,230,165,.08);border:1px solid rgba(73,230,165,.2);color:var(--green)}.result-title{font-size:18px;font-weight:850}.result-sub{font-size:11px;color:#71859a;margin-top:3px}.result-actions{display:flex;gap:8px;align-items:center}.copy-msg{color:var(--green);font-size:11px}.code-wrap{padding:0 15px 15px}.code-frame{position:relative;border:1px solid rgba(112,137,164,.17);border-radius:17px;overflow:hidden;background:#030609;margin-top:15px}.code-bar{height:37px;display:flex;align-items:center;justify-content:space-between;padding:0 13px;border-bottom:1px solid rgba(255,255,255,.06);background:rgba(255,255,255,.025)}.dots{display:flex;gap:6px}.dots i{width:7px;height:7px;border-radius:50%;background:#33404e}.file-name{font:10px ui-monospace,SFMono-Regular,monospace;color:#657a90}.lang{font-size:9px;letter-spacing:.13em;color:#5d7288;font-weight:800}pre{margin:0;max-height:620px;white-space:pre;overflow:auto;padding:21px;font:13px/1.65 ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace;color:#dce9f5;tab-size:4}pre::-webkit-scrollbar{width:9px;height:9px}pre::-webkit-scrollbar-thumb{background:#263442;border-radius:99px}.verify{margin:0 15px 18px;padding:15px 16px;border:1px solid rgba(73,230,165,.16);background:rgba(73,230,165,.035);border-radius:14px;color:#89a2b8;font-size:12px;line-height:1.6}.verify strong{color:#72e9b5}.verify.fail{border-color:rgba(255,100,124,.2);background:rgba(255,100,124,.035)}.verify.fail strong{color:#ff8a9c}
.features{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:22px}.feature{padding:20px;border:1px solid var(--border);border-radius:20px;background:rgba(9,14,21,.52);transition:.3s}.feature:hover{transform:translateY(-4px);border-color:rgba(98,230,255,.22);background:rgba(13,21,31,.65)}.feature-icon{font-size:19px;margin-bottom:12px}.feature h3{margin:0 0 6px;font-size:14px}.feature p{margin:0;color:#71869c;font-size:11px;line-height:1.65}
.reveal{opacity:0;transform:translateY(24px);transition:opacity .75s ease,transform .75s ease}.reveal.visible{opacity:1;transform:none}
@keyframes spin{to{transform:rotate(360deg)}}@keyframes pulse{50%{opacity:.45;transform:scale(.75)}}@keyframes float{50%{transform:translateY(-16px) scale(1.04)}}@keyframes bob{50%{transform:translateY(6px)}}@keyframes rise{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}@keyframes reveal{from{opacity:0;transform:translateY(30px) scale(.985)}to{opacity:1;transform:none}}
/* Physical engineering workbench layer */
.scene-depth{position:fixed;inset:0;pointer-events:none;z-index:-2;overflow:hidden;perspective:1200px}
.scene-depth:before{content:"";position:absolute;left:-15%;right:-15%;bottom:-32%;height:72%;background:linear-gradient(rgba(98,230,255,.10) 1px,transparent 1px),linear-gradient(90deg,rgba(98,230,255,.07) 1px,transparent 1px);background-size:58px 58px;transform:rotateX(64deg);transform-origin:center bottom;mask-image:linear-gradient(to top,black,transparent 88%);animation:gridDrift 16s linear infinite}
.scene-depth:after{content:"";position:absolute;width:520px;height:520px;left:50%;top:42%;transform:translate(-50%,-50%);border:1px solid rgba(98,230,255,.09);border-radius:50%;box-shadow:0 0 90px rgba(98,230,255,.04),inset 0 0 90px rgba(155,124,255,.035);animation:corePulse 5s ease-in-out infinite}
@keyframes gridDrift{to{background-position:0 58px,58px 0}}
@keyframes corePulse{50%{transform:translate(-50%,-50%) scale(1.06);opacity:.55}}
.engineering-badge{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:9px;letter-spacing:.18em;color:#7690a8}
.hero h1{transform:translateZ(20px);text-shadow:0 12px 45px rgba(0,0,0,.55)}
.hero p{transform:translateZ(10px)}
.workbench{transform-style:preserve-3d;transition:transform .22s ease-out,box-shadow .35s ease}
.workbench:after{content:"";position:absolute;inset:1px;border-radius:25px;pointer-events:none;background:linear-gradient(105deg,transparent 15%,rgba(98,230,255,.06) 48%,transparent 70%);transform:translateX(-110%);animation:surfaceSweep 7s ease-in-out infinite}
@keyframes surfaceSweep{0%,58%{transform:translateX(-110%)}78%,100%{transform:translateX(110%)}}
.stage{transform:translateZ(0);box-shadow:0 10px 24px rgba(0,0,0,.18);overflow:hidden}
.stage:before{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(98,230,255,.10),transparent);transform:translateX(-120%);animation:stageScan 3.6s linear infinite}
@keyframes stageScan{to{transform:translateX(120%)}}
.feature{transform-style:preserve-3d;box-shadow:0 14px 40px rgba(0,0,0,.16)}
.feature:hover{transform:translateY(-7px) rotateX(2deg) rotateY(-1deg);box-shadow:0 24px 60px rgba(0,0,0,.28)}
.code-frame{transform:translateZ(12px);box-shadow:0 25px 65px rgba(0,0,0,.35),inset 0 1px rgba(255,255,255,.04)}
.scroll-progress{position:fixed;left:0;top:0;width:100%;height:2px;background:rgba(255,255,255,.03);z-index:100}
.scroll-progress i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--cyan),var(--violet));box-shadow:0 0 14px rgba(98,230,255,.55)}
.cursor-orb{position:fixed;width:180px;height:180px;border-radius:50%;pointer-events:none;z-index:-1;background:radial-gradient(circle,rgba(98,230,255,.065),transparent 68%);filter:blur(3px);transform:translate(-50%,-50%);transition:left .12s linear,top .12s linear}
@media(prefers-reduced-motion:reduce){.scene-depth:before,.scene-depth:after,.workbench:after,.stage:before{animation:none}.workbench{transition:none}}

@media(max-width:800px){.hero{min-height:520px;padding-top:75px}.pipeline{grid-template-columns:repeat(2,1fr)}.features{grid-template-columns:1fr}.workbench{padding:17px}.wrap{width:min(100% - 20px,1240px)}.topbar{top:7px}.live{display:none}.hero h1{font-size:48px}.action-row{align-items:stretch}.primary{width:100%}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important;animation-duration:.001ms!important;animation-iteration-count:1!important;transition-duration:.001ms!important}}

/* --- Premium physical-engineering visual layer --- */
body{
  perspective:1400px;
  background-attachment:fixed;
}
body:before{
  background-size:48px 48px;
  transform:perspective(900px) rotateX(58deg) scale(1.65);
  transform-origin:50% 100%;
  opacity:.32;
  mask-image:linear-gradient(to top,rgba(0,0,0,.9),transparent 72%);
}
body:after{
  background:repeating-linear-gradient(0deg,transparent 0,transparent 5px,rgba(98,230,255,.018) 6px);
  opacity:.5;
  mix-blend-mode:screen;
}
.topbar{
  transform:translateZ(22px);
  transition:transform .35s ease, border-color .35s ease, box-shadow .35s ease;
}
.topbar:hover{
  transform:translateY(-2px) translateZ(30px);
  border-color:rgba(98,230,255,.27);
  box-shadow:0 18px 60px rgba(0,0,0,.35),0 0 38px rgba(98,230,255,.055);
}
.panel{
  transform-style:preserve-3d;
  transition:transform .45s cubic-bezier(.2,.75,.2,1),border-color .35s ease,box-shadow .45s ease;
}
.workbench.panel:hover{
  border-color:rgba(98,230,255,.22);
  box-shadow:0 30px 100px rgba(0,0,0,.48),0 0 70px rgba(98,230,255,.045);
}
.hero .orb{
  box-shadow:inset 0 0 90px rgba(98,230,255,.05),0 0 100px rgba(155,124,255,.08);
}
.hero:after{
  content:"";
  position:absolute;
  width:min(900px,92vw);
  height:240px;
  bottom:12px;
  left:50%;
  transform:translateX(-50%) perspective(600px) rotateX(62deg);
  border:1px solid rgba(98,230,255,.08);
  border-radius:50%;
  box-shadow:0 0 0 22px rgba(98,230,255,.012),0 0 0 44px rgba(155,124,255,.01);
  pointer-events:none;
  opacity:.8;
}
.hero-kicker{
  box-shadow:inset 0 0 18px rgba(98,230,255,.025),0 0 30px rgba(98,230,255,.04);
}
.input-shell{
  box-shadow:inset 0 0 35px rgba(98,230,255,.018);
}
.code-frame{
  box-shadow:inset 0 0 40px rgba(98,230,255,.018),0 18px 55px rgba(0,0,0,.28);
}
.stage{
  overflow:hidden;
}
.stage:after{
  content:"";
  position:absolute;
  left:-80%;
  top:0;
  width:55%;
  height:100%;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.07),transparent);
  transform:skewX(-18deg);
  transition:left .8s ease;
}
.stage.active:after{left:125%}
.feature{
  transform-style:preserve-3d;
}
.feature:hover{
  box-shadow:0 18px 50px rgba(0,0,0,.24),0 0 35px rgba(98,230,255,.035);
}
.reveal{
  will-change:transform,opacity;
}
@media(prefers-reduced-motion:reduce){
  body{perspective:none}
  .panel,.topbar{transform:none!important}
  .hero:after{display:none}
}
</style>
</head>
<body>
<div class="scroll-progress"><i id="scrollProgress"></i></div><div class="cursor-orb" id="cursorOrb"></div><div class="scene-depth"></div>
<div class="wrap">
  <nav class="topbar">
    <div class="brand"><div class="brand-mark">RTL</div><div>ECE RTL AI Engineer<small>Autonomous HDL Workbench</small></div></div>
    <div class="live"><span class="dot"></span> AI ENGINE ONLINE</div>
  </nav>

  <section class="hero">
    <div class="orb"></div>
    <div>
      <div class="hero-kicker"><span class="dot"></span> Design → Simulate → Verify</div>
      <h1>Build hardware at the<br><span class="gradient">speed of intelligence.</span></h1>
      <p>Describe your digital circuit in plain language. The ECE RTL AI Engineer turns your idea into clean Verilog/SystemVerilog and verifies the generated design automatically.</p>
      <div class="hero-actions"><button class="primary" onclick="focusInput()">Start Building <span>↘</span></button></div>
      <div class="scroll-cue">Scroll to enter workbench<span class="chev"></span></div>
    </div>
  </section>

  <main id="workbench" class="panel workbench reveal">
    <div class="section-head">
      <div><div class="eyebrow">01 / Hardware specification</div><div class="section-title">Tell the AI what you want to build</div></div>
      <div class="mini-status">VERILOG • SYSTEMVERILOG</div>
    </div>
    <div class="input-shell">
      <textarea id="req" maxlength="5000" placeholder="Example: Design a parameterized synchronous FIFO with configurable depth and data width, active-low reset, full/empty flags, and safe read/write behavior."></textarea>
      <div class="input-footer"><span>Natural language → synthesizable RTL</span><span class="counter"><span id="count">0</span> / 5000</span></div>
    </div>
    <div class="prompt-row">
      <button class="chip" onclick="usePrompt('Design a 4-to-1 multiplexer with 1-bit inputs and a 2-bit select line.')">4:1 MUX</button>
      <button class="chip" onclick="usePrompt('Design a 4-bit ripple carry adder with carry-in and carry-out.')">4-bit Adder</button>
      <button class="chip" onclick="usePrompt('Design an 8-bit ALU supporting ADD, SUB, AND, OR and XOR operations with zero and carry flags.')">8-bit ALU</button>
      <button class="chip" onclick="usePrompt('Design a synchronous FIFO with 16 entries, 8-bit data, full and empty flags, and safe read/write behavior.')">16×8 FIFO</button>
    </div>
    <div class="action-row">
      <div class="hint"><span class="kbd">⌘</span> + <span class="kbd">Enter</span> to generate</div>
      <button id="buildBtn" class="primary" onclick="build()">Generate & Verify HDL <span>✦</span></button>
    </div>
    <div id="status" class="status-area"></div>
    <div id="pipeline" class="pipeline hidden">
      <div class="stage" id="s1">Understand</div><div class="stage" id="s2">Generate RTL</div><div class="stage" id="s3">Simulate</div><div class="stage" id="s4">Verify</div>
    </div>
  </main>

  <section id="out" class="output hidden">
    <div class="panel">
      <div class="result-top">
        <div class="result-name"><div class="shield">✓</div><div><div class="result-title">Generated SystemVerilog</div><div class="result-sub">Clean RTL output — internal agent reasoning stays hidden</div></div></div>
        <div class="result-actions"><button class="secondary" onclick="copyCode()">Copy Code</button><span id="copyMsg" class="copy-msg"></span></div>
      </div>
      <div class="code-wrap">
        <div class="code-frame">
          <div class="code-bar"><div class="dots"><i></i><i></i><i></i></div><div class="file-name">generated_design.sv</div><div class="lang">SYSTEMVERILOG</div></div>
          <pre id="rtl"></pre>
        </div>
      </div>
      <div id="verifyStatus" class="verify"><strong>Verification</strong><br>Waiting for result...</div>
    </div>
  </section>

  <section class="features reveal">
    <div class="feature"><div class="feature-icon">◈</div><h3>Natural-language hardware</h3><p>Describe muxes, ALUs, FIFOs, FSMs, datapaths and other digital RTL without manually starting from a template.</p></div>
    <div class="feature"><div class="feature-icon">⌁</div><h3>Automatic verification</h3><p>The existing backend pipeline generates verification logic, simulates the design and reports the final verification state.</p></div>
    <div class="feature"><div class="feature-icon">◇</div><h3>Clean engineering output</h3><p>The interface keeps internal agent details out of the main view and focuses on the actual RTL you can inspect and copy.</p></div>
  </section>
</div>
<script>
let generatedRTL='';
let stageTimer=null;
const reqEl=document.getElementById('req');
const countEl=document.getElementById('count');
reqEl.addEventListener('input',()=>countEl.textContent=reqEl.value.length);
reqEl.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key==='Enter'){e.preventDefault();build();}});
function focusInput(){document.getElementById('workbench').scrollIntoView({behavior:'smooth',block:'center'});setTimeout(()=>reqEl.focus(),450);}
function usePrompt(text){reqEl.value=text;reqEl.dispatchEvent(new Event('input'));focusInput();}
function setStage(n){
  for(let i=1;i<=4;i++){const el=document.getElementById('s'+i);el.classList.toggle('active',i===n);el.classList.toggle('done',i<n);}
}
function startPipeline(){
  document.getElementById('pipeline').classList.remove('hidden');
  let n=1;setStage(n);clearInterval(stageTimer);
  stageTimer=setInterval(()=>{if(n<4){n++;setStage(n)}},1900);
}
function stopPipeline(success){clearInterval(stageTimer);setStage(success?4:1);}
async function build(){
  const req=reqEl.value.trim(),btn=document.getElementById('buildBtn'),status=document.getElementById('status'),out=document.getElementById('out');
  if(!req){status.innerHTML='<span class="badge bad">⚠ Enter a hardware requirement.</span>';reqEl.focus();return;}
  btn.disabled=true;btn.innerHTML='<span class="spinner"></span> Synthesizing hardware...';
  status.innerHTML='<span class="badge neutral"><span class="spinner"></span> AI hardware engineer is generating and verifying your design...</span>';
  out.classList.add('hidden');document.getElementById('copyMsg').textContent='';startPipeline();
  try{
    const r=await fetch('/api/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request:req})});
    const raw=await r.text();let d={};
    try{d=raw?JSON.parse(raw):{};}catch(e){throw new Error('Server returned an invalid response (HTTP '+r.status+').');}
    if(!r.ok)throw new Error(d.error||'HDL generation failed.');
    generatedRTL=d.rtl||'';document.getElementById('rtl').textContent=generatedRTL;
    const v=d.verification||{};
    if(v.passed){
      status.innerHTML='<span class="badge ok">✓ VERIFIED — RTL passed automated verification</span>';
      document.getElementById('verifyStatus').innerHTML='<strong>✓ Verification passed</strong><br>RTL compiled successfully and the automatically generated self-checking testbench passed.';
      document.getElementById('verifyStatus').className='verify';stopPipeline(true);
    }else{
      status.innerHTML='<span class="badge bad">⚠ GENERATED — verification did not pass</span>';
      document.getElementById('verifyStatus').innerHTML='<strong>⚠ Verification did not pass</strong><br>The RTL was generated, but automated verification did not pass. Review the code before using it.';
      document.getElementById('verifyStatus').className='verify fail';stopPipeline(false);
    }
    out.classList.remove('hidden');
    requestAnimationFrame(()=>out.scrollIntoView({behavior:'smooth',block:'start'}));
  }catch(e){clearInterval(stageTimer);status.innerHTML='<span class="badge bad">✕ '+esc(e?.message||String(e))+'</span>';}
  finally{btn.disabled=false;btn.innerHTML='Generate & Verify HDL <span>✦</span>';}
}
async function copyCode(){
  if(!generatedRTL)return;
  try{await navigator.clipboard.writeText(generatedRTL);document.getElementById('copyMsg').textContent='Copied ✓';setTimeout(()=>document.getElementById('copyMsg').textContent='',1600);}
  catch(e){document.getElementById('copyMsg').textContent='Copy failed';}
}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

// Subtle physical-depth interaction: the workbench follows the pointer by only a few pixels.
// It is intentionally restrained so the page feels engineered rather than like a game.
const workbench=document.getElementById('workbench');
if(window.matchMedia('(prefers-reduced-motion: no-preference)').matches){
  workbench.addEventListener('pointermove',e=>{
    const r=workbench.getBoundingClientRect();
    const x=(e.clientX-r.left)/r.width-.5;
    const y=(e.clientY-r.top)/r.height-.5;
    workbench.style.transform=`perspective(1200px) rotateX(${(-y*1.25).toFixed(2)}deg) rotateY(${(x*1.4).toFixed(2)}deg)`;
  });
  workbench.addEventListener('pointerleave',()=>{workbench.style.transform='';});
}
const observer=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting)e.target.classList.add('visible')}),{threshold:.12});
document.querySelectorAll('.reveal').forEach(el=>observer.observe(el));

// Physical-space interaction: restrained, engineering-style depth rather than generic AI-card motion.
const scrollBar=document.getElementById('scrollProgress');
const cursorOrb=document.getElementById('cursorOrb');
function updateScrollDepth(){const h=document.documentElement.scrollHeight-window.innerHeight;scrollBar.style.width=(h>0?(window.scrollY/h)*100:0)+'%';}
window.addEventListener('scroll',updateScrollDepth,{passive:true});updateScrollDepth();
window.addEventListener('pointermove',e=>{cursorOrb.style.left=e.clientX+'px';cursorOrb.style.top=e.clientY+'px';},{passive:true});
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

def _is_timeout_error(exc):
    """Detect HTTP/socket read/connect timeouts that may not carry an HTTP code."""
    name = exc.__class__.__name__.lower()
    text = str(exc).lower()
    return (
        "timeout" in name
        or "timeout" in text
        or "timed out" in text
        or "read operation timed out" in text
    )


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
    if _is_timeout_error(exc):
        return f"Gemini model '{model}' did not respond within the configured timeout."
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
    """Call Gemini with bounded retries, timeout handling, and model fallback.

    Important: the SDK's own retry loop is disabled at client construction.
    This function is the single place that decides whether to retry, wait,
    switch models, or fail cleanly.
    """
    require_client()
    _ensure_pipeline_time()
    models = _model_sequence()
    errors = []
    quota_models = []

    for model_index, model in enumerate(models):
        _ensure_pipeline_time()
        model_saw_quota = False
        model_attempts = 0
        max_attempts = max(GEMINI_RETRY_ATTEMPTS, GEMINI_TIMEOUT_RETRIES + 1)

        while model_attempts < max_attempts:
            model_attempts += 1
            _ensure_pipeline_time()

            try:
                remaining = None
                pipeline_deadline = _pipeline_deadline()
                if pipeline_deadline is not None:
                    remaining = max(1.0, pipeline_deadline - time.monotonic())

                timeout_seconds = GEMINI_REQUEST_TIMEOUT_SECONDS
                if remaining is not None:
                    timeout_seconds = min(timeout_seconds, max(1.0, remaining - 0.5))

                config = types.GenerateContentConfig(
                    temperature=0,
                    http_options=types.HttpOptions(
                        timeout=int(timeout_seconds * 1000),
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                )

                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )
                result = (getattr(response, "text", "") or "").strip()
                if not result:
                    raise RuntimeError(
                        f"Gemini returned an empty response from model '{model}'."
                    )
                return result

            except Exception as exc:
                code = _exception_code(exc)
                timeout_error = _is_timeout_error(exc)
                errors.append((model, code, exc))

                if _is_quota_exhausted(exc):
                    model_saw_quota = True
                    quota_models.append(model)
                    print(
                        f"[Gemini] quota exhausted for model={model}; switching without retry",
                        flush=True,
                    )
                    break

                if code == 429:
                    # A non-quota 429 is a short-lived rate limit. Give it only
                    # the explicitly configured bounded retry, then switch model.
                    if model_attempts >= GEMINI_429_RETRIES + 1:
                        print(
                            f"[Gemini] rate limit exhausted model={model}; switching fallback",
                            flush=True,
                        )
                        break
                    delay = min(5.0, _retry_delay(exc, model_attempts))
                    deadline = _pipeline_deadline()
                    if deadline is not None:
                        delay = min(
                            delay,
                            max(0.0, deadline - time.monotonic() - 1.0),
                        )
                    if delay > 0:
                        print(
                            f"[Gemini] rate limited model={model}; retrying in {delay:.2f}s",
                            flush=True,
                        )
                        time.sleep(delay)
                    continue

                if timeout_error:
                    # Read/connect timeouts have no HTTP status code. Treat them
                    # as transient, but keep the retry budget smaller than the
                    # general 5xx budget so a slow model cannot consume the whole
                    # Render request. After the bounded timeout retry, fallback.
                    if model_attempts > GEMINI_TIMEOUT_RETRIES:
                        print(
                            f"[Gemini] timeout model={model}; switching fallback",
                            flush=True,
                        )
                        break
                    deadline = _pipeline_deadline()
                    if deadline is not None and deadline - time.monotonic() <= 2:
                        raise PipelineTimeoutError()
                    delay = min(1.0, max(0.0, GEMINI_INITIAL_BACKOFF / 2))
                    print(
                        f"[Gemini] timeout model={model}; retrying once in {delay:.2f}s",
                        flush=True,
                    )
                    if delay:
                        time.sleep(delay)
                    continue

                if code in TRANSIENT_GEMINI_CODES:
                    if model_attempts >= GEMINI_RETRY_ATTEMPTS:
                        print(
                            f"[Gemini] transient retries exhausted model={model} code={code}; switching fallback",
                            flush=True,
                        )
                        break
                    delay = _retry_delay(exc, model_attempts)
                    deadline = _pipeline_deadline()
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 1.0:
                            raise PipelineTimeoutError()
                        delay = min(delay, remaining - 1.0)
                    print(
                        f"[Gemini] transient error model={model} code={code} "
                        f"attempt={model_attempts}/{GEMINI_RETRY_ATTEMPTS}; "
                        f"retrying in {delay:.2f}s",
                        flush=True,
                    )
                    time.sleep(max(0.0, delay))
                    continue

                if code == 404:
                    print(
                        f"[Gemini] model '{model}' not found; switching fallback",
                        flush=True,
                    )
                    break

                # Authentication/permission and other deterministic failures
                # should fail immediately rather than consuming the request budget.
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
            print(
                f"[Gemini] switching from '{model}' to fallback '{models[model_index + 1]}'",
                flush=True,
            )

    if quota_models and len(quota_models) == len(models):
        raise GeminiQuotaError(quota_models)

    temporary = [
        (m, c, e)
        for m, c, e in errors
        if c in TRANSIENT_GEMINI_CODES or c == 429 or _is_timeout_error(e)
    ]
    if temporary:
        summary = "; ".join(
            f"{m}:{c or e.__class__.__name__}" for m, c, e in temporary[-len(models):]
        )
        raise GeminiUnavailableError(
            "Gemini is currently unavailable on all configured models. "
            f"Attempt summary: {summary}",
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


def low_call_generate_agent(user_request):
    """
    One Gemini call for the normal path:
    requirement understanding + RTL + independent self-checking testbench.
    The simulator, not Gemini, decides whether the result is verified.
    """
    prompt = f"""
You are the primary RTL engineer for a professional ECE hardware workbench.

Convert the user's natural-language requirement into a synthesizable SystemVerilog
DUT and an INDEPENDENT self-checking SystemVerilog testbench.

This is a GENERAL digital RTL agent. Do not assume the design is a fixed circuit.
Infer the required architecture, interface, clock/reset behavior, latency and corner
cases from the request. Use reasonable explicit assumptions only when necessary.

IMPORTANT:
- The DUT must be synthesizable SystemVerilog.
- The testbench must independently calculate expected behavior; do NOT simply copy
  the DUT implementation into the checker.
- Exercise normal cases and meaningful corner cases.
- For small combinational spaces, prefer exhaustive testing.
- For sequential designs, test reset, state transitions, boundaries and back-to-back use.
- The testbench must print exactly "TEST_RESULT: PASS" only if every check passes.
- It must print "TEST_RESULT: FAIL" and useful mismatch information on failure.
- The testbench module MUST be named `tb`.
- Avoid vendor-specific primitives unless requested.
- No shell commands, file I/O, DPI, network calls, or unsafe system tasks.
- Return ONLY valid JSON. No markdown fences.

JSON schema:
{{
  "design_name": "...",
  "rtl": "complete SystemVerilog DUT source",
  "testbench": "complete SystemVerilog testbench source",
  "assumptions": ["..."]
}}

USER REQUIREMENT:
{user_request}
"""
    result = extract_json(gemini_text(prompt))
    rtl = extract_code(result.get("rtl", ""))
    tb = extract_code(result.get("testbench", ""))
    if not rtl:
        raise ValueError("Gemini returned no RTL.")
    if not tb:
        raise ValueError("Gemini returned no testbench.")
    if not safe_hdl(rtl):
        raise ValueError("Generated RTL contains a forbidden system construct.")
    if not safe_hdl(tb):
        raise ValueError("Generated testbench contains a forbidden system construct.")
    if not re.search(r'\bmodule\s+tb\b', tb):
        raise ValueError("Generated testbench must contain a module named tb.")
    return {
        "design_name": str(result.get("design_name") or "generated_design"),
        "rtl": rtl,
        "testbench": tb,
        "assumptions": result.get("assumptions") or [],
    }


def low_call_repair_agent(user_request, rtl, tb, sim):
    """
    One Gemini call only when objective compilation/simulation fails.
    It repairs the RTL and/or testbench without weakening verification.
    """
    prompt = f"""
You are a senior RTL debug and repair engineer.

A generated digital RTL project failed objective Icarus Verilog compilation or
self-checking simulation.

Repair the project. Determine whether the fault is in the DUT, testbench, interface,
reset/clock timing, latency assumptions, or expected-value model.

Rules:
- Preserve the user's original hardware requirement.
- Do not weaken, remove, bypass, or comment out tests merely to obtain PASS.
- Keep the testbench genuinely independent from the DUT.
- The DUT must remain synthesizable SystemVerilog.
- The testbench module must be named `tb`.
- Return complete replacement source for BOTH RTL and testbench.
- No markdown fences.
- No shell/file/network/DPI/system commands.
- The testbench must print exactly "TEST_RESULT: PASS" only when all checks pass.
- Return ONLY valid JSON.

JSON:
{{
  "diagnosis": "...",
  "rtl": "complete corrected SystemVerilog DUT",
  "testbench": "complete corrected SystemVerilog testbench"
}}

USER REQUIREMENT:
{user_request}

CURRENT RTL:
```systemverilog
{rtl}
```

CURRENT TESTBENCH:
```systemverilog
{tb}
```

OBJECTIVE SIMULATION RESULT:
{json.dumps(sim, indent=2)}
"""
    result = extract_json(gemini_text(prompt))
    corrected_rtl = extract_code(result.get("rtl", "")) or rtl
    corrected_tb = extract_code(result.get("testbench", "")) or tb
    if not safe_hdl(corrected_rtl):
        raise ValueError("Repair agent produced unsafe RTL.")
    if not safe_hdl(corrected_tb):
        raise ValueError("Repair agent produced unsafe testbench.")
    if not re.search(r'\bmodule\s+tb\b', corrected_tb):
        raise ValueError("Repair agent produced an invalid testbench module.")
    return {
        "diagnosis": str(result.get("diagnosis") or "Automatic repair applied."),
        "rtl": corrected_rtl,
        "testbench": corrected_tb,
    }


def run_pipeline(user_request):
    """
    Low-Gemini-call execution path.

    Normal request:
        1 Gemini call -> RTL + independent TB
        local compile/simulation -> verification

    Failure:
        one Gemini repair call -> local compile/simulation again
        repeat only when needed, bounded by MAX_REPAIR_ATTEMPTS.
    """
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOB_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    deadline_token = _set_pipeline_deadline(time.monotonic() + MAX_PIPELINE_SECONDS)

    rtl = ""
    tb = ""
    sim = {"pass": False, "stage": "not_started", "log": ""}
    repair_history = []

    try:
        _ensure_pipeline_time()

        generated = low_call_generate_agent(user_request)
        rtl = generated["rtl"]
        tb = generated["testbench"]

        for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
            _ensure_pipeline_time()

            sim = simulate(rtl, tb, job_dir)
            repair_history.append({
                "attempt": attempt,
                "simulation": {
                    "pass": bool(sim.get("pass")),
                    "stage": sim.get("stage"),
                },
            })

            if sim.get("pass"):
                break

            if attempt >= MAX_REPAIR_ATTEMPTS:
                break

            _ensure_pipeline_time()
            repair = low_call_repair_agent(user_request, rtl, tb, sim)
            rtl = repair["rtl"]
            tb = repair["testbench"]

        # Persist engineering artifacts, but do not expose internal planning
        # artifacts through the normal UI/API response.
        (job_dir / "design.sv").write_text(rtl, encoding="utf-8")
        (job_dir / "testbench.sv").write_text(tb, encoding="utf-8")
        (job_dir / "simulation.log").write_text(sim.get("log", ""), encoding="utf-8")
        (job_dir / "repair_history.json").write_text(
            json.dumps(repair_history, indent=2), encoding="utf-8"
        )
        (job_dir / "request.txt").write_text(user_request, encoding="utf-8")
        (job_dir / "assumptions.json").write_text(
            json.dumps(generated.get("assumptions", []), indent=2), encoding="utf-8"
        )
        make_zip(job_dir)

        passed = bool(sim.get("pass"))
        return {
            "job_id": job_id,
            "rtl": rtl,
            "verification": {
                "passed": passed,
                "quality": "strong" if passed else "failed",
                "stage": sim.get("stage"),
                "repair_attempts": len(repair_history) - 1,
            },
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
        "gemini_timeout_retries": GEMINI_TIMEOUT_RETRIES,
        "gemini_thinking_level": GEMINI_THINKING_LEVEL,
        "max_pipeline_seconds": MAX_PIPELINE_SECONDS,
        "max_repair_attempts": MAX_REPAIR_ATTEMPTS,
        "iverilog": shutil.which("iverilog") is not None,
        "graphviz": shutil.which("dot") is not None,
    })

@app.get("/api/config")
def api_config():
    # Safe diagnostic information only; never expose the API key.
    return jsonify({
        "primary_model": MODEL,
        "fallback_models": FALLBACK_MODELS,
        "retry_attempts": GEMINI_RETRY_ATTEMPTS,
        "rate_limit_retries": GEMINI_429_RETRIES,
        "timeout_retries": GEMINI_TIMEOUT_RETRIES,
        "request_timeout_seconds": GEMINI_REQUEST_TIMEOUT_SECONDS,
        "max_repair_attempts": MAX_REPAIR_ATTEMPTS,
        "architecture": "1 Gemini generation + local Icarus verification + repair only on failure"
    })

@app.post("/api/build")
def api_build():
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error":"Request body must be JSON.","error_type":"invalid_request","retryable":False}), 400
        user_request = (data.get("request") or "").strip()
        if not user_request:
            return jsonify({"error":"Missing hardware requirement.","error_type":"invalid_request","retryable":False}), 400
        if len(user_request) > 12000:
            return jsonify({"error":"Requirement is too long. Keep it under 12,000 characters.","error_type":"invalid_request","retryable":False}), 400

        result = run_pipeline(user_request)

        # Public API intentionally exposes only the clean user-facing result.
        # Testbench, simulator logs, repair history and other internal artifacts
        # remain server-side.
        return jsonify({
            "rtl": result.get("rtl", ""),
            "verification": result.get("verification", {
                "passed": False,
                "quality": "failed",
            }),
        }), 200
    except GeminiServiceError as e:
        app.logger.warning("Build stopped: %s", e)
        return jsonify({"error":str(e),"error_type":e.code,"retryable":e.retryable}), e.status
    except ValueError as e:
        app.logger.warning("Build validation failed: %s", e)
        return jsonify({"error":str(e),"error_type":"validation_error","retryable":False}), 422
    except Exception as e:
        app.logger.exception("Build failed")
        return jsonify({"error":"The hardware build failed unexpectedly.","details":str(e),"error_type":"internal_error","retryable":False}), 500

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
