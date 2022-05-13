import gzip
import hashlib
import logging
import logging.config
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import subprocess
from typing import Any

import requests
from pydantic import BaseModel
from typing_extensions import Self

from fabric import Fabric, FabricYarn
from jardescs import JarDescs, JarDescsMapping
from util import progress, sort_dict


DIR = Path(__file__).parent
MAPPINGIO_JAR = Path(DIR / "mapping-io-cli-0.3.0-all.jar")
MAPPINGS_DIR = Path(DIR / "mappings")
DEFAULT_COMBINED_JSON = Path(DIR / "combined.json")


logging.config.fileConfig("logging.conf")
logger = logging.getLogger("combined")


class CombinedJarDesc(JarDescsMapping):
    pass

    @property
    def out_path(self) -> Path:
        return Path(MAPPINGS_DIR / f"{self.version_id}-{self.jar_key}.json")

    @classmethod
    def from_jar_descs_mapping(cls, jar_descs_mapping: JarDescsMapping) -> Self:
        return CombinedJarDesc.parse_obj(jar_descs_mapping)

    def mappingio(self, yarn: "CombinedYarn") -> None:
        mappingio_args = [
            "yarnfulldescs",
            self.path.relative_to(Path.cwd()),
            yarn.path.relative_to(Path.cwd()),
            self.out_path.relative_to(Path.cwd()),
            "JSON",
        ]
        logger.info(f"CombinedJarDesc.mappingio {' '.join(str(arg) for arg in mappingio_args)}")
        return_code = subprocess.call(["java", "-jar", MAPPINGIO_JAR, *mappingio_args])
        if return_code:
            raise Exception("mapping-io-cli error")


class CombinedYarn(FabricYarn):
    version_id: str
    version_release_time: datetime

    @property
    def path(self) -> Path:
        return Path(MAPPINGS_DIR / f"{self.version_id}-yarn.tiny")

    @classmethod
    def from_fabric_yarn(
        cls,
        fabric_yarn: FabricYarn,
        version_id: str,
        version_release_time: datetime,
    ) -> Self:
        return cls(
            version_id=version_id,
            version_file_id=fabric_yarn.version_file_id,
            version_release_time=version_release_time,
            separator=fabric_yarn.separator,
            build=fabric_yarn.build,
            fabric_name=fabric_yarn.fabric_name,
        )

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, CombinedYarn):
            return (
                self.version_id == other.version_id
                and self.version_file_id == other.version_file_id
                and self.version_release_time == other.version_release_time
                and self.separator == other.separator
                and self.build == other.build
                and self.fabric_name == other.fabric_name
            )
        return False

    def _iter(self, **kwargs: Any):
        for key in [
            "version_id",
            "version_file_id",
            "version_release_time",
            "separator",
            "build",
            "fabric_name",
        ]:
            yield key, getattr(self, key)

    def download(self) -> None:
        cache = self.path.with_suffix(".tiny.gz")

        cache_hit = False
        if cache.exists() and self.path.exists():
            logger.info(f"CombinedYarn.download {self.tiny_gz_url}.sha1")
            r = requests.get(self.tiny_gz_url + ".sha1")
            r.raise_for_status()

            online_sha1 = r.text
            local_sha1 = hashlib.sha1(cache.read_bytes()).hexdigest()
            cache_hit = online_sha1 == local_sha1

        if cache_hit:
            logger.info(f"CombinedYarn.download {self.tiny_gz_url} cache hit")
            return

        logger.info(f"CombinedYarn.download {self.tiny_gz_url}")
        r = requests.get(self.tiny_gz_url)
        r.raise_for_status()

        cache.write_bytes(r.content)
        self.path.write_text(gzip.open(BytesIO(r.content)).read().decode("utf-8"))


class CombinedCombined(BaseModel):
    version_id: str
    version_file_id: str
    version_release_time: datetime
    yarn: CombinedYarn
    jars: dict[str, CombinedJarDesc]

    def update(self, fabric_yarn: FabricYarn, jar_descs_mappings: list[JarDescsMapping]) -> bool:
        dirty = False
        yarn_dirty = False

        new_yarn = CombinedYarn.from_fabric_yarn(
            fabric_yarn=fabric_yarn,
            version_id=self.version_id,
            version_release_time=self.version_release_time,
        )
        if self.yarn != new_yarn:
            self.yarn = new_yarn
            new_yarn.download()
            dirty = True
            yarn_dirty = True

        for mapping in jar_descs_mappings:
            new_jar = CombinedJarDesc.from_jar_descs_mapping(mapping)
            jar_dirty = False

            if mapping.jar_key not in self.jars or self.jars[mapping.jar_key] != new_jar:
                self.jars[mapping.jar_key] = new_jar
                dirty = True
                jar_dirty = True

            if yarn_dirty or jar_dirty:
                # create or update mapping files
                new_jar.mappingio(self.yarn)

        if dirty:
            # sort
            self.jars = sort_dict(self.jars)

        return dirty

    def mappingio(self) -> None:
        logger.info(f"CombinedCombined.mappingio")
        for jar in self.jars.values():
            jar.mappingio(self.yarn)


class Combined(BaseModel):
    timestamp: datetime
    jar_descs_timestamp: datetime
    fabric_timestamp: datetime
    combined: dict[str, CombinedCombined]

    @classmethod
    def empty(cls) -> Self:
        return cls(
            timestamp=datetime.min,
            jar_descs_timestamp=datetime.min,
            fabric_timestamp=datetime.min,
            combined=dict(),
        )

    @classmethod
    def new(cls) -> Self:
        self = cls.empty()
        self.update()
        return self

    @classmethod
    def load(cls, file: Path | str = DEFAULT_COMBINED_JSON) -> Self:
        logger.info(f"Combined.load {file}")
        return Combined.parse_file(file)

    def save(self, file: Path | str = DEFAULT_COMBINED_JSON) -> None:
        self.timestamp = datetime.now(timezone.utc)
        logger.info(f"Combined.save {file} {self.timestamp}")
        Path(file).write_text(self.json(indent=2))

    def update(self) -> bool:
        dirty = False

        fabric = Fabric.load()
        jar_descs = JarDescs.load()

        if (
            self.fabric_timestamp == fabric.timestamp
            and self.jar_descs_timestamp == jar_descs.timestamp
        ):
            # no changes, nothing to do
            logger.info("Combined.update already up to date")
            return False

        i_max = len(fabric.yarn)
        for i, (version_file_id, fabric_yarn) in enumerate(fabric.yarn.items()):
            prefix_start = f"Combined.update {progress(i, i_max)}"
            prefix_end = f"Combined.update {progress(i + 1, i_max)}"

            version_id = jar_descs.get_version_id(version_file_id)
            version_release_time = jar_descs.get_version_release_time(version_id)

            logger.info(f"{prefix_start} {version_id}")

            # init new
            if version_id not in self.combined:
                combined_yarn = CombinedYarn.from_fabric_yarn(
                    fabric_yarn=fabric_yarn,
                    version_id=version_id,
                    version_release_time=version_release_time,
                )
                combined_yarn.download()

                combined_jars = {
                    j.jar_key: CombinedJarDesc.from_jar_descs_mapping(j)
                    for j in jar_descs.get_jars(version_id)
                }

                self.combined[version_id] = CombinedCombined(
                    version_id=version_id,
                    version_file_id=version_file_id,
                    version_release_time=version_release_time,
                    yarn=combined_yarn,
                    jars=combined_jars,
                )
                self.combined[version_id].mappingio()
                dirty = True
                logger.info(f"{prefix_end} {version_id} initialized")
                continue

            # update existing
            combined_dirty = self.combined[version_id].update(
                fabric_yarn=fabric_yarn,
                jar_descs_mappings=jar_descs.get_jars(version_id),
            )

            if combined_dirty:
                logger.info(f"{prefix_end} {version_id} updated")
                dirty = True
            else:
                logger.info(f"{prefix_end} {version_id} skipped")

        if dirty:
            # sort by version
            self.combined = sort_dict(
                self.combined,
                key=lambda i: fabric.sorted_version_file_ids.index(i[1].version_file_id),
            )

        # update timestamps
        self.fabric_timestamp = fabric.timestamp
        self.jar_descs_timestamp = jar_descs.timestamp

        logger.info("Combined.update done")
        return dirty


if __name__ == "__main__":
    combined = Combined.load()
    if combined.update():
        combined.save()
