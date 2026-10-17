"""Schnellprüfung der Installation: Vorhandenes übernehmen, Fehlendes/Beschädigtes/Veraltetes neu installieren."""

import hashlib
import json

from quellenuebersetzer.catalog import load_catalog
from quellenuebersetzer.config import Paths
from quellenuebersetzer.hardware import Gpu, SystemInfo
from quellenuebersetzer.install.manifest import Entry, Manifest
from quellenuebersetzer.install.verify import MARKER, model_ok, reconcile, write_marker
from quellenuebersetzer.planner import build_plan
from quellenuebersetzer.profile import Profile, SourceKind

GTX = SystemInfo("Windows 11", 26100, 15.9, 400.0, [Gpu("NVIDIA GeForce GTX 1660 Ti", "NVIDIA", 6.0, "566.36")])


def _fake_component(paths, cid):
    comp = load_catalog().components[cid]
    check = paths.root / comp.check
    check.parent.mkdir(parents=True, exist_ok=True)
    check.write_bytes(b"x")
    write_marker(paths, comp)
    return comp


def test_existing_program_is_adopted_without_manifest(tmp_path):
    paths = Paths(tmp_path)
    _fake_component(paths, "typst")
    manifest = Manifest(paths)  # leer – z. B. nach einer Neuinstallation
    notes = reconcile(paths, load_catalog(), manifest)
    assert manifest.has("component", "typst") and any("übernommen" in n for n in notes)


def test_outdated_program_version_is_reinstalled(tmp_path):
    paths = Paths(tmp_path)
    comp = _fake_component(paths, "pandoc")
    (paths.root / comp.target / MARKER).write_text(json.dumps({"id": "pandoc", "sha256": "alt"}), encoding="utf-8")
    manifest = Manifest(paths)
    manifest.add(Entry("pandoc", "component", "alt", [comp.target]))
    reconcile(paths, load_catalog(), manifest)
    assert not manifest.has("component", "pandoc", comp.files[0].sha256)


def test_truncated_layout_model_is_detected_and_planned(tmp_path):
    from quellenuebersetzer.runtime.layout import LayoutDetector

    paths = Paths(tmp_path)
    comp = load_catalog().components["layout"]
    model = paths.root / comp.check
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"halb kopiert")
    manifest = Manifest(paths)
    manifest.add(Entry("layout", "component", comp.files[0].sha256, [comp.target]))  # alter, falscher Eintrag
    assert not LayoutDetector(paths).available and not LayoutDetector(paths).ready()
    reconcile(paths, load_catalog(), manifest)
    plan = build_plan(Profile([SourceKind.DRUCK], "pl", ["18jh"]), GTX, load_catalog(), manifest, "schnell", "stufe5")
    assert "layout" in {i.id for i in plan.to_install}


def test_tessdata_with_correct_checksum_is_adopted(tmp_path):
    paths = Paths(tmp_path)
    cat = load_catalog()
    spec = cat.tessdata["pol"]
    target = paths.runtime / "tesseract" / "tessdata" / spec.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"falsch")
    manifest = Manifest(paths)
    reconcile(paths, cat, manifest)
    assert not manifest.has("tessdata", "pol")  # falscher Inhalt wird nicht übernommen


def _fake_model(paths, tag, complete=True):
    name, _, version = tag.partition(":")
    blob = ("gewichte-" + tag).encode()
    digest = "sha256:" + hashlib.sha256(blob).hexdigest()
    (paths.models / "blobs").mkdir(parents=True, exist_ok=True)
    if complete:
        (paths.models / "blobs" / digest.replace(":", "-")).write_bytes(blob)
    mdir = paths.models / "manifests" / "registry.ollama.ai" / "library" / name
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / version).write_text(json.dumps({"layers": [{"digest": digest, "size": len(blob)}]}), encoding="utf-8")


def test_models_are_found_in_ollama_folder(tmp_path):
    paths = Paths(tmp_path)
    _fake_model(paths, "gemma4:e4b-it-qat")
    _fake_model(paths, "glm-ocr:q8_0", complete=False)
    assert model_ok(paths, "gemma4:e4b-it-qat") and not model_ok(paths, "glm-ocr:q8_0")
    manifest = Manifest(paths)
    reconcile(paths, load_catalog(), manifest)
    plan = build_plan(Profile([SourceKind.DRUCK], "pl", ["18jh"]), GTX, load_catalog(), manifest, "schnell", "stufe5")
    planned_models = {i.id for i in plan.to_install if i.kind == "model"}
    assert planned_models == {"glm-ocr:q8_0"}  # nur das unvollständige Modell wird neu geladen


def test_stored_tier_is_kept_on_startup_check(tmp_path):
    paths = Paths(tmp_path)
    plan = build_plan(Profile([SourceKind.DRUCK], "pl", ["18jh"]), GTX, load_catalog(), Manifest(paths), "gruendlich",
                      "stufe5")
    assert plan.tier.key == "stufe5" and plan.main_model == "gemma4:12b-it-qat"
