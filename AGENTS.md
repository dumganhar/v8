# V8 Standalone Maintenance Guide

## Scope

This repository is a reproducible, flattened snapshot of a normal `gclient`
V8 checkout. It keeps only the source needed to build V8 for macOS, iOS, and
Android. It must not contain nested Git repositories or upstream history.

The repositories must be sibling directories under the same parent:

- Upstream multi-repository checkout: `<repo-parent>/v8`
- Standalone repository: `<repo-parent>/v8-standalone`

Run commands from the standalone repository root. Initialize these variables at
the start of a maintenance shell; `SOURCE_ROOT` is derived from the required
sibling layout:

```sh
STANDALONE_ROOT="$(git rev-parse --show-toplevel)"
SOURCE_ROOT="$(cd "$STANDALONE_ROOT/../v8" && pwd)"
```

Only macOS, iOS, and Android are supported. Do not expand the snapshot or CI
for Linux, Windows, Fuchsia, Chrome, tests, samples, or unrelated tooling unless
the user explicitly changes the scope.

## Source Of Truth

- `.standalone-sync.json` selects upstream repositories and paths.
- `.standalone-sync/lock.json` records the exact imported commits, manifest
  hash, patch hashes, and V8 version. It is generated; never edit it manually.
- `.standalone-sync/patches` contains every standalone-only change to imported
  upstream files. Patches are applied in manifest order.
- `local_paths` contains files owned by this repository, such as build scripts,
  CI, documentation, the synchronizer, and its tests.
- All other tracked files are generated from committed upstream `HEAD` objects.

The synchronizer exports each selected repository with `git archive HEAD`.
Dirty or staged changes in the upstream checkout are not imported. If a source
change is intentional, commit it in the corresponding upstream repository or
represent it as a standalone patch.

## Non-Negotiable Rules

1. Build a candidate before changing the standalone tree.
2. Never copy an entire dependency checkout or any `.git` directory.
3. Never hand-edit `lock.json`.
4. Do not fix an imported file only in the standalone tree. Add or update a
   patch, then regenerate the file through the synchronizer.
5. Keep standalone-owned files in `local_paths`; otherwise the next sync will
   delete them.
6. Keep patches narrow and platform-scoped. Do not disable warnings, assertions,
   fatal linker warnings, or compiler checks globally to hide a toolchain issue.
7. Preserve unrelated user changes. `apply` requires a clean tracked target and
   must not be forced around that guard.
8. Do not push unless the user explicitly asks. Commit only after verification.

## Prepare The Upstream Checkout

The V8 solution must be a complete, synchronized `gclient` checkout. Android
dependencies are conditional, so its `.gclient` file must include:

```py
target_os = ["android"]
```

Ensure `depot_tools` and `gclient` are on `PATH`, then synchronize from the
upstream checkout:

```sh
(cd "$SOURCE_ROOT" && gclient sync)
```

Before synchronization, verify every entry in `.standalone-sync.json` exists
as a Git repository and is at the intended commit. Inspect `git status` in the
root and any dependency repository relevant to the update; remember that
uncommitted source changes will be ignored.

## Routine Upstream Upgrade

Use this path when only upstream repository commits changed and the current
manifest, patches, and local files remain valid.

```sh
git status --short --branch

python3 tools/standalone_sync.py stage \
  --source "$SOURCE_ROOT" \
  --staging /tmp/v8-standalone-candidate \
  --report /tmp/v8-standalone-sync-report.json \
  --verbose

cat /tmp/v8-standalone-sync-report.json
```

The staging directory must be empty. Review added, modified, and deleted paths,
the V8 version, repository commits, and unexpected size changes before apply.
Large unexplained additions usually indicate an overly broad manifest entry.

Apply only with a clean tracked target:

```sh
python3 tools/standalone_sync.py apply \
  --source "$SOURCE_ROOT"
```

`apply` replaces the tracked snapshot transactionally, preserves a backup while
copying, rejects conflicting untracked files, and does not commit.

## Changing Patches Or Local-Owned Files

When a V8 upgrade needs a new patch, manifest change, build-script change, or
other `local_paths` change, keep the target clean by using a detached worktree
as `local-root`. `/tmp/v8-standalone-sync-local` must not already exist or be an
active worktree; inspect `git worktree list` first:

```sh
git -C "$STANDALONE_ROOT" worktree add \
  --detach /tmp/v8-standalone-sync-local HEAD
```

Edit the manifest, patches, and local-owned files under
`/tmp/v8-standalone-sync-local`. Then stage and apply with explicit paths:

```sh
python3 "$STANDALONE_ROOT/tools/standalone_sync.py" stage \
  --source "$SOURCE_ROOT" \
  --target "$STANDALONE_ROOT" \
  --local-root /tmp/v8-standalone-sync-local \
  --manifest /tmp/v8-standalone-sync-local/.standalone-sync.json \
  --staging /tmp/v8-standalone-candidate \
  --report /tmp/v8-standalone-sync-report.json \
  --verbose

python3 "$STANDALONE_ROOT/tools/standalone_sync.py" apply \
  --source "$SOURCE_ROOT" \
  --target "$STANDALONE_ROOT" \
  --local-root /tmp/v8-standalone-sync-local \
  --manifest /tmp/v8-standalone-sync-local/.standalone-sync.json
```

Remove the detached worktree only after the applied target and commit are
verified. The non-forced cleanup command is:

```sh
git -C "$STANDALONE_ROOT" worktree remove \
  /tmp/v8-standalone-sync-local
```

This command refuses a dirty maintenance worktree. Never add `--force` until
its changes are present in the standalone commit and have been verified.

### Ownership Decision

- Change which upstream files are exported: edit `.standalone-sync.json`.
- Change an imported upstream file only for standalone builds: add a numbered
  patch and list it under `patches` in dependency order.
- Change CI, scripts, documentation, or sync tooling: edit the local-owned file
  and ensure its path is in `local_paths`.
- Change upstream V8 itself for all consumers: make that change in the upstream
  repository, not here.

An independent patch should pass against the raw upstream checkout:

```sh
git -C "$SOURCE_ROOT" apply \
  --check --whitespace=error-all /path/to/patch
```

Use sufficient hunk context. A patch that applies only because it matches a
generic `}` can silently land in the wrong GN target after an upstream update.
Patches may depend on earlier patches, so a later dependent patch is not
required to apply to the raw checkout by itself. The authoritative cumulative
validation is `standalone_sync.py stage`: it applies and checks every patch in
manifest order on a disposable candidate. Never validate a dependent patch by
skipping its predecessors.

## Required Verification

Always run:

```sh
python3 -m unittest tests.test_standalone_sync
git diff --check
python3 tools/standalone_sync.py check \
  --source "$SOURCE_ROOT"
git status --short --branch
```

`check` must report `0 added, 0 modified, 0 deleted`. If a custom `local-root`
was used, pass the same `--target`, `--local-root`, and `--manifest` arguments
to `check`.

For GN edits, run the matching GN formatter. For platform changes, generate GN
and build the affected architecture. Do not claim an Android build was tested
on macOS: this V8 checkout asserts that Android builds require a Linux host.

## Platform Matrix

### macOS

- Architectures: `arm64`, `x64`
- Command: `./build-mac.sh <arch>`
- Uses Xcode Clang and downloaded macOS GN.

### iOS

- Device: `./build-ios.sh arm64 device`
- Apple Silicon simulator: `./build-ios.sh arm64 simulator`
- Intel simulator: `./build-ios.sh x64 simulator`
- `x64` is simulator-only.
- Keep `-Wl,-fatal_warnings`; fix linker warnings rather than suppressing them.

### Android

- Architectures: `arm64`, `arm`, `x64`, `x86`
- Requires an x86_64 Linux host and official Android NDK r28c.
- Command: `NDK_ROOT=/path/to/android-ndk-r28c ./build-android.sh <arch>`
- The official r28c Linux archive contains only `linux-x86_64` host tools. It
  cannot run natively in a Linux arm64 container.
- Target objects use NDK Clang 19, its sysroot, libc++, compiler-rt, `llvm-ar`,
  and linker tools.
- Host tools and snapshot generators use Chromium Clang and the Debian host
  sysroot. Do not collapse the host and target toolchains.
- Minimum Android API level is 23.

`build-android.sh` does not bootstrap the host dependencies. Before a local
Linux build, download Linux amd64 GN to `buildtools/linux64/gn`, install Ninja,
run `python3 tools/clang/scripts/update.py`, and install the host sysroot. Use
`python3 build/linux/sysroot_scripts/install-sysroot.py --arch=amd64`
for an `arm64` or `x64` target, and use `--arch=i386` for an `arm` or `x86`
target.

Use `.github/workflows/build.yml` as the canonical provisioning sequence.
macOS and native Linux arm64 are not supported hosts for the official r28c
Android build because the NDK archive contains only x86_64 host executables.

GitHub Actions is the authoritative Android full-build environment. It installs
the correct amd64/i386 Debian sysroot for host tools, downloads Chromium Clang,
and builds all four Android ABIs.

## Known Compatibility Lessons

- Keep the required Chromium `build` files. Missing
  `build/toolchain/sysroot.gni` or `build/config/apple/mobile_config.gni` means
  the export allowlist is incomplete, not that imports should be removed.
- `third_party/cpu_features/src/ndk_compat/cpu-features.c` is a vendored source
  dependency. Modern NDKs do not provide it as a source file to compile.
- NDK runtime libraries must come from the target architecture's Android
  compiler-rt directory. A host
  `x86_64-unknown-linux-gnu/libclang_rt.builtins.a` is not an Android runtime.
- NDK r28c libc++ lacks `std::atomic_ref`. V8 code must use
  `src/base/atomic-ref.h`; after atomic errors, scan the entire retained source
  tree for direct `std::atomic_ref` calls instead of fixing one file at a time.
- simdutf uses its own atomic compatibility backend. Propagate its define with
  a GN `config` and `public_configs`; `public_defines` is not a supported
  `source_set` variable in this build configuration.
- Chromium Clang may emit warning flags unknown to NDK Clang 19. Filter only
  the confirmed unsupported flags when
  `standalone_use_android_ndk_clang=true`.
- NDK Clang 19 can incorrectly escalate the regexp operand traversal into an
  immediate function when `consteval` helpers are used from runtime lambdas.
  Keep those helpers `constexpr` unless the NDK toolchain is upgraded and the
  compatibility patch is proven unnecessary.
- iOS arm64 uses 16 KiB minimum page alignment, but the iOS x64 simulator uses
  4 KiB. Do not apply the arm64 alignment to every `V8_OS_IOS` build.

Current compatibility patches are documented by their filenames under
`.standalone-sync/patches`. Read all patches before changing toolchain behavior;
later patches assume the host/target split introduced by earlier patches.

## Diagnosing Build Failures

1. Record the failing platform, target ABI, host architecture, compiler path,
   sysroot, API/deployment target, and the first real error.
2. Confirm the compile or link command uses the intended host or target
   toolchain before changing source.
3. Search the retained tree for every use of the failing API, flag, GN variable,
   or source path. Fix the class of problem, not only the first object file.
4. Use `ninja -C out/android -k 0 v8_monolith d8` during investigation when a
   single CI run should collect all independent Android compile errors.
5. Distinguish GN parse/generation failures, missing exported files, compiler
   compatibility failures, and linker/runtime selection failures.
6. Prefer an existing V8/Chromium abstraction over a third-party-specific
   workaround. Keep fallbacks small, typed, and covered on every affected ABI.
7. Reproduce the final change through the sync patch and rerun `check`.

When local platform constraints prevent full verification, run every safe
partial check available, state exactly what was not run, and leave the final
platform build to CI. Never report a partial syntax or GN check as a completed
Android build.

## Commit Discipline

- Review `git diff --stat`, the full diff, and `git diff --check`.
- Stage only synchronization-related files.
- After staging, review `git diff --cached` and run
  `git diff --cached --check`; unstaged checks do not validate the index.
- Keep each commit focused on one synchronization or compatibility change.
- Include the generated manifest/lock/source changes in the same commit as the
  patch or local-owned change that produced them.
- Report the commit hash, verification performed, and any remaining CI-only
  validation. Do not push without explicit authorization.
