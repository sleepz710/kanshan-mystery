"""质量提示应从磁盘经目录、开局接口传给新浏览器，不依赖编剧会话。"""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.studio.mock import mock_story


@pytest.mark.parametrize("checked", [False, True, None])
def test_quality_metadata_survives_catalog_and_new_game_without_owner_session(checked):
    with TemporaryDirectory(prefix="kanshan-quality-status-") as directory:
        root = Path(directory)
        generated = root / "stories"
        generated.mkdir()
        story = mock_story()
        if checked is not None:
            story["checked"] = checked
        (generated / f"{story['id']}.yaml").write_text(yaml.safe_dump(story, allow_unicode=True), encoding="utf-8")
        application = create_app(stories_dir=root / "official", generated_stories_dir=generated)
        with TestClient(application) as client:
            catalog = client.get("/api/stories")
            assert catalog.status_code == 200
            response = client.post("/api/games", json={"story_id": story["id"]})
            assert response.status_code == 201
            for public in (catalog.json()[0], response.json()):
                if checked is None:
                    assert "checked" not in public
                else:
                    assert public["checked"] is checked
                assert "truth" not in public and "facts" not in public
