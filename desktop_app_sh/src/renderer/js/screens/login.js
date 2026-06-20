import { login } from "../auth.js";
import { refreshNetworkStatus, isOnline } from "../networkService.js";
import { toast } from "../notifications.js";
import { renderShell } from "./shell.js";

export async function renderLogin() {
  await refreshNetworkStatus();
  document.getElementById("app").innerHTML = `
    <main class="login-page">
      <section class="login-card">
        <div class="login-logo">م</div>
        <h1>تسجيل الدخول</h1>
        <p class="muted">نظام إدارة الملابس والمخزون والطلبات</p>
        <p><span class="status-pill ${isOnline() ? "status-online" : "status-offline"}">${isOnline() ? "Online" : "Offline"}</span></p>
        <form id="loginForm" class="form-grid">
          <label><span>اسم المستخدم</span><input name="username" required autocomplete="username"></label>
          <label><span>كلمة المرور</span><input name="password" type="password" autocomplete="current-password"></label>
          <button class="btn btn-primary full-width" type="submit">دخول</button>
        </form>
      </section>
    </main>
  `;
  document.getElementById("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const button = event.currentTarget.querySelector("button");
    button.disabled = true;
    button.textContent = "جاري الدخول...";
    try {
      await refreshNetworkStatus();
      await login(form.get("username"), form.get("password"));
      toast(isOnline() ? "تم تسجيل الدخول من السيرفر" : "تم تسجيل الدخول محليًا", "success");
      renderShell();
    } catch (error) {
      toast(error.message || "فشل تسجيل الدخول", "error");
    } finally {
      button.disabled = false;
      button.textContent = "دخول";
    }
  });
}
