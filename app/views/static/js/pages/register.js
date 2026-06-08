import { postJson, showToast } from "../core/utils.js";

document.getElementById("register-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();

  const form = event.currentTarget;
  const usernameInput = form.querySelector('input[name="username"]');
  const passwordInput = form.querySelector('input[name="password"]');
  const confirmPasswordInput = form.querySelector('input[name="confirm_password"]');
  const submitButton = form.querySelector('button[type="submit"]');

  if (!usernameInput || !passwordInput || !confirmPasswordInput || !submitButton) {
    showToast("注册表单初始化失败。");
    return;
  }

  submitButton.disabled = true;

  try {
    const result = await postJson("/api/auth/register", {
      username: usernameInput.value.trim(),
      password: passwordInput.value,
      confirm_password: confirmPasswordInput.value,
    });

    if (!result.success) {
      showToast(result.message || "注册失败。");
      return;
    }

    showToast(result.message || "注册成功。");
    window.setTimeout(() => {
      window.location.href = result.redirect_url || "/login";
    }, 200);
  } catch (error) {
    showToast("注册失败，请稍后再试。");
  } finally {
    submitButton.disabled = false;
  }
});
