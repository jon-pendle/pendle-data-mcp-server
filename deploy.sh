#!/bin/bash
# Emergency manual deploy. Normal path is push-to-main via the Cloud Build
# trigger that runs cloudbuild.yaml end-to-end. Use this only when the
# trigger is unavailable (e.g. GCP incident, permissions issue).
set -e

# Sync the boros-kb submodule so Dockerfile's COPY boros-kb/ sees content.
echo "Syncing submodules..."
git submodule update --init --recursive

# Build image AND deploy to Cloud Run (cloudbuild.yaml contains both steps).
# SHORT_SHA defaults to 'latest' here so the manual image doesn't collide with
# trigger-produced SHA-tagged images.
echo "Submitting build + deploy to Cloud Build..."
gcloud builds submit --config cloudbuild.yaml --substitutions=SHORT_SHA=latest .

echo "Deploy complete."
