"""Latency Injection Fault — Uses tc netem via pod exec to add network delay."""

import asyncio
from kubernetes import client
from kubernetes.stream import stream


class LatencyInjectionFault:
    def __init__(self, core_v1: client.CoreV1Api):
        self.core_v1 = core_v1

    async def inject(self, experiment) -> dict:
        """Add network latency to target pods using tc netem."""
        target = experiment.target
        delay_ms = experiment.parameters.get("delay_ms", 500)
        jitter_ms = experiment.parameters.get("jitter_ms", 100)

        # List matching pods
        pods = await asyncio.to_thread(
            self.core_v1.list_namespaced_pod,
            namespace=target.namespace,
            label_selector=target.label_selector,
        )

        if not pods.items:
            raise Exception(f"No pods found matching {target.label_selector}")

        affected_pods = []
        for pod in pods.items:
            pod_name = pod.metadata.name
            cmd = [
                "sh", "-c",
                f"tc qdisc add dev eth0 root netem delay {delay_ms}ms {jitter_ms}ms distribution normal || "
                f"tc qdisc change dev eth0 root netem delay {delay_ms}ms {jitter_ms}ms distribution normal"
            ]

            print(f"🐌 Injecting {delay_ms}ms latency (±{jitter_ms}ms) into pod: {pod_name}")
            try:
                await asyncio.to_thread(
                    stream,
                    self.core_v1.connect_get_namespaced_pod_exec,
                    pod_name,
                    target.namespace,
                    command=cmd,
                    stderr=True,
                    stdout=True,
                    stdin=False,
                    tty=False,
                )
                affected_pods.append(pod_name)
            except Exception as e:
                print(f"⚠️ Failed to inject latency into {pod_name}: {e}")

        return {
            "affected_pods": affected_pods,
            "delay_ms": delay_ms,
            "jitter_ms": jitter_ms,
        }

    async def rollback(self, experiment) -> None:
        """Remove the tc netem qdisc from affected pods."""
        state = experiment.rollback_state
        affected_pods = state.get("affected_pods", [])

        for pod_name in affected_pods:
            cmd = ["sh", "-c", "tc qdisc del dev eth0 root netem 2>/dev/null || true"]
            print(f"✅ Removing latency from pod: {pod_name}")
            try:
                await asyncio.to_thread(
                    stream,
                    self.core_v1.connect_get_namespaced_pod_exec,
                    pod_name,
                    experiment.target.namespace,
                    command=cmd,
                    stderr=True,
                    stdout=True,
                    stdin=False,
                    tty=False,
                )
            except Exception as e:
                print(f"⚠️ Failed to remove latency from {pod_name}: {e}")
