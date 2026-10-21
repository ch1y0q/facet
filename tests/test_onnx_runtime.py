"""utils.onnx_runtime: which onnxruntime-gpu a CUDA PyTorch needs, and the command that installs it (issue #229).

The helper imports neither torch, onnx nor onnxruntime, so none of them is faked
here. How install.sh and the Dockerfile stay tied to these constants is covered
in test_onnx_runtime_install_consistency.py.
"""

import importlib.metadata

import pytest

from utils import onnx_runtime
from utils.onnx_runtime import (
    CPU_REPAIR_COMMAND,
    gpu_requirement,
    installed_distributions,
    repair_command,
    repair_hint,
)

CUDA11 = "onnxruntime-gpu>=1.15.0,<1.18"
CUDA12 = "onnxruntime-gpu>=1.19.0,<1.27"
CUDA13 = "onnxruntime-gpu>=1.27.0"


class TestGpuRequirement:
    def test_cuda_11_gets_the_cudnn_8_line(self):
        assert gpu_requirement("11.8") == CUDA11

    @pytest.mark.parametrize("torch_cuda", ["12.4", "12.6", "12.8"])
    def test_every_cuda_12_build_gets_the_same_range(self, torch_cuda):
        assert gpu_requirement(torch_cuda) == CUDA12

    def test_cuda_13_gets_the_open_ended_range(self):
        assert gpu_requirement("13.0") == CUDA13

    @pytest.mark.parametrize("torch_cuda", [None, ""])
    def test_a_build_without_a_cuda_version_has_no_requirement(self, torch_cuda):
        """ROCm torch reports the cuda device with ``torch.version.cuda is None``."""
        assert gpu_requirement(torch_cuda) is None

    def test_an_unparsable_version_does_not_raise(self):
        assert gpu_requirement("unknown") is None


class TestRepairCommand:
    @pytest.mark.parametrize("machine", ["x86_64", "AMD64"])
    def test_installs_the_quoted_cuda_12_range_after_removing_both_distributions(self, machine):
        command = repair_command("12.8", machine)
        assert command.startswith("pip uninstall -y onnxruntime onnxruntime-gpu && ")
        assert command.endswith(f'pip install "{CUDA12}"')

    @pytest.mark.parametrize("torch_cuda, machine", [
        ("12.8", "aarch64"),
        (None, "x86_64"),
        ("", "x86_64"),
    ])
    def test_no_command_when_no_gpu_wheel_applies(self, torch_cuda, machine):
        assert repair_command(torch_cuda, machine) is None

    def test_the_machine_defaults_to_the_running_one(self, monkeypatch):
        monkeypatch.setattr(onnx_runtime.platform, "machine", lambda: "aarch64")
        assert repair_command("12.8") is None
        monkeypatch.setattr(onnx_runtime.platform, "machine", lambda: "x86_64")
        assert repair_command("12.8") is not None


class TestRepairHint:
    def test_leads_with_the_command_when_one_applies(self):
        hint = repair_hint("12.8", "x86_64")
        assert hint.startswith("Fix:")
        assert repair_command("12.8", "x86_64") in hint

    def test_off_x86_names_the_machine_and_pins_nothing(self):
        hint = repair_hint("12.8", "aarch64")
        assert "aarch64" in hint
        assert "<1.27" not in hint
        assert "pip install" not in hint

    @pytest.mark.parametrize("torch_cuda", [None, ""])
    def test_without_a_cuda_version_says_it_does_not_apply(self, torch_cuda):
        hint = repair_hint(torch_cuda, "x86_64")
        assert "does not apply" in hint
        assert "pip install" not in hint


class TestInstalledDistributions:
    @staticmethod
    def _install(monkeypatch, *names):
        def version(name):
            if name in names:
                return "1.0"
            raise importlib.metadata.PackageNotFoundError(name)

        monkeypatch.setattr(importlib.metadata, "version", version)

    def test_neither(self, monkeypatch):
        self._install(monkeypatch)
        assert installed_distributions() == []

    def test_only_the_cpu_build(self, monkeypatch):
        self._install(monkeypatch, "onnxruntime")
        assert installed_distributions() == ["onnxruntime"]

    def test_only_the_gpu_build(self, monkeypatch):
        self._install(monkeypatch, "onnxruntime-gpu")
        assert installed_distributions() == ["onnxruntime-gpu"]

    def test_both_lists_the_cpu_build_first(self, monkeypatch):
        self._install(monkeypatch, "onnxruntime-gpu", "onnxruntime")
        assert installed_distributions() == ["onnxruntime", "onnxruntime-gpu"]


def test_cpu_repair_command_removes_both_distributions_before_installing_the_cpu_build():
    assert CPU_REPAIR_COMMAND.startswith("pip uninstall -y onnxruntime onnxruntime-gpu && ")
    assert CPU_REPAIR_COMMAND.endswith('pip install "onnxruntime>=1.15.0"')
