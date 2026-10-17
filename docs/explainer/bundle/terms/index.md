# Terms

* [Anam](anam.md) - The service this repository feeds, which keeps one person's record as append-only facts and accepts data only through envelopes posted by importers.
* [Asserted person](asserted-person.md) - The person id an envelope claims the data belongs to, set from the plugin's person_id config, or left out when the source cannot say.
* [Batch](batch.md) - At most 49 envelopes sent in one request, which Anam admits whole or refuses whole in a single transaction.
* [ductile](ductile.md) - A gateway that runs small plugins on schedules and events, passing each one JSON on stdin and routing the events it returns, used here to run importers.
* [Envelope](envelope.md) - The one message Anam accepts, a facet type, a Definition version and a payload, with an optional asserted person and nothing that names a source.
* [Facet](facet.md) - One immutable fact in Anam's record, made from a payload an importer sent, with a type, an identity, a fact time and a content hash.
* [Facet Definition](facet-definition.md) - A JSON manifest that names a facet type and version, the closed JSON Schema its payload must satisfy, and how its identity and fact time are read from the payload.
* [Fact time](fact-time.md) - The moment a fact was true in the world, read by Anam from a pointer in the payload using the Definition's layout and zone.
* [Identity key](identity-key.md) - The list of payload fields a Definition composes a facet's identity from, so an importer must send those fields and nothing else decides which fact a row is.
* [Importer](importer.md) - A plugin that reads one source, shapes its rows to a Facet Definition, and emits batch events for anam_submit to post.
* [Lookback window](lookback-window.md) - The number of days of recent files or messages that a handle run re-reads, set by the lookback_days key, because the source has no cursor and the importer keeps no state.
* [No-op](no-op.md) - The outcome Anam gives an envelope whose payload hash matches the facet it already holds, which is what makes resending everything safe.
* [Records file](records-file.md) - A YAML or JSON file of facts written down from a source document by hand or by an extractor script, with the document and extraction method as provenance.
* [Sidecar](sidecar.md) - A .meta.yaml file beside a document that states the document's own date and any title or note, because the date is not in the file's bytes.
* [Snapshot](snapshot.md) - A labelled set of batches that together claim to be everything a source holds of some types, letting Anam report what it holds live that the run did not carry.
* [Source](source.md) - The name Anam attributes a fact to, set by the token an importer posts under and never by the importer's payload.
* [Spool](spool.md) - A folder of JSON-lines files that the gateway's OwnTracks plugin writes, one line per message the phone posted, which two importers read and neither modifies.
