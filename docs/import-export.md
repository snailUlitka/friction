# Import, Export, and Backup

Legacy import accepts the historical CLI, Emacs, and Neovim JSONL shapes.
Normalization covers dashed and underscored Git keys, `filetype` and
`major-mode`, compact and colonized UTC offsets, empty values, and the CLI's
historical use of `path` for its working directory.

Legacy `wip` becomes `open`. CLI paths become `cwd`; editor paths remain source
files. Absolute Emacs `git-repo` values become `git_root` plus a basename
`git_repo`. Original timestamp/status/schema information remains in
`metadata.legacy`.

Dry-run validates without creating or migrating a user database. Real imports
are atomic per source file. A content-derived fingerprint plus duplicate ordinal
makes repeated or relocated imports idempotent without collapsing intentional
identical lines.

Canonical JSONL v1 is a portable item snapshot and is importable by Friction.
The SQLite backup command preserves the complete event and import provenance.
Private source logs and generated exports must never be committed.

Each canonical line has this shape:

```json
{"schema_version":1,"record_type":"friction_item","data":{}}
```

Export without `--output` writes JSONL to stdout. A file output is replaced
atomically only with `--force`; a directory output receives a timestamped
filename. Backup uses SQLite's online backup API, runs `integrity_check`, and
reports its byte size and SHA-256 digest.
