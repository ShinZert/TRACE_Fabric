# --- Stage 1: build the React/Vite frontend bundle --------------------------
FROM node:20-slim AS frontend-build

WORKDIR /build

# Install JS deps first (cached layer when frontend/package*.json don't change)
COPY frontend/package.json frontend/package-lock.json* ./frontend/
RUN cd frontend && (npm ci || npm install)

# Build — Vite outputs to ../static/dist/ relative to the frontend directory
COPY frontend/ ./frontend/
RUN cd frontend && npm run build

# --- Stage 2: Python runtime ------------------------------------------------
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Drop in the freshly-built frontend bundle
COPY --from=frontend-build /build/static/dist /app/static/dist

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120", "app:app"]
