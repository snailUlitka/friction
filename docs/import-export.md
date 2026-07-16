# Import, Export, and Backup

Legacy import accepts the historical CLI, Emacs, and Neovim JSONL shapes.
Normalization covers dashed and underscored Git keys, `filetype` and
`major-mode`, compact and colonized UTC offsets, empty values, and the CLI's
historical use of `path` for its working directory.

Dry-run validates without creating or migrating a user database. Real imports
are atomic per source file. A content-derived fingerprint plus duplicate ordinal
makes repeated or relocated imports idempotent without collapsing intentional
identical lines.

Canonical JSONL v1 is a portable item snapshot and is importable by Friction.
The SQLite backup command preserves the complete event and import provenance.
Private source logs and generated exports must never be committed.

