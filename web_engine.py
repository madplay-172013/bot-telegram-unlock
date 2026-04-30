from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import os

URL = "https://webops.clbo-hubtv.com/index.php"
USUARIO = os.getenv("WEB_USER", "ssalgadclvt")
PASSWORD = os.getenv("WEB_PASS", "SSalgado87")

SCREENSHOTS_DIR = "/tmp/screenshots"
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

def consultar_y_desbloquear(operador: str, serial: str) -> dict:
    screenshots = []

    def capturar(page, nombre, selector_foco=None):
        path = f"{SCREENSHOTS_DIR}/{nombre}.png"
        try:
            if selector_foco:
                try:
                    elem = page.locator(selector_foco).first
                    elem.scroll_into_view_if_needed(timeout=3000)
                    page.wait_for_timeout(500)
                except Exception:
                    pass
            page.screenshot(path=path, full_page=True)
            screenshots.append(path)
        except Exception as e:
            print(f"Error capturando screenshot {nombre}: {e}")

    def pagina_tiene_error_edm_real(page):
        try:
            texto = page.inner_text("body").upper()
        except Exception:
            return False

        errores_edm = ["NO EDM INFO AVAILABLE", "EDM API SERVICE UNREACHABLE"]
        tiene_error_edm = any(e in texto for e in errores_edm)
        if not tiene_error_edm:
            return False

        indicadores_datos = ["DEVICE STATUS", "STB BASIC STATUS", "EDM LOCKING STATUS"]
        tiene_datos = any(ind in texto for ind in indicadores_datos)
        return not tiene_datos

    def tiene_data_real(page):
        # Espera inicial para que el JS cargue los datos (como se ve en el video)
        page.wait_for_timeout(7000)

        for intento in range(12): # Total ~40 seg max
            if pagina_tiene_error_edm_real(page):
                return False
            
            try:
                # Si aparece el botón Unlock o el estado del dispositivo, hay datos
                if page.locator("text=Device Status").count() > 0 or page.locator('button:has-text("Unlock")').count() > 0:
                    return True
            except Exception:
                pass
            
            page.wait_for_timeout(3000)
        return False

    def login(page):
        page.goto(URL, timeout=40000)
        page.wait_for_selector("input:visible", timeout=20000)
        inputs = page.locator("input:visible")
        inputs.nth(0).fill(USUARIO)
        inputs.nth(1).fill(PASSWORD)
        page.locator("button:visible").first.click()
        page.wait_for_timeout(6000)

    def seleccionar_operador(page, operador):
        # Selector más robusto para el menú de compañías
        selector = page.locator("select").first
        if operador == "CLARO":
            selector.select_option(label="Producción @ Claro, Chile")
        elif operador == "VTR":
            selector.select_option(label="Producción @ VTR, Chile")
        page.wait_for_timeout(4000)

    def abrir_device_query(page):
        page.get_by_text("Query User", exact=True).click()
        page.wait_for_timeout(2000)
        page.get_by_text("Device Query", exact=True).click()
        page.wait_for_timeout(3000)

    def ejecutar_query(page, serial):
        search_input = page.locator("input:visible").last
        search_input.clear()
        search_input.fill(serial)
        query_btn = page.locator('button:has-text("Query"), input[value="Query"]').first
        query_btn.click()

    def ejecutar_unlock(page):
        """Maneja los 2 popups del video de forma automática."""
        try:
            unlock_btn = page.locator('button:has-text("Unlock"), input[value="Unlock"]').first
            unlock_btn.wait_for(state="visible", timeout=12000)

            # Manejador de diálogos para aceptar los 2 mensajes automáticamente
            def handle_dialogs(dialog):
                print(f"  [PopUp] Aceptando: {dialog.message}")
                dialog.accept()

            page.on("dialog", handle_dialogs)
            
            unlock_btn.click()
            # Esperamos 7 segundos para asegurar que ambos popups aparezcan y se cierren
            page.wait_for_timeout(7000)
            
            page.remove_listener("dialog", handle_dialogs)
            return True
        except Exception as e:
            print(f"Error en proceso Unlock: {e}")
            return False

    def ejecutar_query_final(page):
        """Presiona Query otra vez para que el candado pase de Rojo a Verde."""
        query_btn = page.locator('button:has-text("Query"), input[value="Query"]').first
        query_btn.click()
        # Espera final para que la tabla se refresque con el candado verde
        page.wait_for_timeout(8000)

    # --- FLUJO PRINCIPAL ---
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()

            # 1. Login y Navegación
            login(page)
            seleccionar_operador(page, operador)
            abrir_device_query(page)

            # 2. Primera Consulta
            ejecutar_query(page, serial)
            
            # 3. Validar si existen datos (EDM)
            if not tiene_data_real(page):
                capturar(page, "5_sin_datos", selector_foco="text=Results")
                browser.close()
                return {
                    "exito": False,
                    "sin_datos_edm": True,
                    "operador": operador,
                    "screenshots": screenshots,
                    "mensaje": (
                        f"❌ *Datos no encontrados*\n\n"
                        f"La serie `{serial}` no registra datos en *{operador}*.\n"
                        f"Prueba seleccionando la otra compañía.\n\n"
                        f"💰 _No se descontaron créditos._"
                    )
                }

            # 4. Proceso de Desbloqueo (Aceptar PopUps)
            print(f"[{operador}] Datos detectados. Ejecutando Unlock...")
            if not ejecutar_unlock(page):
                capturar(page, "error_unlock")
                browser.close()
                return {"exito": False, "sin_datos_edm": False, "mensaje": "⚠️ Error al presionar Unlock."}

            # 5. Query Final (Actualizar Candado)
            print(f"[{operador}] Actualizando estado final...")
            ejecutar_query_final(page)
            capturar(page, "7_resultado_final", selector_foco="text=Device Status")

            browser.close()
            return {
                "exito": True,
                "sin_datos_edm": False,
                "operador": operador,
                "screenshots": screenshots,
                "mensaje": (
                    f"✅ *Desbloqueo Exitoso*\n\n"
                    f"📡 Operador: *{operador}*\n"
                    f"🔢 Serie: `{serial}`\n\n"
                    f"El equipo ha sido actualizado a estado: **OPEN** 🔓"
                )
            }

    except Exception as e:
        return {"exito": False, "sin_datos_edm": False, "mensaje": f"❌ Error técnico: {str(e)}"}
