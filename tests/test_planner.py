from quellenuebersetzer.catalog import load_catalog
from quellenuebersetzer.config import Paths
from quellenuebersetzer.hardware import Gpu, SystemInfo, merge_gpus, parse_nvidia_smi
from quellenuebersetzer.install.manifest import Manifest
from quellenuebersetzer.planner import Light, build_plan
from quellenuebersetzer.profile import Profile, SourceKind


def _info(vram=24.0, driver="566.36", ram=32.0, disk=500.0, vendor="NVIDIA"):
    gpus = [Gpu("RTX Test", vendor, vram, driver if vendor == "NVIDIA" else None)]
    return SystemInfo("Windows 11", 26100, ram, disk, gpus)


def _plan(tmp_path, info, kinds=(SourceKind.DRUCK,), periods=("18jh",), mode="schnell"):
    return build_plan(Profile(list(kinds), "pl", list(periods)), info, load_catalog(), Manifest(Paths(tmp_path)), mode)


def test_parse_nvidia_smi():
    gpus = parse_nvidia_smi("NVIDIA GeForce RTX 4090, 24564, 566.36\n")
    assert gpus[0].vram_gb == 24.0 and gpus[0].driver == "566.36"
    merged = merge_gpus([Gpu("NVIDIA GeForce RTX 4090", "NVIDIA", 23.6), Gpu("Intel UHD", "Intel", 0.1)], gpus)
    assert {g.vendor for g in merged} == {"NVIDIA", "Intel"} and len(merged) == 2


def test_best_tier_on_24gb(tmp_path):
    plan = _plan(tmp_path, _info(24))
    assert plan.tier.number == 1 and plan.hardware_optimal and plan.overall == Light.GRUEN
    tags = [i.id for i in plan.items if i.kind == "model"]
    assert tags == ["gemma4:31b-it-qat", "glm-ocr:latest"]


def test_tiers_by_vram(tmp_path):
    assert _plan(tmp_path, _info(16)).tier.number == 2
    assert _plan(tmp_path, _info(12)).tier.number == 3
    assert _plan(tmp_path, _info(8)).tier.number == 4
    assert _plan(tmp_path, _info(6)).tier.key == "stufe5"
    assert _plan(tmp_path, _info(0.5, vendor="Intel")).tier.key == "stufe6"


def test_old_driver_falls_back_and_explains(tmp_path):
    plan = _plan(tmp_path, _info(24, driver="472.12"))
    assert plan.tier.key == "stufe6"
    assert any("Treiber" in n for n in plan.notes)


def test_handwriting_is_never_green_and_warns(tmp_path):
    plan = _plan(tmp_path, _info(24), kinds=(SourceKind.HANDSCHRIFT,))
    assert plan.overall == Light.GELB and plan.warnings
    assert _plan(tmp_path, _info(8), kinds=(SourceKind.HANDSCHRIFT,)).overall == Light.ROT


def test_fraktur_adds_tessdata(tmp_path):
    ids = {i.id for i in _plan(tmp_path, _info(24), kinds=(SourceKind.ALTDRUCK,)).items if i.kind == "tessdata"}
    assert {"frak2021", "pol", "lat"} <= ids


def test_blockers(tmp_path):
    plan = _plan(tmp_path, _info(24, disk=5))
    assert not plan.can_install and any("Speicherplatz" in b for b in plan.blockers)
    assert not _plan(tmp_path, _info(24, ram=4)).can_install


def test_gtx_1660_ti_with_16gb_ram(tmp_path):
    """Hardware des Auftraggebers: GTX 1660 Ti (6 GB), 16 GB RAM."""
    info = SystemInfo("Windows 11", 26100, 15.9, 400.0, [Gpu("NVIDIA GeForce GTX 1660 Ti", "NVIDIA", 6.0, "566.36")])
    fast = _plan(tmp_path, info)
    assert fast.tier.key == "stufe5" and fast.mode == "schnell" and fast.main_model == "gemma4:e4b-it-qat"
    assert {i.id for i in fast.items if i.kind == "model"} == {"gemma4:e4b-it-qat", "glm-ocr:q8_0"}
    thorough = _plan(tmp_path, info, mode="gruendlich")
    assert thorough.mode == "gruendlich" and thorough.main_model == "gemma4:12b-it-qat"
    assert any("aufgeteilt" in n for n in thorough.notes)
    # gestaffelt: das schnelle Modell wird für den ersten Durchgang mitinstalliert
    assert thorough.draft_model == "gemma4:e4b-it-qat"
    assert {i.id for i in thorough.items if i.kind == "model"} == {"gemma4:12b-it-qat", "gemma4:e4b-it-qat",
                                                                    "glm-ocr:q8_0"}
    assert thorough.assessments[0].light == Light.GRUEN  # Druck im Modus „Gründlich“


def test_gruendlich_needs_enough_ram(tmp_path):
    info = SystemInfo("Windows 11", 26100, 8.0, 400.0, [Gpu("NVIDIA GeForce GTX 1660 Ti", "NVIDIA", 6.0, "566.36")])
    plan = _plan(tmp_path, info, mode="gruendlich")
    assert plan.mode == "schnell" and any("Arbeitsspeicher" in n for n in plan.notes)


def test_tuning_depends_on_gpu():
    from quellenuebersetzer.runtime.ollama import tuning_for

    gtx = tuning_for("NVIDIA GeForce GTX 1660 Ti", 6.0)
    assert "OLLAMA_FLASH_ATTENTION" not in gtx and gtx["OLLAMA_MAX_LOADED_MODELS"] == "1"
    rtx = tuning_for("NVIDIA GeForce RTX 4090", 24.0)
    assert rtx["OLLAMA_FLASH_ATTENTION"] == "1" and rtx["OLLAMA_MAX_LOADED_MODELS"] == "2"
