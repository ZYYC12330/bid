FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=18010 \
    LLM_BASE_URL=http://10.25.1.48/v1 \
    LLM_MODEL=qwen-

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice \
        poppler-utils \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fastapi_backend.py README.md ./
COPY scripts ./scripts
COPY frontend ./frontend

RUN mkdir -p /app/runtime/fastapi_jobs /app/runtime/knowledge_images

EXPOSE 18010

CMD ["python", "-m", "uvicorn", "fastapi_backend:app", "--host", "0.0.0.0", "--port", "18010"]
