"""Which ONNX Runtime build a CUDA PyTorch needs, and the command that installs it (issue #229).

``onnxruntime`` and ``onnxruntime-gpu`` install into the same ``onnxruntime/``
tree, so whichever pip installs last wins, and ``insightface`` hard-requires the
CPU one. On top of that ``onnxruntime-gpu`` is split by CUDA major on PyPI: the
1.19-1.26 wheels are CUDA 12 builds and 1.27 onwards are CUDA 13 builds, which
cannot load beside the CUDA 12 PyTorch that Facet installs. The ONNX Runtime
major has to follow the PyTorch CUDA build, never the driver's CUDA version.

This module owns that mapping and the repair text so the doctor, the scan
warning, ``install.sh``'s verify step and the consistency tests share one copy.
It imports neither torch, onnx nor onnxruntime: the doctor and the scan warning
must be able to describe a broken ONNX Runtime without importing it.
"""

import importlib.metadata
import platform

ORT_DISTRIBUTIONS = ("onnxruntime", "onnxruntime-gpu")

# Machines that have a CUDA 12 onnxruntime-gpu wheel. The aarch64 GPU wheels exist
# only for 1.29 and later, which are CUDA 13 builds.
GPU_WHEEL_MACHINES = frozenset({"x86_64", "amd64"})

GPU_REQUIREMENT_CUDA11 = "onnxruntime-gpu>=1.15.0,<1.18"
GPU_REQUIREMENT_CUDA12 = "onnxruntime-gpu>=1.19.0,<1.27"
GPU_REQUIREMENT_CUDA13 = "onnxruntime-gpu>=1.27.0"

CPU_REPAIR_COMMAND = 'pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime>=1.15.0"'


def installed_distributions():
    """Names of the ONNX Runtime distributions pip has installed, CPU build first."""
    found = []
    for name in ORT_DISTRIBUTIONS:
        try:
            importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        found.append(name)
    return found


def gpu_requirement(torch_cuda):
    """The ``onnxruntime-gpu`` requirement for a PyTorch CUDA version, or None.

    ``torch_cuda`` is ``torch.version.cuda``: None on a CPU build and on ROCm,
    whose torch still reports the ``cuda`` device but carries no CUDA version.
    """
    if not torch_cuda:
        return None
    try:
        major = int(str(torch_cuda).split(".")[0])
    except ValueError:
        return None
    if major < 12:
        return GPU_REQUIREMENT_CUDA11
    if major == 12:
        return GPU_REQUIREMENT_CUDA12
    return GPU_REQUIREMENT_CUDA13


def _machine(machine):
    return (machine or platform.machine()).lower()


def repair_command(torch_cuda, machine=None):
    """Shell command that leaves exactly the matching ``onnxruntime-gpu``, or None.

    None when no GPU wheel applies: no CUDA version on the PyTorch build, or a
    machine with no CUDA 12 wheel. Uninstalling both names first is what makes
    the swap safe, because the two distributions own the same shared libraries.
    """
    requirement = gpu_requirement(torch_cuda)
    if requirement is None or _machine(machine) not in GPU_WHEEL_MACHINES:
        return None
    return f'pip uninstall -y onnxruntime onnxruntime-gpu && pip install "{requirement}"'


def repair_hint(torch_cuda, machine=None):
    """One sentence for the doctor and the scan warning: the fix, or why none applies."""
    command = repair_command(torch_cuda, machine)
    if command is not None:
        return f"Fix: {command}"
    if not gpu_requirement(torch_cuda):
        return "ONNX Runtime CUDA does not apply: this PyTorch build reports no CUDA version (CPU or ROCm)"
    return (f"no onnxruntime-gpu wheel built for CUDA 12 exists for {_machine(machine)}; "
            "InsightFace stays on the CPU here")
