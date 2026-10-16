#!/usr/bin/env python3
"""Check the probe against the default image's disposable private devnet."""
import pathlib
import subprocess
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAME = "cardano-readiness-" + uuid.uuid4().hex[:8]
IMAGE = "ghcr.io/blinklabs-io/cardano-node:11.1.3-1"


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=35)


def main():
    try:
        result = docker("run", "-d", "--name", NAME, "--network", "none", "--cpus", "2", "--memory", "2g", "--entrypoint", "/bin/sh", "-v", str(ROOT / "scripts/fixtures/cardano-readiness") + ":/fixture:ro", "-v", str(ROOT / "charts/cardano-node/files") + ":/health:ro", "-e", "CARDANO_NETWORK=devnet", "-e", "CARDANO_CONFIG=/opt/cardano/config/devnet/config.json", "-e", "CARDANO_NODE_SOCKET_PATH=/ipc/node.socket", "-e", "READINESS_MAX_TIP_AGE_SECONDS=600", "-e", "READINESS_CLI_TIMEOUT_SECONDS=5", IMAGE, "/fixture/devnet.sh")
        assert result.returncode == 0, result.stderr
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            result = docker("exec", NAME, "/bin/sh", "/health/readiness.sh")
            if result.returncode == 0:
                break
            if docker("inspect", "--format", "{{.State.Running}}", NAME).stdout.strip() != "true":
                raise RuntimeError("devnet exited: " + docker("logs", NAME).stdout[-4000:] + docker("logs", NAME).stderr[-4000:])
            time.sleep(2)
        else:
            raise RuntimeError("devnet readiness failed: " + result.stderr)
        unavailable = docker("exec", "-e", "CARDANO_NODE_SOCKET_PATH=/ipc/missing.socket", NAME, "/bin/sh", "/health/readiness.sh")
        assert unavailable.returncode != 0, "missing local-state socket admitted"
        print("PASS: real devnet local-state query and era-history freshness; missing socket rejected")
    finally:
        docker("rm", "-f", NAME)


if __name__ == "__main__":
    main()
