"""Exchange communication gateway skeleton."""

from typing import Any, Dict, Optional

from app.infrastructure.communication.base_client import BaseTransportClient


class ExchangeGatewayClient(BaseTransportClient):
    def fetch(
        self,
        channel: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        request_payload = payload or {}
        return self.send({"channel": channel, "request": request_payload})
