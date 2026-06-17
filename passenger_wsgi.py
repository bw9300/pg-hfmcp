"""
passenger_wsgi.py — Phusion Passenger entrypoint voor salonhub_mcp.

Passenger ondersteunt ook ASGI (via passenger_asgi.py), maar WSGI is breder
beschikbaar op gedeelde hosting. We draaien de ASGI-app via asgiref.

Als jouw hostingprovider ASGI wél ondersteunt, hernoem dit bestand naar
passenger_asgi.py en vervang de inhoud door:

    from salonhub_mcp import mcp
    application = mcp.get_app()
"""

import os
import sys

# Zorg dat de app-map in het Python-pad zit
sys.path.insert(0, os.path.dirname(__file__))

# Omgevingsvariabelen — pas aan naar jouw salon
os.environ.setdefault("SALONHUB_CLIENT", "hairfix")
os.environ.setdefault("SALONHUB_SALON", "burgreigerst")
os.environ.setdefault("MCP_HOST", "0.0.0.0")
os.environ.setdefault("MCP_PORT", "8000")

from asgiref.wsgi import WsgiToAsgi  # noqa: E402  (na os.environ instellen)
from salonhub_mcp import mcp          # noqa: E402

# FastMCP geeft een Starlette/ASGI-app terug via .get_app()
_asgi_app = mcp.get_app()

# Passenger roept 'application' aan als WSGI-callable
application = WsgiToAsgi(_asgi_app)  # type: ignore[arg-type]
