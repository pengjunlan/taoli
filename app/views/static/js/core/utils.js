export function showToast(message) {
  const root = document.getElementById("toast-root");
  if (!root) return;

  if (root.__toastTimer) {
    window.clearTimeout(root.__toastTimer);
  }

  root.innerHTML = "";
  root.classList.add("is-active");

  const mask = document.createElement("div");
  mask.className = "toast-mask";

  const toast = document.createElement("div");
  toast.className = "toast toast--centered";
  toast.textContent = message;

  mask.appendChild(toast);
  root.appendChild(mask);

  root.__toastTimer = window.setTimeout(() => {
    root.classList.remove("is-active");
    root.innerHTML = "";
  }, 3000);
}

export async function postJson(url, payload = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Requested-With": "XMLHttpRequest",
    },
    credentials: "same-origin",
    body: JSON.stringify(payload),
  });

  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    data = { success: false, message: "服务响应格式错误。" };
  }

  if (!data.message && typeof data.detail === "string" && data.detail.trim()) {
    data.message = data.detail.trim();
  }

  if (!response.ok && !data.message) {
    data.message = "请求失败，请稍后再试。";
  }

  return data;
}

export function bindLogoutAction() {
  const logoutButton = document.querySelector("[data-auth-logout]");
  if (!logoutButton) return;

  logoutButton.addEventListener("click", async (event) => {
    event.preventDefault();
    logoutButton.setAttribute("aria-disabled", "true");

    try {
      const result = await postJson("/api/auth/logout");
      if (!result.success) {
        showToast(result.message || "退出登录失败。");
        return;
      }

      showToast(result.message || "已退出登录。");
      window.setTimeout(() => {
        window.location.href = result.redirect_url || "/login";
      }, 200);
    } catch (error) {
      showToast("退出登录失败，请稍后再试。");
    } finally {
      logoutButton.removeAttribute("aria-disabled");
    }
  });
}
