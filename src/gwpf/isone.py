"""Day-ahead hourly LMP from ISO-NE web services.

Two calls. `info` answers what ISO-NE has posted: the start of the last
posted hour and when the posting was made. `day_ahead` returns one
operating day's hourly prices at one location; a day ISO-NE has not
posted answers with an empty list.
"""

import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import NamedTuple

import requests
from requests.auth import HTTPBasicAuth

from gwpf.sema.property_format import UTCSeconds

ISONE_NAMESPACE = {"ns": "http://WEBSERV.iso-ne.com"}
ISONE_API = "https://webservices.iso-ne.com/api/v1.1"
DAY_AHEAD_URL = ISONE_API + "/hourlylmp/da/final/day/{day}/location/{location}"
INFO_URL = ISONE_API + "/hourlylmp/da/final/info"
ISONE_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%f%z"
TIMEOUT_S = 30


class HourlyLmp(NamedTuple):
    """One hour's day-ahead locational marginal price at one node: the
    hour's start and the total LMP in USD/MWh. Interior to the fetch;
    the forecast word is the boundary form."""

    hour_start_s: UTCSeconds
    lmp_usd_per_mwh: float


class Publication(NamedTuple):
    """What ISO-NE has posted for the day-ahead market: the start of the
    last posted hour and the time of the posting. Interior to the
    fetch."""

    latest_begin_s: UTCSeconds
    posted_s: UTCSeconds


class IsoneClient:
    """Fetches day-ahead hourly LMP for one location with basic auth."""

    def __init__(self, user: str, password: str, location_id: str) -> None:
        self.auth = HTTPBasicAuth(user, password)
        self.location_id = location_id

    def info(self) -> Publication:
        """The latest day-ahead posting."""
        response = requests.get(INFO_URL, auth=self.auth, timeout=TIMEOUT_S)
        response.raise_for_status()
        return parse_info(response.text)

    def day_ahead(self, day: date) -> list[HourlyLmp]:
        """The day's day-ahead hourly LMP in hour order; empty when ISO-NE
        has not posted that day."""
        url = DAY_AHEAD_URL.format(
            day=day.strftime("%Y%m%d"), location=self.location_id
        )
        response = requests.get(url, auth=self.auth, timeout=TIMEOUT_S)
        response.raise_for_status()
        return parse_day_ahead(response.text, self.location_id)


def isone_seconds(parent: ET.Element, tag: str) -> UTCSeconds:
    return int(
        datetime.strptime(element_text(parent, tag), ISONE_TIME_FORMAT).timestamp()
    )


def element_text(parent: ET.Element, tag: str) -> str:
    element = parent.find(f"ns:{tag}", ISONE_NAMESPACE)
    if element is None or element.text is None:
        raise ValueError(f"ISO-NE {parent.tag} without {tag}")
    return element.text


def parse_info(xml_text: str) -> Publication:
    root = ET.fromstring(xml_text)
    return Publication(
        latest_begin_s=isone_seconds(root, "LatestBeginDate"),
        posted_s=isone_seconds(root, "CreationDate"),
    )


def parse_day_ahead(xml_text: str, location_id: str) -> list[HourlyLmp]:
    """The HourlyLmp rows for the location, sorted by hour start."""
    root = ET.fromstring(xml_text)
    rows: list[HourlyLmp] = []
    for hourly in root.findall("ns:HourlyLmp", ISONE_NAMESPACE):
        location = hourly.find("ns:Location", ISONE_NAMESPACE)
        if location is None or location.attrib.get("LocId") != location_id:
            continue
        rows.append(
            HourlyLmp(
                hour_start_s=isone_seconds(hourly, "BeginDate"),
                lmp_usd_per_mwh=float(element_text(hourly, "LmpTotal")),
            )
        )
    return sorted(rows)
