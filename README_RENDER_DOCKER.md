# Render deployment for ECE RTL AI Agent

The native Python runtime cannot be used for this MVP because the app needs OS-level
programs: Icarus Verilog (`iverilog`/`vvp`) and Graphviz (`dot`).

Use Render's Docker runtime.

Repository:
- app.py
- requirements.txt
- Dockerfile
- .dockerignore

Render:
1. New -> Web Service
2. Select the GitHub repository.
3. Runtime/Language: Docker
4. Dockerfile Path: ./Dockerfile
5. Leave Build Command empty.
6. Leave Start Command empty; Dockerfile CMD starts Gunicorn.
7. Add environment variable:
   GEMINI_API_KEY = your fresh Gemini API key
8. Optional:
   GEMINI_MODEL = gemini-3.8-flash
   MAX_REPAIR_ATTEMPTS = 4
   SIM_TIMEOUT_SECONDS = 20
9. Health Check Path: /health
10. Deploy.

Do not put the Gemini API key in GitHub or Dockerfile.

The Docker image installs:
- Python
- Icarus Verilog
- Graphviz
- Python dependencies

After deployment, /health should report:
status=ok
gemini_configured=true
iverilog=true
graphviz=true
