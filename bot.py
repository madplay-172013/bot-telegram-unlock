from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

import os
import json
import asyncio
import firebase_admin
from firebase_admin import credentials, firestore
from concurrent.futures import ThreadPoolExecutor

from web_engine import consultar_y_desbloquear

# 🔥 Firebase
cred_json = os.getenv("FIREBASE_CRED")

if cred_json:
    cred_dict = json.loads(cred_json)
    cred = credentials.Certificate(cred_dict)
else:
    cred = credentials.Certificate("credenciales.json")

firebase_admin.initialize_app(cred)

db = firestore.client()

# Ejecutor para Playwright en hilo separado
executor = ThreadPoolExecutor(max_workers=3)

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = 5714303692

estado_usuario = {}

# ── Helpers ───────────────────────────────────────────────────────────────────

def usuario_autorizado(user_id):
    if user_id == ADMIN_ID:
        return True
    user = obtener_usuario(user_id)
    return user.get("activo", False)

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
    return ReplyKeyboardMarkup([["🆕 Nueva consulta"], ["💰 Ver saldo"]], resize_keyboard=True)

def obtener_menu_operador():
    return ReplyKeyboardMarkup([["CLARO", "VTR"]], resize_keyboard=True)

async def enviar_screenshots_admin(context, user_id, operador, serial, screenshots):
    """Envía las capturas de pantalla solo al admin con contexto de la operación."""
    if not screenshots:
        return

    labels = {
        "1_login": "🔐 Paso 1 — Login",
        "2_resultado_busqueda": "🔍 Paso 2 — Resultado búsqueda",
        "3_antes_confirmar": "🔓 Paso 3 — Antes de confirmar unlock",
        "3_sin_datos": "⚠️ Paso 3 — Sin datos encontrados",
        "3_sin_boton_unlock": "⚠️ Paso 3 — Sin botón Unlock",
        "4_resultado_final": "✅ Paso 4 — Resultado final",
    }

    # Cabecera al admin
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

    # Enviar cada screenshot con su etiqueta
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

# ── Handlers ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not usuario_autorizado(user_id):
        await update.message.reply_text("❌ No tienes acceso a este sistema.")
        return
    await update.message.reply_text("✅ Bienvenido al Sistema", reply_markup=obtener_menu_principal())

async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = obtener_usuario(user_id)
    if not user.get("activo", True):
        await update.message.reply_text("❌ Usuario bloqueado.")
        return
    await update.message.reply_text(f"💰 Tienes {user.get('creditos', 0)} créditos disponibles")

async def addcreditos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ No autorizado.")
        return
    try:
        target_id = context.args[0]
        cantidad = int(context.args[1])
        nombre = context.args[2] if len(context.args) > 2 else None
    except:
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
    docs = db.collection("usuarios").stream()
    mensaje = "📊 Lista de usuarios:\n\n"
    for doc in docs:
        data = doc.to_dict()
        estado = "🟢" if data.get("activo", False) else "🔴"
        mensaje += f"{estado} {data.get('nombre', 'Sin nombre')} → {data.get('creditos', 0)} créditos\n"
    await update.message.reply_text(mensaje)

async def bloquear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ No autorizado.")
        return
    try:
        target_id = context.args[0]
    except:
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
    except:
        await update.message.reply_text("Uso: /desbloquear ID")
        return
    db.collection("usuarios").document(str(target_id)).set({"activo": True}, merge=True)
    await update.message.reply_text(f"✅ Usuario {target_id} desbloqueado")

async def ver_historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ No autorizado.")
        return
    docs = db.collection("historial").order_by("fecha", direction=firestore.Query.DESCENDING).limit(5).stream()
    mensaje = "📜 Últimas consultas:\n\n"
    count = 0
    for doc in docs:
        data = doc.to_dict()
        resultado = "✅" if data.get("exito") else "❌"
        mensaje += (
            f"{resultado} Usuario: {data['user_id']}\n"
            f"📡 Operador: {data['operador']}\n"
            f"🔢 Serie: {data['serial']}\n"
            f"💰 Restante: {data['creditos_restantes']}\n"
            f"----------------------\n"
        )
        count += 1
    if count == 0:
        mensaje = "No hay historial aún."
    await update.message.reply_text(mensaje)

# ── Handler principal ─────────────────────────────────────────────────────────

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    texto = update.message.text.strip().upper()

    if not usuario_autorizado(user_id):
        await update.message.reply_text("❌ No tienes acceso a este sistema.")
        return

    user = obtener_usuario(user_id)

    if not user.get("activo", True):
        await update.message.reply_text("❌ Usuario bloqueado.")
        return

    # Ver saldo
    if texto == "💰 VER SALDO":
        await update.message.reply_text(
            f"💰 Tienes {user.get('creditos', 0)} créditos disponibles",
            reply_markup=obtener_menu_principal()
        )

    # Nueva consulta
    elif texto == "🆕 NUEVA CONSULTA":
        estado_usuario[user_id] = {"paso": "esperando_operador"}
        await update.message.reply_text("¿El equipo es CLARO o VTR?", reply_markup=obtener_menu_operador())

    # Selección operador
    elif texto in ["CLARO", "VTR"]:
        if user_id in estado_usuario and estado_usuario[user_id].get("paso") == "esperando_operador":
            estado_usuario[user_id]["operador"] = texto
            estado_usuario[user_id]["paso"] = "esperando_serial"
            await update.message.reply_text(
                "Envíame la serie del equipo en mayúsculas, tal como aparece en pantalla.\n"
                "Ejemplo: E77BZG987654321"
            )
        else:
            await update.message.reply_text("Primero pulsa 🆕 Nueva consulta", reply_markup=obtener_menu_principal())

    # Recepción del serial → ejecutar desbloqueo
    elif user_id in estado_usuario and estado_usuario[user_id].get("paso") == "esperando_serial":
        serial = texto

        if not serial.isalnum():
            await update.message.reply_text("❌ La serie solo debe contener letras y números.")
            return

        if len(serial) < 10 or len(serial) > 20:
            await update.message.reply_text("❌ La serie debe tener entre 10 y 20 caracteres.")
            return

        creditos_actuales = user.get("creditos", 0)
        if creditos_actuales <= 0:
            await update.message.reply_text("❌ No tienes créditos disponibles.", reply_markup=obtener_menu_principal())
            return

        operador = estado_usuario[user_id]["operador"]
        estado_usuario[user_id]["paso"] = "procesando"

        await update.message.reply_text(
            f"⏳ Procesando solicitud...\n\n"
            f"📡 Operador: {operador}\n"
            f"🔢 Serie: {serial}\n\n"
            f"Esto puede tardar unos segundos, por favor espera."
        )

        # Ejecutar Playwright en hilo separado
        loop = asyncio.get_event_loop()
        resultado = await loop.run_in_executor(
            executor,
            consultar_y_desbloquear,
            operador,
            serial
        )

        # ── Enviar screenshots al admin (siempre, éxito o error) ──────────
        screenshots = resultado.get("screenshots", [])
        if screenshots:
            await enviar_screenshots_admin(context, user_id, operador, serial, screenshots)

        if resultado["exito"]:
            # Descontar crédito solo si fue exitoso
            ok, creditos_restantes = descontar_credito(user_id)
            guardar_historial(user_id, operador, serial, creditos_restantes, exito=True)

            await update.message.reply_text(
                f"{resultado['mensaje']}\n\n💰 Créditos restantes: {creditos_restantes}",
                reply_markup=obtener_menu_principal(),
                parse_mode="Markdown"
            )
        else:
            guardar_historial(user_id, operador, serial, creditos_actuales, exito=False)

            mensaje = resultado["mensaje"]

        if len(mensaje) > 3500:
            mensaje = mensaje[:3500] + "\n\n...mensaje cortado por ser muy largo."

        await update.message.reply_text(
            mensaje,
            reply_markup=obtener_menu_principal()
        )

        estado_usuario.pop(user_id, None)

    else:
        await update.message.reply_text("Elige una opción del menú.", reply_markup=obtener_menu_principal())

# ── App ────────────────────────────────────────────────────────────────────────

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("saldo", saldo))
app.add_handler(CommandHandler("addcreditos", addcreditos))
app.add_handler(CommandHandler("usuarios", usuarios))
app.add_handler(CommandHandler("bloquear", bloquear))
app.add_handler(CommandHandler("desbloquear", desbloquear_usuario))
app.add_handler(CommandHandler("historial", ver_historial))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

print("Bot iniciado...")
app.run_polling()
