#!/usr/bin/env bash
# Updates a Helm chart's image tag, appVersion, and chart version patch number.
# Mirrors the add-version.sh pattern from blinklabs-io/cardano-up-packages.
#
# Usage:
#   ./scripts/update-chart-version.sh <chart-name> <values-tag> <app-version>
#
# Arguments:
#   chart-name   - Directory name under charts/ (e.g. dingo, cardano-node)
#   values-tag   - Full image tag string to write into values.yaml (e.g. 0.52.0, v1.4.0)
#   app-version  - Full appVersion string to write into Chart.yaml (e.g. 0.52.0, v1.4.0)
#
# What this script does:
#   1. Replaces the top-level image.tag in charts/<name>/values.yaml
#   2. Replaces appVersion in charts/<name>/Chart.yaml
#   3. Bumps the patch segment of version in charts/<name>/Chart.yaml

set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <chart-name> <values-tag> <app-version>"
  echo "Example: $0 dingo 0.52.0 0.52.0"
  exit 1
fi

CHART_NAME="$1"
NEW_VALUES_TAG="$2"
NEW_APP_VERSION="$3"

CHART_DIR="charts/${CHART_NAME}"
VALUES_FILE="${CHART_DIR}/values.yaml"
CHART_FILE="${CHART_DIR}/Chart.yaml"

if [[ ! -d "$CHART_DIR" ]]; then
  echo "ERROR: Chart directory not found: $CHART_DIR"
  exit 1
fi

# ── 1. Derive current and next chart version ──────────────────────────────────
# Strip any surrounding quotes from the version field
CURRENT_CHART_VERSION=$(grep '^version:' "$CHART_FILE" | head -1 | awk '{print $2}' | tr -d '"')

# Split on '.' and bump the patch (third) segment
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_CHART_VERSION"
NEW_CHART_VERSION="${MAJOR}.${MINOR}.$((PATCH + 1))"

echo "Updating chart: ${CHART_NAME}"
echo "  values.yaml  image.tag  : ${NEW_VALUES_TAG}"
echo "  Chart.yaml   appVersion : ${NEW_APP_VERSION}"
echo "  Chart.yaml   version    : ${CURRENT_CHART_VERSION} -> ${NEW_CHART_VERSION}"
echo ""

# Portable sed: BSD sed (macOS) needs -i '' while GNU sed (Linux/CI) needs -i.
# Using SED_INPLACE makes the script work in both environments.
if sed --version 2>/dev/null | grep -q GNU; then
  SED_INPLACE=(sed -i)
else
  SED_INPLACE=(sed -i '')
fi

# ── 2. Update values.yaml ─────────────────────────────────────────────────────
# Replace the first (and only) top-level `  tag:` line in the file.
# All target charts have exactly one two-space-indented `tag:` key, which belongs
# to the primary image block.  Nested image blocks use deeper indentation.
"${SED_INPLACE[@]}" "s|^  tag:.*|  tag: ${NEW_VALUES_TAG}|" "$VALUES_FILE"

# ── 3. Update Chart.yaml ──────────────────────────────────────────────────────
# appVersion may be unquoted or quoted; replace the whole line either way.
"${SED_INPLACE[@]}" "s|^appVersion:.*|appVersion: ${NEW_APP_VERSION}|" "$CHART_FILE"

# Bump the chart version.
"${SED_INPLACE[@]}" "s|^version:.*|version: ${NEW_CHART_VERSION}|" "$CHART_FILE"

echo "Updated ${VALUES_FILE}:"
grep '  tag:' "$VALUES_FILE" | head -1
echo ""
echo "Updated ${CHART_FILE}:"
grep -E '^(version|appVersion):' "$CHART_FILE"
echo ""
echo "Please review the diff before committing:"
git diff -- "$VALUES_FILE" "$CHART_FILE" || true
