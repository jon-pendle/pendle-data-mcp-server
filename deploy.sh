#!/bin/bash
set -e

# Clone/update Boros knowledge base into build context
BOROS_KB="./boros-kb"
BOROS_KB_REPO="https://github.com/pendle-finance/boros-knowledge-base.git"
if [ -d "$BOROS_KB/.git" ]; then
    echo "Updating Boros KB..."
    git -C "$BOROS_KB" pull --ff-only
else
    echo "Cloning Boros KB..."
    rm -rf "$BOROS_KB"
    git clone --depth 1 "$BOROS_KB_REPO" "$BOROS_KB"
fi

# Build the image
echo "Building image..."
gcloud builds submit --config cloudbuild.yaml --substitutions=SHORT_SHA=latest .

# Get project ID and construct image URL
PROJECT_ID=$(gcloud config get-value project --quiet)
IMAGE="asia-southeast1-docker.pkg.dev/${PROJECT_ID}/cloud-run/pendle-mcp-server:latest"

# Deploy to Cloud Run
echo "Deploying to Cloud Run..."
gcloud run deploy p-data-mcp-server \
  --image "$IMAGE" \
  --region asia-southeast1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 1024Mi \
  --cpu 1 \
  --max-instances 3 \
  --service-account p-data-mcp-server@pendle-data.iam.gserviceaccount.com \
  --set-env-vars "GOOGLE_OAUTH_CLIENT_ID=756482294543-flqkea2lpkugufl15rh7tjne6mjcbif7.apps.googleusercontent.com,MCP_SERVER_BASE_URL=https://p-data-mcp-server-7vz6iynqna-as.a.run.app,QA_SERVICE_URL=https://llm-service-qa-7vz6iynqna-uc.a.run.app" \
  --set-secrets "GOOGLE_OAUTH_CLIENT_SECRET=JONJON_MCP_OAUTH_CLIENT_SECRET:latest"

echo "Deploy complete."
