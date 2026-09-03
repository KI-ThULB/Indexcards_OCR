"""Security tests for the bulk import layer.

Covers: disabled by default, traversal in folder names, symlink escapes,
independent extension enforcement, and the folder cap.
"""
import pytest

from app.core.config import settings
from app.services import bulk_import
from app.services.bulk_import import BulkImportDisabled, BulkImportError

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"


@pytest.fixture
def import_root(tmp_path, monkeypatch):
    """A scratch import root with three folders of mixed-case images."""
    root = tmp_path / "amiga"
    for i, exts in enumerate([("JPG", "jpeg"), ("jpg", "JPEG"), ("Jpg", "jpg")], start=1):
        folder = root / f"Batch_{i:03d}"
        folder.mkdir(parents=True)
        for j, ext in enumerate(exts):
            (folder / f"IMG_{j}.{ext}").write_bytes(JPEG)
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", str(root))
    return root


# --------------------------------------------------------------------------- #
# Disabled by default
# --------------------------------------------------------------------------- #
def test_disabled_by_default():
    assert bulk_import.is_enabled() is False
    with pytest.raises(BulkImportDisabled):
        bulk_import.import_root()
    with pytest.raises(BulkImportDisabled):
        bulk_import.list_source_folders()


def test_disabled_when_root_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "BULK_IMPORT_ROOT", str(tmp_path / "missing"))
    assert bulk_import.is_enabled() is False


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #
def test_lists_only_immediate_subfolders(import_root):
    (import_root / "Batch_001" / "nested").mkdir()
    (import_root / "Batch_001" / "nested" / "deep.jpg").write_bytes(JPEG)

    listing = bulk_import.list_source_folders()
    names = [f["name"] for f in listing["folders"]]
    assert names == ["Batch_001", "Batch_002", "Batch_003"]
    assert "nested" not in names
    # No recursion: the nested image is not counted
    assert listing["folders"][0]["images_total"] == 2


def test_case_insensitive_extensions_are_counted(import_root):
    listing = bulk_import.list_source_folders()
    assert [f["images_total"] for f in listing["folders"]] == [2, 2, 2]


def test_unsupported_files_are_not_counted(import_root):
    (import_root / "Batch_001" / "notes.txt").write_text("hi")
    (import_root / "Batch_001" / "archive.zip").write_bytes(b"PK")
    listing = bulk_import.list_source_folders()
    assert listing["folders"][0]["images_total"] == 2


def test_hidden_folders_are_hidden(import_root):
    (import_root / ".snapshot").mkdir()
    names = [f["name"] for f in bulk_import.list_source_folders()["folders"]]
    assert ".snapshot" not in names


def test_folder_cap_truncates(import_root, monkeypatch):
    monkeypatch.setattr(settings, "BULK_MAX_FOLDERS", 2)
    listing = bulk_import.list_source_folders()
    assert len(listing["folders"]) == 2
    assert listing["truncated"] is True


# --------------------------------------------------------------------------- #
# Path traversal — folder names are never trusted as paths
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "evil",
    [
        "../",
        "..",
        "../../etc",
        "../amiga/Batch_001",
        "/etc",
        "/etc/passwd",
        "Batch_001/../../etc",
        "Batch_001/nested",
        ".",
        "",
        "foo\x00bar",
        "..\\..\\windows",
    ],
)
def test_traversal_in_folder_name_rejected(import_root, evil):
    with pytest.raises(BulkImportError):
        bulk_import.resolve_source_folder(evil)


def test_symlinked_folder_pointing_outside_root_rejected(import_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.jpg").write_bytes(JPEG)
    (import_root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(BulkImportError):
        bulk_import.resolve_source_folder("escape")
    # And it is never offered in the listing either.
    assert "escape" not in [f["name"] for f in bulk_import.list_source_folders()["folders"]]


def test_symlinked_files_are_skipped(import_root, tmp_path):
    """A link planted in the import root must not pull an arbitrary file into a
    batch directory (from which /batches-static/ would serve it)."""
    secret = tmp_path / "shadow"
    secret.write_bytes(b"root:x:0:0")
    (import_root / "Batch_001" / "innocent.jpg").symlink_to(secret)

    assert bulk_import.list_source_folders()["folders"][0]["images_total"] == 2
    names = [p.name for p in bulk_import.source_images(import_root / "Batch_001")]
    assert "innocent.jpg" not in names


def test_resolve_valid_folder(import_root):
    resolved = bulk_import.resolve_source_folder("Batch_002")
    assert resolved == (import_root.resolve() / "Batch_002")


def test_unknown_folder_rejected(import_root):
    with pytest.raises(BulkImportError):
        bulk_import.resolve_source_folder("Batch_999")


# --------------------------------------------------------------------------- #
# Import mode validation
# --------------------------------------------------------------------------- #
def test_invalid_import_mode_rejected(import_root):
    with pytest.raises(BulkImportError):
        bulk_import.materialise_folder("Batch_001", fields=["Komponist"], mode="symlink")


def test_empty_folder_rejected(import_root):
    (import_root / "Batch_empty").mkdir()
    with pytest.raises(BulkImportError):
        bulk_import.materialise_folder("Batch_empty", fields=["Komponist"])
