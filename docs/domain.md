# Domain

The primary entity is a friction item. It has a stable UUID, non-empty note,
lifecycle status, timestamps, optional source context, tags, JSON metadata, and
an integer revision.

Valid status transitions are:

```text
open -> done
open -> dismissed
done -> open
dismissed -> open
```

Setting the current status again is a no-op. Direct `done <-> dismissed`
transitions are invalid. Archiving is independent of status and is reversible.

Revisions begin at one and increase once for each actual mutation. Updates that
carry an expected revision use compare-and-swap semantics; stale writes fail
without changing the item or its event history.

All stored timestamps are timezone-aware UTC. Imported timestamps retain their
instant even when the legacy representation uses a local offset.

