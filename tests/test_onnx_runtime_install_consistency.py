"""install.sh and the Dockerfile must install the onnxruntime-gpu that utils.onnx_runtime says (issue #229).

The helper owns the CUDA-major to requirement mapping; install.sh and the
Dockerfile carry their own copies because neither can import Python at the point
it installs. These tests read both files as text so the copies cannot drift apart
from the helper silently, and pin the one ordering that matters in install.sh:
the GPU swap runs after everything that pulls the CPU ``onnxruntime`` back in.
"""

import pathlib
import re

import pytest
from packaging.requirements import Requirement

from utils.onnx_runtime import gpu_requirement

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _text(name):
    return (ROOT / name).read_text(encoding="utf-8")


class TestInstallShConstants:
    def test_cuda_12_constant_is_the_helper_range(self):
        match = re.search(r'^ORT_GPU_CUDA12="([^"]+)"', _text("install.sh"), re.MULTILINE)
        assert match, "install.sh no longer defines ORT_GPU_CUDA12"
        assert match.group(1) == gpu_requirement("12.8")

    def test_cuda_11_branch_is_the_helper_range(self):
        assert f'ONNX_PACKAGE="{gpu_requirement("11.8")}"' in _text("install.sh")

    def test_every_package_assignment_is_a_known_requirement(self):
        """A stale ``onnxruntime-gpu>=1.17.0`` resolves to a CUDA 13 build today."""
        allowed = {"$ORT_GPU_CUDA12", gpu_requirement("11.8"), "onnxruntime>=1.15.0"}
        assigned = re.findall(r'^\s*ONNX_PACKAGE="([^"]*)"', _text("install.sh"), re.MULTILINE)
        assert assigned, "install.sh no longer assigns ONNX_PACKAGE"
        assert set(assigned) <= allowed
        assert "onnxruntime-gpu>=1.17.0" not in _text("install.sh")


class TestInstallShRepairText:
    def test_the_verify_step_takes_its_fix_text_from_the_helper(self):
        text = _text("install.sh")
        assert re.search(r"from utils\.onnx_runtime import[^\n]*\brepair_hint\b", text)
        assert 'pip install "onnxruntime-gpu' not in text


class TestInstallShOrder:
    def test_the_swap_runs_after_every_install_that_pulls_the_cpu_build(self):
        """insightface (``requirements.restricted.txt``) requires plain onnxruntime and overwrites the GPU one."""
        text = _text("install.sh")
        swap = text.index("$UNINSTALLER onnxruntime onnxruntime-gpu")
        assert text.index("requirements.restricted.txt") < swap
        assert text.index('"transformers>=') < swap
        assert swap < text.index("Verify imports")


class TestDockerfile:
    @pytest.mark.parametrize("torch_cuda", ["12.8", "12.6"])
    def test_pinned_version_satisfies_the_helper_range_of_both_cuda_bases(self, torch_cuda):
        match = re.search(r"^ARG ORT_GPU_VERSION=(\S+)", _text("Dockerfile"), re.MULTILINE)
        assert match, "Dockerfile no longer declares ARG ORT_GPU_VERSION"
        assert Requirement(gpu_requirement(torch_cuda)).specifier.contains(match.group(1))
