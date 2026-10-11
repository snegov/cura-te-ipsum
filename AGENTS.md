# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## Project Overview

cura-te-ipsum is a space-efficient incremental backup utility for Linux and
macOS. It creates hardlink-based snapshots similar to Time Machine/rsnapshot,
where unchanged files share inodes between backups to minimize storage.

## Development Commands

### Environment Setup
Project uses `uv` for Python version and dependency management:
```bash
uv sync --all-extras --dev
```

### Testing
```bash
uv run pytest                    # run all tests
uv run pytest -v                 # verbose output
uv run pytest tests/test_fs.py   # run specific test file
```

### Installation
```bash
uv pip install .          # install from source
```

### Running the Tool
```bash
cura-te-ipsum -b /path/to/backups /path/to/source
cura-te-ipsum -b /backups /src1 /src2 --dry-run --verbose
```

## Architecture

### Core Modules

**curateipsum/backup.py**: Main backup orchestration
- `initiate_backup()`: Main entry point - coordinates hardlinking from
  previous backup and rsync from sources
- `cleanup_old_backups()`: Implements grandfather-father-son retention
  (daily/weekly/monthly/yearly) with configurable thresholds
- Lock management (`set_backups_lock`, `release_backups_lock`): Prevents
  concurrent backups using PID-based lock file
- Backup markers (`set_backup_marker`, `_is_backup`): Tracks completed vs
  incomplete backups

**curateipsum/fs.py**: Low-level filesystem operations
- `rsync()`: Pure Python rsync implementation - syncs source to destination
  with delete support
- `rsync_ext()`: Wrapper for external rsync command
- `hardlink_dir()`: Recursively hardlinks entire directory tree (Python or
  external cp)
- `nest_hardlink()`: Hardlinks individual files to `.backup_delta` directory
  preserving structure
- `scantree()`: Recursive directory iterator
- `copy_direntry()`, `update_direntry()`, `rm_direntry()`: DirEntry
  manipulation utilities

**curateipsum/cli.py**: Command-line interface
- Argument parsing and validation
- Platform check (Linux/macOS only)
- Logging setup and execution flow

### Key Data Structures

**PseudoDirEntry**: Emulates os.DirEntry for paths that don't exist yet or
for consistency in handling both real and pseudo entries. Used extensively
in backup operations.

**Actions enum**: Tracks filesystem changes during rsync (NOTHING, DELETE,
REWRITE, UPDATE_TIME, UPDATE_PERM, UPDATE_OWNER, CREATE, ERROR).

### Backup Process Flow

1. Acquire lock file (`.backups_lock`) with PID
2. Clean up old backups per retention policy
3. Hardlink entire previous backup directory to new timestamped directory
4. Remove backup markers from hardlinked copy
5. Delete `.backup_delta` directory from hardlinked copy
6. Rsync each source to new backup (overwrites changed files, breaking
   hardlinks)
7. For each changed file, hardlink to `.backup_delta` directory
8. Set backup marker (`.backup_finished_TIMESTAMP`)
9. Release lock

### Important Implementation Details

**Retention policy**: `cleanup_old_backups()` implements threshold-based
retention where each threshold is inclusive. For example, `keep_weekly=1`
on Thursday keeps one backup from current week AND one from previous week.

**Delta tracking**: Changed files are hardlinked to `.backup_delta/` within
each backup to track what changed in that specific backup snapshot.

**Hardlink breakage**: When rsync overwrites a hardlinked file, it breaks
the hardlink, creating a new inode. This is how changed files get tracked
while unchanged files continue sharing inodes.

**External tools**: Can use external rsync (--external-rsync) or GNU cp/gcp
for hardlinking (--external-hardlink) instead of Python implementations.
macOS requires `gcp` (GNU cp) for external hardlinking.

**Dry run behavior**: Creates backup directory and performs operations but
removes directory at end without setting backup marker.

## Platform Specifics

- Linux: Uses standard `cp` command
- macOS: Requires `gcp` (GNU coreutils) for external hardlinking
- Only these platforms are supported (checked in cli.py)

## Testing

Tests use unittest.TestCase with mock.patch for datetime manipulation.
Focus is on backup cleanup logic with various retention scenarios.
Tests create temporary backup directories and verify correct backups are
kept/removed.

## Version Management

Version is automatically derived from git tags using `setuptools_scm`.
The version file `curateipsum/_version.py` is auto-generated during build
and should not be committed to version control.

To create a new release, tag the commit:
```bash
git tag -a v0.0.4 -m "Release 0.0.4"
git push origin v0.0.4
```
