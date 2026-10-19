# Data structures

* [Admission receipt](admission-receipt.md) - Anam's 200 answer to a batch, with the new watermark, the change count and one outcome per envelope, which the client accepts only when every part is present and consistent.
* [Batch event](batch-event.md) - The ductile event an importer emits for each batch, named <plugin>.batch, carrying envelopes, the Definition manifests as text, a label, and optionally a snapshot label and documents.
* [Cached Logbook result](cached-result.md) - One JSON file per workout under cache_dir, holding the Logbook's result object and its strokes exactly as fetched.
* [Definition manifest](definition-manifest.md) - A JSON file with a meta block and a closed JSON Schema, in the format Anam publishes and an importer carries, one file per facet type.
* [Document reference](document-ref.md) - One entry in a batch event's documents list, naming a document's folder-relative path and the local file whose bytes anam_submit posts to Anam's library.
* [Envelope](envelope.md) - The message Anam accepts, with the type, the Definition version, the payload, and an optional asserted person.
* [Plugin manifest](plugin-manifest.md) - The manifest.yaml in each plugin folder, which tells the gateway the plugin's commands, the events each emits, and its required and optional config keys.
* [Plugin request](plugin-request.md) - The one JSON object a plugin reads from stdin, naming a command and carrying the instance config, any granted secrets, and the triggering event.
* [Plugin response](plugin-response.md) - The one JSON object a plugin writes to stdout, either ok with a result line and events or error with a message and a retry flag, plus info log lines.
* [Records file](records-file.md) - A YAML or JSON file with a document, an extracted block and a list of records, each a facet type, an id and the payload fields.
* [Sidecar file](sidecar-file.md) - The <file>.meta.yaml beside a document, a mapping with a required date and optional title, note and other fields that become part of the record.document payload.
* [Snapshot label](snapshot-label.md) - The small object a resend-everything run puts on every batch, with a run id, the part number, the part count and the facet types the run claims to cover.
* [Spool line](spool-line.md) - One JSON line of the OwnTracks spool, holding the receiver's id, the phone's message body as text, and when it was received.
* [Stay payload](stay-payload.md) - The payload of a place.stay envelope, with an id, the device, the start and end, the centroid, the fix count, the spread in metres and an optional named place.
