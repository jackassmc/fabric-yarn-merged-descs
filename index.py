import logging
import logging.config
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel
from typing_extensions import Self

from combined import DEFAULT_COMBINED_JSON, Combined, CombinedCombined, CombinedJarDesc


DIR = Path(__file__).parent
DEFAULT_INDEX_JSON = Path(DIR / "index.json")
BASE_URL = "https://jackassmc.github.io/fabric-yarn-merged-descs"


logging.config.fileConfig("logging.conf")
logger = logging.getLogger("index")


class IndexJar(BaseModel):
    version_id: str
    version_file_id: str
    version_release_time: datetime
    yarn_build: int
    jar_key: str

    path: Path
    url: str

    @classmethod
    def from_combined_jar(cls, combined_jar: CombinedJarDesc, yarn_build: int) -> Self:
        path = combined_jar.out_path.relative_to(DIR)
        return cls(
            version_id=combined_jar.version_id,
            version_file_id=combined_jar.version_file_id,
            version_release_time=combined_jar.version_release_time,
            yarn_build=yarn_build,
            jar_key=combined_jar.jar_key,
            path=path,
            url=f"{BASE_URL}/{path}",
        )


class IndexVersion(BaseModel):
    version_id: str
    version_file_id: str
    version_release_time: datetime
    yarn_build: int
    jars: dict[str, IndexJar]

    @classmethod
    def from_combined(cls, combined: CombinedCombined) -> Self:
        self = cls(
            version_id=combined.version_id,
            version_file_id=combined.version_file_id,
            version_release_time=combined.version_release_time,
            yarn_build=combined.yarn.build,
            jars=dict(),
        )
        for jar_key, jar in combined.jars.items():
            self.jars[jar_key] = IndexJar.from_combined_jar(jar, combined.yarn.build)
        return self


class Index(BaseModel):
    timestamp: datetime
    versions: dict[str, IndexVersion]

    @classmethod
    def empty(cls) -> Self:
        return cls(timestamp=datetime.min, versions=dict())

    @classmethod
    def new(cls) -> Self:
        self = cls.empty()
        self.update()
        return self

    @classmethod
    def load(cls, file: Path | str = DEFAULT_INDEX_JSON) -> Self:
        logger.info(f"Index.load {file}")
        return Index.parse_file(file)

    def save(self, file: Path | str = DEFAULT_INDEX_JSON) -> None:
        logger.info(f"Index.save {file} {self.timestamp}")
        Path(file).write_text(self.json(indent=2))

    def update(self, combined_json_file: Path | str = DEFAULT_COMBINED_JSON) -> bool:
        dirty = False

        combined_root = Combined.load(combined_json_file)
        if self.timestamp == combined_root.timestamp:
            # no changes and nothing to do
            logger.info(f"Index.update already up to date")
            dirty = False
        else:
            self.timestamp = combined_root.timestamp
            dirty = True

            self.versions = dict()

            for version_id, combined in combined_root.combined.items():
                if version_id not in self.versions:
                    self.versions[version_id] = IndexVersion.from_combined(combined)

            logger.info(f"Index.update updated")

        return dirty

Index.new().save()