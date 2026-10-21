"""Prove, without a GPU, that the ONNX Runtime CUDA provider's libraries resolve (issue #229).

``onnxruntime-gpu`` is split by CUDA major on PyPI: 1.19-1.26 are CUDA 12 builds and
1.27 onwards are CUDA 13 builds. A CUDA 13 wheel beside a CUDA 12 PyTorch still lists
``CUDAExecutionProvider`` in ``get_available_providers()``, because that lists what the
wheel was compiled with, and only falls back to the CPU when a session is created and the
provider library cannot load its dependencies. A CI runner has no GPU to create that
session, so this script asks the dynamic linker instead: which libraries does
``libonnxruntime_providers_cuda.so`` need, and do they resolve against the CUDA libraries
the image's PyTorch maps?

Run it inside the image, over stdin, so nothing has to be copied into it::

    docker run --rm -i --entrypoint python "$image" - < scripts/check_ort_cuda_link.py

Exit codes:
  0  every library the provider needs resolves (``libcuda.so.1`` excepted, see below)
  1  the provider is missing (a CPU build) or a library does not resolve
  2  the check would be vacuous: PyTorch did not map one of the CUDA library families
  3  ``ldd`` is unavailable or could not read the provider

``libcuda.so.1`` is the driver's library: it is injected by the container runtime and is
absent on a GPU-less runner, so it is not held against the image. The CUDA 12 wheels do not
need it at link time; a CUDA 13 wheel fails on its ``*.so.13`` libraries first.

Limit: ``ldd`` lists direct dependencies only, not the cuDNN sub-libraries ONNX Runtime
``dlopen``s later. Only a real CUDA session proves those (``python facet.py --doctor`` on a GPU).
"""

import importlib.util
import os
import re
import subprocess
import sys

# The CUDA library families the provider is linked against.
FAMILIES = ("libcublasLt", "libcublas", "libcudnn", "libcudart", "libcufft", "libcurand")
PROVIDER = "libonnxruntime_providers_cuda.so"
# The driver's library: not part of the image, so never a finding here.
DRIVER_LIBRARY = "libcuda.so.1"

# libcudnn is mapped as libcudnn.so.9 plus libcudnn_graph.so.9 and friends: all one family.
_FAMILY_RE = re.compile(r"^(libcublasLt|libcublas|libcudnn(?:_[a-z0-9_]+)?|libcudart|libcufft|libcurand)\.so")


def provider_path():
    """Where the CUDA provider library lives, without importing ONNX Runtime; None when absent."""
    spec = importlib.util.find_spec("onnxruntime")
    if spec is None or not spec.origin:
        return None
    path = os.path.join(os.path.dirname(spec.origin), "capi", PROVIDER)
    return path if os.path.isfile(path) else None


def mapped_library_dirs():
    """Directories of the CUDA libraries this process has mapped, keyed by family."""
    found = {}
    with open("/proc/self/maps", encoding="utf-8") as handle:
        for line in handle:
            fields = line.split(None, 5)
            if len(fields) < 6:
                continue
            path = fields[5].strip()
            if path.endswith(" (deleted)"):
                path = path[: -len(" (deleted)")]
            match = _FAMILY_RE.match(os.path.basename(path))
            if not match:
                continue
            family = "libcudnn" if match.group(1).startswith("libcudnn") else match.group(1)
            found.setdefault(family, [])
            directory = os.path.dirname(path)
            if directory not in found[family]:
                found[family].append(directory)
    return found


def unresolved_libraries(provider, directories):
    """Lines of ``ldd`` output reporting a missing library, minus the driver's. None when ldd cannot run."""
    env = dict(os.environ, LD_LIBRARY_PATH=os.pathsep.join(directories))
    try:
        result = subprocess.run(["ldd", provider], env=env, capture_output=True, text=True, check=False)
    except OSError as ex:
        print(f"FAIL: cannot run ldd: {ex}")
        return None
    if result.returncode != 0:
        print(f"FAIL: ldd could not read {provider}: {(result.stderr or result.stdout).strip()}")
        return None
    return [
        line.strip() for line in result.stdout.splitlines()
        if "not found" in line and DRIVER_LIBRARY not in line
    ]


def main():
    # torch first, as Facet does at scan time: importing it maps the CUDA libraries the
    # ONNX Runtime provider then reuses instead of searching for its own copies.
    import torch
    print(f"torch {torch.__version__}, CUDA {torch.version.cuda}")
    provider = provider_path()
    if provider is None:
        print(f"FAIL: onnxruntime has no capi/{PROVIDER}: not installed, or the CPU build. "
              "This image has no ONNX Runtime CUDA provider to check.")
        return 1
    print(f"provider: {provider}")
    mapped = mapped_library_dirs()
    missing = [family for family in FAMILIES if family not in mapped]
    if missing:
        print(f"VACUOUS: this torch did not map {', '.join(missing)}, so the check would pass "
              "without testing them. Extend the script (for example import the missing "
              "backend) before trusting it.")
        return 2
    directories = []
    for family in FAMILIES:
        for directory in mapped[family]:
            if directory not in directories:
                directories.append(directory)
    print("library directories: " + os.pathsep.join(directories))
    unresolved = unresolved_libraries(provider, directories)
    if unresolved is None:
        return 3
    if unresolved:
        print(f"FAIL: {len(unresolved)} librar{'y' if len(unresolved) == 1 else 'ies'} the provider needs do not resolve "
              "(a onnxruntime-gpu 1.27+ wheel is a CUDA 13 build and needs *.so.13 libraries):")
        for line in unresolved:
            print(f"  {line}")
        return 1
    print(f"OK: every library {PROVIDER} needs resolves ({DRIVER_LIBRARY} excepted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
