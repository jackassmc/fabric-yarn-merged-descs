import sys
from datetime import datetime, timezone
from pathlib import Path

from git.repo import Repo
from git.util import Actor

from combined import Combined
from fabric import Fabric
from index import Index
from jardescs import JarDescs


DIR = Path(__file__).parent


def update(push: bool = False) -> None:
    new_data = False

    # update jardescs
    jar_descs = JarDescs.load()
    if jar_descs.pull_and_update():
        new_data = True

    # update fabric
    fabric = Fabric.load()
    if fabric.update():
        fabric.save()
        new_data = True

    if new_data:
        # update combined
        combined = Combined.load()
        if combined.update():
            combined.save()

            # update index
            index = Index.load()
            if index.update():
                index.save()

    if push:
        repo = Repo(DIR)
        if repo.is_dirty(untracked_files=True):
            repo.git.add(all=True)
            gh_actions_bot = Actor(
                "github-actions[bot]",
                "github-actions[bot]@users.noreply.github.com",
            )
            repo.index.commit(
                message=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                author=gh_actions_bot,
                committer=gh_actions_bot,
            )
            repo.git.push()


if __name__ == "__main__":
    update(push=(len(sys.argv) > 1 and sys.argv[1] == "push"))
