# Local MCP Server

Friction exposes a local-only MCP server over stdio. It creates one
`FrictionService`, applies packaged migrations before protocol startup, and
never binds a socket. There is no HTTP, SSE, host, port, authentication, daemon,
or remote-access mode.

A generic MCP host configuration for the default database is:

```json
{
  "mcpServers": {
    "friction": {
      "command": "friction",
      "args": ["mcp"]
    }
  }
}
```

For another database, preserve root-option ordering:

```json
{"command":"friction","args":["--db","/absolute/path/friction.db","mcp"]}
```

## Surface

The server registers exactly these tools:

- `friction_add`, `friction_list`, `friction_search`, `friction_get`;
- `friction_update`, `friction_mark_done`, `friction_dismiss`;
- `friction_reopen`, `friction_archive`, `friction_unarchive`;
- `friction_history`.

Mutations require the current revision and never retry a conflict. Update uses
`clear_fields` for nullable context fields; archive is the reversible delete
semantic and there is no hard-delete tool. MCP capture forces `source="mcp"`.
Success and expected failure results include structured JSON.

Resources are `friction://items/{identifier}`, `friction://views/open`,
`friction://views/recent`, and `friction://schema`, all with
`application/json`. The read-only `triage_friction` prompt accepts optional
repository and tag filters plus a limit.

No editor opening, arbitrary file read, shell execution, SQL, import/export,
backup, doctor, database-path mutation, bulk mutation, or network listener is
exposed.

## Trust boundary

An MCP host runs the process as the same local user and therefore receives
access to private friction notes plus the explicitly exposed mutations. The
server does not add a second confirmation layer; approval and tool policy
belong to the host. Configure it only in a host that should be allowed to read
and change the selected Friction database.

Stdout contains protocol traffic only. Diagnostics and unexpected-error logs go
to stderr and user-facing tool results never contain tracebacks.
