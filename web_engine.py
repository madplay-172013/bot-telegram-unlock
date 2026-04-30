from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import os

URL = "https://webops.clbo-hubtv.com/index.php"
USUARIO = os.getenv("WEB_USER", "ssalgadclvt")
PASSWORD = os.getenv("WEB_PASS", "SSalgado87")

SCREENSHOTS_DIR = "/tmp/screenshots"
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


def consultar_y_desbloquear(operador: str, serial: str) -> dict:
    screenshots = []

    def capturar(page, nombre):
        path = f"{SCREENSHOTS_DIR}/{nombre}.png"
        page.screenshot(path=path)
        screenshots.append(path)

    def pagina_tiene_error_edm(page):
        try:
            texto = page.inner_text("body").upper()
        except Exception:
            return False

        errores = [
            "NO EDM INFO AVAILABLE",
            "EDM API SERVICE UNREACHABLE",
            "HARDWARE SERIAL NUMBER NOT FOUND",
            "THE STB WASN'T FOUND",
            "NO DATA",
        ]

        return any(error in texto for error in errores)

    def tiene_data_real(page):
        selectores_validos = [
            "text=Device Status",
            "text=STB basic status",
            "text=Remote Control Unit",
            "text=TiVo Remote",
            "text=Customer Information",
            "text=TiVO Contract Details",
            "text=Device Metadata",
            "text=Uptime",
            "text=EDM locking status",
        ]

        textos_validos = [
            "DEVICE STATUS",
            "STB BASIC STATUS",
            "REMOTE CONTROL UNIT",
            "TIVO REMOTE",
            "CUSTOMER INFORMATION",
            "TIVO CONTRACT DETAILS",
            "DEVICE METADATA",
            "UPTIME",
            "EDM LOCKING STATUS",
        ]

        for _ in range(20):
            try:
                page.mouse.wheel(0, 3000)
            except Exception:
                pass

            for selector in selectores_validos:
                try:
                    if page.locator(selector).count() > 0:
                        return True
                except Exception:
                    pass

            try:
                texto = page.inner_text("body").upper()
                if any(indicador in texto for indicador in textos_validos):
                    return True
            except Exception:
                pass

            page.wait_for_timeout(1000)

        return False

    def seleccionar_operador(page, operador):
        if operador == "CLARO":
            page.locator("select").select_option(label="Producción @ Claro, Chile")
        elif operador == "VTR":
            page.locator("select").select_option(label="Producción @ VTR, Chile")

        page.wait_for_timeout(4000)

    def abrir_device_query(page):
        page.get_by_text("Query User", exact=True).click()
        page.wait_for_timeout(1500)

        page.get_by_text("Device Query", exact=True).click()
        page.wait_for_timeout(4000)

    def buscar_serial(page, serial):
        search_input = page.locator("input:visible").last
        search_input.fill(serial)

        page.wait_for_timeout(1000)

        query_btn = page.locator(
            'button:has-text("Query"), input[value="Query"], a:has-text("Query")'
        ).first

        query_btn.wait_for(timeout=10000)
        query_btn.click()

        page.wait_for_timeout(9000)

        return query_btn

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )

            page = browser.new_page(viewport={"width": 1280, "height": 900})

            # Login
            page.goto(URL, timeout=30000)
            page.wait_for_timeout(4000)

            page.wait_for_selector("input:visible", timeout=15000)
            inputs = page.locator("input:visible")
            inputs.nth(0).fill(USUARIO)
            inputs.nth(1).fill(PASSWORD)

            page.wait_for_timeout(2000)
            page.locator("button:visible").first.click()
            page.wait_for_timeout(7000)

            # Operador elegido manualmente por el usuario
            seleccionar_operador(page, operador)
            abrir_device_query(page)
            query_btn = buscar_serial(page, serial)

            # Validar data real solo en el operador elegido
            ok = tiene_data_real(page)

            if not ok or pagina_tiene_error_edm(page):
                capturar(page, "3_sin_datos")
                browser.close()
                return {
                    "exito": False,
                    "operador": operador,
                    "screenshots": screenshots,
                    "mensaje": (
                        f"⚠️ No se encontraron datos reales en {operador}.\n\n"
                        f"Verifica la serie o prueba con la otra compañía.\n\n"
                        f"No se descontaron créditos."
                    )
                }

            # Unlock solo si hay data real
            try:
                unlock_btn = page.locator(
                    'button:has-text("Unlock"), input[value="Unlock"], a:has-text("Unlock")'
                ).first

                unlock_btn.wait_for(timeout=15000)
                page.once("dialog", lambda dialog: dialog.accept())
                unlock_btn.click()
                page.wait_for_timeout(5000)

            except PlaywrightTimeoutError:
                capturar(page, "3_sin_boton_unlock")
                browser.close()
                return {
                    "exito": False,
                    "operador": operador,
                    "screenshots": screenshots,
                    "mensaje": (
                        "⚠️ Se encontraron datos reales, pero no apareció el botón UNLOCK.\n\n"
                        "No se descontaron créditos."
                    )
                }

            # Refrescar Query final
            try:
                query_btn = page.locator(
                    'button:has-text("Query"), input[value="Query"], a:has-text("Query")'
                ).first

                query_btn.wait_for(timeout=10000)
                query_btn.click()
                page.wait_for_timeout(8000)
                capturar(page, "4_resultado_final")

            except PlaywrightTimeoutError:
                capturar(page, "4_error_refresco_query")
                browser.close()
                return {
                    "exito": False,
                    "operador": operador,
                    "screenshots": screenshots,
                    "mensaje": (
                        "⚠️ Se ejecutó UNLOCK, pero no se pudo refrescar con QUERY.\n\n"
                        "Revisa manualmente el estado del equipo.\n\n"
                        "No se descontaron créditos automáticamente."
                    )
                }

            browser.close()

            return {
                "exito": True,
                "operador": operador,
                "screenshots": screenshots,
                "mensaje": (
                    f"✅ *Proceso completado correctamente*\n\n"
                    f"📡 Operador: {operador}\n"
                    f"🔢 Serie: {serial}\n\n"
                    f"Equipo verificado y desbloqueado correctamente."
                )
            }

    except PlaywrightTimeoutError:
        return {
            "exito": False,
            "operador": operador,
            "screenshots": screenshots,
            "mensaje": (
                "⏱️ Tiempo de espera agotado. La web tardó demasiado en responder.\n"
                "No se descontaron créditos. Intenta nuevamente."
            )
        }

    except Exception as e:
        return {
            "exito": False,
            "operador": operador,
            "screenshots": screenshots,
            "mensaje": (
                f"❌ Error inesperado al conectar con la web.\n"
                f"No se descontaron créditos. Intenta nuevamente.\n\n"
                f"Detalle técnico: {str(e)}"
            )
        }

