"""FaceAnalyzer logs one warning when CUDA was selected but InsightFace runs on the CPU (issue #229).

InsightFace silently drops a provider ONNX Runtime cannot offer, so a CPU-only
``onnxruntime`` (the build ``insightface`` pulls in) leaves face detection on the
CPU while Facet believes it selected CUDA. The sessions' own providers are the
signal; insightface, torch and the sessions are faked, so CI needs none of them.
"""

import logging
import platform
import sys
import types

import pytest

from analyzers import face as face_module
from analyzers.face import FaceAnalyzer

CPU_ONLY = ['CPUExecutionProvider']
CUDA_FIRST = ['CUDAExecutionProvider', 'CPUExecutionProvider']
REPAIR_COMMAND = 'pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime-gpu>=1.19.0,<1.27"'


class _FakeModel:
    def __init__(self, providers):
        self.session = types.SimpleNamespace(get_providers=lambda: list(providers))


def _fake_face_analysis(session_providers, accessed):
    """A FaceAnalysis stand-in whose models report ``session_providers``; reads of ``models`` are recorded."""

    class FakeFaceAnalysis:
        def __init__(self, **kwargs):
            pass

        def prepare(self, **kwargs):
            pass

        @property
        def models(self):
            accessed.append('models')
            return {'detection': _FakeModel(session_providers), 'recognition': _FakeModel(session_providers)}

    return FakeFaceAnalysis


class _NoModelsFaceAnalysis:
    """A future InsightFace layout: no ``models`` attribute at all."""

    def __init__(self, **kwargs):
        pass

    def prepare(self, **kwargs):
        pass


def _install_fakes(monkeypatch, face_analysis, torch_cuda='12.6'):
    insightface = types.ModuleType('insightface')
    app = types.ModuleType('insightface.app')
    app.FaceAnalysis = face_analysis
    insightface.app = app
    torch = types.ModuleType('torch')
    torch.version = types.SimpleNamespace(cuda=torch_cuda)
    monkeypatch.setitem(sys.modules, 'insightface', insightface)
    monkeypatch.setitem(sys.modules, 'insightface.app', app)
    monkeypatch.setitem(sys.modules, 'torch', torch)


@pytest.fixture(autouse=True)
def _fresh_process_state(monkeypatch):
    """A new process's warn-once flag, on the platform the pinned repair command targets."""
    monkeypatch.setattr(face_module, '_cpu_session_warned', False)
    monkeypatch.setattr(platform, 'machine', lambda: 'x86_64')


@pytest.fixture
def warnings_logged(caplog):
    caplog.set_level(logging.WARNING, logger='facet.face_analyzer')

    def records():
        return [r for r in caplog.records
                if r.name == 'facet.face_analyzer' and 'running on the CPU' in r.getMessage()]

    return records


class TestCpuSessionWarning:
    def test_cpu_sessions_on_cuda_log_one_warning_with_the_fix(self, monkeypatch, warnings_logged):
        accessed = []
        _install_fakes(monkeypatch, _fake_face_analysis(CPU_ONLY, accessed))
        analyzer = FaceAnalyzer(device='cuda')
        (record,) = warnings_logged()
        assert record.levelno == logging.WARNING
        message = record.getMessage()
        assert REPAIR_COMMAND in message
        assert 'CPUExecutionProvider' in message
        assert 'CUDAExecutionProvider' not in message
        assert 'python facet.py --doctor' in message
        assert analyzer.available is True

    def test_a_second_analyzer_in_the_same_process_does_not_warn_again(self, monkeypatch, warnings_logged):
        _install_fakes(monkeypatch, _fake_face_analysis(CPU_ONLY, []))
        FaceAnalyzer(device='cuda')
        FaceAnalyzer(device='cuda')
        assert len(warnings_logged()) == 1

    def test_a_cpu_build_with_other_providers_listed_still_warns_and_names_them(self, monkeypatch, warnings_logged):
        """The CPU wheel over the GPU one, as seen on an RTX 4070 Ti SUPER: Azure is offered, CUDA is not."""
        _install_fakes(monkeypatch, _fake_face_analysis(['AzureExecutionProvider', 'CPUExecutionProvider'], []))
        FaceAnalyzer(device='cuda')
        (record,) = warnings_logged()
        assert 'AzureExecutionProvider, CPUExecutionProvider' in record.getMessage()

    def test_cuda_sessions_are_quiet(self, monkeypatch, warnings_logged):
        _install_fakes(monkeypatch, _fake_face_analysis(CUDA_FIRST, []))
        analyzer = FaceAnalyzer(device='cuda')
        assert warnings_logged() == []
        assert analyzer.available is True

    def test_cpu_device_never_probes_the_sessions(self, monkeypatch, warnings_logged):
        accessed = []
        _install_fakes(monkeypatch, _fake_face_analysis(CPU_ONLY, accessed))
        analyzer = FaceAnalyzer(device='cpu')
        assert accessed == []
        assert warnings_logged() == []
        assert analyzer.available is True

    def test_an_unreadable_session_layout_neither_warns_nor_fails_the_analyzer(self, monkeypatch, warnings_logged):
        _install_fakes(monkeypatch, _NoModelsFaceAnalysis)
        analyzer = FaceAnalyzer(device='cuda')
        assert warnings_logged() == []
        assert analyzer.available is True

    def test_rocm_torch_explains_instead_of_pinning_a_command(self, monkeypatch, warnings_logged):
        _install_fakes(monkeypatch, _fake_face_analysis(CPU_ONLY, []), torch_cuda=None)
        FaceAnalyzer(device='cuda')
        (record,) = warnings_logged()
        message = record.getMessage()
        assert 'does not apply' in message
        assert 'pip install' not in message

    def test_aarch64_names_the_platform_instead_of_pinning_a_range(self, monkeypatch, warnings_logged):
        monkeypatch.setattr(platform, 'machine', lambda: 'aarch64')
        _install_fakes(monkeypatch, _fake_face_analysis(CPU_ONLY, []))
        FaceAnalyzer(device='cuda')
        (record,) = warnings_logged()
        message = record.getMessage()
        assert 'aarch64' in message
        assert '<1.27' not in message
        assert 'pip install' not in message
