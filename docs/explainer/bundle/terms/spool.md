---
type: term
title: Spool
description: A folder of JSON-lines files that the gateway's OwnTracks plugin writes, one line per message the phone posted, which two importers read and neither modifies.
timestamp: 2026-10-17T00:00:00Z
---

The layout is `<spool_dir>/<device>/<YYYY-MM>.jsonl`. Each line is `{id, body, received_at}` where `body` is the phone's message exactly as posted, as a string. The [OwnTracks importer](/components/importer-owntracks.md) groups location messages into hours. The [stays importer](/components/importer-stays.md) reads the same spool to find stops. A last line without a newline is a write in progress and is not read yet. See [Spool line](/data-structures/spool-line.md).
