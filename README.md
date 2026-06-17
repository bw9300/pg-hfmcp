# SalonHub beschikbaarheid — MCP-server voor Retell AI

Een MCP-server die de online beschikbaarheid van een SalonHub-salon als tools
aanbiedt, zodat een Retell AI-agent live kan checken wanneer er plek is. Alle
tools zijn **read-only**; boeken zit er bewust niet in.

## Tools

| Tool | Doel |
|------|------|
| `salonhub_list_employees` | Medewerkers (kappers) ophalen, om een genoemde naam aan een id te koppelen |
| `salonhub_list_treatments` | Behandelingen met prijs en duur ophalen (id nodig voor de check) |
| `salonhub_check_availability` | **Hoofd-tool**: eerstvolgende vrije dagen + tijden voor een behandeling |
| `salonhub_get_available_times` | Vrije tijden op één specifieke dag |

## Installeren en lokaal draaien

```bash
pip install -r requirements.txt
export SALONHUB_CLIENT=hairfix
export SALONHUB_SALON=burgreigerst
python salonhub_mcp.py            # streamable HTTP op http://0.0.0.0:8000/mcp
```

Lokaal testen met de MCP Inspector (stdio):

```bash
python salonhub_mcp.py --transport stdio
# of:  npx @modelcontextprotocol/inspector python salonhub_mcp.py --transport stdio
```

## Configuratie (omgevingsvariabelen)

| Variabele | Standaard | Betekenis |
|-----------|-----------|-----------|
| `SALONHUB_CLIENT` | `hairfix` | client-code van de salon |
| `SALONHUB_SALON` | `burgreigerst` | salon-code |
| `MCP_HOST` | `0.0.0.0` | luister-adres |
| `MCP_PORT` | `8000` | poort |

## Online zetten (Retell heeft een publieke URL nodig)

Retell verbindt als client met je MCP-server, dus die moet bereikbaar zijn via
een **publieke https-URL**. Opties:

- Snel testen: `ngrok http 8000` → gebruik de https-URL die ngrok geeft, met `/mcp` erachter.
- Productie: draai het op een VPS of een platform als Render/Railway/Fly, achter https.

De MCP-endpoint wordt dan bijv. `https://jouw-host/mcp`.

## Koppelen in Retell AI

1. Open je agent → **+ Add MCP**.
2. Vul je MCP Server-URL in: `https://jouw-host/mcp`.
3. (Aanbevolen) Zet onder **custom headers** een geheime sleutel, bijv.
   `X-API-Key: <willekeurig-geheim>`, en controleer die in een proxy/middleware
   vóór de server. Zo kan niet zomaar iedereen je endpoint aanroepen.
4. Sla op; de tools verschijnen dan in je agent en kunnen tijdens gesprekken
   worden aangeroepen.

### Voorbeeld-gespreksflow voor de agent

1. Beller vraagt om een afspraak → agent roept `salonhub_list_treatments` aan om
   de juiste behandeling-id te vinden.
2. Optioneel `salonhub_list_employees` als de beller een vaste kapper noemt.
3. `salonhub_check_availability` met die `treatment_id` (en eventueel
   `employee_id` / `from_date`) → agent leest de eerstvolgende openingen voor.

## Beveiliging

De beschikbaarheids-endpoints van SalonHub zijn openbaar, dus deze server stuurt
geen wachtwoorden of tokens. Bescherm wél je eigen MCP-endpoint (zie stap 3) en
houd het gebruik redelijk: vuur niet onnodig veel verzoeken af richting SalonHub.

## Boeken

Deze server checkt alleen beschikbaarheid. Daadwerkelijk boeken vereist een
Bearer-token en schrijft een echte afspraak weg — dat is een aparte, riskantere
stap die je bewust apart wilt houden van een telefoon-agent.
