# Backup Pro

A comprehensive backup tool that makes the life easier when backing up/restoring configurations, files, packages of the system.
Some features:

* Tracking installed packages (e.g. `apt` packages)

* Tracking configurations (e.g. `gsettings`)

* Tracking paths on the filesystem

* Capability of excluding specified subdirectories

* Environment variable support on tracked paths (e.g. `$USER`)

* Scanning for filesystem index snapshots

* Calculating diffs between scanned snapshots

## Requirements

Python >= 3.10 is required. (CPython and PyPy are both supported)
<br><br>
`ujson` is an optional dependency for CPython for the sake of faster JSON operations.

## Installation

Backup Pro can be either installed with pip:

```shell
python3 -m pip install backup-pro
```

Or it can be installed from the source:

```shell
git clone https://github.com/simsekhalit/backup-pro.git
python3 -m pip install -e ./backup-pro
```

## Manual

```
$ python3 -m backup_pro --help
usage: backup-pro [-h] [-c CONF_DIR] [-t TARGET_DIR] COMMAND ...

A comprehensive backup tool that makes the life easier when backing up/restoring configurations, files, packages of the system.

positional arguments:
  COMMAND
    backup              backup the system
    check               check configurations and packages
    diff                calculate diff using the previous scans
    restore             restore the system to the previous backup point
    scan                scan the system to generate filesystem index snapshot that is used by the diff command
    settings            change settings of the backup-pro

options:
  -h, --help            show this help message and exit
  -c CONF_DIR, --conf-dir CONF_DIR
                        folder that contains the backup-pro configurations. defaults to the current directory
  -t TARGET_DIR, --target-dir TARGET_DIR
                        folder that contains the target backup file. defaults to the current directory

For more information: https://github.com/simsekhalit/backup-pro
```

### Getting Started

There are two global options that are essential for the Backup Pro:

* `-c` `--conf-dir`: The folder that contains all Backup Pro configurations (e.g. settings, metadata, indexes, etc.).
Defaults to the current directory.

* `-t` `--target-dir`: The folder that contains the target backup file as `backup-pro-data.zip`.
Defaults to the current directory.

### Backup Operation

Firstly, tracked paths should be configured in order to specify which paths should be backed up.
Each tracked path has a strategy that can be one of 'auto', 'backup-only', 'manual'.
<br>
* `auto` means that path should be automatically handled during backup/restore processes.
This is the default strategy.

* `backup-only` means that path should only be automatically backed up but never be restored.
This is mostly for archiving purposes.

* `manual` means that path should be backed up automatically but restored in a manual way.
`Meld` is supported for manual restoration process.

A tracked path can be added as the following:

```shell
python3 -m backup_pro settings add-tracked-path '$HOME/.config'
```

Additionally, strategy can be specified as well:

```shell
python3 -m backup_pro settings add-tracked-path --strategy manual '$HOME/.ssh'
```

:information_source:

> Please note that environment variables (e.g. `$HOME`, `$USER`) are supported.
> When they are given in a shell escaped way (e.g. `'$HOME'`), Backup Pro understands and treats them as variables.
> For example if `$HOME` variable is change at the moment of restore operation, 
> home directory is extracted to the new value of the variable.

It's possible to exclude some subdirectories of given tracked paths:

```shell
python3 -m backup_pro settings add-tracked-path "/opt/myapp"
python3 -m backup_pro settings add-archive-exclude-path "/opt/myapp/cache"
```

A regex pattern can be specified to exclude paths during backup.
For example, following command excludes python cache files (*.pyc, *.pyo):

```shell
python3 -m backup_pro settings add-archive-exclude-pattern '.+\.py[co]$'
```

After tracked paths are all set, backup operation can be triggered:

```shell
python3 -m backup_pro backup
```

Above command results to a file named as `backup-pro-data.zip` under the path that is specified with the `--target-dir`.

### Check Operation

Every time a `backup` command is executed,
all installed packages and configurations are silently scanned behind the scene.
If new packages are installed (e.g. with `apt install`)
or some configurations are changed (e.g. with `gsettings set`), `check` command detects them and
asks how should the changes be handled.

#### Handling packages:

```
$ python3 -m backup_pro check
Choose package strategy:
d: mark as dependency
i: ignore
r: remove
t: track
S: skip

apt/gparted is detected
[d/i/r/t/S]
```

* If mark as dependency is selected, then `apt-mark auto gparted` command is going to be executed during restoration.
* If ignore is selected, then `gparted` is going to be ignored and no action is going to be taken.
* If remove is selected, then `gparted` is going to be removed with `apt purge gparted` during restoration.
* If track is selected, then `gparted` is going to be installed with `apt install gparted` during restoration.
* If skip is selected, then this package is skipped for now and it's going to be brought up again in the next `check` command.

#### Handling configurations:

```
$ python3 -m backup_pro check
Choose configuration strategy:
i: ignore
t: track
S: skip

gsettings/org.gnome.FileRoller.Listing.sort-method
<'size'
>'name'
[i/t/S]
```

* If ignore is selected, then this configuration is going to be ignored and no action is going to be taken.
* If track is selected, then this configuration is going to be restored with
the value that was recorded with the latest `backup` operation.

### Restore Operation

After the `backup` operation is executed, a file named as `backup-pro-data.zip` is generated under the path that is
specified with the `--target-dir`.
`restore` command restores the system using that file:

```shell
python3 -m backup_pro restore
```

A dry run can be executed in order to see what is going to happen during restore without actually changing anything:

```shell
python3 -m backup_pro --dry-run restore
```

If there are tracked paths with the `manual` strategy,
output of the restore command is going to contain lines as the following:

```
[M] /tmp/backup-pro-data.tmp123456/opt/mydata /opt/mydata
```

These paths should be restored manually.
Backup Pro supports running `meld` for each manually tracked path if `DIFF_CHECKER` variable is set to `meld`:

```shell
export DIFF_CHECKER=meld
python3 -m backup_pro restore
```

Furthermore, it can be forced to restore each file manually in an interactive way
regardless of whether their strategy is `auto` or `manual`:

```shell
export DIFF_CHECKER=meld
python3 -m backup_pro restore --interactive
```

### Scan & Diff Operations

Backup Pro has a mechanism for generating filesystem index snapshot on a specific point in time by scanning the filesystem.
Multiple snapshots can be generated on different times, and then they can be compared to see the differences between them. 
This is useful for tracking what is going on within the filesystem.
<br><br>
Running a scan operation:

```shell
python3 -m backup_pro scan
```

After using the system for some time, `scan` operation is run again.
Following command lists the previously generated snapshots:

```
$ python3 -m backup_pro scan --list
1687685886 (2023-06-25T09:38:06)
1687865209 (2023-06-27T11:26:49)
```

`1687685886` is the key of the first snapshot. The difference between two snapshots can be compared as the following:

```shell
python3 -m backup_pro diff --from-time 1687685886 --to-time 1687865209
```

Please note that:
* `--to-time` defaults to the latest snapshot.
* `--from-time` defaults to the second-latest snapshot.

Therefore, `diff` command can be executed without any arguments in this scenario:

```shell
python3 -m backup_pro diff
```

Alternatively, `--from-time` argument can be given as a timestamp of an arbitrary point in time.
In this case, no previous snapshot exists with the given timestamp
so Backup Pro finds all the files that are changed after the given timestamp.
This is useful for some cases.
For example, if all the files that are changed within the last 30 minutes of the latest snapshot are needed,
the following yields the result:

```
$ python3 -m backup_pro scan --list
1691138286 (2023-08-04T08:38:06)
1691491328 (2023-08-08T10:42:08)

$ python3 -m diff --from-time 1691489528
...
```

Above command prints all the files in the snapshot of `1691491328 (2023-08-08T10:42:08)`
that have modification timestamp newer than `1691489528 (2023-08-08T10:12:08)`.

### Helpful Tip
Generally, system backup/restore tools require root permissions for reading from/writing to system directories.
Using virtual environments with the `sudo` command can be tricky at that point.
For a smoother experience, an executable file can be created as:

```shell
sudo touch /usr/local/bin/backup_pro
sudo chmod 755 /usr/local/bin/backup_pro
```

Following content can be written to the file using the favourite text editor.

```shell
#!/usr/bin/env bash
set -e

if [ "$UID" != 0 ]; then
    exec sudo -E $(readlink -f $0) "$@"
fi

CONF_DIR="$HOME/.config"
TARGET_DIR="/opt"
VENV_PATH="$HOME/venv"

export DIFF_CHECKER="meld"

source "$VENV_PATH/bin/activate"
python3 -m backup_pro -c "$CONF_DIR" -t "$TARGET_DIR" "$@"
```

*Please remember to modify variables according to your own setup.*
