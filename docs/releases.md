# Releases

Friction publishes the CLI, TUI, and local stdio MCP server as one Python
application. The Emacs integration is versioned in the same repository and is
installed directly from Git through Emacs `package-vc`. PyPI and MELPA are not
release channels.

## Versioning

Releases use semantic versions and annotated Git tags named `vX.Y.Z`.
`project.version` in `pyproject.toml` is the source of truth. The public Python
`friction.__version__`, `friction --version`, distribution metadata, Git tag,
and the `Version` header in `integrations/emacs/friction.el` must agree.

The release workflow publishes a wheel, a source distribution, and
`SHA256SUMS` to a GitHub Release. The wheel must contain the CLI, TUI, MCP
adapter, and packaged Alembic migrations. The source distribution additionally
contains the standalone Emacs package and its documentation.

## Release Procedure

1. Choose the release version and update `project.version` plus the Emacs
   `Version` header.
2. Update user documentation and durable contracts for every public change.
3. Run the complete sequence in `validation.md` from a clean worktree.
4. Run `scripts/verify_release.py --tag vX.Y.Z` against freshly built
   distributions.
5. Commit the release preparation and push `main`.
6. Create and push the annotated `vX.Y.Z` tag.
7. Let the release workflow validate and publish the GitHub Release.
8. Smoke-test installation from the published wheel, Emacs `package-vc`, and an
   MCP stdio handshake against temporary databases.
9. Update the `friction` formula in `snailUlitka/homebrew-tap`, then test its
   source build, installed commands, upgrade path, and packaged migrations.

Never publish an artifact built from an uncommitted tree. Never put a user
database, friction log, editor state, credential, or package cache in a release.

## Homebrew Handoff

The tap is a separate public repository named `snailUlitka/homebrew-tap`.
Formulae use immutable tagged source plus SHA-256 checksums and install the
Python application into an isolated Homebrew-managed virtual environment. The
formula must not invoke `uv tool install`, depend on a source checkout, or
delete the default database during uninstall or upgrade.

The initial formula update is manual. Automation may open a tap pull request
after a GitHub Release succeeds, but it must not publish a formula before the
release artifacts and acceptance checks pass.
