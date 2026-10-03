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
REQUEST_TIMEOUT = max(18, min(25, float(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "18"))))
MAX_REPAIR_ATTEMPTS = max(0, min(2, int(os.getenv("MAX_REPAIR_ATTEMPTS", "1"))))
SIM_TIMEOUT = max(12, min(20, int(os.getenv("SIM_TIMEOUT_SECONDS", "15"))))
MAX_BUILD_SECONDS = max(90, min(120, int(os.getenv("MAX_BUILD_SECONDS", "110"))))
MAX_REQUEST_CHARS = max(5000, min(12000, int(os.getenv("MAX_REQUEST_CHARS", "12000"))))
GENERATION_RECOVERY_ATTEMPTS = max(1, min(2, int(os.getenv("GENERATION_RECOVERY_ATTEMPTS", "2"))))
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
:root{--bg:#070706;--panel:#0d0d0b;--panel2:#14120d;--line:#302c21;--line2:#62583e;--text:#f2eee5;--muted:#aaa28f;--dim:#706957;--lime:#e7c46a;--gold:#d8ad4b;--gold2:#f4d98b;--cyan:#78d7cf;--orange:#e2a15c;--red:#ff7777;--blue:#9cb7d9;--shadow:0 30px 90px rgba(0,0,0,.52),0 0 70px rgba(216,173,75,.045)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 12% 5%,rgba(231,196,106,.05),transparent 25%),radial-gradient(circle at 88% 20%,rgba(120,215,207,.045),transparent 25%),linear-gradient(180deg,#080a0b,#0b0e0f 50%,#080a0b);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow-x:hidden}body:before{content:"";position:fixed;inset:0;pointer-events:none;z-index:-2;background-image:linear-gradient(rgba(255,255,255,.022) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.022) 1px,transparent 1px);background-size:36px 36px;mask-image:linear-gradient(#000,transparent 82%)}body:after{content:"";position:fixed;top:-15%;left:0;width:100%;height:15%;pointer-events:none;z-index:60;background:linear-gradient(transparent,rgba(231,196,106,.035),transparent);animation:scan 13s linear infinite}button,textarea{font:inherit}.shell{width:min(1420px,calc(100% - 34px));margin:auto;padding-bottom:90px}#scrollProgress{position:fixed;left:0;top:0;width:0;height:2px;background:var(--lime);box-shadow:0 0 12px rgba(231,196,106,.55);z-index:100}
.nav{height:64px;margin-top:12px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:50;background:rgba(9,11,12,.88);backdrop-filter:blur(16px)}.brand{display:flex;align-items:center;gap:11px}.brandmark{width:34px;height:34px;border:1px solid var(--line2);background:#151919;display:grid;place-items:center;color:var(--lime);font:900 10px ui-monospace,monospace;position:relative}.brandmark:after{content:"";position:absolute;right:-4px;bottom:-4px;width:7px;height:7px;background:var(--lime)}.brand b{font-size:12px;letter-spacing:.1em}.brand small{display:block;color:var(--dim);font:800 7px ui-monospace,monospace;letter-spacing:.18em;margin-top:3px}.navlinks{display:flex;gap:18px}.navlinks a{color:#737d79;text-decoration:none;font:800 8px ui-monospace,monospace;letter-spacing:.12em}.navlinks a:hover{color:var(--lime)}.health{display:flex;gap:7px;align-items:center;color:#7f8985;font:800 8px ui-monospace,monospace}.health i{width:6px;height:6px;border-radius:50%;background:var(--lime);box-shadow:0 0 12px rgba(231,196,106,.7);animation:pulse 1.8s infinite}
.hero{min-height:700px;display:grid;grid-template-columns:1.05fr .95fr;align-items:center;gap:30px}.heroCopy{padding:70px 0}.eyebrow{display:inline-flex;gap:8px;align-items:center;border:1px solid var(--line2);padding:7px 9px;background:#111516;color:#aab4b0;font:900 8px ui-monospace,monospace;letter-spacing:.15em}.eyebrow b{color:var(--lime)}.hero h1{font-size:clamp(55px,7.5vw,101px);line-height:.86;letter-spacing:-.075em;margin:24px 0 20px;max-width:850px}.hero h1 span{display:block;color:#737b78}.hero h1 em{font-style:normal;color:var(--lime)}.hero p{max-width:680px;color:#919b97;line-height:1.8;font-size:14px}.heroStats{display:flex;margin-top:30px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);width:max-content}.stat{padding:13px 20px 12px 0;margin-right:20px;border-right:1px solid var(--line)}.stat:last-child{border-right:0}.stat b{display:block;font-size:14px}.stat span{color:#65706d;font:800 7px ui-monospace,monospace;letter-spacing:.12em}.scrollCue{margin-top:42px;color:#626d69;font:900 8px ui-monospace,monospace;letter-spacing:.16em}.scrollCue:after{content:"↓";display:inline-block;margin-left:10px;color:var(--lime);animation:bob 1.4s infinite}.heroVisual{height:550px;position:relative;display:grid;place-items:center;perspective:1100px;transition:transform .15s linear}.board3d{width:min(510px,90%);aspect-ratio:1.35/1;border:1px solid #46514d;background:linear-gradient(135deg,#181d1c,#0d1111 52%,#171c19);transform:rotateX(58deg) rotateZ(-28deg);box-shadow:30px 45px 0 rgba(0,0,0,.22),0 80px 100px rgba(0,0,0,.4),inset 0 0 60px rgba(231,196,106,.035);position:relative;animation:boardFloat 7s ease-in-out infinite;overflow:hidden}.board3d:before{content:"";position:absolute;inset:22px;background:repeating-linear-gradient(90deg,transparent 0 31px,rgba(231,196,106,.09) 32px,transparent 33px),repeating-linear-gradient(0deg,transparent 0 25px,rgba(120,215,207,.08) 26px,transparent 27px)}.board3d:after{content:"";position:absolute;width:120px;height:120px;border:1px solid rgba(231,196,106,.25);background:#111716;left:42%;top:35%;box-shadow:0 0 0 12px rgba(231,196,106,.025),0 0 35px rgba(231,196,106,.08);animation:chipPulse 3s ease-in-out infinite}.traceLine{position:absolute;height:1px;background:var(--lime);box-shadow:0 0 8px rgba(231,196,106,.5);transform-origin:left center}.t1{width:170px;left:4%;top:27%;transform:rotate(7deg)}.t2{width:220px;right:2%;top:65%;transform:rotate(-8deg);background:var(--cyan)}.t3{width:150px;left:12%;bottom:17%;transform:rotate(-12deg);background:var(--orange)}.node{position:absolute;width:7px;height:7px;border:1px solid #0a0c0d;background:var(--lime);z-index:2}.n1{left:9%;top:26%}.n2{right:8%;top:64%;background:var(--cyan)}.n3{left:18%;bottom:16%;background:var(--orange)}.floatCard{position:absolute;border:1px solid var(--line2);background:rgba(17,22,22,.88);backdrop-filter:blur(12px);padding:12px;box-shadow:var(--shadow);font:800 8px ui-monospace,monospace;color:#a0aaa6;animation:cardFloat 5s ease-in-out infinite}.floatCard b{display:block;color:var(--lime);font-size:11px;margin-bottom:5px}.fc1{top:15%;right:2%}.fc2{bottom:14%;left:4%;animation-delay:-2s}
.section{padding:72px 0 18px}.sectionHead{display:flex;justify-content:space-between;align-items:end;gap:35px;margin-bottom:22px}.kicker{color:#68736f;font:900 8px ui-monospace,monospace;letter-spacing:.18em}.sectionHead h2{font-size:clamp(30px,4vw,56px);letter-spacing:-.065em;margin:7px 0 0}.sectionHead p{max-width:470px;color:#77817e;font-size:12px;line-height:1.75;margin:0}.visualRail{display:grid;grid-template-columns:1.15fr .85fr 1fr;gap:12px}.techShot{height:330px;position:relative;overflow:hidden;border:1px solid #303938;background:#111515}.techShot.tall{height:390px}.techShot img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:grayscale(.25) saturate(.6) contrast(1.12) brightness(.56);transform:scale(1.02);transition:1s cubic-bezier(.2,.7,.2,1)}.techShot:hover img{transform:scale(1.1);filter:grayscale(.05) saturate(.9) contrast(1.08) brightness(.73)}.techShot:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,transparent 44%,rgba(5,7,7,.95));pointer-events:none}.techShot figcaption{position:absolute;z-index:2;left:15px;right:15px;bottom:13px;display:flex;justify-content:space-between;color:#dfe5e1;font:900 8px ui-monospace,monospace;letter-spacing:.1em}.techShot figcaption b{color:var(--lime)}
.motifGrid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.motif{border:1px solid #303938;background:#101415;min-height:220px;padding:14px;position:relative;overflow:hidden}.motif:hover{border-color:#56615d}.motifTop{display:flex;justify-content:space-between;color:#6c7773;font:900 7px ui-monospace,monospace;letter-spacing:.14em}.motifTop b{color:var(--lime)}.motif svg{width:100%;height:155px;margin-top:10px}
.workstation:before{content:"";display:block;height:2px;background:linear-gradient(90deg,transparent,var(--lime),var(--cyan),transparent);opacity:.55}.workstation{margin-top:28px;margin-bottom:12px;border:1px solid #38413f;background:#101415;box-shadow:var(--shadow)}.stationHead{display:grid;grid-template-columns:1fr auto;border-bottom:1px solid #303938;padding:18px 20px;background:#131819}.stationTitle h2{margin:6px 0 0;font-size:19px;letter-spacing:-.03em}.stationMeta{align-self:center;border:1px solid #3a4542;padding:7px 9px;color:#929b97;font:900 7px ui-monospace,monospace}.stationBody{padding:18px 20px 20px}.inputPanel{border:1px solid #394441;background:#0b0f10}.panelBar{height:34px;border-bottom:1px solid #303938;display:flex;justify-content:space-between;align-items:center;padding:0 11px;color:#7c8783;font:900 7px ui-monospace,monospace}.traffic{display:inline-flex;gap:4px;margin-right:7px}.traffic i{width:5px;height:5px;border-radius:50%;background:#4b5552}.inputPanel textarea{display:block;width:100%;min-height:210px;max-height:440px;resize:vertical;border:0;outline:0;background:#080b0c;color:#e2e8e4;padding:18px;font:13px/1.75 ui-monospace,SFMono-Regular,Consolas,monospace}.inputPanel textarea::placeholder{color:#59635f}.inputFoot{display:flex;justify-content:space-between;border-top:1px solid #303938;padding:7px 11px;color:#606b67;font:800 7px ui-monospace,monospace}.promptStrip{display:flex;gap:7px;flex-wrap:wrap;margin:12px 0}.prompt{border:1px solid #394441;background:#151a1a;color:#a1aaa6;padding:7px 9px;cursor:pointer;font:900 7px ui-monospace,monospace}.prompt:hover{color:#dfffa5;border-color:#6d7b73}.stationControls{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:13px}.buildHint{color:#69736f;font:800 8px ui-monospace,monospace}.buildBtn{border:1px solid #8b7136;background:#e7c46a;color:#10130d;padding:12px 16px;font-size:9px;font-weight:950;cursor:pointer;box-shadow:0 8px 30px rgba(231,196,106,.1);transition:.2s}.buildBtn:hover{transform:translateY(-2px);box-shadow:0 12px 35px rgba(231,196,106,.18)}.buildBtn:disabled{opacity:.5;cursor:not-allowed;transform:none}.status{min-height:40px;padding-top:13px}.notice{border:1px solid #394441;background:#0b0f10;padding:10px 12px;color:#9da6a2;font-size:10px}.notice.ok{border-color:#66562f;color:#c6e98a}.notice.err{border-color:#6c3e40;color:#ff9b9d}.notice.wait{color:#a8c2c0}.stageRail{display:grid;grid-template-columns:repeat(6,1fr);gap:4px;margin-top:10px;border-top:1px solid #303938;padding-top:12px}.stage{position:relative;border:1px solid #303938;background:#0b0f10;padding:10px 7px;color:#58625e;font:900 7px ui-monospace,monospace;text-align:center;letter-spacing:.1em}.stage small{display:block;color:#444d4a;font-size:6px;margin-bottom:5px}.stage.active{color:var(--lime);border-color:#725e31;background:#141a12}.stage.active:after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:2px;background:var(--lime);animation:stagePulse 1s infinite}.stage.done{color:#90a77b;border-color:#4c5a3c}
.result{margin-top:28px;border:1px solid #38413f;background:#0e1213}.resultHead{display:flex;justify-content:space-between;align-items:center;gap:15px;padding:15px 17px;border-bottom:1px solid #303938;background:#121718}.resultIdentity{display:flex;gap:10px;align-items:center}.resultIcon{width:30px;height:30px;border:1px solid #4a5652;display:grid;place-items:center;color:#909a96;font:900 13px ui-monospace,monospace}.resultIcon.pass{color:var(--lime);border-color:#657d3c}.resultIcon.fail{color:var(--red);border-color:#754547}.resultIdentity b{font-size:13px}.resultIdentity small{display:block;color:#65706d;font:700 7px ui-monospace,monospace;margin-top:4px}.actions{display:flex;gap:5px;flex-wrap:wrap}.toolBtn{border:1px solid #3c4744;background:#171c1c;color:#b1bbb7;padding:7px 9px;cursor:pointer;font:900 7px ui-monospace,monospace}.toolBtn:hover{color:#e9f0ec;border-color:#707b76}.artifactGrid{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px}.artifact{border:1px solid #303938;background:#090d0e;min-width:0}.artifact.full{grid-column:1/-1}.artifactHead{height:34px;border-bottom:1px solid #303938;display:flex;justify-content:space-between;align-items:center;padding:0 11px;color:#69736f;font:900 7px ui-monospace,monospace}.artifactHead b{color:#aab3af}.codeWindow{display:grid;grid-template-columns:44px minmax(0,1fr);max-height:560px;overflow:auto;background:#070a0b}.lineNums{padding:15px 8px 15px 0;text-align:right;color:#3e4845;border-right:1px solid #222b29;font:11px/1.72 ui-monospace,SFMono-Regular,Consolas,monospace;user-select:none}.code{margin:0;padding:15px 16px;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;color:#dbe2de;font:11px/1.72 ui-monospace,SFMono-Regular,Consolas,monospace;tab-size:4}.code .kw{color:#e7c46a}.code .str{color:#ffbf79}.code .num{color:#8fb8ff}.code .com{color:#65716c}.visual{padding:12px;overflow:auto;min-height:230px;background:#070a0b}.visual svg{display:block;width:100%;height:auto;min-width:650px}.empty{min-height:205px;border:1px dashed #35403d;display:grid;place-items:center;text-align:center;color:#5d6864;font:900 8px ui-monospace,monospace;letter-spacing:.1em}.console{padding:13px}.verify{border:1px solid #3b4945;background:#0a0e0f;padding:13px;color:#85918c;font-size:9px;line-height:1.75}.verify.pass{border-color:#5f512f}.verify.pass strong{color:var(--lime)}.verify.fail{border-color:#673e40}.verify.fail strong{color:#ff9a9b}.log{margin-top:9px;border-top:1px solid #303938;padding-top:9px;white-space:pre-wrap;overflow:auto;max-height:260px;color:#6e7975;font:9px/1.65 ui-monospace,SFMono-Regular,Consolas,monospace}.resultNote{padding:11px 13px;border-top:1px solid #303938;color:#66716d;font-size:8px;line-height:1.7}.infoGrid{display:grid;grid-template-columns:1.2fr .8fr .8fr;gap:12px;margin-top:35px}.infoCard{border:1px solid #303938;background:#101415;padding:17px;min-height:145px;position:relative;overflow:hidden}.infoCard b{font-size:11px}.infoCard p{color:#737e7a;font-size:9px;line-height:1.7}.infoCard:after{content:"";position:absolute;width:120px;height:120px;border:1px solid rgba(231,196,106,.08);right:-45px;bottom:-55px;transform:rotate(45deg)}.footer{margin-top:45px;color:#515c58;text-align:center;font:900 7px ui-monospace,monospace;letter-spacing:.16em}.reveal{opacity:0;transform:translateY(34px);transition:opacity .8s ease,transform .8s cubic-bezier(.2,.7,.2,1)}.reveal.visible{opacity:1;transform:none}.spinner{display:inline-block;width:10px;height:10px;border:2px solid #34433d;border-top-color:var(--lime);border-radius:50%;animation:spin .65s linear infinite;vertical-align:-2px}
@keyframes pulse{50%{opacity:.25;transform:scale(.65)}}@keyframes spin{to{transform:rotate(360deg)}}@keyframes scan{to{transform:translateY(720%)}}@keyframes boardFloat{0%,100%{transform:rotateX(58deg) rotateZ(-28deg) translateY(0)}50%{transform:rotateX(58deg) rotateZ(-28deg) translateY(-15px)}}@keyframes chipPulse{50%{box-shadow:0 0 0 18px rgba(231,196,106,.02),0 0 50px rgba(231,196,106,.12)}}@keyframes cardFloat{50%{transform:translateY(-9px)}}@keyframes bob{50%{transform:translateY(5px)}}@keyframes stagePulse{50%{opacity:.35}}
@media(max-width:980px){.hero{grid-template-columns:1fr;min-height:850px}.heroCopy{padding-top:80px}.heroVisual{height:400px}.navlinks{display:none}.visualRail{grid-template-columns:1fr}.techShot,.techShot.tall{height:300px}.motifGrid{grid-template-columns:1fr}.infoGrid{grid-template-columns:1fr}.artifactGrid{grid-template-columns:1fr}.artifact.full{grid-column:auto}.stageRail{grid-template-columns:repeat(3,1fr)}}
@media(max-width:620px){.shell{width:calc(100% - 18px)}.hero h1{font-size:55px}.heroStats{width:100%}.stat{padding-right:10px;margin-right:10px}.heroVisual{height:300px}.board3d{width:88%}.floatCard{display:none}.stationHead{grid-template-columns:1fr}.stationMeta{width:max-content;margin-top:10px}.stationControls{flex-direction:column;align-items:stretch}.buildBtn{width:100%}.stageRail{grid-template-columns:repeat(2,1fr)}.codeWindow{grid-template-columns:34px minmax(0,1fr)}.code,.lineNums{font-size:10px}.artifactGrid{padding:8px}.section{padding-top:50px}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation-duration:.001ms!important;animation-iteration-count:1!important;scroll-behavior:auto!important;transition-duration:.001ms!important}}

/* ============================================================
   GOLDEN HARDWARE LAB — VISUAL LAYER ONLY
   Keeps the existing RTL pipeline untouched.
   ============================================================ */
html{scroll-padding-top:82px}
body{background:
  radial-gradient(circle at 76% 8%,rgba(216,173,75,.10),transparent 22%),
  radial-gradient(circle at 15% 34%,rgba(120,215,207,.045),transparent 25%),
  linear-gradient(180deg,#050504 0%,#0a0907 35%,#070706 100%);
  color:#f2eee5}
body:before{background-image:
  linear-gradient(rgba(231,196,106,.025) 1px,transparent 1px),
  linear-gradient(90deg,rgba(231,196,106,.025) 1px,transparent 1px);
  background-size:42px 42px;
  mask-image:linear-gradient(#000 0%,rgba(0,0,0,.8) 48%,transparent 94%)}
body:after{height:11%;background:linear-gradient(transparent,rgba(231,196,106,.055),transparent);filter:blur(.2px);animation:goldScan 11s linear infinite}
#scrollProgress{height:3px;background:linear-gradient(90deg,#9a6d27,#e7c46a,#f4d98b,#78d7cf);box-shadow:0 0 18px rgba(231,196,106,.7),0 0 35px rgba(231,196,106,.22)}
.nav{border-color:#3b3527;background:rgba(6,6,5,.86);box-shadow:0 10px 40px rgba(0,0,0,.3)}
.nav:after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:1px;background:linear-gradient(90deg,transparent,#7f632e,transparent);opacity:.75}
.brandmark{border-color:#6b5a38;background:linear-gradient(145deg,#17150f,#0c0c09);color:var(--gold2);box-shadow:inset 0 0 18px rgba(231,196,106,.07)}
.brandmark:after{background:var(--gold2);box-shadow:0 0 12px rgba(231,196,106,.65)}
.navlinks a:hover{color:var(--gold2)}
.health i{background:var(--gold2);box-shadow:0 0 14px rgba(231,196,106,.8)}
.eyebrow{border-color:#675633;background:linear-gradient(180deg,#14120d,#0b0b08);box-shadow:inset 0 0 24px rgba(231,196,106,.035)}
.eyebrow b{color:var(--gold2)}
.hero{position:relative}
.hero:before{content:"";position:absolute;inset:12% 0 8%;pointer-events:none;background:radial-gradient(circle at 68% 46%,rgba(231,196,106,.08),transparent 24%);filter:blur(18px)}
.hero h1 em{color:var(--gold2);text-shadow:0 0 35px rgba(231,196,106,.13)}
.hero h1 span{color:#77736a}
.heroStats{border-color:#3b3528}
.stat{border-color:#3b3528}
.scrollCue:after{color:var(--gold2)}
.heroVisual{filter:drop-shadow(0 30px 55px rgba(0,0,0,.45))}
.board3d{border-color:#625635;background:
  linear-gradient(135deg,#19160f,#0b0b08 52%,#15130e),
  repeating-linear-gradient(90deg,transparent 0 31px,rgba(231,196,106,.08) 32px,transparent 33px);
  box-shadow:30px 45px 0 rgba(0,0,0,.28),0 80px 100px rgba(0,0,0,.5),inset 0 0 70px rgba(231,196,106,.07)}
.board3d:before{background:repeating-linear-gradient(90deg,transparent 0 31px,rgba(231,196,106,.10) 32px,transparent 33px),repeating-linear-gradient(0deg,transparent 0 25px,rgba(120,215,207,.06) 26px,transparent 27px)}
.board3d:after{border-color:rgba(231,196,106,.35);background:#12100b;box-shadow:0 0 0 12px rgba(231,196,106,.025),0 0 45px rgba(231,196,106,.12)}
.traceLine{background:var(--gold2);box-shadow:0 0 10px rgba(231,196,106,.65)}
.t2{background:var(--cyan)}.t3{background:var(--orange)}
.node{background:var(--gold2)}.n2{background:var(--cyan)}.n3{background:var(--orange)}
.floatCard{border-color:#5a4d32;background:rgba(14,13,9,.9);box-shadow:0 25px 60px rgba(0,0,0,.55),inset 0 0 22px rgba(231,196,106,.035)}
.floatCard b{color:var(--gold2)}
.section{position:relative}
.section:after{content:"";position:absolute;left:0;right:0;top:35px;height:1px;background:linear-gradient(90deg,rgba(231,196,106,.22),transparent 45%,rgba(120,215,207,.12),transparent);opacity:.6}
.kicker{color:#8a7954}.sectionHead h2{color:#eee9df}
.visualRail{perspective:1000px}
.techShot{border-color:#4b412d;background:#0d0c09;box-shadow:0 18px 50px rgba(0,0,0,.35);transform-style:preserve-3d;transition:transform .65s cubic-bezier(.2,.8,.2,1),border-color .35s,box-shadow .35s}
.techShot:before{content:"";position:absolute;inset:0;z-index:1;background:linear-gradient(125deg,rgba(231,196,106,.10),transparent 28%,transparent 70%,rgba(120,215,207,.055));mix-blend-mode:screen;pointer-events:none}
.techShot:hover{border-color:#8a713a;box-shadow:0 30px 75px rgba(0,0,0,.5),0 0 35px rgba(231,196,106,.07)}
.techShot img{translate:0 var(--img-shift,0);filter:grayscale(.15) sepia(.13) saturate(.7) contrast(1.14) brightness(.48);transition:transform 1.15s cubic-bezier(.15,.8,.2,1),filter 1.15s}
.techShot:hover img{filter:grayscale(.02) sepia(.05) saturate(.92) contrast(1.1) brightness(.67)}
.techShot figcaption b{color:var(--gold2)}
.motif{border-color:#3f3829;background:linear-gradient(145deg,#11100c,#0b0b09);box-shadow:0 18px 55px rgba(0,0,0,.25);transition:transform .5s cubic-bezier(.2,.8,.2,1),border-color .35s,box-shadow .35s}
.motif:hover{border-color:#756039;box-shadow:0 28px 70px rgba(0,0,0,.42),0 0 28px rgba(231,196,106,.055);transform:translateY(-6px)}
.motifTop b{color:var(--gold2)}
.motif svg{color:#d9d2c5;filter:drop-shadow(0 0 7px rgba(231,196,106,.07))}
.workstation{border-color:#51452f;background:linear-gradient(145deg,#11100c,#0b0b09);box-shadow:0 28px 85px rgba(0,0,0,.45),inset 0 0 40px rgba(231,196,106,.025)}
.workstation:before{background:linear-gradient(90deg,transparent,#a57c32,#e7c46a,#78d7cf,transparent);box-shadow:0 0 18px rgba(231,196,106,.18)}
.stationHead{border-color:#393225;background:linear-gradient(180deg,#15130e,#0f0e0b)}
.stationMeta{border-color:#5a4d32;color:#a89b7e}
.inputPanel{border-color:#4b412e;background:#080806;box-shadow:inset 0 0 35px rgba(231,196,106,.025)}
.panelBar{border-color:#393226;color:#8d8062}
.inputPanel textarea{background:#060605;color:#eee9df;caret-color:var(--gold2)}
.inputPanel textarea::selection{background:rgba(231,196,106,.22)}
.inputFoot{border-color:#393226}
.prompt{border-color:#4a402d;background:#12110d;color:#a79b81;transition:transform .25s,border-color .25s,color .25s,box-shadow .25s}
.prompt:hover{color:#f1d78e;border-color:#8a7037;box-shadow:0 0 20px rgba(231,196,106,.06);transform:translateY(-2px)}
.buildBtn{border-color:#9b7938;background:linear-gradient(135deg,#e1b84f,#f2d47e);color:#161208;box-shadow:0 10px 35px rgba(231,196,106,.16)}
.buildBtn:hover{box-shadow:0 15px 45px rgba(231,196,106,.25);filter:brightness(1.05)}
.notice.ok{border-color:#716039;color:#e5cf8d;background:rgba(83,67,32,.13)}
.stage{border-color:#3d372b;background:#0b0b09}.stage.active{color:var(--gold2);border-color:#7d6637;background:#17140d}.stage.active:after{background:linear-gradient(90deg,var(--gold),var(--gold2))}.stage.done{color:#a99668;border-color:#5b4c2d}
.result{border-color:#4b412e;background:#0c0c0a;box-shadow:0 25px 80px rgba(0,0,0,.4)}
.resultHead{border-color:#393226;background:#13120e}.resultIcon.pass{color:var(--gold2);border-color:#7c6837}.artifact{border-color:#3c3529;background:#080806}.artifactHead{border-color:#393226;color:#81755c}.artifactHead b{color:#b7aa8d}.codeWindow{background:#060606}.lineNums{border-color:#28251e;color:#504b40}.code{color:#e4dfd5}.visual{background:#060706}.empty{border-color:#443c2b;color:#776b54}.console .verify{background:#090907}.verify.pass{border-color:#66562f}.verify.pass strong{color:var(--gold2)}.log{border-color:#393226}.resultNote{border-color:#393226;color:#766d5c}
.infoCard{border-color:#3e372b;background:linear-gradient(145deg,#11100c,#0b0b09);transition:transform .5s,border-color .35s,box-shadow .35s}.infoCard:hover{transform:translateY(-5px);border-color:#6b5833;box-shadow:0 25px 60px rgba(0,0,0,.35)}.infoCard:after{border-color:rgba(231,196,106,.11)}
.footer{color:#625a4b}
.reveal{opacity:0;transform:translate3d(0,52px,0) scale(.985);filter:blur(4px);transition:opacity .9s ease,transform 1s cubic-bezier(.16,.75,.18,1),filter .9s ease}
.reveal.visible{opacity:1;transform:none;filter:none}
.visualRail .techShot:nth-child(1),.motifGrid .motif:nth-child(1){transition-delay:.02s}.visualRail .techShot:nth-child(2),.motifGrid .motif:nth-child(2){transition-delay:.10s}.visualRail .techShot:nth-child(3),.motifGrid .motif:nth-child(3){transition-delay:.18s}
@keyframes goldScan{0%{transform:translateY(-140%)}100%{transform:translateY(1100%)}}
@keyframes boardFloat{0%,100%{transform:rotateX(58deg) rotateZ(-28deg) translate3d(0,0,0)}50%{transform:rotateX(58deg) rotateZ(-28deg) translate3d(0,-16px,0)}}
@keyframes chipPulse{50%{box-shadow:0 0 0 18px rgba(231,196,106,.025),0 0 55px rgba(231,196,106,.14)}}
@media(max-width:980px){.hero:before{inset:10% 0}.techShot:hover,.motif:hover{transform:none}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation-duration:.001ms!important;animation-iteration-count:1!important;scroll-behavior:auto!important;transition-duration:.001ms!important}.reveal{opacity:1!important;transform:none!important;filter:none!important}}

/* ============================================================
   RESPONSIVE ENGINEERING WORKSTATION — VISUAL ONLY
   ============================================================ */
.codeWindow{overscroll-behavior:contain;-webkit-overflow-scrolling:touch}
.code{white-space:pre;overflow-x:auto;overflow-y:visible;overflow-wrap:normal;word-break:normal}
.lineNums{white-space:pre;min-width:44px}
.artifactHead{gap:10px}.artifactHead span,.artifactHead b{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.actions{overflow-x:auto;flex-wrap:nowrap;-webkit-overflow-scrolling:touch;padding-bottom:2px}.toolBtn,.buildBtn,.prompt{min-height:40px;touch-action:manipulation}
.prompt{min-height:38px}
.nav{padding:0 2px}.health{white-space:nowrap}
@media(max-width:980px){
  .shell{width:min(100% - 24px,760px)}
  .hero{min-height:auto;gap:8px;padding-top:12px}.heroCopy{padding:58px 0 20px}
  .heroVisual{height:360px;order:2}.section{padding-top:58px}
  .sectionHead{align-items:flex-start;flex-direction:column;gap:12px}.sectionHead p{max-width:680px}
  .workstation{margin-top:18px}.stationBody{padding:14px}.inputPanel textarea{min-height:180px}
  .artifactGrid{gap:10px}.visual{min-height:220px}
}
@media(max-width:700px){
  html{scroll-padding-top:68px}
  .shell{width:calc(100% - 16px);padding-bottom:48px}
  .nav{height:56px;margin-top:4px}.brand{gap:8px}.brandmark{width:30px;height:30px}.brand b{font-size:10px}.brand small{font-size:6px}.health{font-size:7px}.health i{width:5px;height:5px}
  .heroCopy{padding-top:42px}.hero h1{font-size:clamp(42px,13vw,58px);line-height:.9;margin-top:18px}.hero p{font-size:12px;line-height:1.7}
  .heroStats{width:100%;overflow-x:auto}.stat{flex:0 0 auto;padding:11px 12px 10px 0;margin-right:12px}.stat b{font-size:12px}
  .heroVisual{height:270px}.board3d{width:92%;transform:rotateX(56deg) rotateZ(-25deg)}
  .section{padding-top:44px}.sectionHead h2{font-size:clamp(30px,10vw,44px)}.sectionHead p{font-size:11px}
  .visualRail{gap:9px}.techShot,.techShot.tall{height:245px}
  .stationHead{padding:14px}.stationTitle h2{font-size:17px}.stationMeta{font-size:6px;padding:6px 7px}
  .stationControls{gap:9px}.buildHint{font-size:7px;line-height:1.5}.buildBtn{padding:13px 14px;width:100%;font-size:9px}
  .stageRail{grid-template-columns:repeat(2,minmax(0,1fr));gap:5px}.stage{min-height:54px;padding:9px 5px;font-size:6px}.stage small{font-size:5px}
  .resultHead{align-items:flex-start;flex-direction:column;padding:13px}.resultIdentity{width:100%}.actions{width:100%}.toolBtn{flex:0 0 auto;font-size:6px;padding:8px 9px}
  .artifactGrid{grid-template-columns:1fr;padding:7px;gap:8px}.artifact.full{grid-column:auto}.artifactHead{height:36px;padding:0 9px;font-size:6px}.artifactHead b{font-size:6px}
  .codeWindow{grid-template-columns:36px minmax(0,1fr);max-height:460px}.lineNums{min-width:36px;padding-right:7px;font-size:9px}.code{padding:12px;font-size:10px;line-height:1.7}
  .visual{padding:8px;min-height:190px}.visual svg{min-width:620px}.empty{min-height:170px;font-size:7px;padding:20px}
  .console{padding:8px}.verify{padding:11px;font-size:8px}.log{font-size:8px;max-height:230px}
  .infoGrid{gap:8px;margin-top:24px}.infoCard{min-height:125px;padding:13px}
}
@media(max-width:390px){
  .health{display:none}.hero h1{font-size:43px}.heroVisual{height:235px}.floatCard{display:none}
  .inputPanel textarea{min-height:165px;padding:14px;font-size:12px}.prompt{padding:8px;font-size:6px}.stage{min-height:50px}
  .artifactHead span{max-width:55%}.artifactHead b{max-width:45%}
}
@media(hover:none){
  .techShot:hover{transform:none}.techShot:hover img{transform:scale(1.03);filter:grayscale(.08) sepia(.05) saturate(.8) contrast(1.1) brightness(.58)}
  .buildBtn:hover{transform:none}.prompt:hover,.toolBtn:hover{border-color:inherit;color:inherit}
}
</style>
</head>
<body>
<div id="scrollProgress"></div>
<div class="shell">
<nav class="nav"><div class="brand"><div class="brandmark">RF</div><div><b>RTL FORGE</b><small>DIGITAL HARDWARE WORKSTATION</small></div></div><div class="navlinks"><a href="#visuals">HARDWARE</a><a href="#workstation">WORKSTATION</a><a href="#results">OUTPUT</a></div><div class="health"><i></i> LOCAL SIMULATION READY</div></nav>
<section id="workstation" class="workstation reveal"><div class="stationHead"><div class="stationTitle"><div class="kicker">01 / ENGINEERING WORKSTATION</div><h2>Specify the hardware. The pipeline handles the rest.</h2></div><div class="stationMeta">GENERAL-PURPOSE ECE / NO DEMO LIMIT</div></div><div class="stationBody"><div class="inputPanel"><div class="panelBar"><span><span class="traffic"><i></i><i></i><i></i></span> hardware_requirement.txt</span><span>NATURAL LANGUAGE</span></div><textarea id="req" maxlength="12000" placeholder="Describe any digital ECE circuit: interface, widths, clocks, resets, timing, state behavior, corner cases, and verification expectations."></textarea><div class="inputFoot"><span>SPECIFICATION → RTL → TESTBENCH → COMPILE → SIMULATE → VERIFY</span><span id="count">0 / 12000</span></div></div><div class="promptStrip"><button class="prompt" onclick="usePrompt('Design a UART transmitter and receiver with configurable baud divider, 8N1 framing, status signals and an independent self-checking testbench.')">UART</button><button class="prompt" onclick="usePrompt('Design a synchronous FIFO, 16 entries x 8-bit, with full, empty, almost-full and almost-empty flags and a self-checking testbench.')">SYNC FIFO</button><button class="prompt" onclick="usePrompt('Design an SPI master supporting 8-bit transfers, CPOL/CPHA modes, programmable clock divider, busy and done status.')">SPI</button><button class="prompt" onclick="usePrompt('Design an I2C master controller with start, stop, write, read, acknowledge handling and a conservative synthesizable interface.')">I2C</button><button class="prompt" onclick="usePrompt('Design an 8-bit ALU supporting ADD, SUB, AND, OR, XOR, shifts, zero flag and carry flag.')">ALU</button><button class="prompt" onclick="usePrompt('Design a PWM controller with programmable period and duty cycle, synchronous enable and reset behavior.')">PWM</button><button class="prompt" onclick="usePrompt('Design a CRC-8 streaming calculator with valid input, start control and an independent reference-model testbench.')">CRC-8</button></div><div class="stationControls"><div class="buildHint">⌘ / CTRL + ENTER &nbsp;•&nbsp; OBJECTIVE BUILD</div><button id="generate" class="buildBtn" onclick="build()">BUILD &amp; VERIFY →</button></div><div id="status" class="status"></div><div id="stageRail" class="stageRail hidden"><div id="s1" class="stage"><small>01</small>SPECIFY</div><div id="s2" class="stage"><small>02</small>ARCHITECT</div><div id="s3" class="stage"><small>03</small>GENERATE RTL</div><div id="s4" class="stage"><small>04</small>COMPILE</div><div id="s5" class="stage"><small>05</small>SIMULATE</div><div id="s6" class="stage"><small>06</small>VERIFY</div></div></div></section>

<section class="hero"><div class="heroCopy reveal"><div class="eyebrow"><b>02</b> DIGITAL HARDWARE / RTL WORKSTATION</div><h1>Build circuits.<br><span>Read the <em>signals.</em></span></h1><p>Turn an engineering requirement into synthesizable SystemVerilog, an independent self-checking testbench, a functional schematic and a real simulation waveform. One workstation for arbitrary digital ECE designs.</p><div class="heroStats"><div class="stat"><b>ANY ECE</b><span>NO CIRCUIT CATALOGUE</span></div><div class="stat"><b>SV / 2012</b><span>RTL TARGET</span></div><div class="stat"><b>Icarus</b><span>OBJECTIVE SIM</span></div></div><div class="scrollCue">SCROLL THROUGH THE DESIGN FIELD</div></div><div class="heroVisual" id="heroVisual"><div class="board3d"><span class="traceLine t1"></span><span class="traceLine t2"></span><span class="traceLine t3"></span><i class="node n1"></i><i class="node n2"></i><i class="node n3"></i></div><div class="floatCard fc1"><b>RTL / 01</b>syn · compile · inspect</div><div class="floatCard fc2"><b>TRACE / 04</b>VCD signal history</div></div></section>
<section id="visuals" class="section reveal"><div class="sectionHead"><div><div class="kicker">03 / HARDWARE REFERENCES</div><h2>Boards, silicon, instruments.</h2></div><p>Physical electronics imagery sits beside generated engineering diagrams. The visual language stays grounded in hardware instead of generic AI graphics.</p></div><div class="visualRail"><figure class="techShot tall"><img loading="lazy" src="https://images.unsplash.com/photo-1617839625591-e5a789593135?auto=format&fit=crop&w=1400&q=88" alt="Close-up printed circuit board with integrated circuits"><figcaption><b>01</b><span>GOLD PCB / TRACE FIELD</span></figcaption></figure><figure class="techShot"><img loading="lazy" src="https://images.unsplash.com/photo-1631378961385-21bee7eb41ad?auto=format&fit=crop&w=1200&q=88" alt="Electronic circuit board components and traces"><figcaption><b>02</b><span>FPGA / DEVELOPMENT BOARD</span></figcaption></figure><figure class="techShot tall"><img loading="lazy" src="https://cdn3.fh-joanneum.at/media/sites/11/2019/12/infrastructure-12.jpg" alt="Electronics engineering laboratory equipment"><figcaption><b>03</b><span>OSCILLOSCOPE / SIGNAL LAB</span></figcaption></figure></div></section>
<section class="section reveal"><div class="sectionHead"><div><div class="kicker">04 / DIGITAL DESIGN LANGUAGE</div><h2>Logic. States. Timing.</h2></div><p>Interface-native engineering motifs: combinational paths, finite-state control and signal timing. These are visual context, not fake simulation output.</p></div><div class="motifGrid"><article class="motif"><div class="motifTop"><span>COMBINATIONAL</span><b>DATA PATH</b></div><svg viewBox="0 0 600 210" fill="none"><g stroke="currentColor" stroke-width="3"><path d="M20 30H170L330 105H570"/><path d="M20 80H170L330 105"/><path d="M20 130H170L330 105"/><path d="M20 180H170L330 105"/><path d="M330 105l55-50v100z"/></g><g fill="currentColor"><circle cx="20" cy="30" r="5"/><circle cx="20" cy="80" r="5"/><circle cx="20" cy="130" r="5"/><circle cx="20" cy="180" r="5"/><circle cx="570" cy="105" r="5"/></g></svg></article><article class="motif"><div class="motifTop"><span>SEQUENTIAL</span><b>FSM CONTROL</b></div><svg viewBox="0 0 600 210" fill="none"><g stroke="currentColor" stroke-width="2"><circle cx="105" cy="105" r="38"/><circle cx="300" cy="55" r="38"/><circle cx="300" cy="155" r="38"/><circle cx="495" cy="105" r="38"/><path d="M143 92L262 65M143 118L262 145M338 55h119M338 155h119M457 92l-80-25M457 118l-80 25"/></g><g fill="currentColor" font-family="monospace" font-size="14" text-anchor="middle"><text x="105" y="110">IDLE</text><text x="300" y="60">LOAD</text><text x="300" y="160">RUN</text><text x="495" y="110">DONE</text></g></svg></article><article class="motif"><div class="motifTop"><span>VERIFICATION</span><b>WAVEFORM</b></div><svg viewBox="0 0 600 210" fill="none"><g stroke="#394744" stroke-width="1"><path d="M10 35H590M10 85H590M10 135H590M10 185H590"/></g><path d="M10 58H80V20H150V58H220V20H290V58H360V20H430V58H500V20H590" stroke="#e7c46a" stroke-width="4"/><path d="M10 150H55V110H120V150H180V110H250V150H320V110H390V150H460V110H530V150H590" stroke="#78d7cf" stroke-width="4"/></svg></article></div></section>

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
async function build(){const text=req.value.trim();if(!text){setStatus('err','Enter a hardware requirement before building.');req.focus();return}const btn=document.getElementById('generate');btn.disabled=true;btn.innerHTML='<span class="spinner"></span> BUILDING';setStatus('wait','<span class="spinner"></span> Running specification → RTL → compile → simulation → verification.');startStages();document.getElementById('results').classList.add('hidden');try{const r=await fetch('/api/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request:text})});const d=await r.json().catch(()=>({error:'The generation engine returned an incomplete response.'}));if(!r.ok){setStatus('wait','⟳ Generation service is recovering. Your hardware request was not rejected. Retrying once…');await new Promise(x=>setTimeout(x,1800));const retry=await fetch('/api/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request:text})});const rd=await retry.json().catch(()=>({}));if(!retry.ok)throw new Error(rd.message||rd.error||'The generation engine is temporarily busy.');Object.assign(d,rd)}generated=d.rtl||'';generatedTB=d.testbench||'';currentJob=d.job_id||'';document.getElementById('results').classList.remove('hidden');document.getElementById('resultHeading').textContent=(d.verification&&d.verification.passed?'Verified — ':'Generated — ')+(d.design_name||'Digital design');const icon=document.getElementById('resultIcon');icon.className='resultIcon '+(d.verification&&d.verification.passed?'pass':'fail');icon.textContent=d.verification&&d.verification.passed?'✓':'!';renderCode('rtl','rtlLines',generated);renderCode('tbcode','tbLines',generatedTB);if(d.diagram_svg)document.getElementById('diagram').innerHTML=d.diagram_svg;else empty('diagram','NO FUNCTIONAL SCHEMATIC RETURNED');if(d.waveform_svg)document.getElementById('waveform').innerHTML=d.waveform_svg;else empty('waveform','NO WAVEFORM — SIMULATION DID NOT COMPLETE');const v=d.verification||{};document.getElementById('log').textContent=v.log||'';if(v.passed){document.getElementById('verify').className='verify pass';document.getElementById('verify').innerHTML='<strong>✓ VERIFIED</strong><br>Icarus compilation succeeded, VVP simulation completed and the independent testbench reported TEST_RESULT: PASS.';setStatus('ok','✓ Hardware generated and objectively verified.');finishStages(true)}else{document.getElementById('verify').className='verify fail';document.getElementById('verify').innerHTML='<strong>⚠ NOT VERIFIED</strong><br>Artifacts are available for inspection, but the objective build did not pass. Stage: '+esc(v.stage||'unknown')+'.';setStatus('err','⚠ Generated artifacts returned, but verification did not pass.');finishStages(false)}document.getElementById('results').scrollIntoView({behavior:'smooth',block:'start'})}catch(e){finishStages(false);setStatus('wait','⟳ Engineering generation is temporarily busy. Your request is still a valid hardware specification; retry the build when the generation engine is ready.');document.getElementById('results').classList.add('hidden')}finally{btn.disabled=false;btn.textContent='BUILD & VERIFY →'}}
function copyCode(which){const t=which==='tb'?generatedTB:generated;if(!t)return;navigator.clipboard?.writeText(t);setStatus('ok','Copied '+(which==='tb'?'testbench':'RTL')+' to clipboard.')}function downloadArtifact(k){if(currentJob)location.href='/api/download/'+encodeURIComponent(currentJob)+'/'+k}
window.addEventListener('scroll',()=>{const h=document.documentElement.scrollHeight-innerHeight;const p=h>0?(scrollY/h)*100:0;document.getElementById('scrollProgress').style.width=p+'%';document.documentElement.style.setProperty('--scroll-p',p.toFixed(2));document.querySelectorAll('.techShot').forEach((el,i)=>{const r=el.getBoundingClientRect();const center=(innerHeight*.52-r.top)/(innerHeight+r.height);el.style.setProperty('--img-shift',(center*18).toFixed(2)+'px')})},{passive:true});

document.querySelectorAll('.techShot').forEach(card=>{card.addEventListener('pointermove',e=>{if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;const r=card.getBoundingClientRect();const x=(e.clientX-r.left)/r.width-.5;const y=(e.clientY-r.top)/r.height-.5;card.style.transform='perspective(900px) rotateX('+(-y*3.5).toFixed(2)+'deg) rotateY('+(x*4.5).toFixed(2)+'deg) translateY(-4px)'});card.addEventListener('pointerleave',()=>card.style.transform='')});
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

def format_hdl(code):
    """Format Verilog/SystemVerilog for the source viewer without changing logic."""
    if not isinstance(code, str) or not code.strip():
        return code or ''
    s=code.replace('\r\n','\n').replace('\r','\n').strip()
    s=re.sub(r'^```(?:systemverilog|verilog|sv)?\s*', '', s, flags=re.I)
    s=re.sub(r'\s*```$', '', s).strip()

    # Split ANSI module ports so a compact model response never becomes a
    # single unreadable paragraph in the code viewer.
    def module_ports(m):
        head=m.group(1)
        body=m.group(2).strip()
        if not body:
            return 'module '+head+'();'
        parts=[];buf=[];depth=0;in_str=False;esc=False
        for ch in body:
            if in_str:
                buf.append(ch)
                if esc: esc=False
                elif ch=='\\': esc=True
                elif ch=='"': in_str=False
                continue
            if ch=='"': in_str=True;buf.append(ch);continue
            if ch in '([': depth+=1
            elif ch in ')]': depth=max(0,depth-1)
            if ch==',' and depth==0:
                parts.append(''.join(buf).strip());buf=[]
            else:
                buf.append(ch)
        if buf: parts.append(''.join(buf).strip())
        return 'module '+head+'(\n'+'\n'.join(
            '    '+x+(',' if i<len(parts)-1 else '') for i,x in enumerate(parts)
        )+'\n);'
    s=re.sub(
        r'\bmodule\s+([A-Za-z_][\w$]*(?:\s*#\s*\(.*?\))?)\s*\((.*?)\)\s*;',
        module_ports,s,flags=re.I|re.S
    )

    out=[];buf=[];indent=0;i=0;n=len(s)
    in_str=False;in_line=False;in_block=False;escaped=False
    def emit():
        nonlocal buf
        t=''.join(buf).strip()
        if t: out.append('    '*max(0,indent)+t)
        buf=[]

    while i<n:
        ch=s[i];nxt=s[i+1] if i+1<n else ''
        if in_line:
            buf.append(ch)
            if ch=='\n': in_line=False;emit()
            i+=1;continue
        if in_block:
            buf.append(ch)
            if ch=='*' and nxt=='/': buf.append(nxt);i+=2;in_block=False
            else: i+=1
            continue
        if in_str:
            buf.append(ch)
            if escaped: escaped=False
            elif ch=='\\': escaped=True
            elif ch=='"': in_str=False
            i+=1;continue
        if ch=='/' and nxt=='/':
            buf.extend([ch,nxt]);i+=2;in_line=True;continue
        if ch=='/' and nxt=='*':
            buf.extend([ch,nxt]);i+=2;in_block=True;continue
        if ch=='"': in_str=True;buf.append(ch);i+=1;continue

        if ch.isalpha() or ch=='_':
            j=i+1
            while j<n and (s[j].isalnum() or s[j] in '_$'): j+=1
            word=s[i:j];low=word.lower()
            if low=='begin':
                emit();out.append('    '*indent+word);indent+=1;i=j;continue
            if low in ('end','endcase','endfunction','endtask','endgenerate'):
                emit();indent=max(0,indent-1);out.append('    '*indent+word);i=j;continue
            if low=='endmodule':
                emit();out.append('endmodule');i=j;continue
            if low=='else':
                emit();out.append('    '*max(0,indent)+word);i=j;continue
            if low in ('case','casex','casez'):
                emit();out.append('    '*indent+word);i=j;continue
            if low=='default':
                emit();out.append('    '*indent+word);i=j;continue
            buf.append(word);i=j;continue

        if ch==';':
            buf.append(';');emit();i+=1;continue
        if ch=='\n':
            if ''.join(buf).strip(): emit()
            i+=1;continue
        if ch=='\t': buf.append('    ');i+=1;continue
        buf.append(ch);i+=1
    emit()

    text='\n'.join(out)
    # Put an else/else-if after the preceding end block on its own line.
    text=re.sub(r'(?m)^(\s*)end\s*\n\s*else\s+if\b', r'\1end\n\1else if', text)
    text=re.sub(r'(?m)^(\s*)end\s*\n\s*else\b', r'\1end\n\1else', text)
    def indent_module_header(m):
        body='\n'.join('    '+line.strip() for line in m.group(1).splitlines() if line.strip())
        return '(\n'+body+'\n);'
    text=re.sub(r'\(\n((?:(?!\n\);).)*?)\n\);', indent_module_header, text, flags=re.S)
    return text.strip()

def preflight_hdl(rtl,tb):
    """Run narrow, high-confidence checks before spending simulation time.

    The product remains general-purpose. These rules only activate for patterns
    that are strongly associated with known objective-simulation failures, with
    special structural checks for the explicitly requested dual-clock FIFO.
    """
    issues=[]
    low=rtl.lower()

    # Generic combinational self-loop checks.
    patterns=[
        (r'\bwr_ptr_next\b[^;]*\bfull\b', r'\bassign\s+full\s*=', 'async FIFO full is combinationally self-referential'),
        (r'\brd_ptr_next\b[^;]*\bempty\b', r'\bassign\s+empty\s*=', 'async FIFO empty is combinationally self-referential'),
    ]
    for lhs_pat,status_pat,msg in patterns:
        if re.search(lhs_pat,rtl,re.I|re.S) and re.search(status_pat,rtl,re.I|re.S):
            issues.append(msg)

    # A request mentioning an asynchronous/dual-clock FIFO gets a stronger
    # architecture preflight. This prevents an obviously unsafe FIFO from ever
    # reaching VVP and gives the single repair call a precise diagnosis.
    if re.search(r'\b(async(?:hronous)?|dual[- ]clock)\s+fifo\b', low, re.I):
        if re.search(r'\bassign\s+full\b', rtl, re.I) or re.search(r'\bassign\s+empty\b', rtl, re.I):
            issues.append('async FIFO full/empty must be registered in their destination clock domains, not continuously assigned')
        if not re.search(r'always_ff\s*@\([^)]*wr_clk[^)]*\)[\s\S]{0,500}full\s*<=', rtl, re.I):
            issues.append('async FIFO full flag is not visibly registered on wr_clk')
        if not re.search(r'always_ff\s*@\([^)]*rd_clk[^)]*\)[\s\S]{0,500}empty\s*<=', rtl, re.I):
            issues.append('async FIFO empty flag is not visibly registered on rd_clk')
        # Accept the canonical names or common sync1/sync2 naming variants.
        gray_syncs=len(re.findall(r'\b(?:gray|ptr)[A-Za-z0-9_]*(?:sync[_]?1|sync[_]?2|[wr]1|[wr]2)\b', rtl, re.I))
        has_canonical=all(re.search(p,rtl,re.I) for p in (
            r'rd_ptr_gray_(?:w1|sync1)', r'rd_ptr_gray_(?:w2|sync2)',
            r'wr_ptr_gray_(?:r1|sync1)', r'wr_ptr_gray_(?:r2|sync2)'))
        if not has_canonical and gray_syncs < 4:
            issues.append('async FIFO must use two-stage Gray-pointer synchronizers into both clock domains')
        if not re.search(r'\bgray\b', rtl, re.I) or not re.search(r'>>\s*1|\^', rtl):
            issues.append('async FIFO Gray-coded pointer logic is missing or incomplete')

    # Generic DUT/TB contract checks.
    if rtl and tb:
        m = re.search(r'\bmodule\s+([A-Za-z_][\w$]*)\s*\(', rtl, re.I)
        if m:
            dut_name = m.group(1)
            if not re.search(r'\bmodule\s+tb\b', tb, re.I):
                issues.append('testbench top module must be named tb')
            if not re.search(r'\b' + re.escape(dut_name) + r'\b', tb):
                issues.append(f'testbench does not instantiate DUT {dut_name}')
        if re.search(r'\balways_ff\s*@\([^)]*posedge\b', rtl, re.I) and not re.search(r'(forever\s*#|always\s*#|always\s*@\([^)]*posedge\b)', tb, re.I):
            issues.append('clocked DUT has no obvious clock stimulus in testbench')

    # Protocol-specific correctness checks. These are intentionally narrow and
    # activate only when the user's specification clearly requires the protocol.
    # They prevent a visually impressive but semantically weak PASS.
    req_context = globals().get('_PREFLIGHT_REQUEST', '') or ''
    qreq = req_context.lower()
    if tb and re.search(r'\b(packet|packetized)\b', qreq) and re.search(r'\b(ready|backpressure|valid)\b', qreq):
        # Ready/valid producer behavior: VALID must not be gated by READY.
        if re.search(r'\brd_valid\s*(?:<=|=)\s*\([^;\n]*\brd_ready|\brd_valid\s*(?:<=|=)\s*\brd_ready', rtl, re.I):
            issues.append('ready/valid violation: rd_valid must not be generated by rd_ready; data and valid must remain available while ready is low')
        if not re.search(r'\brd_ready\s*=\s*0|\brd_ready\s*<=\s*0', tb, re.I):
            issues.append('packet streaming testbench must explicitly exercise read backpressure with rd_ready=0')
        if not re.search(r'\brd_valid\b[\s\S]{0,500}\brd_ready\b', tb, re.I):
            issues.append('packet streaming testbench must check valid/ready acceptance behavior')
        if not re.search(r'\b(?:expected|ref|reference)[A-Za-z0-9_]*\b', tb, re.I):
            issues.append('packet streaming testbench needs an independent reference model/scoreboard')
        # Strong accounting: a packet test must compare sent/received totals, not
        # merely require that at least one packet arrived.
        if not re.search(r'(?:total_.*sent|sent.*total|packets_.*sent|sent_.*packets)', tb, re.I) or not re.search(r'(?:total_.*recv|received.*total|packets_.*recv|recv_.*packets)', tb, re.I):
            issues.append('packet testbench must account for total transmitted and received transactions')
        if re.search(r'errors\s*==\s*0\s*&&[\s\S]{0,100}total_.*>\s*0', tb, re.I):
            issues.append('packet testbench PASS condition is too weak: it must prove all expected transactions were received, not just that some data arrived')
    # Generic ready/valid RTL guard for explicit streaming interfaces.
    if rtl and re.search(r'\b(valid|ready)\b', qreq) and re.search(r'\bvalid\b', rtl, re.I) and re.search(r'\bready\b', rtl, re.I):
        if re.search(r'\b[a-zA-Z_][\w$]*valid[a-zA-Z_]*\s*(?:<=|=)\s*\([^;\n]*\b[a-zA-Z_][\w$]*ready[a-zA-Z_]*', rtl, re.I):
            issues.append('streaming valid signal appears combinationally gated by ready; verify the protocol contract and hold valid/data independently during backpressure')

    # Every generated verification bench must be finite and self-reporting.
    if tb:
        if 'TEST_RESULT: PASS' not in tb or 'TEST_RESULT: FAIL' not in tb:
            issues.append('testbench must contain both TEST_RESULT: PASS and TEST_RESULT: FAIL outcomes')
        if '$finish' not in tb:
            issues.append('testbench must terminate with $finish')
    return '; '.join(dict.fromkeys(issues)) or None

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

def response_looks_like_refusal(data):
    """Detect model text that refuses instead of producing engineering artifacts."""
    if not isinstance(data, dict):
        return True
    rtl = str(data.get('rtl', '') or '').strip().lower()
    tb = str(data.get('testbench', '') or '').strip().lower()
    name = str(data.get('design_name', '') or '').strip().lower()
    refusal = re.compile(r"(?:i\s+(?:can(?:not|'t)|am\s+unable)|cannot|can't|unable to|not able to|i\s+don't\s+know|unsupported|not supported|too complex|outside my capabilities|i\s+cannot generate|i\s+can't generate)", re.I)
    if refusal.search(rtl) or refusal.search(tb) or refusal.search(name):
        return True
    return not rtl or not tb or not str(data.get('diagram_dot', '') or '').strip()


def gemini_call(prompt, repair=False):
    """Call configured models with bounded fallback and refusal/JSON recovery."""
    if client is None:
        raise RuntimeError('The hardware generation engine is not connected to Gemini yet.')
    errors=[]
    recovery_prompt = """
IMPORTANT ENGINEERING CONTINUATION RULE:
Do not answer with a refusal, capability disclaimer, unsupported message, or
'I cannot' statement. The project is intentionally a general-purpose digital
ECE RTL engineer. If the specification is unusually difficult, novel, incomplete,
or ambiguous, make conservative engineering assumptions and continue with the
best complete synthesizable SystemVerilog design and an independent
self-checking testbench. Put important assumptions in comments inside the
returned HDL/TB. Preserve every explicit requirement. Never replace the task
with a simpler demo circuit merely because the requested design is difficult.
"""
    for model in model_list():
        recovery_needed=False
        for attempt in range(GENERATION_RECOVERY_ATTEMPTS):
            try:
                use_prompt = prompt + ("\n" + recovery_prompt if recovery_needed else "")
                response=client.models.generate_content(
                    model=model,
                    contents=use_prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=24000,
                        response_mime_type='application/json',
                        response_schema=REPAIR_SCHEMA if repair else DESIGN_SCHEMA,
                    ),
                )
                text=(getattr(response,'text',None) or '').strip()
                if not text:
                    errors.append(f'{model}:empty')
                    recovery_needed=True
                    continue
                try:
                    parsed=json_from(text)
                except Exception:
                    errors.append(f'{model}:invalid_json')
                    recovery_needed=True
                    continue
                if response_looks_like_refusal(parsed):
                    errors.append(f'{model}:refusal')
                    recovery_needed=True
                    continue
                return json.dumps(parsed, ensure_ascii=False)
            except Exception as exc:
                code=api_code(exc)
                errors.append(f'{model}:{code or "error"}')
                if code in (401,403):
                    raise RuntimeError('The hardware generation engine needs a valid Gemini API configuration.')
                # Service errors move immediately to the next configured model.
                # Do not waste quota repeating a 429/503/504 against the same model.
                break
    raise RuntimeError('The hardware generation engine is temporarily busy. Your hardware request remains valid and was not rejected. No reliable RTL artifact was returned by the available generation models on this attempt. The client can retry automatically. Attempt summary: '+', '.join(errors))

# ============================================================
# GENERAL ECE PROMPTS
# ============================================================
def challenge_profile(req_text):
    """Select verification guidance from the user's specification.

    This is guidance, not a circuit whitelist. Unknown/novel hardware falls
    through to the GENERAL profile and is still fully accepted.
    """
    q = (req_text or '').lower()
    profiles = []
    if re.search(r'\b(async|asynchronous|dual[- ]clock|cdc|clock[- ]domain)\b', q):
        profiles.append("CDC/ASYNC: identify every clock domain; cross only safe synchronized state/control; use two-flop synchronizers for single-bit controls and Gray-pointer synchronization for async FIFOs; never assume clocks have a fixed phase or frequency relationship.")
    if re.search(r'\b(fifo|queue|buffer|ram|memory|register file|dual[- ]port)\b', q):
        profiles.append("MEMORY/QUEUE: define exact depth, width, addressing, read/write timing, simultaneous access semantics, rollover, full/empty behavior, and boundary protection. Build an independent reference model in the TB.")
    if re.search(r'\b(fsm|state machine|sequence detector|controller|traffic|elevator|vending)\b', q):
        profiles.append("FSM/CONTROL: derive states and transitions from the specification; verify reset state, every legal transition, illegal/ignored inputs, output timing, and overlapping/back-to-back transactions where relevant.")
    if re.search(r'\b(uart|spi|i2c|i2s|apb|axi|ahb|wishbone|can|usb|protocol|serial)\b', q):
        profiles.append("PROTOCOL: treat the external pins/signals as the contract. Verify cycle/bit ordering, edge polarity, setup/hold relationships, framing, handshake phases, back-to-back transfers, idle behavior and reset. The TB must observe the external interface, not only internal signals.")
    if re.search(r'\b(pipeline|latency|throughput|valid_in|valid_out|ready|backpressure)\b', q):
        profiles.append("TIMING/PIPELINE: explicitly model cycle latency and transaction alignment. Verify reset bubbles, back-to-back valid traffic, stalls or backpressure, and that data/control remain aligned. VALID must describe data availability independently of READY; a producer must hold VALID/data stable while READY is low unless the protocol explicitly specifies a different contract.")
    if re.search(r'\b(packet|packetized|packet boundary|wr_last|rd_last|packet_available)\b', q):
        profiles.append("PACKET/STREAMING: distinguish word acceptance from packet completion. Track every accepted input/output word with an independent scoreboard, verify packet boundaries/last markers, missing or incomplete packets, backpressure stability, packet counts and ordering. Never declare PASS merely because some output was received; all expected transactions must be accounted for.")
    if re.search(r'\b(signed|saturat|overflow|underflow|multiply|mac|alu|arithmetic|fixed[- ]point)\b', q):
        profiles.append("ARITHMETIC: preserve signedness and operand widths; reason about intermediate width, truncation, carry/borrow, overflow/saturation and negative/boundary values. Use an independently computed reference expression in the TB.")
    if re.search(r'\b(pwm|baud|frequency|period|duty|timer|watchdog|timeout|counter)\b', q):
        profiles.append("TIMING/WAVEFORM: verify behavior from observable clock-cycle or pin timing, including period, duty/baud/count boundaries, enable pauses, rollover and reset. The generated VCD must contain useful external signals for waveform inspection.")
    if re.search(r'\b(dma|cpu|processor|datapath|instruction|cache|bus|soc|core)\b', q):
        profiles.append("INTEGRATION: separate datapath, control and storage responsibilities; verify instruction/transaction sequencing, handshakes, address updates, flags/status and reset. Use a small deterministic program or transaction sequence plus an independent software/reference model where possible.")
    if re.search(r'\b(parameter|parameterized|configurable|generic)\b', q):
        profiles.append("PARAMETERIZATION: test at least the requested configuration and boundary parameter values when practical. Avoid hard-coded widths/depths that silently contradict the parameter contract.")
    if not profiles:
        profiles.append("GENERAL: decompose the specification into interface, state/datapath, timing, corner cases and observable outputs. Do not assume the design belongs to a known template. For novel hardware, derive the architecture directly from the user's stated behavior.")
    return "\\n".join(f"- {x}" for x in profiles)


def prompt_for_design(req_text):
    return f'''
You are a senior digital ECE RTL engineer and verification engineer. The user can
request ANY synthesizable digital ECE hardware circuit or subsystem, including a
novel design that does not match any known template. Never limit the task to
examples from a website. This is a general-purpose engineering task, not a
circuit-category classifier. Do not refuse difficult, novel, unusually long,
or unfamiliar digital ECE requirements. Never say 'I can't', 'cannot answer',
'unsupported', 'too complex', or similar capability-disclaimer text. If details
are ambiguous, choose conservative engineering assumptions and continue. If the
request describes a non-digital physical concept, create the closest useful
synthesizable digital behavioral/controller abstraction and clearly mark that
assumption in HDL comments rather than refusing the request.

Treat the user's specification as a formal engineering contract. Before writing
code, internally extract: interfaces, clocks/resets, state, datapath, timing/latency,
protocol rules, parameter constraints, corner cases and required verification.
Then implement and verify every requested item. Never silently simplify, remove,
rename or reinterpret a requirement merely to make simulation pass.

Return exactly one JSON object containing:
1. design_name
2. rtl
3. testbench
4. diagram_dot

RTL:
- Complete synthesizable SystemVerilog DUT.
- Use conservative constructs compatible with iverilog -g2012.
- Preserve exact requested widths, reset polarity, clocking, latency and interfaces.
- FORMAT THE RTL AS HUMAN-READABLE SOURCE: one declaration/statement per line,
  indentation for begin/end blocks, blank lines between major sections, and no
  minified one-line output. The returned rtl string must be directly readable.
- For asynchronous/dual-clock FIFOs specifically, follow this architecture:
  * use a memory array indexed by the LOCAL binary write/read pointer;
  * maintain binary and Gray versions of each local pointer with the extra wrap bit;
  * cross ONLY Gray pointers between clock domains through TWO flip-flop synchronizers;
  * compute a write-side next binary/Gray pointer from wr_en AND the CURRENT
    registered full flag, then REGISTER full on wr_clk using the synchronized read
    Gray pointer and the standard inverted-MSB full comparison;
  * compute a read-side next binary/Gray pointer from rd_en AND the CURRENT
    registered empty flag, then REGISTER empty on rd_clk using the synchronized
    write Gray pointer;
  * full and empty MUST NOT be continuous assigns. They must be sequentially
    registered flags with reset values full=0 and empty=1;
  * NEVER make wr_ptr_next depend on a combinational full that is itself computed
    from wr_ptr_next, and never make rd_ptr_next depend on a combinational empty
    computed from rd_ptr_next; that creates a zero-delay combinational loop and
    can make VVP hang forever;
  * keep the two reset domains independent and synchronize only the pointer state
    needed by the opposite domain. Use explicit, readable names such as
    rd_ptr_gray_w1/w2 and wr_ptr_gray_r1/r2 for the two-stage synchronizers.
- No host-control, shell, network, DPI or arbitrary file I/O in the DUT.
- Do not put testbench logic inside the DUT.

TESTBENCH:
- Top module MUST be named tb.
- Instantiate the DUT exactly.
- Independently calculate expected behavior; do not simply copy DUT equations.
- Test normal cases plus important boundaries/corner cases.
- For sequential logic test reset, clocking, state transitions and latency.
- Drive clock-domain inputs away from active clock edges (for example on negedge)
  and sample/check outputs after active edges to avoid testbench race conditions.
- For CDC designs, use genuinely unrelated clocks and allow enough destination
  clock edges for synchronizers/flags to settle before asserting expectations.
  Do NOT use an unbounded fork/join scoreboard that can wait forever on a flag.
  Keep every stimulus loop finite; it is acceptable to use forever loops ONLY for
  clock generators. The main test sequence must always reach $finish.
- For asynchronous FIFO verification, keep an independent reference queue. Add a
  value to the reference model only when a write is actually accepted (!full), and
  remove/compare a value only when a read is actually accepted (!empty). Drive
  wr_en/rd_en on non-active clock edges, sample outputs after the active edge, and
  explicitly test reset, 16-entry fill, blocked 17th write, drain, blocked read,
  pointer rollover, simultaneous unrelated-clock traffic, and ordering. Do not
  assume the opposite-domain flag changes immediately; wait for synchronizer
  latency where required.
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

ADAPTIVE ENGINEERING GUIDANCE FOR THIS REQUEST:
{challenge_profile(req_text)}

QUALITY GATE:
- The testbench must be capable of failing if the DUT violates a meaningful
- For ready/valid interfaces, VALID is producer-controlled and must not be made
  dependent on READY unless the user explicitly defines a non-standard protocol.
  When READY is low, hold VALID and the associated payload/sideband stable until
  acceptance. The TB must deliberately hold READY low while VALID is asserted and
  check stability across multiple cycles.
- For packet/streaming designs, maintain independent expected word and packet
  counts. PASS requires expected_words == accepted_output_words, expected_packets ==
  received_packets, zero data/sideband mismatches, zero unexpected transfers, and
  empty reference state at the end. Never use a weak condition such as
  errors==0 && received>0.
- For designs with incomplete transactions or packet commit semantics, explicitly
  test reset/abort before completion and prove that incomplete data is not exposed.
- For FIFO/memory designs, deliberately force pointer/address rollover and test
  boundary occupancy, simultaneous operations, blocked operations, and recovery.
  requirement; do not create a testbench that merely follows the DUT's equations.
- Cover every explicitly requested feature and important boundary cases.
- Prefer deterministic finite tests. Any forever loop must be a clock generator only.
- Ensure the testbench reaches $finish on PASS and FAIL paths.
- Ensure the waveform contains external interface signals and useful debug signals.
- Never claim PASS without an actual Icarus/VVP TEST_RESULT: PASS marker.

Before returning, mentally inspect syntax balance, module interfaces, widths,
clock/reset behavior, and independent scoreboard/reference behavior.

FINAL CONTINUATION RULE:
A hard problem is still a valid engineering request. Do not downgrade it to a
simpler example, do not refuse it, and do not return an explanation instead of
artifacts. Work through the specification, make explicit assumptions where
needed, generate the complete RTL/TB/diagram, and let objective simulation decide
whether the implementation passes. If the first implementation fails, the repair
stage must change the implementation or verification strategy rather than telling
the user that the problem is too difficult.

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
reference models and race conditions. If the design is an asynchronous/dual-clock FIFO, explicitly verify that
full/empty are registered in separate clock domains, Gray pointers cross through
exactly two synchronizer stages per destination domain, and there is NO
combinational self-loop through full/empty and next-pointer logic. Never repair a
FIFO timeout by removing checks, shortening the test, or changing the requested
FIFO depth. If simulation timed out, first diagnose the actual cause: zero-delay combinational
loop, non-terminating process, unbounded wait/fork/join, CDC scoreboard deadlock,
clock/reset deadlock, excessive test duration, or an RTL feedback/handshake bug.
Fix the architecture or finite stimulus instead of simply increasing the timeout
or deleting verification checks.

Return human-readable formatted HDL: declarations and statements on separate
lines, consistent indentation, and readable begin/end blocks. Never return a
minified single-line source file.

ADAPTIVE ENGINEERING GUIDANCE FOR THIS REQUEST:
{challenge_profile(req_text)}

REPAIR QUALITY GATE:
- Fix the actual compiler/simulation failure without weakening requested behavior
- Never repair a verification failure by deleting checks, reducing traffic, or
  changing PASS to mean 'some output arrived'. Preserve or strengthen the independent
  scoreboard and transaction accounting.
- For ready/valid interfaces, do not gate VALID with READY. During READY=0, the
  producer must keep VALID and payload/sideband stable until a handshake occurs.
  Add a deliberate multi-cycle backpressure test if the existing TB lacks one.
- For packetized designs, verify complete packet counts, word counts, ordering,
  last markers, incomplete-packet reset/abort behavior, and no dropped/duplicated
  transactions.
  or deleting meaningful checks.
- Re-check all user requirements after repair, not only the line mentioned by log.
- If architecture is wrong, replace the affected architecture rather than patching
  symptoms.
- Keep the testbench independently derived from the specification and finite.
- For protocols, CDC, memories, pipelines, arithmetic and CPU/bus designs,
  preserve the relevant timing and boundary checks.

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
    except subprocess.TimeoutExpired:
        return {'passed':False,'stage':'simulation','log':('Simulation timed out. This often indicates a zero-delay combinational loop,\n'
            'a non-terminating testbench process, or an RTL/testbench deadlock.\n'
            'For CDC/FIFO designs, inspect full/empty and next-pointer dependencies first.')}
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
        rtl=format_hdl(clean_code(data.get('rtl','')));tb=format_hdl(clean_code(data.get('testbench','')));dot=clean_code(data.get('diagram_dot',''))
        name=str(data.get('design_name','General ECE RTL design')).strip() or 'General ECE RTL design'
        tb=ensure_wave_dump(tb)
        repair=False
        global _PREFLIGHT_REQUEST
        _PREFLIGHT_REQUEST = user_request
        issue=unsafe_reason(rtl) or unsafe_reason(tb) or preflight_hdl(rtl,tb)
        if issue:
            if MAX_REPAIR_ATTEMPTS<=0: raise RuntimeError(f'Generated HDL contains blocked construct ({issue}).')
            repair=True;budget('Build deadline reached before safety repair.')
            fixed=json_from(gemini_call(repair_prompt(user_request,rtl,tb,'SAFETY VALIDATION: '+issue,dot),repair=True))
            rtl=format_hdl(clean_code(fixed.get('rtl','')));tb=format_hdl(ensure_wave_dump(clean_code(fixed.get('testbench',''))));dot=clean_code(fixed.get('diagram_dot',dot))
            issue=unsafe_reason(rtl) or unsafe_reason(tb) or preflight_hdl(rtl,tb)
            if issue: raise RuntimeError(f'Repaired HDL still contains blocked construct ({issue}).')
        if not rtl or not tb: raise RuntimeError('Gemini did not return complete RTL and testbench artifacts.')
        budget('Build deadline reached before simulation.')
        sim=simulate(rtl,tb,job,deadline)
        # Bounded objective repair(s). Default is one repair; hard projects can
        # opt into a second bounded repair with MAX_REPAIR_ATTEMPTS=2.
        repair_rounds = 0
        while (not sim['passed'] and repair_rounds < MAX_REPAIR_ATTEMPTS and
               time.monotonic() < deadline):
            repair=True
            repair_rounds += 1
            budget('Build deadline reached before repair.')
            failure_context = (
                f"REPAIR ROUND {repair_rounds}\n"
                f"ADAPTIVE PROFILE:\n{challenge_profile(user_request)}\n\n"
                f"OBJECTIVE FAILURE:\n{sim.get('log','')}"
            )
            fixed=json_from(gemini_call(
                repair_prompt(user_request,rtl,tb,failure_context,dot),repair=True
            ))
            rtl2=format_hdl(clean_code(fixed.get('rtl','')))
            tb2=format_hdl(ensure_wave_dump(clean_code(fixed.get('testbench',''))))
            dot2=clean_code(fixed.get('diagram_dot',dot))
            issue=unsafe_reason(rtl2) or unsafe_reason(tb2) or preflight_hdl(rtl2,tb2)
            if issue: raise RuntimeError(f'Repair generated blocked construct ({issue}).')
            if not rtl2 or not tb2: raise RuntimeError('Repair response did not contain complete RTL and testbench.')
            rtl,tb,dot=rtl2,tb2,dot2
            budget('Build deadline reached before repaired simulation.')
            sim=simulate(rtl,tb,job,deadline)
        rtl=format_hdl(rtl)
        tb=format_hdl(ensure_wave_dump(tb))
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
        'max_build_seconds':MAX_BUILD_SECONDS,'max_repair_attempts':MAX_REPAIR_ATTEMPTS,'max_request_chars':MAX_REQUEST_CHARS,'generation_recovery_attempts':GENERATION_RECOVERY_ATTEMPTS,
        'sim_timeout_seconds':SIM_TIMEOUT,'diagram_timeout_seconds':DIAGRAM_TIMEOUT,
        'iverilog':shutil.which('iverilog') is not None,'vvp':shutil.which('vvp') is not None,
        'graphviz':shutil.which('dot') is not None,'general_purpose':True,
        'hardcoded_demo_fallback':False,'refusal_recovery':True,'version':'rtl-forge-general-ece-6.5','source_cleanup':'plain_hdl_sanitizer_v3_adaptive_verification'
    })

@app.post('/api/build')
def api_build():
    data=request.get_json(silent=True) or {}
    user_request=str(data.get('request','')).strip()
    if not user_request:
        return jsonify({'error':'Please provide a hardware requirement.','message':'Please provide a hardware requirement.'}),400
    if len(user_request)>MAX_REQUEST_CHARS:
        return jsonify({'error':'Hardware requirement is too long.','message':f'Hardware requirement is limited to {MAX_REQUEST_CHARS} characters.'}),400
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
