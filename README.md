# cura-te-ipsum

> **⚠️ Experimental — not yet safe for production use.** This project is
> still working through its data-safety checklist (see
> [IMPROVEMENTS.md](IMPROVEMENTS.md)). Do not rely on it as your only
> backup, and see [Limitations](#limitations) before using it.

**cura-te-ipsum** is a space-efficient incremental backup utility for Linux and macOS that uses hardlinks to minimize storage usage while maintaining complete directory snapshots.

Similar to Time Machine or rsnapshot, cura-te-ipsum creates backups that appear as complete directory trees but intelligently share unchanged files between snapshots, dramatically reducing storage requirements.

## Features

- **Space-Efficient Incremental Backups**: Creates full directory snapshots using hardlinks, unchanged files share inodes with previous backups
- **Intelligent Retention Policies**: Automatic cleanup with configurable grandfather-father-son rotation (daily/weekly/monthly/yearly)
- **Pure Python Implementation**: No external dependencies required for basic operation (optional rsync support available)
- **Delta Tracking**: Automatically identifies and tracks changed files between backups
- **Backup Integrity**: Lock files and completion markers prevent concurrent runs and identify incomplete backups
- **Safe Operations**: Dry-run mode to preview changes before execution
- **Cross-Platform**: Supports both Linux and macOS

## Installation

### From Source

```bash
git clone https://github.com/snegov/cura-te-ipsum.git
cd cura-te-ipsum
pip install .
```

### Requirements

- Python 3.8 or higher
- Linux or macOS operating system
- Optional: `rsync` and GNU `cp` for alternative implementation modes

## Usage

cura-te-ipsum has two subcommands, `backup` and `restore`. For backwards
compatibility, `backup` is implied when the first argument isn't a
recognized subcommand - so `cura-te-ipsum -b DIR SOURCE` and
`cura-te-ipsum backup -b DIR SOURCE` are equivalent.

### Basic Backup

```bash
cura-te-ipsum -b /path/to/backups /path/to/source
```

This creates a timestamped backup in `/path/to/backups/YYYY-MM-DD_HH-MM-SS/`.

### Multiple Sources

```bash
cura-te-ipsum -b /backups /home/user/documents /home/user/photos
```

### Command-Line Options

```
cura-te-ipsum -b BACKUPS_DIR SOURCE [SOURCE ...]

Required Arguments:
  -b BACKUPS_DIR        Directory where backups will be stored
  SOURCE                One or more directories to backup

Optional Arguments:
  -n, --dry-run         Preview changes without creating backup
  -f, --force           Force run even if previous backup is in progress
  -v, --verbose         Enable debug logging
  --external-rsync      Use external rsync instead of Python implementation
  --external-hardlink   Use cp/gcp command for hardlinking
```

### Examples

**Dry run to preview changes:**
```bash
cura-te-ipsum -b /backups /home/user/data --dry-run
```

**Verbose output for debugging:**
```bash
cura-te-ipsum -b /backups /home/user/data --verbose
```

**Using external rsync:**
```bash
cura-te-ipsum -b /backups /home/user/data --external-rsync
```

### Restoring a Backup

```
cura-te-ipsum restore -b BACKUPS_DIR DEST [PATH ...]

Required Arguments:
  -b BACKUPS_DIR        Directory where backups are stored
  DEST                  Directory to restore into (created if missing)

Optional Arguments:
  PATH                  Restore only these snapshot-relative paths - each
                        starts with the source directory's basename (e.g.
                        "data/documents/notes.txt" for a source backed up
                        from /home/user/data); default is everything
  --snapshot NAME       Snapshot to restore, e.g. 20260101_120000
                        (default: the latest snapshot)
  --overwrite {never,always}
                        What to do when a destination path already exists
                        (default: never - existing paths are left alone
                        and reported as skipped)
  --verify              Verify restored content against the snapshot's
                        manifest checksums afterwards
  -n, --dry-run         Show what would be restored without copying
                        anything or creating DEST
  -f, --force           Wait for a running backup/restore instead of
                        exiting immediately
  -v, --verbose         Enable debug logging
```

Restoring the latest snapshot in full:
```bash
cura-te-ipsum restore -b /backups /tmp/recovered
```

Restoring one file from a specific snapshot, verifying it afterwards
(here the source was backed up from `/home/user/data`, so the path
starts with `data/`):
```bash
cura-te-ipsum restore -b /backups --snapshot 20260101_120000 --verify \
  /tmp/recovered data/documents/notes.txt
```

A restore takes the same `.backups_lock` a backup does, so retention
cleanup can never delete a snapshot out from under a restore in progress.
Restored files keep the source's mode, ownership (when running as root),
and timestamps; symlinks are recreated as symlinks, never followed.

## How It Works

### Hardlink-Based Snapshots

cura-te-ipsum creates complete directory snapshots, but files that haven't changed between backups share the same inode (hardlinked). This means:

- Each backup appears as a complete, browseable directory tree
- Only changed or new files consume additional disk space
- Deleting old backups doesn't affect other snapshots until the last reference is removed

### Backup Process

1. **Lock Acquisition**: Creates `.backups_lock` to prevent concurrent operations
2. **Hardlink Creation**: Hardlinks all files from the most recent backup
3. **Rsync Sync**: Syncs source directories to the new backup, updating changed files
4. **Delta Tracking**: Copies changed/new files to `.backup_delta` directory
5. **Completion Marker**: Creates `.backup_finished` marker file
6. **Cleanup**: Removes old backups based on retention policy
7. **Lock Release**: Removes lock file

### Retention Policy

Default retention (configurable in code):

- **7 days**: Keep all backups
- **30 days**: Keep one backup per day
- **52 weeks**: Keep one backup per week
- **12 months**: Keep one backup per month
- **5+ years**: Keep one backup per year

The cleanup process never deletes the only remaining backup.

## Backup Structure

```
backups/
  2025-01-15_10-30-00/          # backup snapshot
    .backup_finished            # completion marker
    .backup_delta/              # changed files in this backup
    [your backed up files]      # complete directory tree
  2025-01-16_10-30-00/
    .backup_finished
    .backup_delta/
    [your backed up files]
  .backups_lock                 # lock file (only during backup)
```

## Limitations

- **Never modify files inside a backup snapshot in place.** Unchanged
  files are hardlinked between snapshots to save space, so editing or
  truncating a file in one snapshot changes that same file's content
  in every other snapshot sharing its inode. Treat every snapshot
  directory as read-only; copy files out before editing them.
- **Restore preserves data content and standard metadata only.** The
  `restore` command copies file content, mode, ownership, timestamps,
  and symlinks; it does not preserve ACLs, extended attributes, or
  filesystem-specific flags.
- **Special filesystem entries (FIFOs, sockets, device nodes) are
  excluded, not backed up** - but only with the default Python
  implementation, which records them in the snapshot manifest as
  exclusions rather than copying them. With `--external-rsync`,
  `rsync`'s `--archive` flag attempts to recreate these entries
  instead, though device nodes typically require root privileges on
  the destination and may be skipped or fail without them.
- **Symlinks are preserved as symlinks**, including ones pointing
  outside the source tree - their targets are never followed or
  copied.
- **ACLs, extended attributes, and filesystem-specific flags (e.g.
  BSD/macOS `chflags`) are never preserved**, by either implementation.
  The Python backend never reads or sets them; `--external-rsync` uses
  `--archive` without `-A`/`-X`/`--fileflags`, so they're dropped too.
- **Sparse files are not preserved as sparse.** Both implementations
  do a whole-file copy (`--whole-file` for external rsync), so holes
  are read and rewritten as allocated zero blocks in the backup.
- **Hardlinks between source files are not preserved as hardlinks.**
  Each hardlinked source file is backed up as an independent file;
  neither backend passes rsync's `-H`. Only hardlinks *within* the
  backup repository (across snapshots) are meaningful.
- **Mode and timestamps are always preserved.** The Python backend
  restores mtime with nanosecond precision; `--external-rsync`'s
  precision depends on the installed rsync build and destination
  filesystem. **Ownership (uid/gid) is preserved only when running as
  root.** In the Python backend a failed `chown` is caught and logged,
  not fatal; with `--external-rsync`, rsync itself just skips
  ownership it isn't permitted to set.
- **Do not mix backends across runs of the same backup.** The default
  Python backend excludes special entries (see above) and its default
  hardlink-forward step only understands files, symlinks, and
  directories - it raises an error on anything else. `--external-rsync`
  can recreate device nodes and sockets (as `root`, via `--archive`'s
  `-D`), so a snapshot it created can contain entries the Python
  backend's hardlinker cannot carry forward into the next backup. Pick
  one of `--external-rsync`/`--external-hardlink` or the Python
  defaults and use it consistently for a given backup destination.
- **`--dry-run` behaves differently per backend, though neither leaves
  a lasting change.** With `--external-rsync`, rsync itself performs no
  I/O. With the Python backend, files are still fully copied into a
  throwaway staging directory, which is then deleted - correct, but
  slower and more I/O-heavy than the external backend's dry run.

## Development

### Running Tests

```bash
pip install -r requirements-dev.txt
pytest
```

### CI/CD

GitHub Actions automatically runs tests on Python 3.6 through 3.11 for every push and pull request.

## Author

Maks Snegov (<snegov@spqr.link>)

## Project Status

Development Status: Pre-Alpha, experimental

This project is under active development and has not yet completed
its data-safety checklist (see [IMPROVEMENTS.md](IMPROVEMENTS.md)).
The API and configuration options may change in future releases.
