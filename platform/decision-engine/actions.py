"""
Action executor — implements the actual K8s recovery actions
that the decision engine triggers based on matched policies.
"""

import asyncio
import logging
from kubernetes import client, config

logger = logging.getLogger("actions")


class ActionExecutor:
    """Executes recovery actions against the K8s cluster."""

    def __init__(self):
        self._initialized = False
        self.core_v1 = None
        self.apps_v1 = None

    def _ensure_init(self):
        """Lazy-init K8s clients on first use."""
        if self._initialized:
            return
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        self._initialized = True

    async def execute(self, service: str, policy: dict, session=None):
        """Route to the appropriate action handler."""
        self._ensure_init()
        action = policy["action"]
        handlers = {
            "restart_pods": self._restart_pods,
            "scale_up": self._scale_up,
            "rolling_restart": self._rolling_restart,
            "increase_memory": self._increase_memory,
        }

        handler = handlers.get(action)
        if not handler:
            raise ValueError(f"Unknown action: {action}")

        logger.info(f"🔧 Executing action '{action}' for {service}")
        await handler(service)

    async def _restart_pods(self, service: str):
        """Delete all pods for a service (deployment will recreate them)."""
        pods = await asyncio.to_thread(
            self.core_v1.list_namespaced_pod,
            namespace="default",
            label_selector=f"app={service}",
        )

        for pod in pods.items:
            logger.info(f"  🔄 Deleting pod: {pod.metadata.name}")
            await asyncio.to_thread(
                self.core_v1.delete_namespaced_pod,
                name=pod.metadata.name,
                namespace="default",
                grace_period_seconds=10,
            )

    async def _scale_up(self, service: str):
        """Scale up the deployment by 1 replica (up to max 5)."""
        deploy = await asyncio.to_thread(
            self.apps_v1.read_namespaced_deployment,
            name=service,
            namespace="default",
        )

        current_replicas = deploy.spec.replicas or 1
        new_replicas = min(current_replicas + 1, 5)

        if new_replicas == current_replicas:
            logger.info(f"  📊 {service} already at max replicas ({current_replicas})")
            return

        patch = {"spec": {"replicas": new_replicas}}
        await asyncio.to_thread(
            self.apps_v1.patch_namespaced_deployment,
            name=service,
            namespace="default",
            body=patch,
        )
        logger.info(f"  📈 Scaled {service}: {current_replicas} → {new_replicas} replicas")

    async def _rolling_restart(self, service: str):
        """Trigger a rolling restart by patching the deployment annotation."""
        from datetime import datetime, timezone

        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()
                        }
                    }
                }
            }
        }
        await asyncio.to_thread(
            self.apps_v1.patch_namespaced_deployment,
            name=service,
            namespace="default",
            body=patch,
        )
        logger.info(f"  🔄 Rolling restart triggered for {service}")

    async def _increase_memory(self, service: str):
        """Increase container memory limit by 50%."""
        deploy = await asyncio.to_thread(
            self.apps_v1.read_namespaced_deployment,
            name=service,
            namespace="default",
        )

        container = deploy.spec.template.spec.containers[0]
        current_limit = container.resources.limits.get("memory", "128Mi") if container.resources and container.resources.limits else "128Mi"

        # Parse current limit and increase by 50%
        value = int("".join(filter(str.isdigit, current_limit)))
        unit = "".join(filter(str.isalpha, current_limit))
        new_value = min(int(value * 1.5), 1024)  # Cap at 1Gi

        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": container.name,
                                "resources": {
                                    "limits": {"memory": f"{new_value}{unit}"},
                                },
                            }
                        ]
                    }
                }
            }
        }
        await asyncio.to_thread(
            self.apps_v1.patch_namespaced_deployment,
            name=service,
            namespace="default",
            body=patch,
        )
        logger.info(f"  💾 Increased {service} memory: {current_limit} → {new_value}{unit}")
