from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.request import HTTPXRequest
import os, json, asyncio, firebase_admin
from firebase_admin import credentials, firestore
from concurrent.futures import ThreadPoolExecutor
from web_engine import consultar_y_desbloquear

cred_json = os.getenv("FIREBASE_CRED")
if cred_json:
    cred = credentials.Certificate(json.loads(cred_json))
else:
    cred = credentials.Certificate("credenciales.json")

firebase_admin.initialize_app(cred)
db = firestore.client()

executor = ThreadPoolExecutor(max_workers=3)

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = 5714303692

estado_usuario = {}


def usuario_autorizado(user_id):
    if user_id == ADMIN_ID:
        return True
    return obtener_usuario(user_id).get("activo", False)


def obtener_usuario(user_id):
    ref = db.collection("usuarios").document(str(user_id))
    doc = ref.get()
    if not doc.exists:
        ref.set({"creditos": 0, "activo": True})
        return {"creditos": 0, "activo": True}
    return doc.to_dict()


def descontar_credito(user_id):
    ref = db.collection("usuarios").document(str(user_id))
    doc = ref.get()
    if not doc.exists:
        return False, 0
    data = doc.to_dict()
    creditos = data.get("creditos", 0)
    if creditos <= 0:
        return False, creditos
    nuevos = creditos - 1
    ref.update({"creditos": nuevos})
    return True, nuevos


def guardar_historial(user_id, operador, serial, creditos_restantes, exito):
    db.collection("historial").add({
        "user_id": str(user_id),
        "operador": operador,
        "serial": serial,
        "fecha": datetime.now().isoformat(),
        "creditos_restantes": creditos_restantes,
        "exito": exito
    })


def obtener_menu_principal():
    return ReplyKeyboardMarkup(
        [["🆕 Nueva consulta"], ["💰 Ver saldo"]],
        resize_keyboard=True
    )


def obtener_menu_operador():
    return ReplyKeyboardMarkup(
        [["CLARO", "VTR"]],
        resize_keyboard=True
    )


def cortar_mensaje(mensaje, limite=3500):
    if len(mensaje) > limite:
        return mensaje[:limite] + "\n\n...mensaje cortado."
    return mensaje


def limpiar_screenshots_usados(screenshots):
    for path in screenshots:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            print(f"Error limpiando screenshot {path}: {e}")


async def enviar_screenshots_admin(context, user_id, operador, serial, screenshots):
    if not screenshots:
        return

    labels = {
        "1_login": "🔐 Login",
        "2_operador": "📡 Operador seleccionado",
        "3_device_query": "🔍 Device Query abierto",
        "4_query_resultado": "📋 Resultado Query",
        "5_sin_datos": "⚠️ Sin datos EDM",
        "5_datos_ok": "✅ Datos encontrados",
        "6_post_unlock": "🔓 Post Unlock",
        "7_resultado_final": "✅ Resultado final",
        "7_error_query_final": "⚠️ Error Query final",
    }

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"📸 *Screenshots de operación*\n\n"
            f"👤 Usuario: `{user_id}`\n"
            f"📡 Operador: {operador}\n"
            f"🔢 Serie: `{serial}`"
        ),
        parse_mode="Markdown"
    )

    for path in screenshots:
        nombre = os.path.splitext(os.path.basename(path))[0]
        caption = labels.get(nombre, nombre)
        try:
            with open(path, "rb") as f:
                await context.bot.send_photo(
                    chat_id=ADMIN_ID,
                    photo=f,
                    caption=caption
                )
        except Exception as e:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"⚠️ No se pudo enviar screenshot `{nombre}`: {e}",
                parse_mode="Markdown"
            )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not usuario_autorizado(user_id):
        await update.message.reply_text("❌ No tienes acceso a este sistema.")
        return
    await update.message.reply_text(
        "✅ Bienvenido al Sistema",
        reply_markup=obtener_menu_principal()
    )


async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = obtener_usuario(user_id)
    if not user.get("activo", True):
        await update.message.reply_text("❌ Usuario bloqueado.")
        return
    await update.message.reply_text(
        f"💰 Tienes {user.get('creditos', 0)} créditos disponibles"
    )


async def addcreditos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ No autorizado.")
        return
    try:
        target_id = context.args[0]
        cantidad = int(context.args[1])
        nombre = context.args[2] if len(context.args) > 2 else None
    except Exception:
        await update.message.reply_text("Uso: /addcreditos ID CANTIDAD NOMBRE(opcional)")
        return
    ref = db.collection("usuarios").document(str(target_id))
    doc = ref.get()
    if not doc.exists:
        data = {"creditos": cantidad, "activo": True}
        if nombre:
            data["nombre"] = nombre
        ref.set(data)
    else:
        data = doc.to_dict()
        update_data = {"creditos": data.get("creditos", 0) + cantidad}
        if nombre:
            update_data["nombre"] = nombre
        ref.update(update_data)
    await update.message.reply_text(f"✅ Créditos agregados a {target_id}")


async def usuarios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ No autorizado.")
        return
    mensaje = "📊 Lista de usuarios:\n\n"
    for doc in db.collection("usuarios").stream():
        data = doc.to_dict()
        estado = "🟢" if data.get("activo", False) else "🔴"
        nombre = data.get("nombre", "Sin nombre")
        creditos = data.get("creditos", 0)
        mensaje += f"{estado} {nombre} → {creditos} créditos\n"
    await update.message.reply_text(cortar_mensaje(mensaje))


async def bloquear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ No autorizado.")
        return
    try:
        target_id = context.args[0]
    except Exception:
        await update.message.reply_text("Uso: /bloquear ID")
        return
    db.collection("usuarios").document(str(target_id)).set({"activo": False}, merge=True)
    await update.message.reply_text(f"⛔ Usuario {target_id} bloqueado")


async def desbloquear_usuario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ No autorizado.")
        return
    try:
        target_id = context.args[0]
    except Exception:
        await update.message.reply_text("Uso: /desbloquear ID")
        return
    db.collection("usuarios").document(str(target_id)).set({"activo": True}, merge=True)
    await update.message.reply_text(f"✅ Usuario {target_id} desbloqueado")


async def ver_historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ No autorizado.")
        return
    docs = (
        db.collection("historial")
        .order_by("fecha", direction=firestore.Query.DESCENDING)
        .limit(5)
        .stream()
    )
    mensaje = "📜 Últimas consultas:\n\n"
    count = 0
    for doc in docs:
        data = doc.to_dict()
        resultado = "✅" if data.get("exito") else "❌"
        mensaje += (
            f"{resultado} Usuario: {data.get('user_id')}\n"
            f"📡 Operador: {data.get('operador', 'N/A')}\n"
            f"🔢 Serie: {data.get('serial')}\n"
            f"💰 Restante: {data.get('creditos_restantes')}\n"
            f"----------------------\n"
        )
        count += 1
    if count == 0:
        mensaje = "No hay historial aún."
    await update.message.reply_text(cortar_mensaje(mensaje))


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    texto = update.message.text.strip()
    texto_upper = texto.upper()

    if not usuario_autorizado(user_id):
        await update.message.reply_text("❌ No tienes acceso a este sistema.")
        return

    user = obtener_usuario(user_id)

    if not user.get("activo", True):
        await update.message.reply_text("❌ Usuario bloqueado.")
        return

    # ── Ver saldo ────────────────────────────────────────────────────────────────
    if texto_upper == "💰 VER SALDO":
        await update.message.reply_text(
            f"💰 Tienes {user.get('creditos', 0)} créditos disponibles",
            reply_markup=obtener_menu_principal()
        )
        return

    # ── Nueva consulta ───────────────────────────────────────────────────────────
    if texto_upper == "🆕 NUEVA CONSULTA":
        estado_usuario[user_id] = {"paso": "esperando_operador"}
        await update.message.reply_text(
            "¿El equipo es CLARO o VTR?",
            reply_markup=obtener_menu_operador()
        )
        return

    estado = estado_usuario.get(user_id, {})
    paso = estado.get("paso", "")

    # ── Esperando operador ───────────────────────────────────────────────────────
    if paso == "esperando_operador":
        if texto_upper not in ["CLARO", "VTR"]:
            await update.message.reply_text(
                "❌ Debes elegir CLARO o VTR.",
                reply_markup=obtener_menu_operador()
            )
            return
        estado_usuario[user_id]["operador"] = texto_upper
        estado_usuario[user_id]["paso"] = "esperando_serial"
        await update.message.reply_text(
            "Envíame la serie del equipo en mayúsculas.\n"
            "Ejemplo: E77BYG243900180"
        )
        return

    # ── Esperando serial ─────────────────────────────────────────────────────────
    if paso == "esperando_serial":
        serial = texto_upper
        operador = estado["operador"]

        if not serial.isalnum():
            await update.message.reply_text(
                "❌ La serie solo debe contener letras y números."
            )
            return

        if len(serial) < 10 or len(serial) > 20:
            await update.message.reply_text(
                "❌ La serie debe tener entre 10 y 20 caracteres."
            )
            return

        creditos_actuales = user.get("creditos", 0)

        if creditos_actuales <= 0:
            await update.message.reply_text(
                "❌ No tienes créditos disponibles.",
                reply_markup=obtener_menu_principal()
            )
            estado_usuario.pop(user_id, None)
            return

        estado_usuario[user_id]["paso"] = "procesando"

        await update.message.reply_text(
            f"⏳ Procesando solicitud...\n\n"
            f"📡 Operador: {operador}\n"
            f"🔢 Serie: {serial}\n\n"
            f"Esto puede tardar unos segundos, por favor espera."
        )

        try:
            loop = asyncio.get_event_loop()
            resultado = await loop.run_in_executor(
                executor,
                consultar_y_desbloquear,
                operador,
                serial
            )
        except Exception as e:
            print(f"Error en executor: {e}")
            await update.message.reply_text(
                "❌ Ocurrió un error inesperado. No se descontaron créditos.",
                reply_markup=obtener_menu_principal()
            )
            estado_usuario.pop(user_id, None)
            return

        operador_final = resultado.get("operador", operador)
        screenshots = resultado.get("screenshots", [])
        sin_datos_edm = resultado.get("sin_datos_edm", False)

        # Enviar screenshots al admin siempre
        if screenshots:
            await enviar_screenshots_admin(
                context, user_id, operador_final, serial, screenshots
            )
            limpiar_screenshots_usados(screenshots)

        if resultado["exito"]:
            # ✅ ÉXITO — descontar crédito SOLO aquí
            ok, creditos_restantes = descontar_credito(user_id)
            guardar_historial(
                user_id, operador_final, serial, creditos_restantes, exito=True
            )
            mensaje = (
                f"{resultado['mensaje']}\n\n"
                f"💰 Créditos restantes: {creditos_restantes}"
            )
            await update.message.reply_text(
                cortar_mensaje(mensaje),
                reply_markup=obtener_menu_principal(),
                parse_mode="Markdown"
            )

        elif sin_datos_edm:
            # ⚠️ Sin datos EDM — NO descontar crédito
            # Informar y devolver al menú para que intente con otra compañía
            guardar_historial(
                user_id, operador_final, serial, creditos_actuales, exito=False
            )
            await update.message.reply_text(
                cortar_mensaje(resultado["mensaje"]),
                reply_markup=obtener_menu_principal(),
                parse_mode="Markdown"
            )

        else:
            # ❌ Error técnico — NO descontar crédito
            guardar_historial(
                user_id, operador_final, serial, creditos_actuales, exito=False
            )
            await update.message.reply_text(
                cortar_mensaje(resultado["mensaje"]),
                reply_markup=obtener_menu_principal(),
                parse_mode="Markdown"
            )

        estado_usuario.pop(user_id, None)
        return

    # ── Sin estado activo ────────────────────────────────────────────────────────
    await update.message.reply_text(
        "Elige una opción del menú.",
        reply_markup=obtener_menu_principal()
    )


# ── Configuración y arranque ─────────────────────────────────────────────────

request = HTTPXRequest(
    connect_timeout=30,
    read_timeout=30,
    write_timeout=30,
    pool_timeout=30
)

app = ApplicationBuilder().token(TOKEN).request(request).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("saldo", saldo))
app.add_handler(CommandHandler("addcreditos", addcreditos))
app.add_handler(CommandHandler("usuarios", usuarios))
app.add_handler(CommandHandler("bloquear", bloquear))
app.add_handler(CommandHandler("desbloquear", desbloquear_usuario))
app.add_handler(CommandHandler("historial", ver_historial))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

print("Bot iniciado...")
app.run_polling(drop_pending_updates=True)

