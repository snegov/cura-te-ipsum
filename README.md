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
- **No dedicated restore command.** Recovering data means manually
  copying files out of a snapshot directory - there is no restore
  workflow with dry-run, partial restore, or overwrite-policy support
  yet.
- **Special filesystem entries (FIFOs, sockets, device nodes) are
  excluded, not backed up.** They're recorded in the snapshot manifest
  as exclusions rather than copied.
- **Symlinks are preserved as symlinks**, including ones pointing
  outside the source tree - their targets are never followed or
  copied.

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
