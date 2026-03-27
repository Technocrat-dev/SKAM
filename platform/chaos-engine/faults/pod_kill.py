"""Pod Kill Fault — Deletes a pod matching the target label selector."""

import asyncio
from kubernetes import client


class PodKillFault:
    def __init__(self, core_v1: client.CoreV1Api):
        self.core_v1 = core_v1

    async def inject(self, experiment) -> dict:
        """Kill one or more pods matching the label selector."""
        target = experiment.target
        count = experiment.parameters.get("count", 1)

        # List matching pods
        pods = self.core_v1.list_namespaced_pod(
            namespace=target.namespace,
            label_selector=target.label_selector,
        )

        if not pods.items:
            raise Exception(f"No pods found matching {target.label_selector}")

        killed = []
        for pod in pods.items[:count]:
            pod_name = pod.metadata.name
            print(f"🔪 Killing pod: {pod_name}")
            await asyncio.to_thread(
                self.core_v1.delete_namespaced_pod,
                name=pod_name,
                namespace=target.namespace,
                grace_period_seconds=0,
            )
            killed.append(pod_name)

        return {"killed_pods": killed, "deployment": target.label_selector}

    async def rollback(self, experiment) -> None:
        """K8s Deployment controller auto-recreates killed pods. No manual rollback needed."""
        print(f"✅ Pod kill rollback: K8s auto-recreates pods for {experiment.target.label_selector}")
