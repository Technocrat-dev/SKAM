"""Pod CrashLoop Fault — Patches deployment to an invalid image."""

import asyncio
from kubernetes import client


class PodCrashLoopFault:
    def __init__(self, core_v1: client.CoreV1Api, apps_v1: client.AppsV1Api):
        self.core_v1 = core_v1
        self.apps_v1 = apps_v1

    async def inject(self, experiment) -> dict:
        """Patch the deployment's container image to an invalid one."""
        target = experiment.target
        invalid_image = experiment.parameters.get("image", "invalid:latest")

        # Extract deployment name from label selector (e.g., "app=order-service" → "order-service")
        deploy_name = target.label_selector.split("=")[-1]

        # Get current deployment to save original image
        deploy = await asyncio.to_thread(
            self.apps_v1.read_namespaced_deployment,
            name=deploy_name,
            namespace=target.namespace,
        )
        original_image = deploy.spec.template.spec.containers[0].image

        # Patch to invalid image
        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{"name": deploy_name, "image": invalid_image}]
                    }
                }
            }
        }
        print(f"💥 Patching {deploy_name} image to '{invalid_image}' (was '{original_image}')")
        await asyncio.to_thread(
            self.apps_v1.patch_namespaced_deployment,
            name=deploy_name,
            namespace=target.namespace,
            body=patch,
        )

        return {
            "deployment": deploy_name,
            "original_image": original_image,
            "invalid_image": invalid_image,
        }

    async def rollback(self, experiment) -> None:
        """Restore the original container image."""
        state = experiment.rollback_state
        deploy_name = state["deployment"]
        original_image = state["original_image"]

        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{"name": deploy_name, "image": original_image}]
                    }
                }
            }
        }
        print(f"✅ Restoring {deploy_name} image to '{original_image}'")
        await asyncio.to_thread(
            self.apps_v1.patch_namespaced_deployment,
            name=deploy_name,
            namespace=experiment.target.namespace,
            body=patch,
        )
