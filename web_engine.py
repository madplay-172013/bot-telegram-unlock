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
        """
        Captura screenshot. Si se pasa selector_foco, hace scroll hasta ese
        elemento para que quede visible en el centro de la captura.
        """
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
        """
        Retorna True SOLO si hay error EDM Y además NO hay Device Status.
        'Device Binding not found' NO es error — puede aparecer junto a datos reales.
        """
        try:
            texto = page.inner_text("body").upper()
        except Exception:
            return False

        errores_edm = [
            "NO EDM INFO AVAILABLE",
            "EDM API SERVICE UNREACHABLE",
        ]
        tiene_error_edm = any(e in texto for e in errores_edm)
        if not tiene_error_edm:
            return False

        # Si hay Device Status, hay datos reales aunque haya error EDM
        indicadores_datos = [
            "DEVICE STATUS",
            "STB BASIC STATUS",
            "REMOTE CONTROL UNIT",
            "UPTIME",
            "EDM LOCKING STATUS",
        ]
        tiene_datos = any(ind in texto for ind in indicadores_datos)
        return not tiene_datos

    def tiene_data_real(page):
        """
        Espera hasta 45s a que aparezca Device Status.
        - Primeros 15s: chequea cada 3s (da tiempo al JS de la web)
        - Siguientes 30s: chequea cada 3s
        Retorna True si encuentra datos, False si no.
        """
        indicadores = [
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
        selectores = [
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

        # Espera inicial fija de 6s — la web tarda ese tiempo mínimo en cargar EDM
        print(f"  Esperando carga inicial EDM (6s)...")
        page.wait_for_timeout(6000)

        # Luego chequeamos hasta 45s más (15 intentos x 3s)
        for intento in range(15):
            # Error EDM real sin datos → salir inmediatamente
            if pagina_tiene_error_edm_real(page):
                print(f"  [intento {intento+1}] Error EDM real detectado")
                return False

            # Buscar selectores
            for selector in selectores:
                try:
                    if page.locator(selector).count() > 0:
                        print(f"  [intento {intento+1}] ✅ Datos encontrados: {selector}")
                        return True
                except Exception:
                    pass

            # Buscar en body
            try:
                texto = page.inner_text("body").upper()
                for ind in indicadores:
                    if ind in texto:
                        print(f"  [intento {intento+1}] ✅ Datos encontrados en body: {ind}")
                        return True
            except Exception:
                pass

            print(f"  [intento {intento+1}] Sin datos aún, esperando 3s...")
            page.wait_for_timeout(3000)

        return False

    def login(page):
        page.goto(URL, timeout=30000)
        page.wait_for_timeout(3000)
        page.wait_for_selector("input:visible", timeout=15000)
        inputs = page.locator("input:visible")
        inputs.nth(0).fill(USUARIO)
        inputs.nth(1).fill(PASSWORD)
        page.wait_for_timeout(1000)
        page.locator("button:visible").first.click()
        page.wait_for_timeout(8000)

    def seleccionar_operador(page, operador):
        if operador == "CLARO":
            page.locator("select").select_option(label="Producción @ Claro, Chile")
        elif operador == "VTR":
            page.locator("select").select_option(label="Producción @ VTR, Chile")
        page.wait_for_timeout(3000)

    def abrir_device_query(page):
        page.get_by_text("Query User", exact=True).click()
        page.wait_for_timeout(2000)
        page.get_by_text("Device Query", exact=True).click()
        page.wait_for_timeout(4000)

    def ejecutar_query(page, serial):
        search_input = page.locator("input:visible").last
        search_input.clear()
        search_input.fill(serial)
        page.wait_for_timeout(1000)
        query_btn = page.locator(
            'button:has-text("Query"), input[value="Query"], a:has-text("Query")'
        ).first
        query_btn.wait_for(timeout=10000)
        query_btn.click()
        # NO ponemos wait fijo aquí — tiene_data_real maneja la espera

    def ejecutar_unlock(page):
        """
        Dos dialogs consecutivos:
        1. "Do you want to unlock the device?" → Aceptar (espera ~2s)
        2. "Unlock sent"                        → Aceptar (espera ~3s)
        """
        try:
            unlock_btn = page.locator(
                'button:has-text("Unlock"), input[value="Unlock"], a:has-text("Unlock")'
            ).first
            unlock_btn.wait_for(timeout=15000)
        except PlaywrightTimeoutError:
            return False

        def handle_dialog(dialog):
            print(f"  Dialog: '{dialog.message}' → aceptando")
            dialog.accept()

        page.on("dialog", handle_dialog)
        unlock_btn.click()

        # Esperar suficiente para que ambos dialogs se disparen y resuelvan
        # Dialog 1 aparece ~2s, Dialog 2 aparece ~3s después
        page.wait_for_timeout(8000)

        page.remove_listener("dialog", handle_dialog)
        return True

    def ejecutar_query_final(page):
        """Query final para ver candado rojo → verde."""
        query_btn = page.locator(
            'button:has-text("Query"), input[value="Query"], a:has-text("Query")'
        ).first
        query_btn.wait_for(timeout=10000)
        query_btn.click()
        # Esperar carga EDM igual que antes
        page.wait_for_timeout(6000)
        # Esperar un poco más para que el estado del candado se actualice
        page.wait_for_timeout(4000)

    # ─── FLUJO PRINCIPAL ────────────────────────────────────────────────────────

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            page = browser.new_page(viewport={"width": 1280, "height": 900})

            # 1. LOGIN
            print(f"[{operador}] Iniciando sesión...")
            login(page)

            # 2. SELECCIONAR OPERADOR
            print(f"[{operador}] Seleccionando operador...")
            seleccionar_operador(page, operador)

            # 3. ABRIR DEVICE QUERY
            print(f"[{operador}] Abriendo Device Query...")
            abrir_device_query(page)

            # 4. QUERY CON LA SERIE
            print(f"[{operador}] Ejecutando Query para serie {serial}...")
            ejecutar_query(page, serial)

            # 5. ESPERAR Y VALIDAR DATOS REALES
            print(f"[{operador}] Esperando carga de datos EDM...")
            hay_datos = tiene_data_real(page)

            if not hay_datos:
                # Screenshot enfocado en Results para ver el error
                capturar(page, "sin_datos", selector_foco="text=Results")
                browser.close()
                print(f"[{operador}] ❌ Sin datos para {serial}")
                return {
                    "exito": False,
                    "sin_datos_edm": True,
                    "operador": operador,
                    "screenshots": screenshots,
                    "mensaje": (
                        f"⚠️ *Operación no realizada*\n\n"
                        f"No se encontraron datos para la serie `{serial}` en *{operador}*.\n\n"
                        f"Inicia una nueva consulta y prueba con la otra compañía.\n\n"
                        f"_No se descontaron créditos._"
                    )
                }

            # 6. DATOS ENCONTRADOS → UNLOCK
            print(f"[{operador}] ✅ Datos encontrados. Ejecutando Unlock...")
            unlock_ok = ejecutar_unlock(page)

            if not unlock_ok:
                # Screenshot enfocado en Operations para ver por qué no hay Unlock
                capturar(page, "sin_unlock", selector_foco="text=Operations")
                browser.close()
                return {
                    "exito": False,
                    "sin_datos_edm": False,
                    "operador": operador,
                    "screenshots": screenshots,
                    "mensaje": (
                        "⚠️ Se encontraron datos pero no apareció el botón *UNLOCK*.\n\n"
                        "_No se descontaron créditos._"
                    )
                }

            # 7. QUERY FINAL → verificar candado
            print(f"[{operador}] Query final para verificar estado...")
            try:
                ejecutar_query_final(page)
                # Screenshot enfocado en Device Status para ver el candado
                capturar(page, "resultado_final", selector_foco="text=Device Status")
            except PlaywrightTimeoutError:
                capturar(page, "error_query_final", selector_foco="text=Results")
                browser.close()
                return {
                    "exito": False,
                    "sin_datos_edm": False,
                    "operador": operador,
                    "screenshots": screenshots,
                    "mensaje": (
                        "⚠️ Se ejecutó UNLOCK pero no se pudo verificar el estado final.\n\n"
                        "Revisa manualmente el equipo.\n\n"
                        "_No se descontaron créditos automáticamente._"
                    )
                }

            browser.close()
            print(f"[{operador}] ✅ Proceso completado para {serial}")
            return {
                "exito": True,
                "sin_datos_edm": False,
                "operador": operador,
                "screenshots": screenshots,
                "mensaje": (
                    f"✅ *Proceso completado correctamente*\n\n"
                    f"📡 Operador: *{operador}*\n"
                    f"🔢 Serie: `{serial}`\n\n"
                    f"Equipo verificado y desbloqueado correctamente. 🔓"
                )
            }

    except PlaywrightTimeoutError:
        return {
            "exito": False,
            "sin_datos_edm": False,
            "operador": operador,
            "screenshots": screenshots,
            "mensaje": (
                "⏱️ Tiempo de espera agotado. La web tardó demasiado.\n"
                "_No se descontaron créditos. Intenta nuevamente._"
            )
        }
    except Exception as e:
        return {
            "exito": False,
            "sin_datos_edm": False,
            "operador": operador,
            "screenshots": screenshots,
            "mensaje": (
                f"❌ Error inesperado.\n_No se descontaron créditos._\n\n"
                f"Detalle: {str(e)}"
            )
        }
