---
type: decision
title: Fetch and shape are separate commands
description: The Concept2 importer reads the remote API in a fetch command that fills a local cache, and shapes only the cache in handle and poll, so shaping never touches the network.
timestamp: 2026-10-17T00:00:00Z
resource: concept2/run.py#fetch
anchor: "def fetch(request: Dict[str, Any]) -> Dict[str, Any]:"
basis: code
tier: detail
alternatives:
  - Call the API from handle and poll, which mixes remote failure modes into shaping and makes a resend depend on the network.
  - Keep the fetched data in memory only, which leaves nothing for a rebuild to read.
affects:
  - /components/importer-concept2.md
  - /workflows/fetch-and-shape-a-concept2-workout.md
tested_by:
  - tests/test_concept2.py#test_fetch_caches_every_result_with_its_strokes_and_a_second_fetch_fetches_nothing
---

**Choice.** `fetch` is the source's reader, with the token, the deadline and the retry rules. `handle`, `poll` and `health` read a folder of JSON files. The cache follows the Logbook's listing whole, including deletions.

**Why.** The cache is the source as far as the rest of the importer is concerned, so a rebuild or a drill needs no network or token. The same shape appears in the OwnTracks case, where a gateway plugin pulls into a spool and the importers read the spool.
