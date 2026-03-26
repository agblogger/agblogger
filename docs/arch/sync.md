# Bidirectional Sync

## Model

AgBlogger uses a bidirectional sync model between the server-managed content tree and a local content directory. Sync is manifest-based and conflict-aware, so it reasons about prior shared state instead of blindly mirroring files in one direction.

## Managed Scope

Sync is limited to the content surface that AgBlogger treats as portable authoring data: site configuration, labels, pages, posts, and managed assets. Private runtime state and hidden application data are outside the sync boundary.

## Sync Protocol

The protocol separates planning from mutation. Clients first compare local state, server state, and prior shared state to compute a plan. They then apply uploads, deletions, merges, and downloads through the API.

One sync run follows this sequence:

- the client scans the local content tree and sends its current file manifest to the server
- the server compares client state, current server state, and the last shared manifest to return a plan: uploads, downloads, remote deletions, local deletions, and conflicts
- the client submits the chosen changes together with the last known shared commit
- the server applies writes under the normal content mutation boundary, performs content-aware merge handling for markdown posts when needed, updates the server manifest, and returns any files the client should re-download
- the client downloads the required server versions and updates its local sync metadata

The manifest represents the last agreed shared file state. The last shared commit gives the server a common merge base for conflict handling. When both client and server changed the same markdown post, the server attempts a structured merge. When a clean merge is not possible, the server keeps the server-side result, reports the conflict, and tells the client which files must be downloaded again.

This is a reconcile-and-commit protocol, not a blind mirror and not continuous replication.

## Conflict Handling

Conflicts are resolved with a three-way model using the last agreed state as the merge base. Structured content receives content-aware handling so post metadata and markdown body can be reconciled separately. When reconciliation cannot be made cleanly, the system preserves content and reports the conflict to the client.

## Relationship to Versioning

Git supports sync by preserving history and providing merge context, but it does not replace the core content model. The filesystem remains authoritative, and sync participates in the same write coordination boundary as other content mutations.

## Client Boundary

The sync client is a separate CLI companion that uses the same authenticated API boundary as the browser and other clients. It authenticates via interactive username/password login (token-login endpoint) and does not bypass the application by reading or writing server files directly.

## Code Entry Points

- `backend/api/sync.py` defines the sync HTTP endpoints.
- `backend/services/sync_service.py` contains sync planning, merge, and commit orchestration.
- `backend/models/sync.py` contains the sync manifest model and `backend/api/sync.py` defines sync-specific request/response schemas inline.
- `cli/sync_client.py` implements the local companion client.
