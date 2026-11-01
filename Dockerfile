# Production image: one container serves the API and the built dashboard (used by Render).
# Local development still uses docker-compose.yml (separate api, worker, dashboard dev server).

# 1. build the dashboard
FROM node:22-alpine AS dashboard
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2. the API, with the built dashboard next to it
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY --from=dashboard /web/dist ./static
EXPOSE 8000
# Render tells the app which port to use in $PORT; --proxy-headers so https links and cookies are right
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
