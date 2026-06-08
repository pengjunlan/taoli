"""Base transport adapter for outbound communication."""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class BaseTransportClient:
    endpoint: str
    is_connected: bool = field(default=False, init=False)

    def connect(self) -> None:
        self.is_connected = True

    def send(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_connected:
            raise RuntimeError("transport client is not connected")
        return {"endpoint": self.endpoint, "payload": payload}

    def close(self) -> None:
        self.is_connected = False
