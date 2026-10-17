"""Systemprüfung: Grafikkarte, Speicher, Betriebssystem.

Ohne PowerShell- oder WMI-Skripte: Grafikkarten werden über die DXGI-Schnittstelle
von Windows abgefragt (ctypes), NVIDIA-Details über ``nvidia-smi``, das jeder
NVIDIA-Treiber mitbringt.
"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import psutil

# Ollama benötigt für CUDA 12 mindestens diese Treiberversion.
MIN_NVIDIA_DRIVER = 531.0

VENDOR_NAMES = {0x10DE: "NVIDIA", 0x1002: "AMD", 0x8086: "Intel", 0x1414: "Microsoft"}


@dataclass
class Gpu:
    name: str
    vendor: str
    vram_gb: float
    driver: str | None = None

    @property
    def is_nvidia(self) -> bool:
        return self.vendor == "NVIDIA"


@dataclass
class SystemInfo:
    os_name: str
    windows_build: int | None
    ram_gb: float
    free_disk_gb: float
    gpus: list[Gpu] = field(default_factory=list)
    cpu_name: str = ""
    cpu_cores: int = 0
    existing_ollama: bool = False

    @property
    def best_gpu(self) -> Gpu | None:
        nvidia = [g for g in self.gpus if g.is_nvidia]
        pool = nvidia or self.gpus
        return max(pool, key=lambda g: g.vram_gb) if pool else None

    @property
    def usable_vram_gb(self) -> float:
        """Grafikspeicher, der für Modelle nutzbar ist (nur NVIDIA mit ausreichendem Treiber)."""
        gpu = self.best_gpu
        if not gpu or not gpu.is_nvidia or self.driver_too_old:
            return 0.0
        return gpu.vram_gb

    @property
    def driver_too_old(self) -> bool:
        gpu = self.best_gpu
        if not gpu or not gpu.is_nvidia or not gpu.driver:
            return False
        try:
            major, minor = gpu.driver.split(".")[:2]
            return float(f"{major}.{minor}") < MIN_NVIDIA_DRIVER
        except ValueError:
            return False

    @property
    def os_supported(self) -> bool:
        if self.windows_build is None:
            return sys.platform != "win32"
        return self.windows_build >= 19045


# --------------------------------------------------------------------------- DXGI


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", ctypes.c_uint32), ("HighPart", ctypes.c_int32)]


class _DXGI_ADAPTER_DESC1(ctypes.Structure):
    _fields_ = [
        ("Description", ctypes.c_wchar * 128),
        ("VendorId", ctypes.c_uint),
        ("DeviceId", ctypes.c_uint),
        ("SubSysId", ctypes.c_uint),
        ("Revision", ctypes.c_uint),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", _LUID),
        ("Flags", ctypes.c_uint),
    ]


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


_IID_IDXGIFactory1 = _GUID(
    0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87)
)
_DXGI_ERROR_NOT_FOUND = 0x887A0002
_DXGI_ADAPTER_FLAG_SOFTWARE = 2


def _com_method(obj: ctypes.c_void_p, index: int, restype, *argtypes):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(vtbl[index])


def _dxgi_adapters() -> list[Gpu]:
    if sys.platform != "win32":
        return []
    try:
        dxgi = ctypes.windll.dxgi
    except OSError:
        return []
    factory = ctypes.c_void_p()
    hr = dxgi.CreateDXGIFactory1(ctypes.byref(_IID_IDXGIFactory1), ctypes.byref(factory))
    if hr != 0 or not factory:
        return []
    gpus: list[Gpu] = []
    try:
        enum_adapters1 = _com_method(factory, 12, ctypes.c_long, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))
        i = 0
        while i < 16:
            adapter = ctypes.c_void_p()
            hr = enum_adapters1(factory, i, ctypes.byref(adapter))
            if (hr & 0xFFFFFFFF) == _DXGI_ERROR_NOT_FOUND or not adapter:
                break
            try:
                get_desc1 = _com_method(adapter, 10, ctypes.c_long, ctypes.POINTER(_DXGI_ADAPTER_DESC1))
                desc = _DXGI_ADAPTER_DESC1()
                if get_desc1(adapter, ctypes.byref(desc)) == 0 and not desc.Flags & _DXGI_ADAPTER_FLAG_SOFTWARE:
                    gpus.append(
                        Gpu(
                            name=desc.Description.strip(),
                            vendor=VENDOR_NAMES.get(desc.VendorId, f"0x{desc.VendorId:04X}"),
                            vram_gb=round(desc.DedicatedVideoMemory / 1024**3, 1),
                        )
                    )
            finally:
                _com_method(adapter, 2, ctypes.c_ulong)(adapter)  # Release
            i += 1
    finally:
        _com_method(factory, 2, ctypes.c_ulong)(factory)
    return gpus


# --------------------------------------------------------------------------- NVIDIA


def _nvidia_smi_path() -> str | None:
    found = shutil.which("nvidia-smi")
    if found:
        return found
    candidate = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe"
    return str(candidate) if candidate.exists() else None


def parse_nvidia_smi(output: str) -> list[Gpu]:
    """Wertet ``nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits`` aus."""
    gpus = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            vram = round(float(parts[1]) / 1024, 1)
        except ValueError:
            continue
        gpus.append(Gpu(name=parts[0], vendor="NVIDIA", vram_gb=vram, driver=parts[2]))
    return gpus


def _nvidia_gpus() -> list[Gpu]:
    exe = _nvidia_smi_path()
    if not exe:
        return []
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_nvidia_smi(out.stdout) if out.returncode == 0 else []


# --------------------------------------------------------------------------- Gesamt


def _cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor()


def merge_gpus(dxgi: list[Gpu], nvidia: list[Gpu]) -> list[Gpu]:
    """NVIDIA-Angaben (genauer, mit Treiber) ersetzen die DXGI-Einträge derselben Hersteller."""
    if not nvidia:
        return dxgi
    return [g for g in dxgi if not g.is_nvidia] + nvidia


def detect(data_dir: Path) -> SystemInfo:
    build = None
    if sys.platform == "win32":
        build = sys.getwindowsversion().build
        os_name = "Windows 11" if build >= 22000 else "Windows 10"
    else:
        os_name = platform.system()

    probe = data_dir
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    free = shutil.disk_usage(probe).free / 1024**3

    existing = shutil.which("ollama") is not None or (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    ).exists()

    return SystemInfo(
        os_name=os_name,
        windows_build=build,
        ram_gb=round(psutil.virtual_memory().total / 1024**3, 1),
        free_disk_gb=round(free, 1),
        gpus=merge_gpus(_dxgi_adapters(), _nvidia_gpus()),
        cpu_name=_cpu_name(),
        cpu_cores=psutil.cpu_count(logical=False) or 0,
        existing_ollama=existing,
    )
