# ECE RTL AI Engineer

Natural-language digital-ECE requirement -> architecture -> SystemVerilog RTL ->
self-checking testbench -> Icarus Verilog simulation -> automatic repair loop ->
verification critique -> Graphviz architecture diagram.

## Colab
1. Install Python packages and Icarus/Graphviz.
2. Set GEMINI_API_KEY.
3. Run app.py locally for testing.

## GitHub
Upload:
- app.py
- requirements.txt

Do NOT upload your Gemini API key.

## Render
Runtime: Python 3
Build command:
pip install -r requirements.txt && apt-get update -qq && apt-get install -y iverilog graphviz

Start command:
gunicorn app:app --workers 1 --timeout 120

Environment variable:
GEMINI_API_KEY = your fresh Gemini API key
Optional:
GEMINI_MODEL = gemini-3.8-flash
MAX_REPAIR_ATTEMPTS = 4
SIM_TIMEOUT_SECONDS = 20

Important: this MVP executes generated HDL. For production with arbitrary user code,
move simulation into an isolated sandbox/container/worker before exposing it publicly.
