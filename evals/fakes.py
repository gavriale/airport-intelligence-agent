"""Test doubles for the evals: a backend that is down and a scripted live feed."""

from collections.abc import Sequence
from typing import NoReturn

from domain.live_status import LiveEvent, LiveStatus
from domain.repository import Airport, MonthlyTraffic, SnapshotInfo


class FailingRepository:
    """Every call fails, like a backend that is down."""

    async def list_airports(
        self,
        *,
        states: Sequence[str] | None = None,
        iatas: Sequence[str] | None = None,
        peers_only: bool = False,
    ) -> list[Airport]:
        self._fail()

    async def get_traffic(self, iatas: Sequence[str] | None = None) -> list[MonthlyTraffic]:
        self._fail()

    async def get_snapshot_info(self) -> SnapshotInfo:
        self._fail()

    @staticmethod
    def _fail() -> NoReturn:
        raise ConnectionError("backend down")


class ScriptedLiveStatus:
    """A fixed live feed: LAX has only a closure notice that restricts general aviation, and
    every other airport has nothing listed. Mirrors what the real feed returned on 2026-10-23."""

    async def get_status(self) -> LiveStatus:
        notice = LiveEvent(
            kind="Airport Closures",
            details={
                "Reason": "!LAX 05/277 LAX AD AP CLSD TO NON SKED TRANSIENT GA ACFT EXC 24HR PPR",
                "Start": "May 27 at 18:26 UTC.",
                "Reopen": "May 28 at 16:00 UTC.",
            },
        )
        return LiveStatus(updated="Fri Oct 23 08:16:57 2026 GMT", events={"LAX": [notice]})
