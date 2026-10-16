#!/usr/bin/env python3
"""Exercise readiness, discovery and draining in an isolated k3d cluster.

The node fixture echoes TCP traffic and supplies controlled CLI query outputs.
The separate devnet test verifies the real cardano-cli contract.
"""
import json
import os
import pathlib
import subprocess
import tempfile
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLUSTER = "cardano-gate-" + uuid.uuid4().hex[:8]
NAMESPACE = "nodes"
RELEASE = "relay"
CLIENT_IMAGE = "docker.io/library/python@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a"


def run(command, *, env=None, input=None, check=True):
    result = subprocess.run(command, env=env, input=input, capture_output=True, text=True, timeout=360)
    if check and result.returncode:
        raise RuntimeError(result.stderr + result.stdout)
    return result


def wait_for(check, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(1)
    raise TimeoutError("test condition did not complete")


def main():
    with tempfile.TemporaryDirectory(prefix="cardano-gate-") as directory:
        root = pathlib.Path(directory)
        kubeconfig = root / "kubeconfig"
        env = dict(os.environ, KUBECONFIG=str(kubeconfig))
        image = CLUSTER + "-fixture"
        (root / "Dockerfile").write_text('FROM ghcr.io/blinklabs-io/cardano-node:11.1.3-1\nARG LAG_SECONDS\nENV LAG_SECONDS=$LAG_SECONDS\nCOPY cardano-cli /usr/local/bin/cardano-cli\nCOPY entrypoint.sh /fixture.sh\nRUN chmod +x /usr/local/bin/cardano-cli\nENTRYPOINT ["/bin/sh", "/fixture.sh"]\n')
        for name in ["cardano-cli", "entrypoint.sh"]:
            (root / name).write_bytes((ROOT / "scripts/fixtures/cardano-readiness" / name).read_bytes())
        for revision, lag in [("old", 0), ("new", 25)]:
            run(["docker", "build", "-t", image + ":" + revision, "--build-arg", "LAG_SECONDS=" + str(lag), str(root)])
        run(["docker", "pull", CLIENT_IMAGE])
        try:
            run(["k3d", "cluster", "create", CLUSTER, "--image", "rancher/k3s:v1.31.5-k3s1", "--k3s-arg", "--disable=traefik@server:0", "--kubeconfig-update-default=false", "--wait"])
            kubeconfig.write_text(run(["k3d", "kubeconfig", "get", CLUSTER]).stdout)
            kubeconfig.chmod(0o600)
            assert run(["kubectl", "config", "current-context"], env=env).stdout.strip() == "k3d-" + CLUSTER
            run(["k3d", "image", "import", image + ":old", image + ":new", CLIENT_IMAGE, "--cluster", CLUSTER])
            run(["kubectl", "create", "namespace", NAMESPACE], env=env)

            def kube(*args, **kwargs):
                return run(["kubectl", "-n", NAMESPACE, *args], env=env, **kwargs)

            def obj(kind, name):
                result = kube("get", kind, name, "-o", "json", check=False)
                return json.loads(result.stdout) if result.returncode == 0 else None

            values = {"fullnameOverride": RELEASE, "replicaCount": 2, "minReadySeconds": 3, "mithril": {"enabled": False}, "image": {"repository": image, "tag": "old"}, "resources": {"requests": {"cpu": "10m", "memory": "32Mi"}}, "storage": {"size": "16Mi"}, "availability": {"enabled": True, "periodSeconds": 2, "cliTimeoutSeconds": 1, "drainDelaySeconds": 15, "terminationGracePeriodSeconds": 45}, "podDisruptionBudget": {"enabled": True, "maxUnavailable": 1}}
            path = root / "values.json"
            path.write_text(json.dumps(values))
            command = ["helm", "upgrade", "--install", RELEASE, str(ROOT / "charts/cardano-node"), "-n", NAMESPACE, "-f", str(path), "--wait", "--timeout", "5m"]
            run(command, env=env)
            originals = [obj("pod", RELEASE + "-" + str(i)) for i in range(2)]
            claims = {p["metadata"]["name"]: p["metadata"]["uid"] for p in json.loads(kube("get", "pvc", "-o", "json").stdout)["items"]}
            program = '''import json,pathlib,socket,time
results={"requests":0,"errors":[]}
while not pathlib.Path("/tmp/stop").exists():
 try:
  with socket.create_connection(("relay",30000),timeout=3) as connection:
   connection.sendall(b"ping")
   assert connection.recv(4)==b"ping"
 except Exception as error:
  results["errors"].append(type(error).__name__)
 results["requests"]+=1
 time.sleep(0.2)
print(json.dumps(results),flush=True)
'''
            client = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "client"}, "spec": {"restartPolicy": "Never", "containers": [{"name": "client", "image": CLIENT_IMAGE, "command": ["python3", "-c", program]}]}}
            kube("apply", "-f", "-", input=json.dumps(client))
            kube("wait", "--for=condition=Ready", "pod/client", "--timeout=60s")
            slow_program = f'import socket,time; connection=socket.create_connection(("{originals[1]["status"]["podIP"]}",30000),timeout=30); print("connected",flush=True); time.sleep(12); connection.sendall(b"pong"); print(connection.recv(4).decode(),flush=True)'
            slow = subprocess.Popen(["kubectl", "-n", NAMESPACE, "exec", "client", "--", "python3", "-c", slow_program], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            assert slow.stdout.readline().strip() == "connected"
            values["image"]["tag"] = "new"
            path.write_text(json.dumps(values))
            upgrade = subprocess.Popen(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            wait_for(lambda: (obj("pod", "relay-1") or {}).get("metadata", {}).get("deletionTimestamp"), 30)
            assert slow.poll() is None
            stdout, stderr = slow.communicate(timeout=30)
            assert slow.returncode == 0 and stdout.strip() == "pong", stderr + stdout
            print("PASS: established N2C proxy connection survived termination draining", flush=True)

            def warming():
                pod = obj("pod", "relay-1")
                return pod if pod and pod["metadata"]["uid"] != originals[1]["metadata"]["uid"] and pod["status"]["phase"] == "Running" and not any(c["type"] == "Ready" and c["status"] == "True" for c in pod["status"].get("conditions", [])) else False

            replacement = wait_for(warming)
            assert obj("pod", "relay-0")["metadata"]["uid"] == originals[0]["metadata"]["uid"]
            endpoints = obj("endpoints", RELEASE)
            ready = [a["targetRef"]["name"] for s in endpoints.get("subsets", []) for a in s.get("addresses", [])]
            assert ready == ["relay-0"], ready
            dns = kube("exec", "client", "--", "python3", "-c", 'import socket; print(socket.gethostbyname_ex("relay-headless")[2])').stdout
            assert replacement["status"]["podIP"] in dns, dns
            wait_for(lambda: obj("pdb", RELEASE)["status"].get("disruptionsAllowed") == 0)
            eviction = {"apiVersion": "policy/v1", "kind": "Eviction", "metadata": {"name": "relay-0", "namespace": NAMESPACE}}
            denied = kube("create", "--raw", f"/api/v1/namespaces/{NAMESPACE}/pods/relay-0/eviction", "-f", "-", input=json.dumps(eviction), check=False)
            assert denied.returncode != 0 and "disruption budget" in denied.stderr.lower()
            print("PASS: syncing pod excluded from client Service, discoverable by peers; healthy ordinal and PDB preserved", flush=True)
            stdout, stderr = upgrade.communicate(timeout=240)
            assert upgrade.returncode == 0, stderr + stdout
            kube("exec", "client", "--", "touch", "/tmp/stop")
            wait_for(lambda: obj("pod", "client")["status"]["phase"] in ["Succeeded", "Failed"], 30)
            results = json.loads(kube("logs", "client").stdout)
            assert results["requests"] > 50 and not results["errors"], results
            final_claims = {p["metadata"]["name"]: p["metadata"]["uid"] for p in json.loads(kube("get", "pvc", "-o", "json").stdout)["items"]}
            assert claims == final_claims
            print("PASS: " + json.dumps(results) + "; PVC identities retained", flush=True)
        finally:
            run(["k3d", "cluster", "delete", CLUSTER], check=False)


if __name__ == "__main__":
    main()
