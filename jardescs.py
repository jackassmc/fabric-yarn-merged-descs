import logging
import logging.config
from datetime import datetime
from itertools import chain
from pathlib import Path

from git.repo import Repo
from pydantic import BaseModel
from typing_extensions import Self

from util import StrAlias


DIR = Path(__file__).parent
JAR_DESCS_DIR = Path(DIR / "minecraft-jars-java-descriptions")
DEFAULT_JAR_DESCS_JSON = Path(JAR_DESCS_DIR / "index.json")


logging.config.fileConfig("logging.conf")
logger = logging.getLogger("jardescs")


class JarDescsMapping(BaseModel):
    version_id: str
    version_file_id: str
    version_release_time: datetime
    jar_key: str
    jar_sha1_meta: str

    @property
    def path(self) -> Path:
        return Path(JAR_DESCS_DIR / f"mappings/{self.version_id}-{self.jar_key}.tiny")


class JarDescs(BaseModel):
    timestamp: datetime
    mappings: dict[StrAlias.minecraft_version, dict[StrAlias.jar_key, JarDescsMapping]]

    @property
    def all(self) -> chain[JarDescsMapping]:
        return chain(*[version.values() for version in self.mappings.values()])

    @classmethod
    def load(cls, file: Path | str = DEFAULT_JAR_DESCS_JSON) -> Self:
        logger.info(f"JarDescs.load")
        return JarDescs.parse_file(file)

    def pull_and_update(self) -> bool:
        dirty = False

        # pull submodule
        logger.info(f"JarDescs.pull_and_update")
        repo = Repo(JAR_DESCS_DIR)
        repo.git.pull("origin", "master")

        # compare commit hash
        latest_timestamp = JarDescs.load().timestamp
        if self.timestamp == latest_timestamp:
            # no changes and nothing to do
            logger.info(f"JarDescs.pull_and_update already up to date")
        else:
            # there are changes
            dirty = True
            logger.info(f"JarDescs.pull_and_update updated to {latest_timestamp}")

        return dirty

    def get_version_id(self, version: str) -> str:
        for jar in self.all:
            if version in [jar.version_id, jar.version_file_id]:
                return jar.version_id
        raise Exception(f"JarDescs.get_version_id failed for {version=}")

    def get_version_file_id(self, version: str) -> str:
        for jar in self.all:
            if version in [jar.version_id, jar.version_file_id]:
                return jar.version_file_id
        raise Exception(f"JarDescs.get_version_file_id failed for {version=}")

    def get_version_release_time(self, version: str) -> datetime:
        for jar in self.all:
            if version in [jar.version_id, jar.version_file_id]:
                return jar.version_release_time
        raise Exception(f"JarDescs.get_version_release_time failed for {version=}")

    def get_jars(self, version: str) -> list[JarDescsMapping]:
        version_id = self.get_version_id(version)
        if version_id in self.mappings:
            return list(self.mappings[version_id].values())
        raise Exception(f"JarDescs.get_jars failed for {version=}")
