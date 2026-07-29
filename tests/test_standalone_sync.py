#!/usr/bin/env python3

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/standalone_sync.py"
SPEC = importlib.util.spec_from_file_location("standalone_sync", MODULE_PATH)
sync = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(sync)


def run(*command: str, cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, capture_output=True)


def initialize_repo(path: Path, files: dict[str, str]) -> None:
    path.mkdir(parents=True)
    run("git", "init", "-q", cwd=path)
    run("git", "config", "user.name", "Standalone Sync Test", cwd=path)
    run("git", "config", "user.email", "sync-test@example.invalid", cwd=path)
    for relative, contents in files.items():
        destination = path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents, encoding="utf-8")
    run("git", "add", ".", cwd=path)
    run("git", "commit", "-qm", "fixture", cwd=path)


class StandaloneSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.target = self.root / "target"
        self.local = self.root / "local"

        initialize_repo(
            self.source,
            {
                "include/v8-version.h": (
                    "#define V8_MAJOR_VERSION 14\n"
                    "#define V8_MINOR_VERSION 4\n"
                    "#define V8_BUILD_NUMBER 258\n"
                    "#define V8_PATCH_LEVEL 49\n"
                ),
                "src/keep.cc": "old\n",
                "test/drop.cc": "drop\n",
                "test/torque/keep.tq": "keep\n",
            },
        )
        initialize_repo(
            self.source / "dep",
            {
                "include/public.h": "public\n",
                "private/internal.h": "private\n",
            },
        )
        initialize_repo(self.target, {"obsolete.txt": "obsolete\n"})

        patch = self.local / ".standalone-sync/patches/api.patch"
        patch.parent.mkdir(parents=True)
        patch.write_text(
            "diff --git a/src/keep.cc b/src/keep.cc\n"
            "--- a/src/keep.cc\n"
            "+++ b/src/keep.cc\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+patched\n",
            encoding="utf-8",
        )
        (self.local / "README.md").write_text("local\n", encoding="utf-8")
        self.manifest = self.local / sync.MANIFEST_NAME
        self.manifest.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "sources": [
                        {
                            "path": ".",
                            "exclude": ["test"],
                            "exclude_exceptions": ["test/torque"],
                        },
                        {"path": "dep", "include": ["include"]},
                    ],
                    "patches": [".standalone-sync/patches/api.patch"],
                    "local_paths": [sync.MANIFEST_NAME, "README.md"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_stage(self, name: str) -> tuple[Path, dict]:
        return sync.create_stage(
            self.source,
            self.target,
            self.local,
            self.manifest,
            self.root / name,
        )

    def test_snapshot_filters_sources_applies_patch_and_has_stable_lock(self) -> None:
        first, report = self.create_stage("first")
        second, _ = self.create_stage("second")

        self.assertEqual("14.4.258.49", report["v8_version"])
        self.assertEqual("patched\n", (first / "src/keep.cc").read_text())
        self.assertTrue((first / "test/torque/keep.tq").is_file())
        self.assertTrue((first / "dep/include/public.h").is_file())
        self.assertFalse((first / "test/drop.cc").exists())
        self.assertFalse((first / "dep/private/internal.h").exists())
        self.assertFalse(any(first.rglob(".git")))
        self.assertEqual(
            (first / sync.LOCK_PATH).read_bytes(),
            (second / sync.LOCK_PATH).read_bytes(),
        )

    def test_apply_then_check_is_idempotent(self) -> None:
        stage, _ = self.create_stage("apply")
        sync.apply_candidate(stage, self.target)
        _, report = self.create_stage("check")

        self.assertEqual(
            {"added": 0, "modified": 0, "deleted": 0},
            report["summary"],
        )
        self.assertFalse((self.target / "obsolete.txt").exists())

    def test_snapshot_rejects_candidate_files_ignored_by_git(self) -> None:
        (self.local / ".gitignore").write_text("/dep\n", encoding="utf-8")
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["local_paths"].append(".gitignore")
        self.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(
            sync.SyncError,
            r"(?s)Candidate contains files excluded.*dep/include/public\.h",
        ):
            self.create_stage("ignored")

        self.assertFalse((self.root / "ignored/.git").exists())


if __name__ == "__main__":
    unittest.main()
