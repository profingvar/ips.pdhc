"""#893 — the compose project name and the external volume, guarded.

#893 (EPS D2) recommends NOT renaming ips to eps, and lists three
operator-gated hazards of doing it. Two of them are facts about this
repo's compose file, and a test is what keeps them facts.

== What #893 got wrong, and why it matters ==

The ticket states `COMPOSE_PROJECT_NAME` is "not pinned anywhere in this
repo — verified, no occurrence in any .yml, .sh, .env* or .md". The
verification is accurate and the conclusion is not: the project name IS
pinned, by `name: ips` on the FIRST LINE of `gateway/docker-compose.yml`,
which is Compose v2's own project-name key. That is why the live
containers are `ips-app-1` / `ips-db-1` and not `ipspdhc-*`, and the
hyphens are themselves the evidence that production runs Compose v2 — v1
named containers `project_service_1` with underscores.

So the grep looked for the VARIABLE and missed the KEY that does the same
job. Same lesson as #804 and as the KNOWN_SERVICES table that was wrong
twice: searching for an identifier is not checking for a capability.

== The hazard, correctly stated ==

Measured 2026-11-02 with a throwaway compose file: `COMPOSE_PROJECT_NAME`
in the environment OVERRIDES `name:` in the file. A file saying
`name: from-the-file`, with `COMPOSE_PROJECT_NAME=from-the-env` set,
resolves to `from-the-env`.

So the risk was never an unpinned project. It is that the variable, if
anyone ever sets it, silently wins — and a blank nobody filled is a blank
somebody can fill wrongly. That is exactly how dashboard's project became
`current` (#113), where a release swap under the wrong name created a
second parallel compose project with colliding ports and volumes.

Hence the value is now written in `.env.example` as well, and this file
asserts the two copies AGREE. Two pins that can disagree are worse than
one.

== The volume ==

`pgdata` is declared `name: ips_pgdata`, `external: true`. External means
compose does not own it, so a project rename cannot orphan it — #893
calls that "the good luck". A test makes it something other than luck:
dropping `external: true` would hand ownership to compose, and a
`down -v` or a project rename could then destroy it. A wrong-direction
copy between volumes during the March 2026 gateway->planp rename
destroyed a production database irrecoverably.
"""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = REPO / "docker-compose.yml"
ENV_EXAMPLE = REPO / ".env.example"

EXPECTED_PROJECT = "ips"
EXPECTED_VOLUME = "ips_pgdata"


@pytest.fixture(scope="module")
def compose_text():
    assert COMPOSE.is_file(), f"missing {COMPOSE}"
    return COMPOSE.read_text()


@pytest.fixture(scope="module")
def env_text():
    assert ENV_EXAMPLE.is_file(), f"missing {ENV_EXAMPLE}"
    return ENV_EXAMPLE.read_text()


def _compose_name(text: str) -> str | None:
    m = re.search(r"^name:\s*(\S+)\s*$", text, re.MULTILINE)
    return m.group(1) if m else None


def _env_project(text: str) -> str | None:
    m = re.search(r"^COMPOSE_PROJECT_NAME=(\S+)\s*$", text, re.MULTILINE)
    return m.group(1) if m else None


class TestTheProjectIsPinned:
    def test_the_compose_file_pins_the_project(self, compose_text):
        """The authoritative pin, which #893 reported as absent."""
        assert _compose_name(compose_text) == EXPECTED_PROJECT

    def test_the_env_example_documents_the_SAME_value(self, env_text):
        assert _env_project(env_text) == EXPECTED_PROJECT

    def test_THE_TWO_PINS_AGREE(self, compose_text, env_text):
        """The check that earns the second pin its place.

        `COMPOSE_PROJECT_NAME` overrides the file's `name:`, so two pins
        that disagree are worse than one — the environment would win
        silently and the compose file would read as if it had decided.
        """
        assert _compose_name(compose_text) == _env_project(env_text)

    def test_the_pin_matches_the_live_container_names(self):
        """Compose v2 names a container `<project>-<service>-<N>`.
        CLAUDE.md §3 records the live names as `ips-app-1` / `ips-db-1`,
        so the project must be `ips` — changing the pin without changing
        the deployment would create a second set of containers beside
        the running ones.
        """
        for live in ("ips-app-1", "ips-db-1"):
            project, service, index = live.rsplit("-", 2)
            assert project == EXPECTED_PROJECT
            assert service in ("app", "db")
            assert index == "1"


class TestTheVolumeIsExternal:
    def test_pgdata_is_named_and_external(self, compose_text):
        """Dropping either line hands ownership of the production data
        to compose."""
        block = compose_text.split("volumes:")[-1]
        assert f"name: {EXPECTED_VOLUME}" in block
        assert "external: true" in block

    def test_the_volume_name_is_NOT_derived_from_the_project(
            self, compose_text):
        """It is `ips_pgdata` by explicit name, not
        `<project>_pgdata` by convention. That is what makes a project
        rename safe — and it is also why the volume must be left alone
        if the rename ever happens: renaming it means dump and restore.
        """
        assert _compose_name(compose_text) == EXPECTED_PROJECT
        assert f"name: {EXPECTED_VOLUME}" in compose_text


class TestTheRenameIsNotHalfDone:
    """#893's recommendation is not to rename. If that is ever revisited
    these guards should fail loudly rather than let a half-rename sit in
    the repo, because a half-rename is the state that creates two live
    vhosts and a second compose project.
    """

    def test_the_compose_file_does_not_mention_eps(self, compose_text):
        assert "eps" not in compose_text.lower()

    def test_the_env_example_names_no_eps_host(self, env_text):
        assert "eps.pdhc.se" not in env_text
