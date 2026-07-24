"""Backup and Export Utility for JATAYU OS."""

import zipfile
import os
from pathlib import Path
from datetime import datetime, timezone
from jatayu.config import get_config

def create_backup_archive() -> str:
    """Creates a ZIP archive of the entire data directory for export.
    Returns the absolute path to the generated archive.
    """
    config = get_config()
    data_dir = Path(config["data_dir"])
    backup_dir = Path(config.get("backup_dir", data_dir.parent / "backups"))
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = backup_dir / f"jatayu_export_{timestamp}.zip"
    
    # We will zip the data directory
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(data_dir):
            root_path = Path(root)
            for file in files:
                file_path = root_path / file
                # Skip temp or lock files if any
                if file.endswith(".lock") or file.endswith(".tmp"):
                    continue
                # The arcname is the relative path within the zip
                arcname = file_path.relative_to(data_dir.parent)
                zf.write(file_path, arcname)
                
    return str(archive_path)
