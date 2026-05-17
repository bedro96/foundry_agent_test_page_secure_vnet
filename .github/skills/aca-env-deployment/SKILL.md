---
name: aca-env-deployment
description: Azure Container Apps deployment pattern using .env files baked into Docker images as single source of truth.
---

# ACA Environment Deployment

## Context
This project deploys both frontend (Next.js) and backend (FastAPI) to Azure Container
Apps (ACA). Configuration is handled by `.env` files that are **baked into the Docker
image** at build time — ACA environment variables are intentionally not used.

Use this knowledge when deploying, updating, or troubleshooting the ACA deployment.

## Key Facts
- **`.env` files are the single source of truth** — they are `COPY`-ed into the Docker
  image during build. No ACA environment variables are set.
- **`update.sh`** is the deployment script for each service and currently uses the
  fixed `:latest` tag:
  1. `az acr build --registry iotacr --image lgit-chat-<service>:latest .`
  2. `az containerapp update --name lgit-chat-<service> --resource-group aks-rg --image iotacr.azurecr.io/lgit-chat-<service>:latest`
- **Caution**: the checked-in scripts are convenient but not deterministic. ACA may reuse
  a cached `:latest` image reference. For reliable rollouts, run the same commands with a
  unique tag manually (commit SHA, version, timestamp).
- **MySQL firewall**: Azure MySQL Flexible Server requires a firewall rule
  `AllowAllAzureIPs` with range `0.0.0.0` – `0.0.0.0` to allow ACA-to-MySQL connectivity.

### Frontend Dockerfile Pattern
```dockerfile
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/.env ./.env          # <-- bake .env into image
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"
CMD ["node", "--env-file=.env", "server.js"]  # <-- load .env at runtime
```

### Backend Dockerfile Pattern
```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev
COPY app ./app
RUN uv sync --no-dev

FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY .env ./.env
COPY app ./app
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
```

## Code Examples
```bash
# Current checked-in backend deploy flow
cd backend
az acr build --registry iotacr --image lgit-chat-backend:latest .
az containerapp update \
  --name lgit-chat-backend \
  --resource-group aks-rg \
  --image iotacr.azurecr.io/lgit-chat-backend:latest

# Recommended deterministic alternative
TAG=$(git rev-parse --short HEAD)
az acr build --registry iotacr --image lgit-chat-backend:$TAG .
az containerapp update \
  --name lgit-chat-backend \
  --resource-group aks-rg \
  --image iotacr.azurecr.io/lgit-chat-backend:$TAG

# Current checked-in frontend deploy flow
cd frontend
az acr build --registry iotacr --image lgit-chat-frontend:latest .
az containerapp update \
  --name lgit-chat-frontend \
  --resource-group aks-rg \
  --image iotacr.azurecr.io/lgit-chat-frontend:latest
```

## Common Pitfalls
- **Forgetting to update `.env` before building** — since the file is baked in, any
  change requires a new image build and deploy.
- **Using the checked-in `:latest` scripts without caution** — ACA may cache the image
  reference and not pull a new image. Prefer a unique tag (commit SHA, version, timestamp)
  for production rollouts.
- **MySQL connection refused** — ensure the `AllowAllAzureIPs` firewall rule
  (`0.0.0.0` – `0.0.0.0`) is set on the Azure MySQL Flexible Server.
- **Not including `.env` in `.dockerignore` exclusions** — the `.env` file must be
  present in the Docker build context; check `.dockerignore` does not exclude it.
- **Setting ACA environment variables** — this project does NOT use ACA env vars;
  all config comes from `.env` inside the image.

## References
- File: `backend/update.sh`
- File: `frontend/update.sh`
- File: `backend/Dockerfile`
- File: `frontend/Dockerfile`
