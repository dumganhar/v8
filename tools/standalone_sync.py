#!/usr/bin/env python3
"""Create a reproducible, flattened V8 standalone source snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


MANIFEST_NAME = ".standalone-sync.json"
LOCK_PATH = ".standalone-sync/lock.json"


class SyncError(RuntimeError):
    pass


def run(command: list[str], *, cwd: Path | None = None,
        capture: bool = True, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        cwd=cwd,
        input=input_bytes,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace") if result.stderr else ""
        raise SyncError(f"Command failed ({result.returncode}): {' '.join(command)}\n{stderr}")
    return result


def git(repo: Path, *args: str) -> str:
    return run(["git", "-C", str(repo), *args]).stdout.decode("utf-8").strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalized_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise SyncError(f"Unsafe relative path in manifest: {value}")
    return path


def is_excluded(path: PurePosixPath, prefixes: list[str]) -> bool:
    value = path.as_posix()
    for raw_prefix in prefixes:
        prefix = normalized_relative(raw_prefix.rstrip("/")).as_posix()
        if value == prefix or value.startswith(prefix + "/"):
            return True
    return False


def is_included(path: PurePosixPath, prefixes: list[str]) -> bool:
    if not prefixes:
        return True
    value = path.as_posix()
    for raw_prefix in prefixes:
        prefix = normalized_relative(raw_prefix.rstrip("/")).as_posix()
        if (value == prefix or value.startswith(prefix + "/") or
                prefix.startswith(value + "/")):
            return True
    return False


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def extract_archive(repo: Path, destination: Path, destination_prefix: PurePosixPath,
                    includes: list[str], excludes: list[str],
                    exclude_exceptions: list[str],
                    owners: dict[str, str], owner: str) -> tuple[int, int]:
    process = subprocess.Popen(
        ["git", "-C", str(repo), "archive", "--format=tar", "HEAD"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    file_count = 0
    byte_count = 0
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for member in archive:
                source_path = normalized_relative(member.name.rstrip("/"))
                excluded = (is_excluded(source_path, excludes) and
                            not is_included(source_path, exclude_exceptions))
                if not is_included(source_path, includes) or excluded:
                    continue
                relative = destination_prefix / source_path
                relative_key = relative.as_posix()
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                previous_owner = owners.get(relative_key)
                if previous_owner is not None:
                    raise SyncError(
                        f"Source collision for {relative_key}: {previous_owner} and {owner}"
                    )
                owners[relative_key] = owner
                target.parent.mkdir(parents=True, exist_ok=True)
                remove_path(target)
                if member.issym():
                    os.symlink(member.linkname, target)
                elif member.isfile():
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise SyncError(f"Could not extract {member.name} from {repo}")
                    temporary = target.with_name(target.name + ".sync-tmp")
                    with temporary.open("wb") as output:
                        shutil.copyfileobj(extracted, output)
                    os.chmod(temporary, member.mode & 0o777)
                    os.replace(temporary, target)
                    byte_count += member.size
                else:
                    raise SyncError(f"Unsupported archive entry type: {member.name}")
                file_count += 1
    finally:
        process.stdout.close()
    stderr = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
    if process.stderr:
        process.stderr.close()
    return_code = process.wait()
    if return_code != 0:
        raise SyncError(f"git archive failed for {repo}: {stderr}")
    return file_count, byte_count


def copy_local_path(local_root: Path, destination: Path, relative_value: str) -> None:
    relative = normalized_relative(relative_value)
    source = local_root.joinpath(*relative.parts)
    target = destination.joinpath(*relative.parts)
    if not source.exists() and not source.is_symlink():
        raise SyncError(f"Local-owned path does not exist: {source}")
    remove_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        os.symlink(os.readlink(source), target)
    elif source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target)


def apply_patches(stage: Path, local_root: Path, patches: list[str]) -> list[dict[str, str]]:
    if not patches:
        return []
    run(["git", "init", "-q"], cwd=stage)
    records = []
    try:
        for relative_value in patches:
            relative = normalized_relative(relative_value)
            patch_path = local_root.joinpath(*relative.parts)
            if not patch_path.is_file():
                raise SyncError(f"Patch does not exist: {patch_path}")
            run(["git", "apply", "--check", "--whitespace=error-all", str(patch_path)], cwd=stage)
            run(["git", "apply", "--whitespace=error-all", str(patch_path)], cwd=stage)
            records.append({"path": relative.as_posix(), "sha256": sha256_file(patch_path)})
    finally:
        remove_path(stage / ".git")
    return records


def read_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SyncError(f"Could not read manifest {path}: {error}") from error
    if manifest.get("schema") != 1:
        raise SyncError(f"Unsupported manifest schema in {path}")
    if not isinstance(manifest.get("sources"), list) or not manifest["sources"]:
        raise SyncError("Manifest must define at least one source")
    return manifest


def repository_record(repo: Path, relative: str) -> dict[str, str]:
    try:
        remote = git(repo, "remote", "get-url", "origin")
    except SyncError:
        remote = ""
    return {
        "path": relative,
        "commit": git(repo, "rev-parse", "HEAD"),
        "remote": remote,
    }


def v8_version(stage: Path) -> str:
    header = (stage / "include/v8-version.h").read_text(encoding="utf-8")
    names = ["V8_MAJOR_VERSION", "V8_MINOR_VERSION", "V8_BUILD_NUMBER", "V8_PATCH_LEVEL"]
    values = []
    for name in names:
        marker = f"#define {name} "
        line = next((line for line in header.splitlines() if line.startswith(marker)), None)
        if line is None:
            raise SyncError(f"Could not find {name} in include/v8-version.h")
        values.append(int(line.split()[-1]))
    if values[-1] == 0:
        values.pop()
    return ".".join(str(value) for value in values)


def write_lock(stage: Path, manifest_path: Path, repositories: list[dict[str, str]],
               patches: list[dict[str, str]]) -> None:
    lock = {
        "schema": 1,
        "v8_version": v8_version(stage),
        "manifest_sha256": sha256_file(manifest_path),
        "repositories": repositories,
        "patches": patches,
    }
    path = stage / LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ensure_no_nested_git(stage: Path) -> None:
    nested = [path for path in stage.rglob(".git")]
    if nested:
        values = ", ".join(str(path.relative_to(stage)) for path in nested[:5])
        raise SyncError(f"Nested Git metadata found in candidate: {values}")


def ensure_candidate_not_ignored(stage: Path) -> None:
    paths = sorted(candidate_files(stage))
    if not paths:
        return

    run(["git", "init", "-q"], cwd=stage)
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-z", "--stdin"],
            cwd=stage,
            input=b"\0".join(path.encode("utf-8") for path in paths) + b"\0",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode not in (0, 1):
            stderr = result.stderr.decode("utf-8", "replace")
            raise SyncError(f"git check-ignore failed ({result.returncode}):\n{stderr}")
        ignored = [
            item.decode("utf-8", "replace")
            for item in result.stdout.split(b"\0")
            if item
        ]
        if ignored:
            preview = "\n".join(ignored[:20])
            remainder = len(ignored) - 20
            suffix = f"\n... and {remainder} more" if remainder > 0 else ""
            raise SyncError(
                "Candidate contains files excluded by its Git ignore rules; "
                "adjust .gitignore so the standalone snapshot can be committed:\n"
                f"{preview}{suffix}"
            )
    finally:
        remove_path(stage / ".git")


def git_blob_oid(path: Path, object_format: str) -> str:
    if path.is_symlink():
        data = os.fsencode(os.readlink(path))
        digest = hashlib.new(object_format)
        digest.update(f"blob {len(data)}\0".encode("ascii"))
        digest.update(data)
        return digest.hexdigest()

    digest = hashlib.new(object_format)
    digest.update(f"blob {path.stat().st_size}\0".encode("ascii"))
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_candidate_not_transformed(stage: Path) -> None:
    run(["git", "init", "-q"], cwd=stage)
    try:
        run(["git", "add", "-A"], cwd=stage)
        object_format = run(
            ["git", "rev-parse", "--show-object-format"], cwd=stage
        ).stdout.decode("ascii").strip()
        index = run(["git", "ls-files", "--stage", "-z"], cwd=stage).stdout
        transformed = []
        for record in index.split(b"\0"):
            if not record:
                continue
            metadata, relative_bytes = record.split(b"\t", 1)
            _, index_oid, _ = metadata.split(b" ")
            relative = relative_bytes.decode("utf-8")
            if git_blob_oid(stage / relative, object_format) != index_oid.decode("ascii"):
                transformed.append(relative)
        if transformed:
            preview = "\n".join(transformed[:20])
            remainder = len(transformed) - 20
            suffix = f"\n... and {remainder} more" if remainder > 0 else ""
            raise SyncError(
                "Candidate files would be modified by Git attributes or clean filters; "
                "adjust .gitattributes so upstream bytes are preserved:\n"
                f"{preview}{suffix}"
            )
    finally:
        remove_path(stage / ".git")


def file_state(path: Path) -> tuple[str, int, str]:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return ("symlink", 0, os.readlink(path))
    if stat.S_ISREG(info.st_mode):
        # Git records only whether a regular file is executable, not its full
        # Unix permission bits (for example, 0644 versus 0664).
        executable = int(bool(info.st_mode & 0o111))
        return ("file", executable, sha256_file(path))
    raise SyncError(f"Unsupported filesystem entry: {path}")


def candidate_files(root: Path) -> dict[str, tuple[str, int, str]]:
    result = {}
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        current = Path(directory)
        directory_names[:] = [name for name in directory_names if name != ".git"]
        for name in file_names:
            path = current / name
            relative = path.relative_to(root).as_posix()
            result[relative] = file_state(path)
        for name in directory_names:
            path = current / name
            if path.is_symlink():
                relative = path.relative_to(root).as_posix()
                result[relative] = file_state(path)
    return result


def tracked_files(repo: Path) -> list[str]:
    raw = run(["git", "-C", str(repo), "ls-files", "-z"]).stdout
    return [item.decode("utf-8") for item in raw.split(b"\0") if item]


def compare_candidate(stage: Path, target: Path) -> dict:
    candidate = candidate_files(stage)
    # Files created by `apply` remain untracked until the caller reviews and
    # stages the snapshot. Include candidate paths that already exist so an
    # immediate `check` is idempotent, while unrelated ignored build outputs
    # and untracked local files remain outside the comparison.
    target_paths = set(tracked_files(target))
    target_paths.update(
        relative
        for relative in candidate
        if (target / relative).exists() or (target / relative).is_symlink()
    )
    target_state = {}
    for relative in target_paths:
        path = target / relative
        if path.exists() or path.is_symlink():
            target_state[relative] = file_state(path)
    added = sorted(candidate.keys() - target_state.keys())
    deleted = sorted(target_state.keys() - candidate.keys())
    modified = sorted(
        relative for relative in candidate.keys() & target_state.keys()
        if candidate[relative] != target_state[relative]
    )
    return {
        "summary": {"added": len(added), "modified": len(modified), "deleted": len(deleted)},
        "added": added,
        "modified": modified,
        "deleted": deleted,
    }


def ensure_clean_target(target: Path) -> None:
    status = git(target, "status", "--porcelain=v1", "--untracked-files=no")
    if status:
        raise SyncError("Target has tracked or staged changes; commit or stash them before apply:\n" + status)


def prune_empty_directories(target: Path) -> None:
    directories = []
    for root, names, _ in os.walk(target, topdown=True):
        current = Path(root)
        names[:] = [name for name in names if name != ".git"]
        directories.extend(current / name for name in names)
    for directory in sorted(directories, key=lambda value: len(value.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass


def backup_tracked_files(target: Path, tracked: list[str], backup: Path) -> None:
    for relative in tracked:
        source = target / relative
        if not source.exists() and not source.is_symlink():
            continue
        destination = backup / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            os.symlink(os.readlink(source), destination)
        elif source.is_file():
            try:
                os.link(source, destination)
            except OSError:
                shutil.copy2(source, destination)


def copy_candidate(stage: Path, target: Path) -> None:
    for source in sorted(stage.rglob("*")):
        relative = source.relative_to(stage)
        destination = target / relative
        if source.is_dir() and not source.is_symlink():
            destination.mkdir(parents=True, exist_ok=True)
        elif source.is_symlink():
            destination.parent.mkdir(parents=True, exist_ok=True)
            remove_path(destination)
            os.symlink(os.readlink(source), destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".sync-tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)


def apply_candidate(stage: Path, target: Path) -> None:
    ensure_clean_target(target)
    tracked = tracked_files(target)
    candidate = candidate_files(stage)
    tracked_set = set(tracked)
    collisions = []
    for relative, state in candidate.items():
        destination = target / relative
        if relative not in tracked_set and (destination.exists() or destination.is_symlink()):
            if file_state(destination) != state:
                collisions.append(relative)
    if collisions:
        preview = "\n".join(collisions[:20])
        raise SyncError(f"Candidate would overwrite untracked files:\n{preview}")

    backup = Path(tempfile.mkdtemp(prefix=".v8-standalone-backup-", dir=target.parent))
    try:
        backup_tracked_files(target, tracked, backup)
        for relative in tracked:
            remove_path(target / relative)
        prune_empty_directories(target)
        copy_candidate(stage, target)
    except Exception:
        for relative in candidate:
            remove_path(target / relative)
        copy_candidate(backup, target)
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)


def create_stage(source_root: Path, target: Path, local_root: Path, manifest_path: Path,
                 requested_stage: Path | None) -> tuple[Path, dict]:
    manifest = read_manifest(manifest_path)
    if requested_stage is None:
        stage = Path(tempfile.mkdtemp(prefix="v8-standalone-candidate-"))
    else:
        stage = requested_stage.resolve()
        if stage.exists() and any(stage.iterdir()):
            raise SyncError(f"Staging directory is not empty: {stage}")
        stage.mkdir(parents=True, exist_ok=True)

    owners: dict[str, str] = {}
    repositories = []
    totals = {"files": 0, "bytes": 0}
    for source in manifest["sources"]:
        relative = source["path"]
        source_relative = normalized_relative(relative)
        repo = source_root.joinpath(*source_relative.parts)
        if relative == ".":
            repo = source_root
            destination_prefix = PurePosixPath()
        else:
            destination_prefix = normalized_relative(source.get("destination", relative))
        if not (repo / ".git").exists():
            raise SyncError(f"Selected source is not a Git repository: {repo}")
        git(repo, "rev-parse", "--verify", "HEAD")
        count, size = extract_archive(
            repo,
            stage,
            destination_prefix,
            source.get("include", []),
            source.get("exclude", []),
            source.get("exclude_exceptions", []),
            owners,
            relative,
        )
        totals["files"] += count
        totals["bytes"] += size
        repositories.append(repository_record(repo, relative))

    patch_records = apply_patches(stage, local_root, manifest.get("patches", []))
    for relative in manifest.get("local_paths", []):
        copy_local_path(local_root, stage, relative)
    write_lock(stage, manifest_path, repositories, patch_records)
    ensure_no_nested_git(stage)
    ensure_candidate_not_ignored(stage)
    ensure_candidate_not_transformed(stage)
    report = compare_candidate(stage, target)
    report["candidate"] = str(stage)
    report["v8_version"] = v8_version(stage)
    report["source_totals"] = totals
    return stage, report


def print_report(report: dict, *, verbose: bool) -> None:
    summary = report["summary"]
    print(f"Candidate: {report['candidate']}")
    print(f"V8 version: {report['v8_version']}")
    print(
        "Changes: "
        f"{summary['added']} added, {summary['modified']} modified, "
        f"{summary['deleted']} deleted"
    )
    print(
        f"Exported: {report['source_totals']['files']} files, "
        f"{report['source_totals']['bytes'] / (1024 * 1024):.1f} MiB"
    )
    if verbose:
        for kind in ("added", "modified", "deleted"):
            for relative in report[kind]:
                print(f"{kind[0].upper()}\t{relative}")


def parse_arguments() -> argparse.Namespace:
    script_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("stage", "apply", "check"))
    parser.add_argument("--source", type=Path, required=True, help="Path to the gclient V8 solution")
    parser.add_argument("--target", type=Path, default=script_root, help="Standalone Git repository")
    parser.add_argument(
        "--local-root",
        type=Path,
        help="Root containing manifest-owned files; defaults to --target",
    )
    parser.add_argument("--manifest", type=Path, help=f"Defaults to LOCAL_ROOT/{MANIFEST_NAME}")
    parser.add_argument("--staging", type=Path, help="Use an empty staging directory")
    parser.add_argument("--report", type=Path, help="Write the complete JSON diff report")
    parser.add_argument("--verbose", action="store_true", help="Print every changed path")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    source = arguments.source.resolve()
    target = arguments.target.resolve()
    local_root = (arguments.local_root or target).resolve()
    manifest_path = (arguments.manifest or (local_root / MANIFEST_NAME)).resolve()
    stage = None
    try:
        stage, report = create_stage(
            source,
            target,
            local_root,
            manifest_path,
            arguments.staging,
        )
        if arguments.report:
            arguments.report.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print_report(report, verbose=arguments.verbose)
        if arguments.command == "apply":
            apply_candidate(stage, target)
            print(f"Applied candidate to {target}; review and commit the Git diff.")
        elif arguments.command == "check":
            summary = report["summary"]
            if any(summary.values()):
                print("Standalone tree is not synchronized.", file=sys.stderr)
                return 1
            print("Standalone tree is synchronized.")
        return 0
    except SyncError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
