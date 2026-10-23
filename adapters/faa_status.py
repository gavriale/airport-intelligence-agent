import asyncio
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict

from domain.live_status import LiveEvent, LiveStatus, LiveStatusUnavailable

FAA_URL = "https://nasstatus.faa.gov/api/airport-status-information"


def parse_status(xml_text: str) -> LiveStatus:
    """The feed has one <Delay_type> per program kind; each entry names its airport in <ARPT>.
    Airports with no active program are simply absent."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise LiveStatusUnavailable(f"FAA feed is not valid XML: {exc}") from exc

    events: dict[str, list[LiveEvent]] = defaultdict(list)
    for delay_type in root.iter("Delay_type"):
        kind = (delay_type.findtext("Name") or "Unknown").strip()
        for entry in delay_type.iter():
            code = entry.findtext("ARPT")
            if code:
                details = {}
                for child in entry:
                    value = (child.text or "").strip() or " ".join(child.attrib.values())
                    if child.tag != "ARPT" and value:
                        details[child.tag] = value
                events[code.strip().upper()].append(LiveEvent(kind=kind, details=details))
    return LiveStatus(updated=(root.findtext("Update_Time") or "").strip(), events=dict(events))


class FaaStatusProvider:
    def __init__(self, url: str = FAA_URL, timeout_s: float = 10) -> None:
        self._url = url
        self._timeout_s = timeout_s

    async def get_status(self) -> LiveStatus:
        return parse_status(await asyncio.to_thread(self._fetch))

    def _fetch(self) -> str:
        request = urllib.request.Request(self._url, headers={"User-Agent": "airport-agent/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                return response.read().decode("utf-8")
        except OSError as exc:
            raise LiveStatusUnavailable(f"FAA feed unreachable: {exc}") from exc
