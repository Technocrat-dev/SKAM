"""CPU Stress Fault — Creates a stress-ng Job targeting the node."""

import asyncio
from kubernetes import client


class CpuStressFault:
    def __init__(self, core_v1: client.CoreV1Api, batch_v1: client.BatchV1Api):
        self.core_v1 = core_v1
        self.batch_v1 = batch_v1

    async def inject(self, experiment) -> dict:
        """Deploy a stress-ng Job that consumes CPU."""
        target = experiment.target
        cpu_cores = experiment.parameters.get("cpu_cores", 2)
        duration = experiment.parameters.get("duration", experiment.duration_seconds)
        job_name = f"chaos-cpu-{experiment.id}"

        job = client.V1Job(
            metadata=client.V1ObjectMeta(
                name=job_name,
                namespace=target.namespace,
                labels={"chaos-experiment": experiment.id},
            ),
            spec=client.V1JobSpec(
                ttl_seconds_after_finished=60,
                backoff_limit=0,
                template=client.V1PodTemplateSpec(
                    spec=client.V1PodSpec(
                        restart_policy="Never",
                        containers=[
                            client.V1Container(
                                name="stress",
                                image="alexeiled/stress-ng:latest",
                                command=["stress-ng"],
                                args=[
                                    "--cpu", str(cpu_cores),
                                    "--timeout", f"{duration}s",
                                    "--metrics-brief",
                                ],
                                resources=client.V1ResourceRequirements(
                                    requests={"cpu": f"{cpu_cores * 500}m"},
                                    limits={"cpu": f"{cpu_cores}"},
                                ),
                            )
                        ],
                    )
                ),
            ),
        )

        print(f"🔥 Creating CPU stress Job: {job_name} ({cpu_cores} cores, {duration}s)")
        await asyncio.to_thread(
            self.batch_v1.create_namespaced_job,
            namespace=target.namespace,
            body=job,
        )

        return {"job_name": job_name, "cpu_cores": cpu_cores, "duration": duration}

    async def rollback(self, experiment) -> None:
        """Delete the stress Job."""
        state = experiment.rollback_state
        job_name = state["job_name"]

        print(f"✅ Deleting CPU stress Job: {job_name}")
        try:
            await asyncio.to_thread(
                self.batch_v1.delete_namespaced_job,
                name=job_name,
                namespace=experiment.target.namespace,
                propagation_policy="Background",
            )
        except client.ApiException as e:
            if e.status != 404:
                raise
