"""Pre-built adversarial environment specifications for musil.

Each submodule provides:

- Named ``Assumption`` constants citing the real source (docs, papers, SLAs)
- ``EnvironmentSpec`` factory functions for model checking with ``check_open``
- ``AdversarialNode`` factories for deterministic simulation testing

Usage::

    from musil.environments.k8s import pod_eviction, NODE_CAPACITY
    from musil.environments.aws import aws_api_faults
    from musil.environments.linux import process_faults
    from musil.environments.sel4 import capability_revocation, HARDWARE_MEMORY_SAFETY
    from musil.environments.etcd import cluster_faults
    from musil.environments.storage import block_volume_faults

Import from specific modules, not from this package directly.
"""

from musil.environments import aws, distributed, etcd, k8s, linux, sel4, storage

__all__ = ["aws", "distributed", "etcd", "k8s", "linux", "sel4", "storage"]
