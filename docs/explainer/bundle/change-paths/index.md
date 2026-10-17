# Change paths

* [Add a config key](add-a-config-key.md) - A value someone could reasonably choose differently becomes a snake_case key with its shipped default, read through the config helpers, listed in the manifest and the defaults document, and covered by the config test.
* [Add a Definition version](add-a-definition-version.md) - Changing a payload's shape means a new Definition file at version N+1 and importer code that emits it, never an edit of a version Anam already holds.
* [Add a record extractor](add-a-record-extractor.md) - An export that will never be sent again gets a deterministic script under records/extract that writes a records file, and no importer.
* [Add an importer](add-an-importer.md) - A new source is a folder with a manifest, a run.py that shapes payloads, and the Definitions it emits, plus a token line in Anam's importers file and an anam_submit instance in the gateway.
* [Release a new version](release-a-new-version.md) - Move the changelog's unreleased entries under the new number, set VERSION and every manifest to it, commit, tag, and lock the changed plugins on the gateway.
