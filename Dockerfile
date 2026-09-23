FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# OS-level dependencies required by the ECE RTL agent
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       iverilog \
       graphviz \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY app.py .

EXPOSE 10000

CMD ["gunicorn", "app:app", "--workers", "1", "--timeout", "120", "--bind", "0.0.0.0:10000"]
