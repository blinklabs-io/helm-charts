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
[`check-image-versions`](.github/workflows/check-image-versions.yml) workflow.
Container-registry tags (Docker Hub or GHCR) are the sole source of truth:
GitHub repository release tags are **not** consulted, because release tags can
diverge from tags that are actually published to the registry (packaging
revisions, mirror re-tags, missing builds, etc.).

### How it works

1. The workflow runs **every Sunday at 00:00 UTC** (and can be triggered
   manually via `workflow_dispatch`).
2. It reads [`scripts/upstream-versions.json`](scripts/upstream-versions.json),
   which maps each manageable chart to the container image (GHCR or Docker
   Hub) that should drive updates.
3. For every chart it lists tags from the configured registry, keeps those
   that fully match `tag_regex`, sorts them with `sort -V`, and picks the
   highest.
4. The resolved tag is compared against `image.tag` in
   `charts/<name>/values.yaml`. The update is applied only when the resolved
   tag is **strictly greater** than the current one (downgrades and equals
   are rejected).
5. When an update is applied,
   [`scripts/update-chart-version.sh`](scripts/update-chart-version.sh):
   - Updates `image.tag` in `values.yaml` (double-quoted to preserve string
     type for YAML).
   - Updates `appVersion` in `Chart.yaml` (double-quoted for the same reason).
   - Bumps the patch segment of `version` in `Chart.yaml`.
6. The changes are committed to a branch named
   `chore/<chart-name>-<core-version>` and a pull-request is opened.

### Adding a new chart to auto-updates

Edit [`scripts/upstream-versions.json`](scripts/upstream-versions.json) and
add an entry following the schema below:

```jsonc
"my-chart": {
  // Container registry that publishes the image. Only "ghcr" and "dockerhub"
  // are supported.
  "registry": "ghcr",

  // Path segment after the registry host: "<org>/<name>".
  // E.g. "blinklabs-io/adder" (GHCR) or "cardanosolutions/kupo" (Docker Hub).
  "image": "org/name",

  // POSIX extended regex that a candidate tag must fully match. Use
  // this to exclude floating tags like "latest", release-candidate tags,
  // and anything with an unexpected shape.
  //   Simple semver           : "^[0-9]+\\.[0-9]+\\.[0-9]+$"
  //   Semver with v-prefix    : "^v[0-9]+\\.[0-9]+\\.[0-9]+$"
  //   Semver + packaging rev  : "^[0-9]+\\.[0-9]+\\.[0-9]+(-[0-9]+)?$"
  //   Four-segment            : "^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$"
  "tag_regex": "^[0-9]+\\.[0-9]+\\.[0-9]+$",

  // Leading substring that is part of the image tag itself but should be
  // stripped before applying the appVersion prefix below. Use "v" when the
  // image tag looks like "v1.2.3" and appVersion needs a plain "1.2.3".
  "tag_pattern": "",

  // Prefix prepended to the (post-strip) version when writing appVersion in
  // Chart.yaml. Use "v" to produce "v1.2.3", "" for a bare "1.2.3".
  "app_version_prefix": ""
}
```

The value written to `values.yaml`'s `image.tag` is always the raw registry
tag (verbatim, so that `image.repository:image.tag` is exactly what will be
pulled). Only `appVersion` is transformed via `tag_pattern` + `app_version_prefix`.

### CI on generated pull requests

Pull requests opened using the default `GITHUB_TOKEN` **do not trigger** the
repository's `pull_request` workflows (chart lint, conventional-commit checks,
etc.). To ensure automated update PRs are CI-checked before merge, configure
a repository secret named `AUTO_PR_TOKEN` containing a PAT or GitHub App
installation token with `contents: write` and `pull-requests: write`. The
workflow uses `AUTO_PR_TOKEN` when present and falls back to `GITHUB_TOKEN`
otherwise.

### Manually triggering

Navigate to **Actions → check-image-versions → Run workflow** in the GitHub UI.

### Scripts

| Script | Purpose |
|--------|---------|
| [`scripts/upstream-versions.json`](scripts/upstream-versions.json) | Config mapping each chart to its upstream source |
| [`scripts/update-chart-version.sh`](scripts/update-chart-version.sh) | Updates `values.yaml`, `Chart.yaml` appVersion, and bumps chart version patch |
