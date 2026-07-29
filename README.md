# V8 Standalone

This repository is a flattened, buildable snapshot of V8 for macOS, iOS, and
Android. It intentionally contains no nested Git repositories and does not
carry the upstream repositories' history.

The source snapshot is generated from a normal `gclient` V8 checkout. The
exact source repositories and commits are recorded in
`.standalone-sync/lock.json`. Local API changes are maintained as explicit
patches under `.standalone-sync/patches`.

## Synchronize

The source checkout must already be synchronized by `gclient` and every source
selected by `.standalone-sync.json` must be a Git repository. Android source
dependencies are conditional in V8's `DEPS`, so the source checkout's
`.gclient` must contain:

```py
target_os = ["android"]
```

Run `gclient sync` after changing this setting and before creating a standalone
candidate.

Create an isolated candidate and inspect the diff:

```sh
python3 tools/standalone_sync.py stage \
  --source /Users/haifan/projects/v8/v8 \
  --report /tmp/v8-standalone-sync-report.json
```

Apply the candidate to a clean standalone worktree:

```sh
python3 tools/standalone_sync.py apply \
  --source /Users/haifan/projects/v8/v8
```

The command does not commit. Review the resulting Git diff and run the platform
builds before committing. To verify that a checkout matches the current source
and manifest, run:

```sh
python3 tools/standalone_sync.py check \
  --source /Users/haifan/projects/v8/v8
```

## Ownership model

- `.standalone-sync.json` is the auditable allowlist of upstream repositories
  and excluded paths.
- `.standalone-sync/lock.json` identifies the exact imported commits.
- `.standalone-sync/patches` contains changes layered over upstream V8.
- Files listed in `local_paths` are owned by this repository and survive every
  synchronization.
- Build outputs, untracked files, ignored files, and all `.git` directories are
  never imported.

## Build

Use `build-mac.sh`, `build-ios.sh`, or `build-android.sh`. Each script builds
`v8_monolith` and `d8` with ICU and the V8 sandbox disabled.

```sh
./build-mac.sh arm64                  # arm64 or x64
./build-ios.sh arm64 device          # arm64 device is the default
./build-ios.sh arm64 simulator       # Apple Silicon simulator
./build-ios.sh x64 simulator         # x64 always targets the simulator
NDK_ROOT=/path/to/android-ndk-r28c ./build-android.sh arm64
```

Android builds require a Linux host and NDK r28c. The GitHub Actions workflow
builds all supported macOS, iOS, and Android architectures.
