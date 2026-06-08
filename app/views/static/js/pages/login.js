import { postJson, showToast } from "../core/utils.js";

document.getElementById("login-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();

  const form = event.currentTarget;
  const usernameInput = form.querySelector('input[name="username"]');
  const passwordInput = form.querySelector('input[name="password"]');
  const rememberMeInput = form.querySelector('input[name="remember_me"]');
  const submitButton = form.querySelector('button[type="submit"]');

  if (!usernameInput || !passwordInput || !submitButton) {
    showToast("登录表单初始化失败。");
    return;
  }

  submitButton.disabled = true;

  try {
    const result = await postJson("/api/auth/login", {
      username: usernameInput.value.trim(),
      password: passwordInput.value,
      remember_me: Boolean(rememberMeInput && rememberMeInput.checked),
    });

    if (!result.success) {
      showToast(result.message || "登录失败。");
      passwordInput.focus();
      return;
    }

    showToast(result.message || "登录成功。");
    window.setTimeout(() => {
      window.location.href = result.redirect_url || "/dashboard";
    }, 200);
  } catch (error) {
    showToast("登录失败，请稍后再试。");
  } finally {
    submitButton.disabled = false;
  }
});
