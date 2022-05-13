import logging
import logging.config
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel
from typing_extensions import Self

from util import sort_dict


DIR = Path(__file__).parent
MAPPINGS_DIR = Path(DIR / "mappings")
DEFAULT_FABRIC_JSON = Path(DIR / "fabric.json")
FARBRIC_VERSIONS_URL = "https://meta.fabricmc.net/v2/versions"
YARN_MAVEN_URL = "https://maven.fabricmc.net/net/fabricmc/yarn"


logging.config.fileConfig("logging.conf")
logger = logging.getLogger("fabric")


class FabricYarn(BaseModel):
    version_file_id: str
    separator: str
    build: int
    fabric_name: str

    @property
    def tiny_gz_url(self) -> str:
        return f"{YARN_MAVEN_URL}/{self.fabric_name}/yarn-{self.fabric_name}-tiny.gz"

    @classmethod
    def from_json(cls, data: Any) -> Self:
        for key in ["gameVersion", "separator", "build", "version"]:
            if key not in data:
                raise Exception(f"FabricYarn.from_json missing {key=}")

        return cls(
            version_file_id=data["gameVersion"],
            separator=data["separator"],
            build=data["build"],
            fabric_name=data["version"],
        )

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, FabricYarn):
            return (
                self.version_file_id == other.version_file_id
                and self.separator == other.separator
                and self.build == other.build
                and self.fabric_name == other.fabric_name
            )
        return False



class Fabric(BaseModel):
    timestamp: datetime
    yarn: dict[str, FabricYarn]

    sorted_version_file_ids: list[str]

    @classmethod
    def empty(cls) -> Self:
        return cls(timestamp=datetime.min, yarn=dict(), sorted_version_file_ids=list())

    @classmethod
    def new(cls, fabric_versions_url: str = FARBRIC_VERSIONS_URL) -> Self:
        self = cls.empty()
        self.update(fabric_versions_url)
        return self

    @classmethod
    def load(cls, file: Path | str = DEFAULT_FABRIC_JSON) -> Self:
        logger.info(f"Fabric.load {file}")
        return Fabric.parse_file(file)

    def save(self, file: Path | str = DEFAULT_FABRIC_JSON) -> None:
        self.timestamp = datetime.now(timezone.utc)
        logger.info(f"Fabric.save {file} {self.timestamp}")
        Path(file).write_text(self.json(indent=2))

    def update(self, fabric_versions_url: str = FARBRIC_VERSIONS_URL) -> bool:
        dirty = False

        logger.info(f"Fabric.update {fabric_versions_url}")
        r = requests.get(fabric_versions_url)
        r.raise_for_status()

        for mapping in r.json()["mappings"]:
            fabric_yarn = FabricYarn.from_json(mapping)

            # remember order
            if fabric_yarn.version_file_id not in self.sorted_version_file_ids:
                self.sorted_version_file_ids.append(fabric_yarn.version_file_id)

            # save yarn version
            if fabric_yarn.version_file_id not in self.yarn or (
                fabric_yarn != self.yarn[fabric_yarn.version_file_id]
                and fabric_yarn.build > self.yarn[fabric_yarn.version_file_id].build
            ):
                self.yarn[fabric_yarn.version_file_id] = fabric_yarn
                dirty = True

        if dirty:
            # sort versions
            self.yarn = sort_dict(self.yarn, key=lambda i: self.sorted_version_file_ids.index(i[0]))

        return dirty


if __name__ == "__main__":
    fabric = Fabric.load()
    if fabric.update():
        fabric.save()
