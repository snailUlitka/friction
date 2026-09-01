# Engineering Harness

This directory is the durable knowledge base for Friction. The root
`AGENTS.md` stays short and operational; rationale, contracts, and repeatable
maintenance procedures live here.

## Documentation Map

- `architecture.md` defines boundaries, data flow, and dependency direction.
- `cli.md` defines human commands, machine mode, and exit behavior.
- `domain.md` defines lifecycle and concurrency invariants.
- `json-contract.md` defines the stable machine interface.
- `import-export.md` defines legacy normalization and portable data behavior.
- `tui.md` defines the terminal interface and its Vim-style interaction.
- `../integrations/emacs/README.md` documents the standalone local Emacs mode.
- `mcp.md` defines the local stdio server and its trust boundary.
- `releases.md` defines versioning, release artifacts, and distribution handoff.
- `interfaces.md` records the complete TUI, Emacs capture, and local MCP
  milestone requirements.
- `validation.md` defines local and CI checks.

## Maintenance Rules

- Update the relevant document in the same commit as a behavior or contract
  change.
- Treat `pyproject.toml` as the release-version source of truth and keep the
  Emacs `Version` header aligned with it.
- Prefer decisions and invariants over implementation narration.
- Do not copy private friction notes, local database contents, or machine state
  into documentation or fixtures.
