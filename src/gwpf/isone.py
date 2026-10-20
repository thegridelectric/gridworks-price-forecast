"""Day-ahead hourly LMP from ISO-NE web services.

One call per operating day and location. ISO-NE publishes a day's
day-ahead prices around 13:00 ET the day before; before that the
endpoint answers with an empty list, which this module reports as no
prices rather than an error.
"""

import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import NamedTuple

import requests
from requests.auth import HTTPBasicAuth

from gwpf.sema.property_format import UTCSeconds

ISONE_NAMESPACE = {"ns": "http://WEBSERV.iso-ne.com"}
DAY_AHEAD_URL = "https://webservices.iso-ne.com/api/v1.1/hourlylmp/da/final/day/{day}/location/{location}"
TIMEOUT_S = 30


class HourlyLmp(NamedTuple):
    """One hour's day-ahead locational marginal price at one node: the
    hour's start and the total LMP in USD/MWh. Interior to the fetch;
    the forecast word is the boundary form."""

    hour_start_s: UTCSeconds
    lmp_usd_per_mwh: float


class IsoneClient:
    """Fetches day-ahead hourly LMP for one location with basic auth."""

    def __init__(self, user: str, password: str, location_id: str) -> None:
        self.auth = HTTPBasicAuth(user, password)
        self.location_id = location_id

    def day_ahead(self, day: date) -> list[HourlyLmp]:
        """The day's day-ahead hourly LMP in hour order; empty when ISO-NE
        has not published that day yet."""
        url = DAY_AHEAD_URL.format(
            day=day.strftime("%Y%m%d"), location=self.location_id
        )
        response = requests.get(url, auth=self.auth, timeout=TIMEOUT_S)
        response.raise_for_status()
        return parse_day_ahead(response.text, self.location_id)


def parse_day_ahead(xml_text: str, location_id: str) -> list[HourlyLmp]:
    """The HourlyLmp rows for the location, sorted by hour start."""
    root = ET.fromstring(xml_text)
    rows: list[HourlyLmp] = []
    for hourly in root.findall("ns:HourlyLmp", ISONE_NAMESPACE):
        location = hourly.find("ns:Location", ISONE_NAMESPACE)
        if location is None or location.attrib.get("LocId") != location_id:
            continue
        begin = hourly.find("ns:BeginDate", ISONE_NAMESPACE)
        total = hourly.find("ns:LmpTotal", ISONE_NAMESPACE)
        if begin is None or begin.text is None or total is None or total.text is None:
            raise ValueError("ISO-NE HourlyLmp row without BeginDate or LmpTotal")
        begin_dt = datetime.strptime(begin.text, "%Y-%m-%dT%H:%M:%S.%f%z")
        rows.append(HourlyLmp(int(begin_dt.timestamp()), float(total.text)))
    return sorted(rows)
