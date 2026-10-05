"""Publish validated draft profiles and rules as one immutable release."""

import argparse
import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.adapters.reports import CONFIG, load_draft_pair
from app.domain.routing import DomainError


def publish(config_dir: Path, author: str, reason: str) -> str:
    author, reason = author.strip(), reason.strip()
    if not (1 <= len(author) <= 128 and 1 <= len(reason) <= 500):
        raise DomainError("Укажите автора (до 128 символов) и причину (до 500 символов)", 422)
    profiles, rules = load_draft_pair(config_dir)
    release_id = uuid.uuid4().hex
    release = {
        "schema_version": 1,
        "release_id": release_id,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "author": author,
        "reason": reason,
        "profiles": profiles,
        "rules": rules,
    }
    contents = (json.dumps(release, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    releases_dir = config_dir / "releases"
    releases_dir.mkdir(exist_ok=True)
    release_path = releases_dir / f"{release_id}.json"
    with release_path.open("xb") as file:
        file.write(contents)
        file.flush()
        os.fsync(file.fileno())
    pointer = {
        "schema_version": 1,
        "release_id": release_id,
        "sha256": hashlib.sha256(contents).hexdigest(),
    }
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".active-release-",
            suffix=".tmp",
            dir=config_dir,
            delete=False,
        ) as file:
            temp_path = Path(file.name)
            json.dump(pointer, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, config_dir / "active-release.json")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return release_id


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish a validated Meditron configuration release"
    )
    parser.add_argument("--author", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        release_id = publish(CONFIG, args.author, args.reason)
    except (DomainError, OSError) as exc:
        print(exc.message if isinstance(exc, DomainError) else f"Ошибка публикации: {exc}")
        return 1
    print(f"Опубликован релиз конфигурации {release_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
