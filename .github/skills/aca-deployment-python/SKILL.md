---
name: aca-deployment-python
display_name: Azure Container Apps Deployment (Python)
description: >-
    Deploy this Python MCP/OpenAPI service to Azure Container Apps via GitHub Actions.
    Covers the exact secrets, variables, OIDC federated identity setup, build and deploy
    workflow anatomy, Jinja2 health-probe template, and common failure modes. Use this
    to replicate the CI/CD pipeline exactly in a new repository.
user-invocable: true
---

# Azure Container Apps Deployment via GitHub Actions

## Why this skill exists

Deploying to Azure Container Apps (ACA) via GitHub Actions is the only reliable,
repeatable path for this service. The pipeline is intentionally fragile-free:
resources are created if missing, updates use a rendered YAML (not raw CLI flags),
health probes are mandatory, and the workflow is triggered automatically by a
successful Docker build. **Do not improvise the pipeline** — replicate it from
this reference exactly.

---

## Repository configuration checklist

Before any workflow runs you must configure these in your GitHub repository
(**Settings → Secrets and variables → Actions**).

### Required Secrets

| Secret name | What it holds |
|---|---|
| `AZURE_CLIENT_ID` | Client (app) ID of the Azure service principal used for OIDC login |
| `AZURE_TENANT_ID` | Azure AD tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID where the Container App lives |
| `REGISTRY_PASSWORD` | ACR admin password (used by ACA to pull the image) |
| `SLACK_WEBHOOK_URL` | Incoming webhook URL for deployment notifications (optional but expected by the workflow) |

### Required Variables

| Variable name | Default if missing | Purpose |
|---|---|---|
| `ACR_NAME` | `iotacr` | Azure Container Registry name (without `.azurecr.io`) |
| `IMAGE_NAME` | `foundry-agent-backend` | Docker image name pushed to ACR |
| `CONTAINER_APP_NAME` | `foundry-agent-backend` | Name of the Azure Container App resource |
| `CONTAINER_APP_ENVIRONMENT` | `nl2sqlenv` | Name of the Container Apps Environment |
| `AZURE_RESOURCE_GROUP` | `aks-rg` | Resource group containing all ACA resources |
| `LOG_ANALYTICS_WORKSPACE` | `workspaceazureaiagent7154` | Log Analytics workspace name for ACA logging |

> All variables have hard-coded fallback defaults in the workflow `env:` block.
> Override them with repository variables so the workflow is portable.

---

## OIDC federated identity setup

This pipeline uses **OpenID Connect (OIDC)** — not a stored client secret — to
authenticate to Azure. This is required for the `azure/login@v2` action.

### Steps to configure

1. **Create (or identify) an Azure service principal:**

   ```bash
   az ad sp create-for-rbac --name "github-aca-deployer" --skip-assignment
   ```

   Note the `appId` (→ `AZURE_CLIENT_ID`), `tenant` (→ `AZURE_TENANT_ID`).

2. **Add a federated credential** for your GitHub repository and branch:

   ```bash
   az ad app federated-credential create \
     --id <appId> \
     --parameters '{
       "name": "github-main",
       "issuer": "https://token.actions.githubusercontent.com",
       "subject": "repo:<owner>/<repo>:ref:refs/heads/main",
       "audiences": ["api://AzureADTokenExchange"]
     }'
   ```

   Repeat for `pull_request` events if needed:
   ```bash
   # subject for PRs:
   "repo:<owner>/<repo>:pull_request"
   ```

3. **Assign roles** to the service principal:

   ```bash
   # Contributor on the resource group (for ACA resource management)
   az role assignment create \
     --assignee <appId> \
     --role Contributor \
     --scope /subscriptions/<sub-id>/resourceGroups/<resource-group>

   # AcrPush on the container registry (for image push)
   az role assignment create \
     --assignee <appId> \
     --role AcrPush \
     --scope /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.ContainerRegistry/registries/<acr-name>
   ```

4. **Store the values** as GitHub secrets:
   - `AZURE_CLIENT_ID` = `appId`
   - `AZURE_TENANT_ID` = `tenant`
   - `AZURE_SUBSCRIPTION_ID` = your subscription ID

The workflow block that consumes these:

```yaml
- uses: azure/login@v2
  with:
    client-id: ${{ secrets.AZURE_CLIENT_ID }}
    tenant-id: ${{ secrets.AZURE_TENANT_ID }}
    subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
```

---

## `build-back.yml` — Build and push the Docker image

**File:** `.github/workflows/build-back.yml`

### Trigger paths

The workflow triggers on `push` or `pull_request` to `main` **only when** these
paths change:

```
main.py  Dockerfile  .env  .env.sample  pyproject.toml  uv.lock
.github/**  src/**  tests/**
```

Changes to README, docs, or other non-runtime files do not trigger a build.
This keeps the pipeline fast. If you add a new runtime file, add its path here.

### What the workflow does

```
Checkout → Docker Buildx setup → Azure OIDC login → ACR login
→ Extract metadata (sha + latest tags) → Build & push image
```

Key details:
- Image is pushed **only on `push` to `main`** — not on pull requests.
  Pull requests build locally to validate the Dockerfile but do not push.
- Tags: `sha-<full-git-sha>` for traceability + `latest` on the default branch.
- Uses `cache-from: type=gha` / `cache-to: type=gha,mode=max` for layer caching between runs.
- Platform: `linux/amd64` (required for ACA; do not add `linux/arm64` unless explicitly needed).

### Required permissions

```yaml
permissions:
  contents: read
  id-token: write   # Required for OIDC
```

---

## `deploy-backend.yml` — Deploy to Azure Container Apps

**File:** `.github/workflows/deploy-backend.yml`

### Trigger

Runs automatically after `build-backend.yml` completes **successfully** on `main`:

```yaml
on:
  workflow_run:
    workflows: ['Build Docker Image - BACKEND']
    types: [completed]
  workflow_dispatch:   # also allows manual trigger
    inputs:
      image_tag:
        default: 'latest'
      force_recreate:
        default: false
```

The critical guard condition that prevents running on failed builds:

```yaml
if: |
  github.event_name == 'workflow_dispatch' ||
  (github.event_name == 'workflow_run' &&
   github.event.workflow_run.conclusion == 'success' &&
   github.event.workflow_run.event == 'push' &&
   github.event.workflow_run.head_branch == 'main')
```

### Job dependency chain

```
check-resources
  ├── [log-analytics missing?] → setup-environment-log-analytics-workspace
  │     └── setup-environment-container-app-environment
  │           └── setup-environment-container-app
  │                 └── update-app
  │                       └── verify-deployment
  └── [resources exist] → (setup jobs SKIP) → update-app → verify-deployment
```

Each setup job uses `always() && (needs.<job>.result == 'success' || needs.<job>.result == 'skipped')`
so existing resources cleanly skip creation steps without blocking the chain.

### Job: `check-resources`

Checks for the existence of three Azure resources and outputs boolean flags:

```bash
az monitor log-analytics workspace show ...  → log-analytics-exists
az containerapp env show ...                 → environment-exists
az containerapp show ...                     → container-app-exists
```

These outputs gate the three setup jobs below.

### Jobs: `setup-environment-*`

Three sequential jobs that provision:
1. **Log Analytics workspace** — if `log-analytics-exists == 'false'`
2. **Container App Environment** — if `environment-exists == 'false'`; links to the workspace
3. **Container App** — if `container-app-exists == 'false'`; sets port 8000, external ingress, CPU 0.25, memory 0.5Gi

Initial Container App creation uses explicit CLI flags:

```bash
az containerapp create \
  --name $CONTAINER_APP_NAME \
  --resource-group $CONTAINER_APP_RESOURCE_GROUP \
  --environment $CONTAINER_APP_ENV \
  --image $REGISTRY_NAME.azurecr.io/$IMAGE_NAME:latest \
  --target-port 8000 \
  --ingress external \
  --registry-server $REGISTRY_NAME.azurecr.io \
  --registry-username $REGISTRY_NAME \
  --registry-password ${{ secrets.REGISTRY_PASSWORD }} \
  --cpu 0.25 \
  --memory 0.5Gi
```

### Job: `update-app`

This is the job that runs on **every deploy** (create or update). It:

1. Installs `jinja2-cli` (`pip install jinja2-cli`).
2. Renders `.github/templates/config.yaml.j2` → `/tmp/health-probes.yaml` with all variables.
3. Calls `az containerapp update --yaml /tmp/health-probes.yaml`.
4. Restarts the latest revision.
5. Cleans up the temp file (`if: always()`).

**Why YAML instead of CLI flags?**
`az containerapp update` with raw flags cannot set health probes. The `--yaml`
flag accepts a partial properties document that is merged with the existing
Container App configuration. The Jinja2 template generates this document.

### Job: `verify-deployment`

Queries the deployed Container App and sends a Slack notification with:
- App name, running status, provisioning state, FQDN, CPU/memory, latest revision.
- Notification always fires (`if: always()`) — success or failure.

---

## Jinja2 template: `config-backend.yaml.j2`

**File:** `.github/templates/config-backend.yaml.j2`

This template is the **single source of truth** for health probes, scale rules,
registry auth, resource limits, and image reference. It is rendered at deploy
time and passed to `az containerapp update --yaml`.

```yaml
properties:
  configuration:
    secrets:
      - name: registry-password
        value: {{ registry_password }}
    registries:
      - server: {{ registry_name }}.azurecr.io
        username: {{ registry_name }}
        passwordSecretRef: registry-password
  template:
    containers:
      - name: {{ container_app_name }}
        image: {{ registry_name }}.azurecr.io/{{ image_name }}:{{ image_tag }}
        resources:
          cpu: 0.25
          memory: 0.5Gi
        probes:
          - type: Liveness
            httpGet:
              path: /health/live
              port: 8000
              scheme: HTTP
            initialDelaySeconds: 2
            periodSeconds: 10
          - type: Readiness
            httpGet:
              path: /health/ready
              port: 8000
              scheme: HTTP
            initialDelaySeconds: 2
            periodSeconds: 10
    scale:
      minReplicas: 1
      maxReplicas: 1
      rules:
        - name: http-scaler
          http:
            metadata:
              concurrentRequests: "20"
```

Variables are injected with `jinja2 -D key=value`:

```bash
jinja2 .github/templates/config-backend.yaml.j2 \
  -D container_app_name=$CONTAINER_APP_NAME \
  -D registry_name=$REGISTRY_NAME \
  -D registry_password=${{ secrets.REGISTRY_PASSWORD }} \
  -D image_name=$IMAGE_NAME \
  -D image_tag=${IMAGE_TAG} > /tmp/health-probes.yaml
```

---

## Health probe requirement (mandatory)

ACA continuously calls `/health/live` and `/health/ready` on port 8000.
**If either returns non-200, ACA marks the revision unhealthy and may terminate it.**

These routes are defined in `src/api.py`:

```python
@router.get("/health/live", response_model=HealthPayload, ...)
async def live_health() -> HealthPayload:
    return HealthPayload(app_name=..., app_mode=..., version=...)

@router.get("/health/ready", response_model=HealthPayload, ...)
async def ready_health() -> HealthPayload:
    return HealthPayload(app_name=..., app_mode=..., version=...)
```

Both routes must:
- Return HTTP 200 under all normal operating conditions.
- Not require authentication (health probes have no auth headers).
- Be registered before the `BearerAuthMiddleware` can block them.
  (The middleware in this repo excludes health routes by checking the path.)

**Never remove, rename, or add auth to these endpoints.**

---

## Dockerfile reference

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.13-bookworm

WORKDIR /app

COPY pyproject.toml uv.lock README.md main.py /app/
COPY .env /app/.env          # .env is NOT excluded — it carries runtime defaults
COPY src /app/src

ENV PATH="/app/.venv/bin:$PATH"
ENV CI=true
ENV PYTHONUNBUFFERED=1

RUN uv sync --frozen --no-dev   # Install only production deps; freeze the lockfile

ENTRYPOINT ["uv", "run", "main.py"]
```

Key points:
- `.env` is copied into the image. It is **not** in `.dockerignore`.
  The container relies on `.env` for production defaults (e.g. `APP_MODE=Production`
  is injected via ACA environment variables, overriding the `.env` value).
- `uv sync --frozen` pins exact versions from `uv.lock` — never resolves fresh.
- `--no-dev` excludes linting, testing, and formatting tools from the image.
- The base image is the official `uv` image with Python 3.13 on Debian Bookworm.

---

## Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `azure/login` fails with "AADSTS" | Federated credential subject mismatch | Check the `subject` in the federated credential matches the workflow trigger (`refs/heads/main` vs `pull_request`) |
| `az acr login` fails | Service principal lacks `AcrPush` role | Assign `AcrPush` role on the ACR resource |
| Docker push succeeds but deploy job skips | `workflow_run.conclusion` check fails — build triggered from a PR, not a push | Verify the push went to `main`, not a feature branch |
| Container App stays in "Provisioning" | Health probes failing immediately | Check app logs; ensure `/health/live` returns 200 on port 8000 without auth |
| Jinja2 render fails | Missing variable passed with `-D` | Confirm all `env:` variables are set in the workflow or repository variables |
| `az containerapp update --yaml` fails | Partial YAML has invalid property | Validate the rendered YAML with `jinja2` locally; check ACA API version constraints |
| Slack notification missing | `SLACK_WEBHOOK_URL` secret not set | Add the secret; or remove the curl step if Slack is not needed |
| Old revision stays active after deploy | `az containerapp revision restart` failed silently | Check the restart step logs; the FQDN from `verify-deployment` should point to the new revision |

---

## Replication checklist

When setting up this pipeline in a new repository:

```
[ ] Create Azure service principal with OIDC federated credentials
[ ] Assign Contributor role on resource group
[ ] Assign AcrPush role on ACR
[ ] Add AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID as GitHub secrets
[ ] Add REGISTRY_PASSWORD as GitHub secret
[ ] Add SLACK_WEBHOOK_URL as GitHub secret (or remove Slack step)
[ ] Add ACR_NAME, IMAGE_NAME, CONTAINER_APP_NAME, CONTAINER_APP_ENVIRONMENT,
    AZURE_RESOURCE_GROUP, AZURE_LOCATION, LOG_ANALYTICS_WORKSPACE as GitHub variables
[ ] Copy .github/workflows/build.yml exactly
[ ] Copy .github/workflows/deploy.yml exactly
[ ] Copy .github/templates/config.yaml.j2 exactly
[ ] Ensure /health/live and /health/ready return 200 on port 8000
[ ] Push to main — build.yml triggers, then deploy.yml triggers automatically
[ ] Check verify-deployment job output for FQDN and running status
```
