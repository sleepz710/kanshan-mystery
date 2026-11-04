"""运行数据目录与只读应用资源分开。"""

import os
from pathlib import Path


def data_root() -> Path:
    configured = os.environ.get("KANSHAN_DATA_DIR")
    return Path(configured).expanduser().resolve() if configured else Path(__file__).resolve().parents[1] / "data"
