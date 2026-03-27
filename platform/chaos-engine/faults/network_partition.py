"""Network Partition Fault — Creates a deny-all NetworkPolicy for the target."""

import asyncio
from kubernetes import client


class NetworkPartitionFault:
    def __init__(self, networking_v1: client.NetworkingV1Api):
        self.networking_v1 = networking_v1

    async def inject(self, experiment) -> dict:
        """Create a NetworkPolicy that blocks all ingress to the target pods."""
        target = experiment.target
        deploy_name = target.label_selector.split("=")[-1]
        policy_name = f"chaos-netpart-{experiment.id}"

        # Parse label selector into match_labels dict
        label_key, label_value = target.label_selector.split("=", 1)

        policy = client.V1NetworkPolicy(
            metadata=client.V1ObjectMeta(
                name=policy_name,
                namespace=target.namespace,
                labels={"chaos-experiment": experiment.id},
            ),
            spec=client.V1NetworkPolicySpec(
                pod_selector=client.V1LabelSelector(
                    match_labels={label_key: label_value}
                ),
                policy_types=["Ingress"],
                ingress=[],  # Empty = deny all ingress
            ),
        )

        print(f"🔒 Creating deny-all NetworkPolicy: {policy_name} for {deploy_name}")
        await asyncio.to_thread(
            self.networking_v1.create_namespaced_network_policy,
            namespace=target.namespace,
            body=policy,
        )

        return {"policy_name": policy_name, "target_service": deploy_name}

    async def rollback(self, experiment) -> None:
        """Delete the chaos NetworkPolicy, restoring network access."""
        state = experiment.rollback_state
        policy_name = state["policy_name"]

        print(f"✅ Deleting NetworkPolicy: {policy_name}")
        try:
            await asyncio.to_thread(
                self.networking_v1.delete_namespaced_network_policy,
                name=policy_name,
                namespace=experiment.target.namespace,
            )
        except client.ApiException as e:
            if e.status != 404:
                raise
