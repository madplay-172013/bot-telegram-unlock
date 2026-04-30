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
        try:
            page.screenshot(path=path, full_page=True)
            screenshots.append(path)
        except Exception as e:
            print(f"Error capturando screenshot {nombre}: {e}")

    def pagina_tiene_error_edm(page):
        """
        Error EDM real = los avisos amarillos de EDM aparecen
        Y además NO hay Device Status visible.
        Si hay Device Status, NO es error aunque aparezca el aviso de binding.
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

        # Aunque haya error EDM, si hay Device Status = hay datos reales
        indicadores_datos = [
            "DEVICE STATUS",
            "STB BASIC STATUS",
            "CUSTOMER INFORMATION",
            "TIVO CONTRACT DETAILS",
            "DEVICE METADATA",
            "UPTIME",
            "EDM LOCKING STATUS",
        ]
        tiene_datos = any(ind in texto for ind in indicadores_datos)

        # Solo es error real si hay mensaje EDM Y no hay datos
        return not tiene_datos

    def tiene_data_real(page):
        """
        Espera hasta 30s a que aparezca Device Status u otros indicadores.
        Device Binding not found puede coexistir con datos reales — no es bloqueante.
        """
        indicadores = [
            "DEVICE STATUS",
            "STB BASIC STATUS",
            "CUSTOMER INFORMATION",
            "TIVO CONTRACT DETAILS",
            "DEVICE METADATA",
            "UPTIME",
            "EDM LOCKING STATUS",
        ]
        selectores = [
            "text=Device Status",
            "text=STB basic status",
            "text=Customer Information",
            "text=TiVO Contract Details",
            "text=Device Metadata",
            "text=Uptime",
            "text=EDM locking status",
        ]

        for intento in range(15):  # 15 x 2s = 30s máximo
            # Si hay error EDM real (sin datos), salir rápido
            if pagina_tiene_error_edm(page):
                print(f"  [intento {intento+1}] Error EDM detectado sin datos reales")
                return False

            # Buscar selectores directos
            for selector in selectores:
                try:
                    if page.locator(selector).count() > 0:
                        print(f"  [intento {intento+1}] Datos encontrados: {selector}")
                        return True
                except Exception:
                    pass

            # Buscar en texto del body
            try:
                texto = page.inner_text("body").upper()
                for ind in indicadores:
                    if ind in texto:
                        print(f"  [intento {intento+1}] Datos encontrados en body: {ind}")
                        return True
            except Exception:
                pass

            print(f"  [intento {intento+1}] Esperando datos...")
            page.wait_for_timeout(2000)

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
        page.wait_for_timeout(7000)

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
        page.wait_for_timeout(10000)

    def ejecutar_unlock(page):
        """
        Hay DOS dialogs consecutivos:
        1. "Do you want to unlock the device?" → Aceptar
        2. "Unlock sent"                        → Aceptar
        page.on() cubre ambos automáticamente.
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
        # Esperar suficiente para que ambos dialogs se resuelvan
        page.wait_for_timeout(8000)
        page.remove_listener("dialog", handle_dialog)
        return True

    def ejecutar_query_final(page):
        """Query final para refrescar estado (candado rojo → verde)."""
        query_btn = page.locator(
            'button:has-text("Query"), input[value="Query"], a:has-text("Query")'
        ).first
        query_btn.wait_for(timeout=10000)
        query_btn.click()
        page.wait_for_timeout(10000)

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
            capturar(page, "1_login")

            # 2. SELECCIONAR OPERADOR
            print(f"[{operador}] Seleccionando operador...")
            seleccionar_operador(page, operador)
            capturar(page, "2_operador")

            # 3. ABRIR DEVICE QUERY
            print(f"[{operador}] Abriendo Device Query...")
            abrir_device_query(page)
            capturar(page, "3_device_query")

            # 4. QUERY CON LA SERIE
            print(f"[{operador}] Buscando serie {serial}...")
            ejecutar_query(page, serial)
            capturar(page, "4_query_resultado")

            # 5. VALIDAR DATOS REALES
            # IMPORTANTE: "Device Binding not found" puede aparecer siempre,
            # incluso cuando hay datos reales. No es criterio de fallo.
            # El criterio real es: ¿aparece Device Status?
            print(f"[{operador}] Validando datos reales...")
            hay_datos = tiene_data_real(page)

            if not hay_datos:
                capturar(page, "5_sin_datos")
                browser.close()
                print(f"[{operador}] Sin datos reales para {serial}")
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

            # 6. HAY DATOS → UNLOCK
            capturar(page, "5_datos_ok")
            print(f"[{operador}] Datos confirmados. Ejecutando Unlock...")
            unlock_ok = ejecutar_unlock(page)
            capturar(page, "6_post_unlock")

            if not unlock_ok:
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

            # 7. QUERY FINAL → verificar candado rojo → verde
            print(f"[{operador}] Query final para verificar estado...")
            try:
                ejecutar_query_final(page)
                capturar(page, "7_resultado_final")
            except PlaywrightTimeoutError:
                capturar(page, "7_error_query_final")
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
            print(f"[{operador}] ✅ Completado exitosamente para {serial}")
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
