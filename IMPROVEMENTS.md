# Improvement Plan

This project manipulates backup data, so correctness and recovery guarantees
come before packaging or profile presentation. The current implementation has
known cases where a failed or incomplete backup can be treated as successful
and where an older snapshot can be modified indirectly.

Until the P0 items are complete, the README should describe the project as
experimental and should not claim that it is safe for production backups.

## P0 - Data-safety requirements

### Make snapshot creation transactional

- [x] Build each snapshot in a unique `.incomplete-<id>` staging directory.
- [x] Treat every copy error, parse error, unsupported entry, and nonzero
  subprocess exit as fatal.
- [x] Return structured results or raise one documented backup exception.
- [x] Write and `fsync` a manifest only after every source succeeds.
- [x] Atomically rename the staging directory to its final snapshot name.
- [x] Release the backup lock in `finally` and return a nonzero CLI exit code.
- [x] Quarantine or clean abandoned staging directories safely on startup.
- [x] Prevent same-second snapshot-name collisions.

Acceptance criteria:

- Injected failures never leave a final snapshot or completion marker.
- The previous completed snapshot remains unchanged.
- A failed run exits nonzero, releases its lock, and can be retried.

### Replace PID-file process killing with a real lock

- [x] Use `fcntl.flock()` and hold the descriptor for the full operation.
- [x] Keep PID and process-start metadata for diagnostics only.
- [x] Remove process killing from `--force` behavior.
- [x] Verify lock ownership before releasing or replacing metadata.

Acceptance criteria:

- Multiprocess tests prove that only one backup or cleanup can run.
- Stale metadata and PID reuse cannot terminate an unrelated process.
- Kernel lock release works after normal exit, signals, and crashes.

### Preserve symlinks and old-snapshot immutability

- [x] Classify entries with `lstat()` and process symlinks before directories.
- [x] Never follow symlinks while applying symlink metadata.
- [x] Break shared hardlinks before changing mode, ownership, flags, or times.
- [x] Define copy-on-write invariants for every mutation.

Acceptance criteria:

- Relative, absolute, broken, file, and directory symlinks remain symlinks.
- External symlink targets are never modified.
- Content and metadata in every older snapshot remain unchanged.

### Validate topology and destructive path boundaries

- [x] Canonicalize source and backup paths and reject every overlap.
- [x] Reject duplicate sources and destination basename collisions, or require
  explicit source labels.
- [x] Require normalized relative paths for nested operations.
- [x] Verify `commonpath` before every write, rename, or deletion.
- [x] Give each backup repository an identity recorded in its manifest.
- [x] Validate repository identity, snapshot type, marker, and device before
  recursive deletion.
- [x] Refuse to cross mount points during deletion.

Acceptance criteria:

- Tests reject output inside source, source inside output, aliases, absolute
  paths, parent traversal, duplicate basenames, and forged markers.
- Bind mounts and nested mount points cannot cause external data deletion.

### Prevent stale, truncated, or changing-file copies

- [x] Handle partial writes correctly or use a proven copy primitive.
- [x] Use nanosecond timestamps and a documented integrity strategy.
- [x] Add checksum verification, either always or through an explicit mode.
- [x] Stat files before and after copying and retry or fail if they changed.
- [x] Record integrity information in the completion manifest.

Acceptance criteria:

- Tests cover partial writes and files changed, replaced, truncated, or renamed
  during copying.
- Same-size content changes with restored timestamps cannot be missed silently.
- A completed snapshot passes manifest verification.

### Correct retention before enabling automatic deletion

- [x] Compute retained snapshots independently for each policy tier and keep
  the union of those sets.
- [x] Compare ISO year and ISO week together.
- [x] Generate and validate a retention plan before deleting anything.
- [x] Run retention only after a new snapshot is durable and complete.
- [x] Quarantine deletion candidates before recursive removal.
- [x] Convert the existing retention `xfail` cases into passing tests.

Acceptance criteria:

- Property tests prove that the latest snapshot and every tier guarantee are
  preserved.
- Backup failure prevents every retention deletion.
- Cross-year weekly retention behaves correctly.

### Handle special filesystem entries explicitly

- [x] Distinguish regular files, directories, symlinks, sockets, FIFOs, block
  devices, and character devices.
- [x] Never open an unsupported entry as a regular file.
- [x] Define a fail or recorded-exclusion policy for every unsupported type.
- [x] Record exclusions in the snapshot manifest.

Acceptance criteria:

- A FIFO without a writer cannot block the backup.
- Tests cover sockets and platform-available device types.
- Unsupported entries produce a visible result and nonzero exit when required.

### Add an immediate safety warning

- [x] Remove the current production-use claim from `README.md`.
- [x] State that the software is experimental until the P0 release gate passes.
- [x] Warn users not to modify hardlinked snapshots in place.
- [x] Document current recovery and metadata limitations honestly.

## P1 - Recovery and release readiness

### Provide a safe restoration workflow

- [x] Implement a restore command or a complete tested restore procedure.
- [x] Support dry-run, partial restore, overwrite policy, and destination
  boundary checks.
- [x] Preserve supported metadata and verify restored content against the
  manifest.
- [x] Test restoration from current and older snapshots.

### Define filesystem compatibility

- [ ] Document behavior for ACLs, xattrs, flags, sparse files, source hardlinks,
  ownership, permissions, and timestamps.
- [x] Add an explicit one-filesystem policy.
- [ ] Make Python and external implementations provide equivalent guarantees or
  document every difference.
- [ ] Test supported behavior on Linux and macOS.

### Make dry-run genuinely non-mutating

- [ ] Separate operation planning from execution.
- [ ] Ensure dry-run creates no files, hardlinks, locks, metadata updates, or
  temporary snapshots.
- [ ] Print proposed copy, exclusion, and deletion operations.
- [ ] Expose validated retention policy through CLI options or configuration.

### Strengthen tests and CI

- [x] Run CI on pull requests as well as pushes.
- [x] Add macOS CI because macOS is an advertised platform.
- [x] Fix the Unix-socket path test that currently fails on a local macOS run.
- [x] Replace nonexistent issue references in `xfail` markers with real tracked
  work, then remove the markers as fixes land.
- [ ] Add subprocess-based concurrency, signal, interruption, and fault tests.
- [ ] Add filesystem-boundary and build/install smoke tests.
- [x] Fix tests that change global state or assert against the wrong path.

Acceptance criteria:

- All known correctness defects have normal passing regression tests.
- Linux and macOS CI pass without unexplained skips or xfails.

### Repair packaging and releases

- [ ] Make source archives build without a `.git` directory.
- [ ] Test wheel and source distribution installation in clean environments.
- [ ] Commit a reproducible development dependency lock or define another
  deterministic policy.
- [ ] Correct OS classifiers and license metadata in `pyproject.toml`.
- [ ] Decide whether PyPI publication is supported and document the decision.
- [ ] Publish GitHub Releases with checksums and release notes.

Acceptance criteria:

- Clean clone, source archive, sdist, and wheel builds all install successfully.
- Each installation can report its version and complete a smoke backup.

### Correct operational documentation

- [ ] Fix the timestamp format, cleanup order, and marker names in `README.md`.
- [ ] Replace the deleted `requirements-dev.txt` installation command.
- [ ] Correct the documented Python matrix to 3.8 through 3.14.
- [ ] Document failure semantics, restore steps, immutable snapshots, mount
  behavior, and implementation differences.
- [ ] Generate or validate examples from integration tests.

## P2 - Maintainability and public presentation

### Separate safety-critical responsibilities

- [ ] Separate planning, copying, locking, retention, and snapshot commit logic.
- [ ] Define typed operation plans and backend interfaces.
- [ ] Share safety checks between Python and external implementations.
- [ ] Add backend contract tests.

### Establish scalability expectations

- [ ] Avoid retaining every source directory entry in memory, or document the
  supported scale explicitly.
- [ ] Benchmark runtime and peak memory on large and deeply nested trees.
- [ ] Publish the benchmark method and expected operating envelope.

### Improve repository maintenance signals

- [ ] Create real issues for every known defect and remove stale annotations.
- [ ] Protect the default branch and require pull-request CI.
- [ ] Add a changelog before the next release.
- [ ] Add concise security and contribution guidance.
- [ ] Align the package author name with the professional profile identity.
- [ ] Replace unclear CLI wording and validate that sources are directories.

### Improve the public project page

- [ ] Add a concise repository description and relevant topics.
- [ ] Add a small architecture diagram showing planning, copy, commit, and
  retention phases.
- [ ] Add a safety-guarantee and limitations table.
- [ ] Add CI and release badges only after those signals are trustworthy.

## Release gate

Do not publish a stable release until all of the following are true:

- [ ] Failed or interrupted backups cannot be marked complete.
- [ ] Previous snapshots are immutable in content and metadata.
- [ ] Locking cannot race or signal unrelated processes.
- [ ] Source, destination, mount, and deletion boundaries are enforced.
- [ ] Retention cannot delete required snapshots or run after backup failure.
- [ ] Unsupported files cannot block or disappear silently.
- [ ] A documented restore has been tested end to end.
- [ ] Linux and macOS CI cover failure and recovery paths.
- [ ] Installable release artifacts work without repository metadata.
- [ ] The README describes tested guarantees and remaining limitations.
