"""
salonhub_mcp - MCP-server die SalonHub-beschikbaarheid als tools aanbiedt.

Bedoeld om als REMOTE MCP-server aan een Retell AI-agent te koppelen, zodat de
(telefoon)agent live kan checken wanneer er plek is. Alle tools zijn read-only;
boeken zit hier bewust niet in.

Start lokaal (HTTP):
    pip install "mcp[cli]" httpx
    SALONHUB_CLIENT=hairfix SALONHUB_SALON=burgreigerst python salonhub_mcp.py

Standaard luistert hij op http://0.0.0.0:8000/mcp (streamable HTTP).
"""

import argparse
import json
import os
import time
from enum import Enum
from typing import Any, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field

from mcp.server.fastmcp import FastMCP

# --- Configuratie -----------------------------------------------------------

BASE = "https://public.salonhub.nl/v2/api"
CLIENT = os.environ.get("SALONHUB_CLIENT", "hairfix")
SALON = os.environ.get("SALONHUB_SALON", "burgreigerst")
HOST = os.environ.get("MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("MCP_PORT", "8000"))

_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Origin": "https://widget.salonhub.nl",
    "Referer": f"https://widget.salonhub.nl/a/{CLIENT}/{SALON}/link.html",
    "User-Agent": "salonhub-mcp/1.0",
}

mcp = FastMCP("salonhub_mcp", host=HOST, port=PORT)


# --- Gedeelde helpers -------------------------------------------------------

class ResponseFormat(str, Enum):
    """Uitvoerformaat voor tool-antwoorden."""
    MARKDOWN = "markdown"
    JSON = "json"


def _parse(r: httpx.Response) -> Any:
    """JSON parsen; sommige endpoints zijn dubbel-encoded (string-in-string)."""
    data = r.json()
    if isinstance(data, str):
        data = json.loads(data)
    return data


async def _api_get(resource: str, action: str = "get", **params) -> Any:
    """GET-call naar de SalonHub-API met vaste client/salon en cache-buster."""
    params.setdefault("client", CLIENT)
    params.setdefault("salon", SALON)
    params["_"] = int(time.time() * 1000)
    url = f"{BASE}/{resource}/{action}"
    async with httpx.AsyncClient(headers=_HEADERS, timeout=15) as http:
        r = await http.get(url, params=params)
        r.raise_for_status()
        return _parse(r)


def _handle_api_error(e: Exception) -> str:
    """Consistente, bruikbare foutmeldingen voor de agent."""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code == 404:
            return "Fout: niet gevonden. Controleer de behandeling- of medewerker-id."
        if code == 429:
            return "Fout: te veel verzoeken. Wacht even en probeer opnieuw."
        return f"Fout: API gaf status {code}."
    if isinstance(e, httpx.TimeoutException):
        return "Fout: time-out bij het ophalen. Probeer opnieuw."
    return f"Fout: onverwachte fout ({type(e).__name__})."


def _eur(cents: int) -> str:
    return f"\u20ac{cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _flatten_treatments(data: Any) -> list[dict]:
    """{'treatments': {'female': [...], 'male': [...]}} -> platte behandellijst."""
    inner = data.get("treatments", data) if isinstance(data, dict) else {}
    out = []
    for groep in ("female", "male"):
        for t in inner.get(groep, []):
            if t.get("type") == "treatment":
                out.append({
                    "id": t["id"],
                    "name": t["name"],
                    "price_eur": _eur(t["price"]["value"]),
                    "duration_min": t["length"],
                })
    return out


def _format(rows: list[dict], render, fmt: ResponseFormat, empty: str) -> str:
    if not rows:
        return empty
    if fmt == ResponseFormat.JSON:
        return json.dumps(rows, ensure_ascii=False, indent=2)
    return "\n".join(render(row) for row in rows)


# --- Input-modellen ---------------------------------------------------------

class ListEmployeesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="'markdown' voor leesbare tekst of 'json' voor data.",
    )


class ListTreatmentsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    employee_id: int = Field(
        default=0,
        description="Medewerker-id (0 = geen voorkeur / volledige lijst).",
        ge=0,
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class CheckAvailabilityInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    treatment_id: int = Field(
        ..., description="Behandeling-id (zie salonhub_list_treatments).", ge=1
    )
    employee_id: int = Field(
        default=0,
        description="Medewerker-id (0 = geen voorkeur / eerste beschikbare).",
        ge=0,
    )
    from_date: Optional[str] = Field(
        default=None,
        description="Vroegst gewenste dag, 'YYYY-MM-DD'. Leeg = vanaf vandaag.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    max_days: int = Field(
        default=5,
        description="Aantal beschikbare dagen met tijden om terug te geven.",
        ge=1, le=10,
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class GetTimesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    treatment_id: int = Field(..., description="Behandeling-id.", ge=1)
    date: str = Field(
        ..., description="Dag 'YYYY-MM-DD'.", pattern=r"^\d{4}-\d{2}-\d{2}$"
    )
    employee_id: int = Field(default=0, description="Medewerker-id (0 = geen voorkeur).", ge=0)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


# --- Tools ------------------------------------------------------------------

@mcp.tool(
    name="salonhub_list_employees",
    annotations={
        "title": "Medewerkers opvragen",
        "readOnlyHint": True, "destructiveHint": False,
        "idempotentHint": True, "openWorldHint": True,
    },
)
async def salonhub_list_employees(params: ListEmployeesInput) -> str:
    """Geef de lijst medewerkers (kappers) van de salon.

    Gebruik dit om een door de beller genoemde naam te koppelen aan een
    medewerker-id, of om 'geen voorkeur' (id 0) aan te bieden.

    Returns:
        str: Per medewerker 'id - naam'. JSON-vorm: lijst van
             {"id": int, "name": str, "type": str}.
    """
    try:
        data = await _api_get("OnlineAppointment.Remote.Employees")
        rows = data.get("employees", data) if isinstance(data, dict) else data
        rows = [{"id": e["id"], "name": e["name"], "type": e["type"]} for e in rows]
        return _format(rows, lambda e: f"{e['id']} - {e['name']}",
                       params.response_format, "Geen medewerkers gevonden.")
    except Exception as e:  # noqa: BLE001
        return _handle_api_error(e)


@mcp.tool(
    name="salonhub_list_treatments",
    annotations={
        "title": "Behandelingen opvragen",
        "readOnlyHint": True, "destructiveHint": False,
        "idempotentHint": True, "openWorldHint": True,
    },
)
async def salonhub_list_treatments(params: ListTreatmentsInput) -> str:
    """Geef de behandelingen met prijs en duur.

    Behandelingen kunnen per medewerker verschillen; laat employee_id op 0 voor
    het volledige aanbod, of geef een specifieke medewerker-id mee.

    Returns:
        str: Per behandeling 'id - naam (prijs, duur)'. JSON-vorm: lijst van
             {"id": int, "name": str, "price_eur": str, "duration_min": int}.
    """
    try:
        data = await _api_get(
            "OnlineAppointment.Remote.Treatments",
            action="getForEmployee", employee=params.employee_id,
        )
        rows = _flatten_treatments(data)
        return _format(
            rows,
            lambda t: f"{t['id']} - {t['name']} ({t['price_eur']}, {t['duration_min']} min)",
            params.response_format, "Geen behandelingen gevonden.",
        )
    except Exception as e:  # noqa: BLE001
        return _handle_api_error(e)


@mcp.tool(
    name="salonhub_check_availability",
    annotations={
        "title": "Beschikbaarheid checken",
        "readOnlyHint": True, "destructiveHint": False,
        "idempotentHint": True, "openWorldHint": True,
    },
)
async def salonhub_check_availability(params: CheckAvailabilityInput) -> str:
    """Geef de eerstvolgende beschikbare dagen met vrije tijden voor een behandeling.

    Dit is de hoofd-tool om 'wanneer kan ik komen?' te beantwoorden. Het zoekt
    vooruit in de agenda en geeft de eerste 'max_days' dagen terug die vrije
    tijden hebben (optioneel vanaf 'from_date' en/of bij een specifieke medewerker).

    Returns:
        str: Per dag de datum met de vrije tijden (HH:MM). JSON-vorm: lijst van
             {"date": "YYYY-MM-DD", "times": ["HH:MM", ...]}.
    """
    try:
        results: list[dict] = []
        start = 0
        seen: set[str] = set()
        while len(results) < params.max_days and start <= 90:
            data = await _api_get(
                "OnlineAppointment.Remote.Dates",
                treatment=params.treatment_id,
                employee=params.employee_id, start=start,
            )
            days = [d["date"] for d in data.get("dates", [])]
            if not days:
                break
            for day in days:
                if day in seen:
                    continue
                seen.add(day)
                if params.from_date and day < params.from_date:
                    continue
                tdata = await _api_get(
                    "OnlineAppointment.Remote.Times",
                    treatment=params.treatment_id,
                    employee=params.employee_id, date=day,
                )
                times = [t["time"][:5] for t in tdata.get("times", [])]
                if times:
                    results.append({"date": day, "times": times})
                if len(results) >= params.max_days:
                    break
            start += 14

        return _format(
            results,
            lambda r: f"{r['date']}: " + ", ".join(r["times"]),
            params.response_format,
            "Geen beschikbaarheid gevonden in de komende periode.",
        )
    except Exception as e:  # noqa: BLE001
        return _handle_api_error(e)


@mcp.tool(
    name="salonhub_get_available_times",
    annotations={
        "title": "Vrije tijden op een dag",
        "readOnlyHint": True, "destructiveHint": False,
        "idempotentHint": True, "openWorldHint": True,
    },
)
async def salonhub_get_available_times(params: GetTimesInput) -> str:
    """Geef de vrije starttijden voor een behandeling op één specifieke dag.

    Gebruik dit als de beller een concrete dag noemt ('kan het donderdag?').

    Returns:
        str: De vrije tijden (HH:MM) op die dag. JSON-vorm: lijst van
             {"time": "HH:MM"}.
    """
    try:
        data = await _api_get(
            "OnlineAppointment.Remote.Times",
            treatment=params.treatment_id,
            employee=params.employee_id, date=params.date,
        )
        rows = [{"time": t["time"][:5]} for t in data.get("times", [])]
        return _format(rows, lambda r: r["time"], params.response_format,
                       f"Geen vrije tijden op {params.date}.")
    except Exception as e:  # noqa: BLE001
        return _handle_api_error(e)


# --- Entrypoint -------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="SalonHub beschikbaarheid MCP-server")
    ap.add_argument("--transport", default="streamable-http",
                    choices=["streamable-http", "stdio"],
                    help="streamable-http voor Retell (remote), stdio voor lokaal testen.")
    args = ap.parse_args()
    transport = "streamable_http" if args.transport == "streamable-http" else "stdio"
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
