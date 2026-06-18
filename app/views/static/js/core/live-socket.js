import { showToast } from "./utils.js";

const RECONNECT_DELAY_MS = 3000;

function buildWebSocketUrl(channel) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/live/${encodeURIComponent(channel)}`;
}

function appendQueryParams(url, params) {
  const query = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    query.set(key, String(value));
  });
  const queryText = query.toString();
  return queryText ? `${url}?${queryText}` : url;
}

export function createLiveSocket({
  channel,
  query = {},
  onMessage,
  onError,
  onOpen,
  onClose,
  suppressErrorToast = false,
}) {
  let socket = null;
  let reconnectTimer = 0;
  let closedManually = false;

  const clearReconnectTimer = () => {
    if (reconnectTimer) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = 0;
    }
  };

  const scheduleReconnect = () => {
    if (closedManually || reconnectTimer) {
      return;
    }
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = 0;
      connect();
    }, RECONNECT_DELAY_MS);
  };

  const connect = () => {
    clearReconnectTimer();

    try {
      socket = new window.WebSocket(appendQueryParams(buildWebSocketUrl(channel), query));
    } catch (error) {
      if (!suppressErrorToast) {
        showToast("实时连接创建失败，请稍后重试");
      }
      if (typeof onError === "function") {
        onError(error);
      }
      scheduleReconnect();
      return;
    }

    socket.addEventListener("open", () => {
      if (typeof onOpen === "function") {
        onOpen();
      }
    });

    socket.addEventListener("message", (event) => {
      let payload = null;
      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        if (typeof onError === "function") {
          onError(error);
        }
        return;
      }

      if (typeof onMessage === "function") {
        onMessage(payload);
      }
    });

    socket.addEventListener("error", (event) => {
      if (typeof onError === "function") {
        onError(event);
      }
    });

    socket.addEventListener("close", () => {
      socket = null;
      if (typeof onClose === "function") {
        onClose();
      }
      scheduleReconnect();
    });
  };

  connect();

  return {
    close() {
      closedManually = true;
      clearReconnectTimer();
      if (socket) {
        socket.close();
        socket = null;
      }
    },
  };
}
