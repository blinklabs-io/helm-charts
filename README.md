# Helm-charts

## ✅ Prerequisites

Before using these charts, ensure you have the following installed and configured:

- **[Helm 3.8+](https://helm.sh/docs/intro/install/)**
  Helm is the package manager for Kubernetes.

- **A running Kubernetes cluster**
  This can be local (e.g. [Minikube](https://minikube.sigs.k8s.io/), [kind](https://kind.sigs.k8s.io/)) or provided by a cloud provider (e.g. GKE, EKS, AKS).

- **`kubectl` configured**
  Helm interacts with your cluster using `kubectl`. You should be able to run:

  ```bash
  kubectl get nodes
  ```

  and see your cluster nodes.

## How to use helm-charts

> 🧊 **Note:** OCI charts do **not** require `helm repo add`. You can install them directly from an OCI registry using the `oci://` URL format.
> 📚 [Learn more in the Helm docs](https://helm.sh/docs/topics/registries/#using-an-oci-based-registry)

### Install the chart

```bash
# Install the chart with default values latest or specific version of the chart

# Latest version
helm install <release-name> oci://ghcr.io/blinklabs-io/helm-charts/charts/<chart-name>

# Version spcific
helm install <release-name> oci://ghcr.io/blinklabs-io/helm-charts/charts/<chart-name> \
  --version <chart-version>

Example:
helm install dingo oci://ghcr.io/blinklabs-io/helm-charts/charts/dingo \
  --version 0.0.6
```

### Preview the chart with default and custom values

```bash
helm template oci://ghcr.io/blinklabs-io/helm-charts/charts/<chart-name> \
  --version <chart-version>

helm template dingo oci://ghcr.io/blinklabs-io/helm-charts/charts/dingo \
  --version 0.0.6

# Preview the chart with custom values
helm template oci://ghcr.io/blinklabs-io/helm-charts/charts/<chart-name> \
  --version <chart-version> \
  -f <custom-values-file>

Example:
helm template dingo oci://ghcr.io/blinklabs-io/helm-charts/charts/dingo \
  --version 0.0.6 \
  -f values.yaml
```

### Pull the chart

```bash
# Pull the chart with default values
helm pull oci://ghcr.io/blinklabs-io/helm-charts/charts/<chart-name> \
  --version <chart-version>

Example:
helm pull oci://ghcr.io/blinklabs-io/helm-charts/charts/dingo \
  --version 0.0.6

# Pull the chart and unpack it
helm pull oci://ghcr.io/blinklabs-io/helm-charts/charts/<chart-name> \
  --version <chart-version> \
  --untar

Example:
helm pull oci://ghcr.io/blinklabs-io/helm-charts/charts/dingo \
  --version 0.0.6 \
  --untar
```

## Automatic image-version updates

Charts are kept in sync with their upstream container images via the
[`check-image-versions`](.github/workflows/check-image-versions.yml) workflow,
which mirrors the approach used in
[blinklabs-io/cardano-up-packages](https://github.com/blinklabs-io/cardano-up-packages).

### How it works

1. The workflow runs **every Sunday at 00:00 UTC** (and can be triggered
   manually via `workflow_dispatch`).
2. It reads [`scripts/upstream-versions.json`](scripts/upstream-versions.json),
   which maps each manageable chart to its upstream GitHub repository (and
   optional Docker Hub / GHCR source).
3. For every chart it fetches the latest published release tag, derives the
   new image tag and `appVersion`, then compares against the value currently
   stored in `charts/<name>/values.yaml`.
4. When a newer version is detected it calls
   [`scripts/update-chart-version.sh`](scripts/update-chart-version.sh), which:
   - Updates `image.tag` in `values.yaml`.
   - Updates `appVersion` in `Chart.yaml`.
   - Bumps the patch segment of `version` in `Chart.yaml`.
5. The changes are committed to a branch named
   `chore/<chart-name>-<version>` and a pull-request is opened automatically.
6. If the chart is already on the latest version, or a PR for that version
   already exists, no action is taken.

### Adding a new chart to auto-updates

Edit [`scripts/upstream-versions.json`](scripts/upstream-versions.json) and
add an entry following the schema below:

```jsonc
"my-chart": {
  // GitHub org/repo whose releases drive the update
  "repo": "org/repo",

  // Prefix to strip from the GitHub release tag to get the plain version.
  // E.g. "v" turns "v1.2.3" into "1.2.3".  Use "" to keep the tag as-is.
  // Note: ignored when "ghcr_image" is set (GHCR tags are filtered by semver
  // regex instead; see the workflow for details).
  "tag_pattern": "v",

  // Prefix written in front of the version when updating values.yaml image.tag.
  // E.g. "v" produces tag: v1.2.3; "" produces tag: 1.2.3.
  "values_tag_prefix": "",

  // Prefix written in front of the version when updating Chart.yaml appVersion.
  "app_version_prefix": "",

  // (Optional) Docker Hub image to resolve full semver when the GitHub release
  // tag is shorter (e.g. v2.11 -> v2.11.0).
  // "docker_image": "org/image",

  // (Optional) Use GHCR as the version source instead of GitHub releases.
  // Useful when the upstream project does not publish GitHub releases.
  // "ghcr_image": "org/image"
}
```

### Manually triggering

Navigate to **Actions → check-image-versions → Run workflow** in the GitHub UI.

### Scripts

| Script | Purpose |
|--------|---------|
| [`scripts/upstream-versions.json`](scripts/upstream-versions.json) | Config mapping each chart to its upstream source |
| [`scripts/update-chart-version.sh`](scripts/update-chart-version.sh) | Updates `values.yaml`, `Chart.yaml` appVersion, and bumps chart version patch |
