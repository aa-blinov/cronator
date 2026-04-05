# Artifacts System — User Guide

## Overview

The artifacts system lets scripts save files during execution. Artifacts can include reports, logs, images, data files, or any other output you want to persist and download from the UI.

## Features

- ✅ Save files up to 10 MB each
- ✅ Automatic unique filename generation with timestamp suffix
- ✅ Filename validation and sanitization
- ✅ Disk space check before saving (minimum 100 MB free required)
- ✅ Artifact metadata stored in the database for fast access
- ✅ Download via UI with original filenames
- ✅ Delete individual artifacts
- ✅ Bulk clear all artifacts via Settings

## Usage in scripts

### Basic example

```python
from cronator_lib import get_logger, save_artifact

log = get_logger()

data = "Hello, World!".encode('utf-8')

try:
    saved_name = save_artifact("report.txt", data)
    log.success(f"Artifact saved as {saved_name}")
except Exception as e:
    log.error(f"Failed to save artifact: {e}")
```

### CSV report

```python
import csv
from io import StringIO
from cronator_lib import save_artifact

csv_buffer = StringIO()
writer = csv.writer(csv_buffer)
writer.writerow(['Date', 'Metric', 'Value'])
writer.writerow(['2026-01-27', 'Users', 1523])
writer.writerow(['2026-01-27', 'Revenue', 45236.50])

csv_data = csv_buffer.getvalue().encode('utf-8')
save_artifact("daily_report.csv", csv_data)
```

### JSON snapshot

```python
import json
from datetime import datetime
from cronator_lib import save_artifact

config = {
    "version": "1.0",
    "timestamp": datetime.now().isoformat(),
    "settings": {"debug": False, "max_retries": 3}
}

json_data = json.dumps(config, indent=2).encode('utf-8')
save_artifact("config_backup.json", json_data)
```

### Binary files (images, etc.)

```python
from cronator_lib import save_artifact

# Example with PIL/Pillow
# from PIL import Image
# import io

# img = Image.new('RGB', (100, 100), color='red')
# buffer = io.BytesIO()
# img.save(buffer, format='PNG')
# image_data = buffer.getvalue()

# save_artifact("chart.png", image_data)
```

## Limits and validation

### File size
- **Maximum:** 10 MB per file
- Exceeding the limit raises `ValueError` with a descriptive message

### Filename
- **Maximum length:** 200 characters
- **Allowed characters:** letters (a-z, A-Z), digits (0-9), dot (.), dash (-), underscore (_)
- **Blocked extensions:** `.exe`, `.bat`, `.sh`, `.cmd`, `.com`, `.pif`, `.scr`, `.vbs`, `.ps1`
- Spaces are automatically replaced with underscores
- Path traversal (`../`, absolute paths) is rejected

### Disk space
- **Minimum:** 100 MB free disk space
- Checked before saving each file

### Unique names
Files are automatically saved with a timestamp suffix to avoid conflicts:
- Input name: `report.csv`
- Saved name: `report_1738012345.csv`

## Managing artifacts via the UI

### Viewing artifacts for an execution

1. Go to the **Executions** page
2. Click an execution (executions with artifacts have a 📦 badge)
3. Scroll down to the **Artifacts** section
4. Each artifact shows:
   - Original filename
   - File size
   - Creation date
   - **Download** and **Delete** buttons

### Downloading artifacts

Click **Download** next to an artifact. The file is served with its original filename.

### Deleting artifacts

- **Single artifact:** click **Delete** → confirm
- **All artifacts for an execution:** delete the execution (artifacts are cascade-deleted)
- **All artifacts in the system:** Settings → Artifacts Storage → **Clear All Artifacts**

### Storage statistics

On the **Settings** page, the **Artifacts Storage** section shows:
- Total number of artifacts
- Total space used
- Number of executions that have artifacts
- Free disk space remaining

## API endpoints

### List artifacts for an execution
```http
GET /api/executions/{execution_id}/artifacts
```

Response:
```json
{
  "items": [
    {
      "id": 1,
      "execution_id": 42,
      "filename": "report_1738012345.csv",
      "original_filename": "report.csv",
      "size_bytes": 1024,
      "created_at": "2026-01-27T12:00:00Z"
    }
  ],
  "total": 1
}
```

### Download an artifact
```http
GET /api/executions/{execution_id}/artifacts/{artifact_id}
```

Returns the file with `Content-Disposition: attachment; filename="<original_filename>"`.

### Delete an artifact
```http
DELETE /api/executions/{execution_id}/artifacts/{artifact_id}
```

### Artifact storage stats
```http
GET /api/settings/artifacts-stats
```

### Clear all artifacts
```http
POST /api/settings/clear-artifacts
```

## Storage layout

### Directory structure
```
data/
└── artifacts/
    ├── 1/          # execution_id=1
    │   ├── report_1738012345.csv
    │   └── config_1738012346.json
    ├── 2/          # execution_id=2
    │   └── log_1738012347.txt
    ...
```

### Database schema

`artifacts` table columns:
- `id` — primary key
- `execution_id` — foreign key to executions (CASCADE DELETE)
- `filename` — on-disk filename (with timestamp suffix)
- `original_filename` — original name provided by the script
- `size_bytes` — file size in bytes
- `created_at` — creation timestamp

`executions` table additional columns:
- `artifacts_count` — number of artifacts for this execution
- `artifacts_size_bytes` — total size of all artifacts

## Error handling

### ValueError
Raised when:
- Filename exceeds 200 characters
- Filename contains invalid characters
- File size exceeds 10 MB
- `CRONATOR_EXECUTION_ID` is not set in the environment
- File has a blocked extension

### OSError
Raised when:
- Less than 100 MB disk space available
- Filesystem write error
- Permission denied

### Example

```python
from cronator_lib import save_artifact, get_logger

log = get_logger()

try:
    save_artifact("report.csv", data)
    log.success("Artifact saved")
except ValueError as e:
    log.error(f"Invalid artifact: {e}")
except OSError as e:
    log.error(f"Storage error: {e}")
except Exception as e:
    log.error(f"Unexpected error: {e}")
```

## Running migrations

The artifacts system requires the `a1b2c3d4e5f6_add_artifacts_support` migration:

```bash
alembic upgrade head
```

When running via Docker Compose, migrations are applied automatically on startup.

The migration:
- Creates the `artifacts` table
- Adds `artifacts_count` and `artifacts_size_bytes` columns to `executions`
- Creates required indexes

## Full example script

See `scripts/artifacts_demo/script.py` for a complete working example demonstrating:
- Saving CSV reports
- Saving JSON snapshots
- Saving text logs
- Error handling
- Logger integration

## Best practices

1. **File size:** Keep artifacts small (under 1 MB when possible)
2. **Naming:** Use descriptive names (`daily_report.csv` rather than `report.csv`)
3. **Cleanup:** Regularly remove old artifacts via Settings
4. **Error handling:** Always wrap `save_artifact()` in try/except
5. **Logging:** Log both successful saves and failures
6. **Format:** Prefer text formats (CSV, JSON, TXT) over binary when you have a choice

## Troubleshooting

### Artifact not appearing in the UI
- Check execution logs for `ARTIFACT_SAVED:` messages
- Verify the file exists under `data/artifacts/{execution_id}/`
- Check the `artifacts` table in the database

### "Not enough disk space"
- Free up disk space or expand the volume
- Clear old artifacts via Settings → Clear All Artifacts
- Check disk quotas

### "Filename too long"
Shorten the name to 200 characters or fewer.

### "File exceeds maximum size"
- Compress data before saving (gzip, zip)
- Split into multiple smaller artifacts
- Save only the critical subset of data

## Configuration

In `app/config.py`:
```python
# Directory for artifact storage
artifacts_dir: Path = Path("./data/artifacts")

# Maximum file size in MB
max_artifact_size_mb: int = 10

# Minimum free disk space in MB
min_free_space_mb: int = 100

# Maximum filename length
max_filename_length: int = 200
```

## Security

✅ **Path validation:** Prevents path traversal attacks
✅ **Filename sanitization:** Strips dangerous characters
✅ **Extension blocking:** Rejects executable file types
✅ **Execution isolation:** Each execution has its own subdirectory
✅ **Limits:** Enforced size and space constraints
