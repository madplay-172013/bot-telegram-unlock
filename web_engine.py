from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import os

URL = "https://webops.clbo-hubtv.com/index.php"
USUARIO = os.getenv("WEB_USER", "ssalgadclvtr")
PASSWORD = os.getenv("WEB_PASS", "SSalgado87")

SCREENSHOTS_DIR = "/tmp/screenshots"
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


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
            

            # 3. Seleccionar operador
            if operador == "CLARO":
                page.locator("select").select_option(label="Producción @ Claro, Chile")
            elif operador == "VTR":
                page.locator("select").select_option(label="Producción @ VTR, Chile")

            page.wait_for_timeout(4000)

            # 4. Abrir Query User → Device Query
            page.get_by_text("Query User", exact=True).click()
            page.wait_for_timeout(1500)

            page.get_by_text("Device Query", exact=True).click()
            page.wait_for_timeout(4000)

            # ── 5. Ingresar serial y buscar ───────────────────────────────
            search_input = page.locator('input:visible').last
            search_input.fill(serial)

            page.wait_for_timeout(1000)

            query_btn = page.locator('button:has-text("Query")').first

            query_btn.click()

            # 🔥 esperar a que aparezca el resultado REAL (no solo tiempo)
            page.wait_for_timeout(5000)

            # intenta esperar cambio en la página
            # esperar más tiempo real
            page.wait_for_timeout(5000)

            # verificar contenido de la página
            page_text = page.inner_text("body")

            if serial.upper() not in page_text.upper():
                capturar(page, "3_sin_datos")
                browser.close()
                return {
                    "exito": False,
                    "screenshots": screenshots,
                    "mensaje": (
                        "⚠️ No se encontraron datos para esa serie.\n\n"
                        "Verifica la serie y el operador.\n\n"
                        "No se descontaron créditos."
                    )
                }

            page.wait_for_timeout(4000)

            

            # 6. Verificar datos
            page_text = page.inner_text("body")

            if serial.upper() not in page_text.upper():
                capturar(page, "3_sin_datos")
                browser.close()
                return {
                    "exito": False,
                    "screenshots": screenshots,
                    "mensaje": (
                        "⚠️ No se encontraron datos para esa serie.\n\n"
                        "Verifica la serie y el operador.\n\n"
                        "No se descontaron créditos."
                    )
                }

            # 7. Presionar botón Unlock
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
                return {
                    "exito": False,
                    "screenshots": screenshots,
                    "mensaje": (
                        "⚠️ No se encontró el botón UNLOCK.\n\n"
                        "Verifica que la serie sea correcta y que los datos se hayan desplegado.\n\n"
                        "No se descontaron créditos."
                    )
                }

            # 8. Refrescar con Query nuevamente
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
                return {
                    "exito": False,
                    "screenshots": screenshots,
                    "mensaje": (
                        "⚠️ Se ejecutó UNLOCK, pero no se pudo refrescar con QUERY.\n\n"
                        "Revisa manualmente el estado del equipo."
                    )
                }

            browser.close()

            return {
                "exito": True,
                "screenshots": screenshots,
                "mensaje": (
                    f"✅ *Proceso completado correctamente*\n\n"
                    f"📡 Operador: {operador}\n"
                    f"🔢 Serie: {serial}\n\n"
                    f"El equipo fue actualizado y verificado correctamente."
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
