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
    cuda_major,
    gpu_requirement,
    installed_distributions,
    repair_command,
    repair_hint,
)

CUDA12 = "onnxruntime-gpu>=1.19.0,<1.27"
CUDA13 = "onnxruntime-gpu>=1.27.0"


class TestCudaMajor:
    @pytest.mark.parametrize("version, major", [("12.6", 12), ("13.0", 13), ("11.8", 11), ("13", 13), (12.4, 12)])
    def test_reads_the_leading_component(self, version, major):
        assert cuda_major(version) == major

    @pytest.mark.parametrize("version", [None, "", "unknown", "x.1"])
    def test_absent_or_unparsable_is_none(self, version):
        assert cuda_major(version) is None


class TestGpuRequirement:
    @pytest.mark.parametrize("torch_cuda", ["11.8", "11.7", "10.2"])
    def test_cuda_11_and_older_have_no_gpu_wheel(self, torch_cuda):
        """The only CUDA 11 onnxruntime-gpu needs cuDNN 8; the cu118 PyTorch wheels ship cuDNN 9."""
        assert gpu_requirement(torch_cuda) is None

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
        ("13.0", "aarch64"),
        (None, "x86_64"),
        ("", "x86_64"),
    ])
    def test_no_command_when_no_gpu_wheel_applies(self, torch_cuda, machine):
        assert repair_command(torch_cuda, machine) is None

    @pytest.mark.parametrize("machine", ["x86_64", "aarch64"])
    def test_cuda_11_repairs_towards_the_cpu_build(self, machine):
        assert repair_command("11.8", machine) == CPU_REPAIR_COMMAND

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

    def test_aarch64_with_cuda_12_says_its_gpu_wheels_are_cuda_13_builds(self):
        hint = repair_hint("12.6", "aarch64")
        assert "no onnxruntime-gpu wheel built for CUDA 12 exists for aarch64" in hint
        assert "1.29" in hint
        assert "CUDA 13" in hint

    def test_aarch64_with_cuda_13_does_not_claim_that_no_wheel_exists(self):
        """CUDA 13 aarch64 wheels exist from 1.29; Facet just does not install or validate them."""
        hint = repair_hint("13.0", "aarch64")
        assert "no onnxruntime-gpu wheel built for CUDA" not in hint
        assert "1.29" in hint
        assert "aarch64" in hint
        assert "pip install" not in hint

    def test_another_architecture_names_the_cuda_build_and_the_machine(self):
        assert "CUDA 12 exists for ppc64le" in repair_hint("12.6", "ppc64le")

    @pytest.mark.parametrize("machine", ["x86_64", "aarch64"])
    def test_cuda_11_says_why_no_gpu_build_applies_and_gives_the_cpu_repair(self, machine):
        hint = repair_hint("11.8", machine)
        assert "CUDA 11.8" in hint
        assert "cuDNN 9" in hint
        assert "cuDNN 8" in hint
        assert CPU_REPAIR_COMMAND in hint
        assert "CUDA 12.4" in hint
        assert "onnxruntime-gpu>=" not in hint
        assert not hint.startswith("Fix:")

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
