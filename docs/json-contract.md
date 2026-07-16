# JSON Contract v1

Machine-readable commands use schema version 1. Successful responses have this
shape:

```json
{"schema_version":1,"data":{},"error":null}
```

Failures keep the same envelope and put a stable code, human message, and
optional details in `error`. JSON output is written only to stdout; diagnostics
for human mode use stderr.

Request and response schemas are owned by `friction.contracts`. New optional
fields may be added within v1; removing fields, changing their meaning, or
changing enum values requires a new schema version.

Lifecycle changes use dedicated operations. The generic update operation may
change note, source context, tags, and metadata, and requires the current
revision.

