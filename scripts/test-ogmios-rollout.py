#!/usr/bin/env python3
"""Exercise semantic readiness and surge rollout in a disposable k3d cluster.

Uses an HTTP fixture in place of Ogmios and the node socket. Requires Docker,
k3d, kubectl, Helm and PyYAML; never uses the current Kubernetes context.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[1]
CLUSTER = "ogmios-readiness-" + uuid.uuid4().hex[:8]
FIXTURE = '''import json, os, time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
started = time.monotonic()
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            body = b"cardano_node_metrics_slotNum_int 1000\\n"
        else:
            healthy = time.monotonic() - started >= float(os.environ["WARMUP"]) and not os.path.exists("/tmp/stale")
            body = json.dumps({"connectionStatus": "connected", "lastKnownTip": {"slot": 1000 if healthy else 100}, "lastTipUpdate": datetime.now(timezone.utc).isoformat()}).encode()
        self.send_response(202 if self.path == "/health" else 200)
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass
HTTPServer(("0.0.0.0", 1337), Handler).serve_forever()
'''


def run(command, *, timeout=30, **kwargs):
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"{command[0]} timed out after {timeout}s") from error
    if result.returncode:
        raise RuntimeError(f"{command[0]} failed: {result.stderr}\n{result.stdout}")
    return result.stdout


def wait(check, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(1)
    raise TimeoutError("readiness condition not reached")


def main():
    with tempfile.TemporaryDirectory(prefix=CLUSTER) as tmp:
        config = Path(tmp) / "kubeconfig"
        env = dict(os.environ, KUBECONFIG=str(config))
        try:
            run(["k3d", "cluster", "create", CLUSTER, "--image", "rancher/k3s:v1.31.5-k3s1", "--servers", "1", "--agents", "0", "--k3s-arg", "--disable=traefik@server:0", "--kubeconfig-update-default=false", "--wait"], timeout=240)
            config.write_text(run(["k3d", "kubeconfig", "get", CLUSTER]))
            config.chmod(0o600)

            def kube(*args, **kwargs):
                return run(["kubectl", "--context", "k3d-" + CLUSTER, "-n", "default", *args], env=env, **kwargs)

            def endpoints():
                obj = json.loads(kube("get", "endpoints", "test-ogmios", "-o", "json"))
                return [a["targetRef"]["name"] for subset in obj.get("subsets", []) for a in subset.get("addresses", [])]

            def apply(warmup):
                rendered = run(["helm", "template", "test", str(ROOT / "charts/ogmios"), "--kube-version", "1.31.5", "--set", "replicaCount=2", "--set", "minReadySeconds=3", "--set", "availability.enabled=true", "--set", "availability.drainDelaySeconds=5", "--set", "availability.pollIntervalSeconds=1", "--set", "availability.referenceTipURLs[0]=http://127.0.0.1:1337/metrics", "--set", "service.enabled=true", "--set", "tolerations=null"])
                objects = list(yaml.safe_load_all(rendered))
                deployment = next(o for o in objects if o["kind"] == "Deployment")
                pod = deployment["spec"]["template"]["spec"]
                pod["initContainers"] = []
                containers = pod["containers"]
                # Only application dependencies are replaced; the actual gate and probes are unchanged.
                containers[0]["image"] = containers[2]["image"]
                containers[0]["command"] = ["python3", "-B", "-c", FIXTURE]
                containers[0]["env"].append({"name": "WARMUP", "value": str(warmup)})
                containers[1]["image"] = containers[2]["image"]
                containers[1]["command"] = ["python3", "-c", "import time; time.sleep(3600)"]
                kube("apply", "-f", "-", input=yaml.safe_dump_all(objects))

            apply(0)
            kube("rollout", "status", "deployment/test-ogmios", "--timeout=180s", timeout=195)
            originals = wait(lambda: endpoints() if len(endpoints()) == 2 else None)
            target = originals[0]
            kube("exec", target, "-c", "ogmios", "--", "touch", "/tmp/stale")
            wait(lambda: target not in endpoints())
            status = json.loads(kube("get", "pod", target, "-o", "json"))["status"]["containerStatuses"]
            assert all(c["restartCount"] == 0 for c in status), status
            assert endpoints(), "healthy replica was removed"
            print("PASS: stale HTTP-202 backend withdrawn without container restarts", flush=True)
            kube("exec", target, "-c", "ogmios", "--", "rm", "/tmp/stale")
            wait(lambda: len(endpoints()) == 2)
            print("PASS: backend recovery readmitted automatically", flush=True)
            apply(20)
            observed_warming = False
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                serving = endpoints()
                assert serving, "rollout removed all ready endpoints"
                pods = json.loads(kube("get", "pods", "-l", "app.kubernetes.io/instance=test", "-o", "json"))["items"]
                for pod in pods:
                    name = pod["metadata"]["name"]
                    if name not in originals and any(s["name"] == "availability" and not s["ready"] for s in pod.get("status", {}).get("containerStatuses", [])):
                        assert name not in serving, "warming replacement admitted"
                        observed_warming = True
                if len(serving) == 2 and not any(name in originals for name in serving):
                    break
                time.sleep(1)
            else:
                raise TimeoutError("surge rollout did not complete")
            assert observed_warming, "no unready replacement observed"
            kube("rollout", "status", "deployment/test-ogmios", "--timeout=60s", timeout=75)
            print("PASS: warming replacements withheld while ready replicas remained available", flush=True)
        finally:
            run(["k3d", "cluster", "delete", CLUSTER], timeout=120)


if __name__ == "__main__":
    main()
