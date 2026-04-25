from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import os
import shutil

URL = "https://webops.clbo-hubtv.com/index.php"
USUARIO = os.getenv("WEB_USER", "ssalgadclvtr")
PASSWORD = os.getenv("WEB_PASS", "SSalgado87")

SCREENSHOTS_DIR = "/tmp/screenshots"
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


def limpiar_screenshots():
    try:
        if os.path.exists(SCREENSHOTS_DIR):
            shutil.rmtree(SCREENSHOTS_DIR)
            os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    except Exception as e:
        print(f"Error limpiando screenshots: {e}")


def consultar_y_desbloquear(operador: str, serial: str) -> dict:
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

            page = browser.new_page(viewport={"width": 1280, "height": 900})

            # 1. Abrir web
            page.goto(URL, timeout=30000)
            page.wait_for_timeout(4000)

            # 2. Login
            page.wait_for_selector("input:visible", timeout=15000)

            inputs = page.locator("input:visible")
            inputs.nth(0).fill(USUARIO)
            inputs.nth(1).fill(PASSWORD)

            page.wait_for_timeout(3000)
            page.locator("button:visible").first.click()

            page.wait_for_timeout(7000)

            # 3. Operador
            if operador == "CLARO":
                page.locator("select").select_option(label="Producción @ Claro, Chile")
            elif operador == "VTR":
                page.locator("select").select_option(label="Producción @ VTR, Chile")

            page.wait_for_timeout(4000)

            # 4. Menú
            page.get_by_text("Query User", exact=True).click()
            page.wait_for_timeout(1500)

            page.get_by_text("Device Query", exact=True).click()
            page.wait_for_timeout(4000)

            # 5. Buscar serial
            search_input = page.locator('input:visible').last
            search_input.fill(serial)

            page.wait_for_timeout(1000)

            query_btn = page.locator('button:has-text("Query")').first
            query_btn.click()

            page.wait_for_timeout(10000)

            page_text = page.inner_text("body")

            if serial.upper() not in page_text.upper():
                capturar(page, "3_sin_datos")
                browser.close()
                limpiar_screenshots()
                return {
                    "exito": False,
                    "screenshots": screenshots,
                    "mensaje": "⚠️ No se encontraron datos para esa serie.\n\nVerifica la serie y el operador."
                }

            page.wait_for_timeout(4000)

            # 6. Unlock
            try:
                unlock_btn = page.locator(
                    'button:has-text("Unlock"), input[value="Unlock"], a:has-text("Unlock")'
                ).first

                unlock_btn.wait_for(timeout=10000)

                page.once("dialog", lambda dialog: dialog.accept())
                unlock_btn.click()

                page.wait_for_timeout(5000)

            except PlaywrightTimeoutError:
                capturar(page, "3_sin_boton_unlock")
                browser.close()
                limpiar_screenshots()
                return {
                    "exito": False,
                    "screenshots": screenshots,
                    "mensaje": "⚠️ No se encontró el botón UNLOCK."
                }

            # 7. Refrescar
            try:
                query_btn = page.locator(
                    'button:has-text("Query"), input[value="Query"], a:has-text("Query")'
                ).first

                query_btn.wait_for(timeout=10000)
                query_btn.click()

                page.wait_for_timeout(7000)
                capturar(page, "4_resultado_final")

            except PlaywrightTimeoutError:
                capturar(page, "4_error_refresco_query")
                browser.close()
                limpiar_screenshots()
                return {
                    "exito": False,
                    "screenshots": screenshots,
                    "mensaje": "⚠️ Unlock hecho, pero no se pudo refrescar."
                }

            browser.close()

            resultado = {
                "exito": True,
                "screenshots": screenshots,
                "mensaje": (
                    f"✅ *Proceso completado correctamente*\n\n"
                    f"📡 Operador: {operador}\n"
                    f"🔢 Serie: {serial}\n\n"
                    f"El equipo fue actualizado y verificado correctamente."
                )
            }

            limpiar_screenshots()
            return resultado

    except PlaywrightTimeoutError:
        limpiar_screenshots()
        return {
            "exito": False,
            "screenshots": screenshots,
            "mensaje": "⏱️ Tiempo de espera agotado."
        }

    except Exception as e:
        limpiar_screenshots()
        return {
            "exito": False,
            "screenshots": screenshots,
            "mensaje": f"❌ Error inesperado:\n{str(e)}"
        }
