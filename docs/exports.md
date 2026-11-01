# Reproducible Dataset Exports

Export a completed, verified dataset run locally:

```powershell
.\.venv\Scripts\flask.exe pilot export --profile pilot --seed 20261022
```

The command accepts `--run-reference` to select a run and `--format` with
`all` (the default), `csv`, `json`, or `sql`. Every selected export is checked
against the stored run counts and checksums before any files are written.

## Output layout

Exports are written beneath the project-local `exports/` directory:

```text
exports/
├── csv/<run-reference>/<table>.csv
├── json/<run-reference>.json
├── json/<run-reference>.ground_truth.json
├── sql/<run-reference>.sql
├── sql/<run-reference>.ground_truth.sql
└── manifests/<run-reference>.json
```

CSV files use fixed table-specific columns. The core JSON and SQL files do not
contain ground truth; labels are placed in separate, clearly named files. The
manifest records the run profile, seed, fixed reference time, generator
version, record counts, dataset checksums, selected formats, and each generated
export artifact's SHA-256 digest and byte size. CSV artifact entries also
include row counts. The manifest itself is not included in its own file list
and therefore has no self-hash.

The run checksums are canonical SHA-256 hashes keyed by business references.
Generated core records are scoped to the run-reference prefix, ground truth
is scoped to the exact run reference, and the shared risk-rule catalogue is
included in full. Repeating an export for the same verified run with the same
selected formats produces identical export files and manifest contents.

## Safety

Exports contain generated dataset records and metadata only; they never contain
database URLs, credentials, or environment configuration. Output files are
local and ignored by Git. SQL identifiers and columns are selected from fixed
allowlists, and data values are encoded rather than interpolated as SQL syntax.
SQL exports are generated artifacts only: review and import them manually into
an isolated schema. The application does not execute exported SQL.

The export command verifies the run through the configured generator and
read-only evaluation-core database sessions. Ground truth is emitted
separately and should be handled as evaluation-only data.
