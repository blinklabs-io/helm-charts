#!/usr/bin/env python3
"""Exercise Dolos chart routing and draining in an isolated k3d cluster.

Requires Docker, k3d, kubectl, Helm and PyYAML. The backend is an API fixture,
not a Cardano node. Never reads or changes the user's current Kubernetes context.
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import uuid

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "dolos"
CLUSTER = "dolos-rollout-" + uuid.uuid4().hex[:8]
NAMESPACE = "dolos-rollout-test"
RELEASE = "dolos-mainnet-az1"


def run(command, *, env=None, input=None, check=True):
    result = subprocess.run(command, env=env, input=input, capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(f"{command[0]} failed: {result.stderr}\n{result.stdout}")
    return result


def wait_for(check, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(1)
    raise TimeoutError("rollout test condition did not complete")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adoption-script", type=pathlib.Path)
    args = parser.parse_args()
    for executable in ["docker", "k3d", "kubectl", "helm"]:
        if not shutil.which(executable):
            raise RuntimeError(f"missing {executable}")
    with tempfile.TemporaryDirectory(prefix="dolos-rollout-") as tmp:
        directory = pathlib.Path(tmp)
        kubeconfig = directory / "kubeconfig"
        env = dict(os.environ, KUBECONFIG=str(kubeconfig))
        image = f"{CLUSTER}-backend"
        defaults = yaml.safe_load((CHART / "values.yaml").read_text())
        base = defaults["availability"]["image"]
        (directory / "backend.py").write_bytes((ROOT / "scripts/fixtures/dolos-rollout/backend.py").read_bytes())
        (directory / "Dockerfile").write_text(
            f'FROM {base["repository"]}@{base["digest"]}\n'
            'ARG REVISION\nARG LAG_SECONDS\nENV REVISION=$REVISION LAG_SECONDS=$LAG_SECONDS\n'
            'COPY backend.py /app/backend.py\nENTRYPOINT ["python3", "-B", "/app/backend.py"]\n'
        )
        for revision, lag in [("old", 0), ("new", 25)]:
            run(["docker", "build", "-t", f"{image}:{revision}", "--build-arg", f"REVISION={revision}", "--build-arg", f"LAG_SECONDS={lag}", str(directory)])
        try:
            run(["k3d", "cluster", "create", CLUSTER, "--image", "rancher/k3s:v1.31.5-k3s1", "--servers", "1", "--agents", "0", "--k3s-arg", "--disable=traefik@server:0", "--kubeconfig-update-default=false", "--wait"])
            kubeconfig.write_text(run(["k3d", "kubeconfig", "get", CLUSTER]).stdout)
            kubeconfig.chmod(0o600)
            assert run(["kubectl", "config", "current-context"], env=env).stdout.strip() == f"k3d-{CLUSTER}"
            run(["k3d", "image", "import", f"{image}:old", f"{image}:new", "--cluster", CLUSTER])
            run(["kubectl", "create", "namespace", NAMESPACE], env=env)

            def kube(*args, **kwargs):
                return run(["kubectl", "-n", NAMESPACE, *args], env=env, **kwargs)

            def obj(kind, name):
                result = kube("get", kind, name, "-o", "json", check=False)
                return json.loads(result.stdout) if result.returncode == 0 else None

            reference = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "reference", "labels": {"role": "reference"}}, "spec": {"containers": [{"name": "reference", "image": f"{image}:old", "imagePullPolicy": "IfNotPresent", "args": ["reference"]}]}}
            ref_service = {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "reference"}, "spec": {"selector": {"role": "reference"}, "ports": [{"port": 8080}]}}
            api_service = {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "api"}, "spec": {"selector": {"cardano_network": "mainnet", "cardano_service": "dolos"}, "ports": [{"port": 8080, "targetPort": "minibf"}]}}
            for item in [reference, ref_service, api_service]:
                kube("apply", "-f", "-", input=json.dumps(item))
            values = {
                "replicaCount": 2, "minReadySeconds": 3, "terminationGracePeriodSeconds": 45,
                "image": {"repository": image, "tag": "old", "pullPolicy": "IfNotPresent"},
                "podLabels": {"cardano_service": "dolos"}, "network": "mainnet", "storage": {"size": "16Mi"},
                "resources": {"requests": {"cpu": "10m", "memory": "64Mi"}, "limits": {"memory": "128Mi"}},
                "ports": {"minikupo": 1442}, "service": {"ports": {"minikupo": 11442}},
                "availability": {"enabled": True, "referenceTipURLs": ["http://reference:8080/metrics"], "maxSlotLag": 5, "drainDelaySeconds": 15},
                "podDisruptionBudget": {"enabled": True},
            }
            values_file = directory / "values.json"
            values_file.write_text(json.dumps(values))
            command = ["helm", "upgrade", "--install", RELEASE, str(CHART), "--namespace", NAMESPACE, "-f", str(values_file), "--wait", "--timeout", "5m"]
            hook = None
            if args.adoption_script:
                hook = ["python3", "-B", str(args.adoption_script.resolve()), "--context", f"k3d-{CLUSTER}", "--namespace", NAMESPACE, "--release", RELEASE, "--reference-namespace", NAMESPACE, "--reference-service", "reference", "--reference-port", "8080", "--drain-seconds", "3"]
                other = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "other-az", "labels": {"app.kubernetes.io/name": "dolos", "app.kubernetes.io/instance": "dolos-mainnet-az2", "cardano_network": "mainnet", "cardano_service": "dolos"}}, "spec": {"containers": [{"name": "dolos", "image": f"{image}:old", "imagePullPolicy": "IfNotPresent", "ports": [{"name": "minibf", "containerPort": 3001}]}]}}
                kube("apply", "-f", "-", input=json.dumps(other))
                kube("wait", "--for=condition=Ready", "pod/other-az", "--timeout=60s")
                values["availability"]["enabled"] = False
                values["replicaCount"] = 1
                values_file.write_text(json.dumps(values))
            run(command, env=env)
            if hook:
                first_claims = {p["metadata"]["name"]: p["metadata"]["uid"] for p in json.loads(kube("get", "pvc", "-o", "json").stdout)["items"]}
                run(hook + ["bootstrap"], env=env)
                run(hook + ["presync"], env=env)
                assert obj("pod", f"{RELEASE}-0")["metadata"]["labels"]["dolos.blinklabs.io/serving"] == "false"
                endpoints = obj("endpoints", "api")
                assert [a["targetRef"]["name"] for subset in endpoints.get("subsets", []) for a in subset.get("addresses", [])] == ["other-az"]
                values["availability"]["enabled"] = True
                values["replicaCount"] = 2
                values_file.write_text(json.dumps(values))
                run(command, env=env)
                run(hook + ["postsync"], env=env)
                for name, uid in first_claims.items():
                    assert obj("pvc", name)["metadata"]["uid"] == uid
                assert obj("pod", "other-az")["metadata"]["labels"]["dolos.blinklabs.io/serving"] == "true"
                assert not obj("lease", "dolos-mainnet-rollout")["spec"].get("holderIdentity")
                print("PASS: legacy adoption withdrew only target AZ, retained PVC and released rollout lease", flush=True)
            else:
                kube("patch", "service", "api", "--type=merge", "-p", json.dumps({"spec": {"selector": {"dolos.blinklabs.io/serving": "true"}}}))
            originals = {str(i): obj("pod", f"{RELEASE}-{i}") for i in range(2)}
            claims = {p["metadata"]["name"]: p["metadata"]["uid"] for p in json.loads(kube("get", "pvc", "-o", "json").stdout)["items"]}
            client = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "client"}, "spec": {"restartPolicy": "Never", "containers": [{"name": "client", "image": f"{image}:old", "imagePullPolicy": "IfNotPresent", "args": ["client", "http://api:8080/blocks/latest"]}]}}
            kube("apply", "-f", "-", input=json.dumps(client))
            kube("wait", "--for=condition=Ready", "pod/client", "--timeout=60s")
            ip = originals["1"]["status"]["podIP"]
            slow = subprocess.Popen(["kubectl", "-n", NAMESPACE, "exec", "client", "--", "python3", "-c", f'import urllib.request; print(urllib.request.urlopen("http://{ip}:3001/blocks/latest?slow=12", timeout=30).read().decode())'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            wait_for(lambda: "slow-request-started" in kube("logs", f"{RELEASE}-1", "-c", "dolos").stdout, 30)
            values["image"]["tag"] = "new"
            values_file.write_text(json.dumps(values))
            if hook:
                run(hook + ["presync"], env=env)
            upgrade = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            wait_for(lambda: (obj("pod", f"{RELEASE}-1") or {}).get("metadata", {}).get("deletionTimestamp"), 30)
            assert slow.poll() is None, "request finished before termination; draining was not exercised"
            stdout, stderr = slow.communicate(timeout=30)
            assert slow.returncode == 0, stderr
            assert json.loads(stdout)["revision"] == "old", "in-flight request was not served by the retiring backend"
            print("PASS: request overlapping pod termination completed", flush=True)

            def warming():
                pod = obj("pod", f"{RELEASE}-1")
                if not pod or pod["metadata"]["uid"] == originals["1"]["metadata"]["uid"]:
                    return False
                ready = any(c["type"] == "Ready" and c["status"] == "True" for c in pod["status"].get("conditions", []))
                return pod if pod["status"]["phase"] == "Running" and not ready else False

            wait_for(warming)
            assert obj("pod", f"{RELEASE}-0")["metadata"]["uid"] == originals["0"]["metadata"]["uid"], "healthy ordinal replaced before replacement caught up"
            endpoints = obj("endpoints", "api")
            addresses = [a["targetRef"]["name"] for subset in endpoints.get("subsets", []) for a in subset.get("addresses", [])]
            assert f"{RELEASE}-0" in addresses and f"{RELEASE}-1" not in addresses, addresses
            wait_for(lambda: obj("pdb", RELEASE)["status"].get("disruptionsAllowed") == 0)
            eviction = {"apiVersion": "policy/v1", "kind": "Eviction", "metadata": {"name": f"{RELEASE}-0", "namespace": NAMESPACE}}
            denied = kube("create", "--raw", f"/api/v1/namespaces/{NAMESPACE}/pods/{RELEASE}-0/eviction", "-f", "-", input=json.dumps(eviction), check=False)
            assert denied.returncode != 0 and "disruption budget" in denied.stderr.lower(), denied.stderr
            print("PASS: stale replacement excluded, healthy ordinal preserved, eviction blocked", flush=True)
            stdout, stderr = upgrade.communicate(timeout=240)
            assert upgrade.returncode == 0, stderr + stdout
            if hook:
                run(hook + ["postsync"], env=env)
            kube("exec", "client", "--", "touch", "/tmp/stop-client")
            wait_for(lambda: obj("pod", "client")["status"]["phase"] in ["Succeeded", "Failed"], 30)
            results = json.loads(kube("logs", "client").stdout)
            assert results["requests"] > 50 and not results["errors"], results
            final_claims = {p["metadata"]["name"]: p["metadata"]["uid"] for p in json.loads(kube("get", "pvc", "-o", "json").stdout)["items"]}
            assert claims == final_claims, "PVC identity changed"
            print("PASS: " + json.dumps(results) + "; PVCs retained", flush=True)
        finally:
            run(["k3d", "cluster", "delete", CLUSTER], check=False)


if __name__ == "__main__":
    main()
