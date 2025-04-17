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
