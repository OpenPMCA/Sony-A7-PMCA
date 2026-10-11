"""Tests for desktop packaging, Casks, AppRun, runtime verification, and CI workflow."""

import hashlib
import importlib.util
from pathlib import Path
import re
import unittest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = REPO_ROOT / "packaging" / "build.py"
DESKTOP_ENTRY = REPO_ROOT / "packaging" / "linux" / "sony-open-pmca.desktop"
CASK_PATH = REPO_ROOT / "Casks" / "sony-open-pmca.rb"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "build.yml"


def load_build_module():
    """Load packaging/build.py via importlib to avoid site-packages collision."""
    if not BUILD_SCRIPT.exists():
        raise ImportError(f"packaging/build.py not found at {BUILD_SCRIPT}")
    spec = importlib.util.spec_from_file_location("pmca_packaging_build", BUILD_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PackagingFilenamesTest(unittest.TestCase):
    def test_versioned_filenames_for_each_platform(self):
        mod = load_build_module()
        self.assertEqual(
            mod.get_asset_name("macos", version="1.0.0", arch="arm64"),
            "Sony-Open-PMCA-1.0.0-macos-arm64.zip",
        )
        self.assertEqual(
            mod.get_asset_name("windows", version="1.0.0", arch="x64"),
            "Sony-Open-PMCA-1.0.0-windows-x64.exe",
        )
        self.assertEqual(
            mod.get_asset_name("linux", version="1.0.0", arch="x86_64"),
            "Sony-Open-PMCA-1.0.0-linux-x86_64.AppImage",
        )

    def test_apprun_argument_forwarding_quoted(self):
        mod = load_build_module()
        apprun_content = mod.get_apprun_content()
        self.assertIn('"$@"', apprun_content, "AppRun must forward arguments with quoted \"$@\"")
        # Ensure no unquoted $@ or $*
        self.assertNotRegex(
            apprun_content,
            r'(?<!")\$[@*](?!")',
            "AppRun must not contain unquoted $@ or $* which would split arguments with spaces",
        )


class DesktopFileTest(unittest.TestCase):
    def test_desktop_file_syntax_and_fields(self):
        self.assertTrue(DESKTOP_ENTRY.exists(), f"Desktop file missing at {DESKTOP_ENTRY}")
        content = DESKTOP_ENTRY.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("[Desktop Entry]"))
        self.assertIn("Name=Sony Open PMCA", content)
        self.assertIn("Exec=Sony-Open-PMCA", content)
        self.assertIn("Icon=sony-open-pmca", content)
        self.assertIn("Terminal=false", content)
        self.assertIn("Type=Application", content)


class RuntimeReportValidationTest(unittest.TestCase):
    def setUp(self):
        self.valid_report = {
            "version": "1.0.0",
            "python": "3.14.8",
            "architecture": "arm64",
            "frozen": True,
            "tcl_version": "9.1.0",
            "libusb_loads": True,
            "libusb_path": "/path/to/libusb-1.0.dylib",
            "spk_roundtrip": True,
            "certificate_key_parses": True,
            "tls_handshake_verified": True,
            "tls_cipher": "AES256-SHA",
            "tls_version": "TLSv1.2",
        }

    def test_valid_report_passes(self):
        mod = load_build_module()
        result = mod.validate_runtime_report(
            self.valid_report, expected_version="1.0.0", expected_arch="arm64"
        )
        self.assertTrue(result.get("valid"))

    def test_strict_booleans_tls_failure(self):
        mod = load_build_module()
        for bad_val in [False, "true", 1, None]:
            report = dict(self.valid_report, tls_handshake_verified=bad_val)
            result = mod.validate_runtime_report(
                report, expected_version="1.0.0", expected_arch="arm64"
            )
            self.assertFalse(result.get("valid"))
            self.assertIn("tls_handshake_verified", result.get("errors", [""])[0].lower())

    def test_strict_booleans_libusb_loads_failure(self):
        mod = load_build_module()
        report = dict(self.valid_report, libusb_loads=False)
        result = mod.validate_runtime_report(
            report, expected_version="1.0.0", expected_arch="arm64"
        )
        self.assertFalse(result.get("valid"))
        self.assertIn("libusb_loads", result.get("errors", [""])[0].lower())

    def test_strict_booleans_frozen_failure(self):
        mod = load_build_module()
        report = dict(self.valid_report, frozen=False)
        result = mod.validate_runtime_report(
            report, expected_version="1.0.0", expected_arch="arm64"
        )
        self.assertFalse(result.get("valid"))
        self.assertIn("frozen", result.get("errors", [""])[0].lower())

    def test_wrong_architecture_rejected(self):
        mod = load_build_module()
        report = dict(self.valid_report, architecture="x86_64")
        result = mod.validate_runtime_report(
            report, expected_version="1.0.0", expected_arch="arm64"
        )
        self.assertFalse(result.get("valid"))
        self.assertTrue(any("architecture" in err.lower() for err in result.get("errors", [])))

    def test_wrong_version_rejected(self):
        mod = load_build_module()
        report = dict(self.valid_report, version="0.18.0")
        result = mod.validate_runtime_report(
            report, expected_version="1.0.0", expected_arch="arm64"
        )
        self.assertFalse(result.get("valid"))
        self.assertTrue(any("version" in err.lower() for err in result.get("errors", [])))


class MissingLibraryTest(unittest.TestCase):
    def test_missing_libusb_raises_explicit_runtime_error(self):
        mod = load_build_module()
        with self.assertRaises(RuntimeError) as ctx:
            mod.find_libusb(platform_override="unknown_platform")
        msg = str(ctx.exception).lower()
        self.assertIn("libusb", msg)


class HomebrewCaskTest(unittest.TestCase):
    def test_cask_content_and_restrictions(self):
        self.assertTrue(CASK_PATH.exists(), f"Cask file missing at {CASK_PATH}")
        content = CASK_PATH.read_text(encoding="utf-8")
        self.assertIn('cask "sony-open-pmca"', content)
        self.assertIn('version "1.0.0"', content)
        self.assertNotIn(":no_check", content, "Cask must not use :no_check")
        self.assertIn("depends_on arch: :arm64", content, "Cask must restrict to arm64")
        self.assertIn('app "Sony Open PMCA.app"', content)
        self.assertIn("https://github.com/OpenPMCA/Sony-Open-PMCA/releases/download/v", content)
        self.assertIn("Sony-Open-PMCA-", content)
        self.assertIn("-macos-arm64.zip", content)

        # Checksum must be 64-char hex
        match = re.search(r'sha256\s+"([0-9a-fA-F]{64})"', content)
        self.assertIsNotNone(match, "Cask must specify a valid 64-character SHA-256 checksum")

    def test_cask_checksum_matches_actual_mac_zip_if_present(self):
        zip_file = REPO_ROOT / "dist" / "Sony-Open-PMCA-1.0.0-macos-arm64.zip"
        if zip_file.exists():
            content = CASK_PATH.read_text(encoding="utf-8")
            match = re.search(r'sha256\s+"([0-9a-fA-F]{64})"', content)
            self.assertIsNotNone(match)
            actual_digest = hashlib.sha256(zip_file.read_bytes()).hexdigest()
            self.assertEqual(match.group(1).lower(), actual_digest.lower())

    def test_cask_generator_produces_consistent_output(self):
        mod = load_build_module()
        dummy_sha = "a" * 64
        cask_text = mod.render_cask(version="1.0.0", sha256_hex=dummy_sha)
        self.assertIn(f'sha256 "{dummy_sha}"', cask_text)
        self.assertIn('version "1.0.0"', cask_text)
        self.assertIn("depends_on arch: :arm64", cask_text)


class WorkflowStructureTest(unittest.TestCase):
    def test_workflow_jobs_and_actions(self):
        self.assertTrue(WORKFLOW_PATH.exists(), f"Workflow file missing at {WORKFLOW_PATH}")
        with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
            workflow = yaml.safe_load(f)

        # Top-level permissions must be read-only
        permissions = workflow.get("permissions", {})
        self.assertEqual(permissions.get("contents"), "read", "Workflow must have contents: read permissions")

        jobs = workflow.get("jobs", {})
        self.assertIn("build-macos", jobs, "Workflow must have build-macos job")
        self.assertIn("build-windows", jobs, "Workflow must have build-windows job")
        self.assertIn("build-linux", jobs, "Workflow must have build-linux job")

        # Check runners
        self.assertEqual(jobs["build-macos"].get("runs-on"), "macos-14")
        self.assertEqual(jobs["build-windows"].get("runs-on"), "windows-2022")
        self.assertEqual(jobs["build-linux"].get("runs-on"), "ubuntu-22.04")

        # Workflow content string checks
        raw_text = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertNotIn("hub release", raw_text, "Workflow must not create releases")
        self.assertNotIn("gh release", raw_text, "Workflow must not create releases")
        self.assertNotIn("action-gh-release", raw_text, "Workflow must not create releases")
        self.assertIn("actions/checkout@v4", raw_text)
        self.assertIn("actions/setup-python@v5", raw_text)
        self.assertIn("actions/upload-artifact@v4", raw_text)
        self.assertIn("if-no-files-found: error", raw_text)


class AppImageToolMetadataTest(unittest.TestCase):
    def test_appimagetool_pinned_and_checksummed(self):
        mod = load_build_module()
        self.assertTrue(hasattr(mod, "APPIMAGETOOL_URL"))
        self.assertTrue(hasattr(mod, "APPIMAGETOOL_SHA256"))
        self.assertTrue(mod.APPIMAGETOOL_URL.startswith("https://"))
        self.assertIn("1.9.1", mod.APPIMAGETOOL_URL)
        self.assertEqual(len(mod.APPIMAGETOOL_SHA256), 64)


if __name__ == "__main__":
    unittest.main()
