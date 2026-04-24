from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import os

URL = "https://webops.clbo-hubtv.com/index.php"
USUARIO = os.getenv("WEB_USER", "ssalgadclvt")
PASSWORD = os.getenv("WEB_PASS", "SSalgado87")

SCREENSHOTS_DIR = "/tmp/screenshots"
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


def consultar_y_desbloquear(operador: str, serial: str) -> dict:
    """
    Retorna un dict con:
      - exito: bool
      - mensaje: str
      - screenshots: list[str]  → rutas de imágenes para enviar al admin
    """
    screenshots = []

    def capturar(page, nombre):
        path = f"{SCREENSHOTS_DIR}/{nombre}.png"
        page.screenshot(path=path)
        screenshots.append(path)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            page = browser.new_page()

            # ── 1. Abrir web ──────────────────────────────────────────────
            page.goto(URL, timeout=30000)
            page.wait_for_timeout(3000)

            # ── 2. Login ──────────────────────────────────────────────────
            page.locator('input[type="text"]').fill(USUARIO)
            page.locator('input[type="password"]').fill(PASSWORD)
            page.locator('button[type="submit"]').click()
            page.wait_for_timeout(5000)
            capturar(page, "1_login")

            # ── 3. Seleccionar operador ───────────────────────────────────
            if operador == "CLARO":
                page.locator("select").select_option(label="Producción @ Claro, Chile")
            elif operador == "VTR":
                page.locator("select").select_option(label="Producción @ VTR, Chile")
            page.wait_for_timeout(3000)

            # ── 4. Abrir Query User → Device Query ────────────────────────
            page.get_by_text("Query User", exact=True).click()
            page.wait_for_timeout(1500)
            page.get_by_text("Device Query", exact=True).click()
            page.wait_for_timeout(4000)

            # ── 5. Ingresar serial y buscar ───────────────────────────────
            search_input = page.locator('input[type="text"]').last
            search_input.fill(serial)

            query_btn = page.get_by_role("button", name="Query").or_(
                page.get_by_role("button", name="Search")
            ).or_(
                page.locator('button:has-text("Query"), button:has-text("Search"), input[type="submit"]')
            ).first
            query_btn.click()
            page.wait_for_timeout(5000)
            capturar(page, "2_resultado_busqueda")

            # ── 6. Verificar que se encontraron datos ─────────────────────
            page_text = page.inner_text("body")

            if serial.upper() not in page_text.upper():
                capturar(page, "3_sin_datos")
                browser.close()
                return {
                    "exito": False,
                    "screenshots": screenshots,
                    "mensaje": (
                        "⚠️ No se encontraron datos para esa serie.\n\n"
                        "Por favor verifica:\n"
                        "1️⃣ Que la serie sea correcta\n"
                        "2️⃣ Que hayas elegido el operador correcto (CLARO o VTR)\n\n"
                        "No se descontaron créditos."
                    )
                }

            # ── 7. Presionar botón Unlock ─────────────────────────────────
            try:
                unlock_btn = page.get_by_role("button", name="Unlock").or_(
                    page.locator('button:has-text("Unlock"), a:has-text("Unlock")')
                ).first
                unlock_btn.wait_for(timeout=5000)
                unlock_btn.click()
            except PlaywrightTimeoutError:
                capturar(page, "3_sin_boton_unlock")
                browser.close()
                return {
                    "exito": False,
                    "screenshots": screenshots,
                    "mensaje": (
                        "⚠️ No se encontró el botón de desbloqueo.\n\n"
                        "Por favor verifica:\n"
                        "1️⃣ Que la serie sea correcta\n"
                        "2️⃣ Que hayas elegido el operador correcto (CLARO o VTR)\n\n"
                        "No se descontaron créditos."
                    )
                }

            page.wait_for_timeout(2000)
            capturar(page, "3_antes_confirmar")

            # ── 8. Confirmar popup ────────────────────────────────────────
            try:
                page.once("dialog", lambda dialog: dialog.accept())
                page.wait_for_timeout(2000)
            except Exception:
                pass

            try:
                confirm_btn = page.get_by_role("button", name="OK").or_(
                    page.get_by_role("button", name="Accept")
                ).or_(
                    page.get_by_role("button", name="Aceptar")
                ).or_(
                    page.locator('button:has-text("OK"), button:has-text("Yes"), button:has-text("Confirm")')
                ).first
                confirm_btn.wait_for(timeout=5000)
                confirm_btn.click()
                page.wait_for_timeout(3000)
            except PlaywrightTimeoutError:
                pass

            # ── 9. Screenshot final ───────────────────────────────────────
            capturar(page, "4_resultado_final")
            final_text = page.inner_text("body")
            browser.close()

            # ── 10. Verificar éxito ───────────────────────────────────────
            error_keywords = ["error", "failed", "invalid", "not found"]
            page_lower = final_text.lower()

            if any(kw in page_lower for kw in error_keywords):
                return {
                    "exito": False,
                    "screenshots": screenshots,
                    "mensaje": (
                        "⚠️ La web reportó un error al desbloquear.\n\n"
                        "Por favor verifica:\n"
                        "1️⃣ Que la serie sea correcta\n"
                        "2️⃣ Que hayas elegido el operador correcto (CLARO o VTR)\n\n"
                        "No se descontaron créditos."
                    )
                }

            return {
                "exito": True,
                "screenshots": screenshots,
                "mensaje": (
                    f"🔓✅ *Desbloqueo exitoso*\n\n"
                    f"📡 Operador: {operador}\n"
                    f"🔢 Serie: {serial}\n\n"
                    f"El equipo ha sido desbloqueado correctamente."
                )
            }

    except PlaywrightTimeoutError:
        return {
            "exito": False,
            "screenshots": screenshots,
            "mensaje": (
                "⏱️ Tiempo de espera agotado. La web tardó demasiado en responder.\n"
                "No se descontaron créditos. Intenta nuevamente."
            )
        }
    except Exception as e:
        return {
            "exito": False,
            "screenshots": screenshots,
            "mensaje": (
                f"❌ Error inesperado al conectar con la web.\n"
                f"No se descontaron créditos. Intenta nuevamente.\n\n"
                f"Detalle técnico: {str(e)}"
            )
        }
