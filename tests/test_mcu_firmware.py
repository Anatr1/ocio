"""Host execution of the actual sketch. Arduino/Zephyr and physical timing remain board checks."""
from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def compiler():
    env = os.environ.copy()
    for name in ("g++", "clang++", "cl"):
        path = shutil.which(name)
        if path:
            return path, env
    if os.name == "nt":
        finder = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
        if finder.exists():
            install = subprocess.check_output([str(finder), "-latest", "-products", "*", "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).strip()
            setup = Path(install) / "VC/Auxiliary/Build/vcvars64.bat"
            if install and setup.exists():
                # Read the compiler's environment; do not print or persist environment variables.
                output = subprocess.check_output(f'cmd.exe /d /c call "{setup}" >nul && set', text=True)
                env.update(line.split("=", 1) for line in output.splitlines() if "=" in line and not line.startswith("="))
                path = shutil.which("cl", path=env.get("Path", env.get("PATH")))
                if path:
                    return path, env
    pytest.skip("host C++ compiler unavailable; run the board compile gate")


def compile_sketch(folder, profile, source=None, old=False, oled=True):
    cxx, env = compiler()
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / ("firmware.exe" if os.name == "nt" else "firmware")
    source = source or ROOT / "firmware/crosswalk_mcu/sketch"
    includes = [ROOT / "tests/firmware_stubs", source]
    defines = [f"OCCHIO_GROVE_PROFILE={profile}"]
    if not oled:
        defines.append("OCCHIO_HAS_OLED=0")
    if old:
        defines.append("OCCHIO_TEST_OLD_SOURCE=1")
    harness = ROOT / "tests/firmware_harness.cpp"
    if Path(cxx).name.lower() in ("cl", "cl.exe"):
        args = [cxx, "/nologo", "/std:c++17", "/EHsc", *(f"/I{p}" for p in includes),
                *(f"/D{d}" for d in defines), str(harness), f"/Fe{exe}", f"/Fo{folder / 'firmware.obj'}"]
    else:
        args = [cxx, "-std=c++17", *(f"-I{p}" for p in includes), *(f"-D{d}" for d in defines), str(harness), "-o", str(exe)]
    result = subprocess.run(args, env=env, cwd=folder, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return exe


@pytest.fixture(scope="module", params=[0, 1])
def firmware(request, tmp_path_factory):
    return compile_sketch(tmp_path_factory.mktemp(f"firmware-{request.param}"), request.param)


@pytest.mark.parametrize("case", ["lamps", "audio", "watchdog", "warning", "danger_audio"])
def test_actual_sketch_output_contract(firmware, case):
    result = subprocess.run([str(firmware), case], text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
