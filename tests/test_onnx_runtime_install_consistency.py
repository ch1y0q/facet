"""install.sh and the Dockerfile must install the onnxruntime-gpu that utils.onnx_runtime says (issue #229).

The helper owns the CUDA-major to requirement mapping; install.sh and the
Dockerfile carry their own copies because neither can import Python at the point
it installs. These tests read both files as text so the copies cannot drift apart
from the helper silently, pin the one ordering that matters in install.sh (the
ONNX Runtime swap runs after everything that pulls the CPU ``onnxruntime`` back
in, and the OpenCV swap after everything that pulls ``opencv-python`` back in),
and run install.sh against stand-in ``uv``, ``pip``, ``nvidia-smi``,
``uname`` and ``python`` to check which packages each path installs.
"""

import os
import pathlib
import re
import stat
import subprocess
import sys

import pytest
from packaging.requirements import Requirement

import diagnostics
from utils.onnx_runtime import CPU_REPAIR_COMMAND, gpu_requirement

ROOT = pathlib.Path(__file__).resolve().parent.parent

CUDA12_RANGE = "onnxruntime-gpu>=1.19.0,<1.27"
CPU_ORT = "onnxruntime>=1.15.0"


def _text(name):
    return (ROOT / name).read_text(encoding="utf-8")


def _code(name):
    """The file without its comment lines: an anchor must be found in a command, not in prose about it."""
    return "\n".join(line for line in _text(name).splitlines() if not line.lstrip().startswith("#"))


def _position(code, anchor):
    """Where ``anchor`` sits in ``code``, asserting it is there exactly once."""
    assert code.count(anchor) == 1, f"{anchor!r} occurs {code.count(anchor)} times outside comments"
    return code.index(anchor)


class TestInstallShConstants:
    def test_cuda_12_constant_is_the_helper_range(self):
        match = re.search(r'^ORT_GPU_CUDA12="([^"]+)"', _text("install.sh"), re.MULTILINE)
        assert match, "install.sh no longer defines ORT_GPU_CUDA12"
        assert match.group(1) == gpu_requirement("12.8") == CUDA12_RANGE

    def test_cuda_11_has_no_gpu_build_so_the_cu118_branch_installs_the_cpu_one(self):
        """cu118 PyTorch depends on cuDNN 9; the only CUDA 11 onnxruntime-gpu links cuDNN 8."""
        assert gpu_requirement("11.8") is None
        code = _code("install.sh")
        start = code.index('whl/cu118"')
        branch = code[start:code.index("\n    else", start)]
        assert "ONNX_PACKAGE=" not in branch
        assert "No onnxruntime-gpu build matches" in branch

    def test_the_cpu_default_is_the_requirement_the_helpers_cpu_repair_installs(self):
        assert re.search(rf'^ONNX_PACKAGE="{re.escape(CPU_ORT)}"', _text("install.sh"), re.MULTILINE)
        assert CPU_REPAIR_COMMAND.endswith(f'pip install "{CPU_ORT}"')

    def test_every_package_assignment_is_a_known_requirement(self):
        """A stale ``onnxruntime-gpu>=1.17.0`` resolves to a CUDA 13 build today."""
        allowed = {"$ORT_GPU_CUDA12", CPU_ORT}
        assigned = re.findall(r'^\s*ONNX_PACKAGE="([^"]*)"', _text("install.sh"), re.MULTILINE)
        assert assigned, "install.sh no longer assigns ONNX_PACKAGE"
        assert set(assigned) <= allowed
        assert "onnxruntime-gpu>=1.17.0" not in _text("install.sh")
        assert "<1.18" not in _text("install.sh")


class TestInstallShVerify:
    def test_the_final_check_is_the_doctors_session_probe_not_a_provider_listing(self):
        """A CUDA 13 wheel and a cuDNN mismatch list the provider, then fall back when a session is built."""
        code = _code("install.sh")
        assert "from diagnostics import verify_onnx_runtime" in code
        assert "get_available_providers" not in code
        assert callable(diagnostics.verify_onnx_runtime)

    def test_the_fix_text_comes_from_the_helper_not_from_install_sh(self):
        assert 'pip install "onnxruntime-gpu' not in _text("install.sh")

    def test_the_exit_codes_install_sh_reads_are_the_ones_diagnostics_returns(self):
        code = _code("install.sh")
        ok_labels = re.search(r"^\s+(\d(?:\|\d)*)\) report_lines ok ", code, re.MULTILINE)
        err_label = re.search(r"^\s+(\d)\) report_lines err ", code, re.MULTILINE)
        could_not_run = re.search(r"print\([^\n]*\)\n\s+sys\.exit\((\d)\)", code)
        assert ok_labels and err_label and could_not_run
        assert set(ok_labels.group(1).split("|")) == {str(diagnostics.VERIFY_ON_CUDA),
                                                      str(diagnostics.VERIFY_LISTED_ONLY)}
        assert err_label.group(1) == str(diagnostics.VERIFY_NOT_ON_CUDA)
        assert could_not_run.group(1) == str(diagnostics.VERIFY_COULD_NOT_RUN)

    def test_run_outside_the_repo_root_the_check_could_not_run_and_says_so(self, tmp_path):
        """The wrapper cannot import ``diagnostics`` from another directory: exit 2, never the 'not on CUDA' code."""
        code = _code("install.sh")
        snippet = code[code.index("$PYTHON -c '", code.index("ORT_REPORT=")) + len("$PYTHON -c '"):]
        snippet = snippet[:snippet.index("'")]
        result = subprocess.run([sys.executable, "-c", snippet], cwd=tmp_path, capture_output=True, text=True,
                                env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": ""}, check=False)
        assert result.returncode == diagnostics.VERIFY_COULD_NOT_RUN
        assert "ModuleNotFoundError" in result.stdout


class TestInstallShOrder:
    def test_the_swap_runs_after_every_install_that_pulls_the_cpu_build(self):
        """insightface (``requirements.restricted.txt``) requires plain onnxruntime and overwrites the GPU one."""
        code = _code("install.sh")
        restricted = _position(code, "install -r requirements.txt -r requirements.restricted.txt")
        transformers = _position(code, '"transformers>=')
        uninstall = _position(code, "$UNINSTALLER onnxruntime onnxruntime-gpu")
        install = _position(code, '$INSTALLER install "$ONNX_PACKAGE"')
        verify = _position(code, 'info "Verifying installation..."')
        assert restricted < uninstall
        assert transformers < uninstall
        assert uninstall < install < verify

    def test_the_opencv_swap_runs_after_every_install_that_can_pull_opencv_python(self):
        """requirements.txt, insightface and facexlib pull the GUI wheel into the headless one's ``cv2/``; the last wins."""
        code = _code("install.sh")
        restricted = _position(code, "install -r requirements.txt -r requirements.restricted.txt")
        transformers = _position(code, '"transformers>=')
        ort_install = _position(code, '$INSTALLER install "$ONNX_PACKAGE"')
        uninstall = _position(code, "$UNINSTALLER opencv-python opencv-python-headless")
        install = _position(code, '$INSTALLER install --no-deps "opencv-python-headless==$CV_VER"')
        verify = _position(code, 'info "Verifying installation..."')
        assert restricted < uninstall
        assert transformers < uninstall
        assert ort_install < uninstall
        assert uninstall < install < verify


class TestDockerfile:
    @pytest.mark.parametrize("torch_cuda", ["12.8", "12.6"])
    def test_pinned_version_satisfies_the_helper_range_of_both_cuda_bases(self, torch_cuda):
        match = re.search(r"^ARG ORT_GPU_VERSION=(\S+)", _text("Dockerfile"), re.MULTILINE)
        assert match, "Dockerfile no longer declares ARG ORT_GPU_VERSION"
        assert Requirement(gpu_requirement(torch_cuda)).specifier.contains(match.group(1))


# nvidia-smi's header, as the two driver generations print it. The newer one labels the field
# "CUDA UMD Version" and puts a "KMD Version" beside it.
SMI_OLD = "| NVIDIA-SMI 570.86.15    Driver Version: 570.86.15    CUDA Version: 12.8     |"
SMI_UMD = "| NVIDIA-SMI 615.78.02              KMD Version: 617.14        CUDA UMD Version: 13.4     |"


def _smi(version):
    return f"| NVIDIA-SMI 535.00    Driver Version: 535.00    CUDA Version: {version}     |"


_STUBS = {
    "python3.12": '''#!/bin/bash
if [ "$1" = "--version" ]; then echo "Python 3.12.3"; exit 0; fi
if [ "$1" = "-c" ]; then
  case "$2" in
    *version_info*) exec "$REAL_PYTHON" -c "$2";;
    *verify_onnx_runtime*) echo "CMD verify-ort" >> "$LOG"; [ -n "$FAKE_ORT_OUT" ] && printf '%b\\n' "$FAKE_ORT_OUT"; exit "${FAKE_ORT_RC:-1}";;
    *importlib.metadata*) printf '%s' "$FAKE_CV_VER"; exit 0;;
    "import torch,"*) exit "${FAKE_CORE_RC:-0}";;
    *) exit 0;;
  esac
fi
exit 0
''',
    "uv": '''#!/bin/bash
[ "$1" = "--version" ] && { echo "uv 0.9"; exit 0; }
echo "CMD uv $*" >> "$LOG"
''',
    "pip": '''#!/bin/bash
echo "CMD pip $*" >> "$LOG"
''',
    "uname": '''#!/bin/bash
case "$1" in -s) echo "${FAKE_OS:-Linux}";; -m) echo "${FAKE_ARCH:-x86_64}";; *) /usr/bin/uname "$@";; esac
''',
    "nvidia-smi": '''#!/bin/bash
[ -z "$FAKE_SMI_HEADER" ] && exit 127
if [ "$1" = "--query-gpu=compute_cap" ]; then
  if [ -n "$FAKE_CAP" ]; then echo "$FAKE_CAP"; exit 0; fi
  echo 'Field "compute_cap" is not a valid field to query.'; exit 2
fi
echo "$FAKE_SMI_HEADER"
''',
}


@pytest.fixture
def run_install(tmp_path):
    """Run install.sh over stand-in tools; returns ``(returncode, commands logged, output without colours)``."""
    if sys.platform == "win32":
        pytest.skip("install.sh is a bash script")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in _STUBS.items():
        (stubs / name).write_text(body, encoding="utf-8")
        (stubs / name).chmod(stubs.stat().st_mode | stat.S_IXUSR)
    workdir = tmp_path / "work"
    workdir.mkdir()

    def run(*args, **fake):
        log = tmp_path / "commands.log"
        log.write_text("", encoding="utf-8")
        env = {"HOME": str(tmp_path), "PATH": f"{stubs}:/usr/bin:/bin", "VIRTUAL_ENV": "/fake/venv",
               "LOG": str(log), "REAL_PYTHON": sys.executable}
        env.update({f"FAKE_{key.upper()}": str(value) for key, value in fake.items()})
        result = subprocess.run(["bash", str(ROOT / "install.sh"), "--skip-client", *args], cwd=workdir, env=env,
                                capture_output=True, text=True, check=False)
        output = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout + result.stderr)
        commands = [line[len("CMD "):] for line in log.read_text(encoding="utf-8").splitlines()]
        return result.returncode, commands, output

    return run


def _ort_commands(commands):
    return [cmd for cmd in commands if "onnxruntime" in cmd]


class TestInstallShRuns:
    """Which ONNX Runtime each install.sh path ends on, with the package managers stubbed out."""

    @pytest.mark.parametrize("flags, installer, uninstall", [
        ([], "uv pip", "uv pip uninstall onnxruntime onnxruntime-gpu"),
        (["--no-uv"], "pip", "pip uninstall -y onnxruntime onnxruntime-gpu"),
    ])
    def test_cuda_12_swaps_in_the_gpu_wheel_last_and_verifies_it(self, run_install, flags, installer, uninstall):
        rc, commands, output = run_install(*flags, smi_header=SMI_OLD, cap="8.9", ort_rc=0,
                                           ort_out="onnxruntime-gpu 1.26.0: a CUDA test session runs on x")
        assert rc == 0
        assert "PyTorch variant: cu128" in output
        assert _ort_commands(commands) == [uninstall, f'{installer} install {CUDA12_RANGE}']
        restricted = next(i for i, cmd in enumerate(commands) if "requirements.restricted.txt" in cmd)
        assert restricted < commands.index(uninstall)
        assert commands[-1] == "verify-ort"
        assert "ONNX Runtime: onnxruntime-gpu 1.26.0" in output

    def test_the_umd_version_label_of_newer_drivers_still_selects_cuda(self, run_install):
        rc, commands, output = run_install(smi_header=SMI_UMD, cap="8.9", ort_rc=0, ort_out="ok")
        assert rc == 0
        assert "CUDA detected: 13.4" in output
        assert "using CPU" not in output
        assert any(cmd.endswith("whl/cu128") for cmd in commands)
        assert f"uv pip install {CUDA12_RANGE}" in commands

    def test_the_old_version_label_still_selects_cuda(self, run_install):
        rc, _, output = run_install(smi_header=SMI_OLD, cap="8.9", ort_rc=0, ort_out="ok")
        assert rc == 0
        assert "CUDA detected: 12.8" in output

    def test_a_failing_compute_capability_query_does_not_abort_the_script(self, run_install):
        """Old nvidia-smi, or 'Failed to initialize NVML': the grep matches nothing and pipefail used to kill the run."""
        rc, commands, output = run_install(smi_header=SMI_OLD, ort_rc=0, ort_out="ok")
        assert rc == 0
        assert "Lowest GPU compute capability" not in output
        assert f"uv pip install {CUDA12_RANGE}" in commands

    @pytest.mark.parametrize("driver_cuda", ["11.8", "12.0", "12.2", "12.3"])
    def test_cu118_keeps_the_cpu_build_and_says_why(self, run_install, driver_cuda):
        """cu118 PyTorch needs cuDNN 9; the only CUDA 11 onnxruntime-gpu needs cuDNN 8, so its provider never loads."""
        rc, commands, output = run_install(smi_header=_smi(driver_cuda), cap="8.9")
        assert rc == 0
        assert "PyTorch variant: cu118" in output
        assert "No onnxruntime-gpu build matches this PyTorch's CUDA 11.8 + cuDNN 9" in output
        assert "reporting CUDA 12.4+" in output
        assert _ort_commands(commands) == ["uv pip uninstall onnxruntime onnxruntime-gpu",
                                           f"uv pip install {CPU_ORT}"]
        assert "verify-ort" not in commands

    def test_cpu_over_a_venv_that_holds_both_removes_both_first(self, run_install):
        rc, commands, _ = run_install("--cpu")
        assert rc == 0
        assert _ort_commands(commands) == ["uv pip uninstall onnxruntime onnxruntime-gpu",
                                           f"uv pip install {CPU_ORT}"]

    def test_aarch64_keeps_the_cpu_build_and_says_why(self, run_install):
        rc, commands, output = run_install("--cuda", "12.8", arch="aarch64")
        assert rc == 0
        assert "No CUDA 12 onnxruntime-gpu wheel exists for aarch64" in output
        assert _ort_commands(commands) == ["uv pip uninstall onnxruntime onnxruntime-gpu",
                                           f"uv pip install {CPU_ORT}"]

    def test_apple_silicon_installs_the_cpu_build(self, run_install):
        rc, commands, _ = run_install(os="Darwin", arch="arm64")
        assert rc == 0
        assert _ort_commands(commands) == ["uv pip uninstall onnxruntime onnxruntime-gpu",
                                           f"uv pip install {CPU_ORT}"]

    def test_commercial_installs_no_onnx_runtime_at_all(self, run_install):
        rc, commands, output = run_install("--commercial", "--cuda", "12.8")
        assert rc == 0
        assert _ort_commands(commands) == []
        assert "Skipping ONNX Runtime" in output
        assert "verify-ort" not in commands

    @pytest.mark.parametrize("code, out, must_say, must_not_say", [
        (0, "onnxruntime-gpu 1.26.0: a CUDA test session runs on CUDAExecutionProvider",
         "✓ ONNX Runtime: onnxruntime-gpu 1.26.0", "not running on CUDA"),
        (3, "onnxruntime-gpu 1.26.0, CUDAExecutionProvider listed\\nno CUDA session was created: no GPU",
         "✓ ONNX Runtime: onnxruntime-gpu 1.26.0, CUDAExecutionProvider listed", "not running on CUDA"),
        (1, "onnxruntime 1.27.0, distributions ['onnxruntime']\\nFix: pip install x",
         "✗ ONNX Runtime is not running on CUDA, so face detection will use the CPU", "Could not check"),
        (2, "RuntimeError: torch exploded",
         "Could not check whether ONNX Runtime runs on CUDA", "not running on CUDA"),
        (139, "",
         "exit code 139, no output", "not running on CUDA"),
    ])
    def test_the_verify_step_reports_each_outcome_in_its_own_words(self, run_install, code, out, must_say,
                                                                    must_not_say):
        rc, _, output = run_install("--cuda", "12.8", ort_rc=code, ort_out=out)
        assert rc == 0
        assert must_say in output
        assert must_not_say not in output


def _opencv_commands(commands):
    return [cmd for cmd in commands if "opencv" in cmd]


def _cv_ver_snippet():
    """The Python install.sh runs to read the installed OpenCV version, exactly as it is written there."""
    opener = "CV_VER=$($PYTHON -c '"
    code = _code("install.sh")
    start = _position(code, opener) + len(opener)
    return code[start:code.index("'", start)]


def _read_cv_ver(tmp_path, distributions):
    """Run the real snippet over a ``sys.path`` holding only fake ``{name: version}`` distribution metadata.

    ``-I -S`` keep the interpreter's own site-packages (this venv's real OpenCV) out of the lookup; the
    fake directory is put on ``sys.path`` by a two-line prefix, since ``-I`` also ignores ``PYTHONPATH``.
    """
    site = tmp_path / "fake-site"
    site.mkdir()
    for name, version in distributions.items():
        info = site / f"{name.replace('-', '_')}-{version}.dist-info"
        info.mkdir()
        (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
                                       encoding="utf-8")
    prefix = f"import sys\nsys.path[:0] = [{str(site)!r}]\n"
    return subprocess.run([sys.executable, "-I", "-S", "-c", prefix + _cv_ver_snippet()], capture_output=True,
                          text=True, check=False)


class TestInstallShOpenCV:
    """opencv-python and the headless build share ``cv2/``; install.sh leaves the headless one, and says so when cv2 is broken."""

    @pytest.mark.parametrize("flags, installer, uninstall", [
        ([], "uv pip", "uv pip uninstall opencv-python opencv-python-headless"),
        (["--no-uv"], "pip", "pip uninstall -y opencv-python opencv-python-headless"),
    ])
    def test_both_distributions_are_removed_then_the_headless_one_is_put_back_at_the_same_version(
            self, run_install, flags, installer, uninstall):
        rc, commands, output = run_install(*flags, cv_ver="5.0.0.93")
        assert rc == 0
        assert _opencv_commands(commands) == [uninstall,
                                              f"{installer} install --no-deps opencv-python-headless==5.0.0.93"]
        assert "OpenCV installed (opencv-python-headless 5.0.0.93)" in output

    def test_it_runs_after_the_requirements_transformers_and_onnx_runtime_installs(self, run_install):
        _, commands, _ = run_install("--cpu", cv_ver="5.0.0.93")
        swap = commands.index("uv pip uninstall opencv-python opencv-python-headless")
        assert next(i for i, cmd in enumerate(commands) if "requirements.restricted.txt" in cmd) < swap
        assert next(i for i, cmd in enumerate(commands) if cmd.startswith("uv pip install transformers")) < swap
        assert commands.index(f"uv pip install {CPU_ORT}") < swap

    def test_commercial_installs_opencv_through_requirements_txt_so_it_swaps_too(self, run_install):
        rc, commands, _ = run_install("--commercial", cv_ver="5.0.0.93")
        assert rc == 0
        assert _opencv_commands(commands) == ["uv pip uninstall opencv-python opencv-python-headless",
                                              "uv pip install --no-deps opencv-python-headless==5.0.0.93"]
        assert _ort_commands(commands) == []

    def test_nothing_is_touched_when_no_opencv_distribution_is_installed(self, run_install):
        rc, commands, output = run_install()
        assert rc == 0
        assert _opencv_commands(commands) == []
        assert "Skipping the OpenCV swap" in output

    @pytest.mark.parametrize("distributions, printed", [
        ({"opencv-python": "4.9.0.80", "opencv-python-headless": "5.0.0.93"}, "5.0.0.93\n"),
        ({"opencv-python": "4.9.0.80"}, "4.9.0.80\n"),
        ({"opencv-python-headless": "5.0.0.93"}, "5.0.0.93\n"),
        ({}, ""),
    ], ids=["headless-preferred", "only-opencv-python", "only-headless", "neither"])
    def test_the_real_version_snippet_prefers_the_headless_build_and_prints_nothing_without_opencv(
            self, tmp_path, distributions, printed):
        """The stub answers ``$FAKE_CV_VER`` for this snippet, so a typo in it would otherwise pass unseen."""
        result = _read_cv_ver(tmp_path, distributions)
        assert (result.returncode, result.stderr) == (0, "")
        assert result.stdout == printed

    def test_a_passing_import_check_ends_with_the_success_banner_and_exit_0(self, run_install):
        rc, _, output = run_install(cv_ver="5.0.0.93", core_rc=0)
        assert rc == 0
        assert "All core imports successful" in output
        assert "Installation complete!" in output
        assert "Installation finished with errors" not in output

    def test_a_failed_import_check_exits_non_zero_without_the_success_banner(self, run_install):
        rc, _, output = run_install(cv_ver="5.0.0.93", core_rc=1)
        assert rc == 1
        assert "✗ Some imports failed" in output
        assert "Installation finished with errors" in output
        assert "python facet.py --doctor" in output.split("Installation finished with errors", 1)[1]
        assert "Installation complete!" not in output
        assert "Next steps" not in output

    def test_a_failed_import_check_still_lets_the_onnx_runtime_verify_and_the_commercial_notice_run(
            self, run_install):
        rc, commands, output = run_install("--cuda", "12.8", core_rc=1, ort_rc=0, ort_out="ok")
        assert rc == 1
        assert commands[-1] == "verify-ort"
        assert "ONNX Runtime: ok" in output
        rc, _, output = run_install("--commercial", core_rc=1)
        assert rc == 1
        assert "Commercial install: enable commercial mode" in output
        assert "Installation complete!" not in output
