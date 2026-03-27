"""Memory Pressure Fault — Patches deployment memory limits to trigger OOMKill."""

import asyncio
from kubernetes import client


class MemoryPressureFault:
    def __init__(self, core_v1: client.CoreV1Api, apps_v1: client.AppsV1Api):
        self.core_v1 = core_v1
        self.apps_v1 = apps_v1

    async def inject(self, experiment) -> dict:
        """Reduce container memory limit to trigger OOMKill."""
        target = experiment.target
        limit_mi = experiment.parameters.get("limit_mi", 64)
        deploy_name = target.label_selector.split("=")[-1]

        # Get current deployment to save original limits
        deploy = await asyncio.to_thread(
            self.apps_v1.read_namespaced_deployment,
            name=deploy_name,
            namespace=target.namespace,
        )

        container = deploy.spec.template.spec.containers[0]
        container_name = container.name
        original_limits = {}
        if container.resources and container.resources.limits:
            original_limits = dict(container.resources.limits)

        original_requests = {}
        if container.resources and container.resources.requests:
            original_requests = dict(container.resources.requests)

        # Patch to low memory limit
        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": container_name,
                                "resources": {
                                    "limits": {"memory": f"{limit_mi}Mi"},
                                    "requests": {"memory": f"{limit_mi}Mi"},
                                },
                            }
                        ]
                    }
                }
            }
        }

        print(f"💣 Patching {deploy_name} memory limit to {limit_mi}Mi (was {original_limits.get('memory', 'unset')})")
        await asyncio.to_thread(
            self.apps_v1.patch_namespaced_deployment,
            name=deploy_name,
            namespace=target.namespace,
            body=patch,
        )

        return {
            "deployment": deploy_name,
            "container_name": container_name,
            "original_limits": original_limits,
            "original_requests": original_requests,
            "injected_limit_mi": limit_mi,
        }

    async def rollback(self, experiment) -> None:
        """Restore original memory limits."""
        state = experiment.rollback_state
        deploy_name = state["deployment"]
        container_name = state.get("container_name", deploy_name)
        original_limits = state.get("original_limits", {"memory": "128Mi", "cpu": "250m"})
        original_requests = state.get("original_requests", {"memory": "64Mi", "cpu": "100m"})

        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": container_name,
                                "resources": {
                                    "limits": original_limits,
                                    "requests": original_requests,
                                },
                            }
                        ]
                    }
                }
            }
        }

        print(f"✅ Restoring {deploy_name} memory to {original_limits.get('memory', 'default')}")
        await asyncio.to_thread(
            self.apps_v1.patch_namespaced_deployment,
            name=deploy_name,
            namespace=experiment.target.namespace,
            body=patch,
        )
