from datetime import datetime

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

# 🔥 Firebase desde variable
cred_json = os.getenv("FIREBASE_CRED")
cred_dict = json.loads(cred_json)

cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)

db = firestore.client()

# 🔐 Token seguro
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = 5714303692

estado_usuario = {}

def es_admin(user_id):
    return user_id == ADMIN_ID

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

    nuevos_creditos = creditos - 1
    ref.update({"creditos": nuevos_creditos})
    return True, nuevos_creditos

def guardar_historial(user_id, operador, serial, creditos_restantes):
    db.collection("historial").add({
        "user_id": str(user_id),
        "operador": operador,
        "serial": serial,
        "fecha": datetime.now().isoformat(),
        "creditos_restantes": creditos_restantes
    })

def obtener_menu_principal():
    keyboard = [
        ["🆕 Nueva consulta"],
        ["💰 Ver saldo"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def obtener_menu_operador():
    keyboard = [["CLARO", "VTR"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not usuario_autorizado(user_id):
        await update.message.reply_text("❌ No tienes acceso a este sistema.")
        return

    await update.message.reply_text(
        "✅ Bienvenido administrador",
        reply_markup=obtener_menu_principal()
    )

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
    except:
        await update.message.reply_text("Uso: /addcreditos ID CANTIDAD")
        return

    ref = db.collection("usuarios").document(str(target_id))
    doc = ref.get()

    if not doc.exists:
        ref.set({"creditos": cantidad, "activo": True})
    else:
        data = doc.to_dict()
        nuevos = data.get("creditos", 0) + cantidad
        ref.update({"creditos": nuevos})

    await update.message.reply_text(f"✅ Créditos agregados a {target_id}")

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

async def desbloquear(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        mensaje += (
            f"👤 Usuario: {data['user_id']}\n"
            f"📡 Operador: {data['operador']}\n"
            f"🔢 Serie: {data['serial']}\n"
            f"💰 Restante: {data['creditos_restantes']}\n"
            f"----------------------\n"
        )
        count += 1

    if count == 0:
        mensaje = "No hay historial aún."

    await update.message.reply_text(mensaje)    

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    texto_original = update.message.text.strip()
    texto = texto_original.upper()

    if not usuario_autorizado(user_id):
        await update.message.reply_text("❌ No tienes acceso a este sistema.")
        return

    user = obtener_usuario(user_id)

    if not user.get("activo", True):
        await update.message.reply_text("❌ Usuario bloqueado.")
        return

    if texto == "💰 VER SALDO":
        await update.message.reply_text(
            f"💰 Tienes {user.get('creditos', 0)} créditos disponibles",
            reply_markup=obtener_menu_principal()
        )

    elif texto == "🆕 NUEVA CONSULTA":
        estado_usuario[user_id] = {"paso": "esperando_operador"}
        await update.message.reply_text(
            "¿El equipo es CLARO o VTR?",
            reply_markup=obtener_menu_operador()
        )

    elif texto in ["CLARO", "VTR"]:
        if user_id in estado_usuario and estado_usuario[user_id].get("paso") == "esperando_operador":
            estado_usuario[user_id]["operador"] = texto
            estado_usuario[user_id]["paso"] = "esperando_serial"
            await update.message.reply_text(
                "Envíame la serie del equipo en mayúsculas, tal como aparece en pantalla.\nEjemplo: E77BZG987654321"
            )
        else:
            await update.message.reply_text(
                "Primero pulsa 🆕 Nueva consulta",
                reply_markup=obtener_menu_principal()
            )

    elif user_id in estado_usuario and estado_usuario[user_id].get("paso") == "esperando_serial":
        serial = texto

        if not serial.isalnum():
            await update.message.reply_text("❌ La serie solo debe contener letras y números.")
            return

        if len(serial) < 10 or len(serial) > 20:
            await update.message.reply_text("❌ La serie debe tener entre 10 y 20 caracteres.")
            return

        ok, creditos_restantes = descontar_credito(user_id)

        if not ok:
            await update.message.reply_text("❌ No tienes créditos disponibles.")
            return

        operador = estado_usuario[user_id]["operador"]

        guardar_historial(user_id, operador, serial, creditos_restantes)

        estado_usuario[user_id]["serial"] = serial
        estado_usuario[user_id]["paso"] = "serial_recibido"

        await update.message.reply_text(
            f"✅ Datos recibidos:\n"
            f"Operador: {operador}\n"
            f"Serie: {serial}\n\n"
            f"💰 Créditos restantes: {creditos_restantes}",
            reply_markup=obtener_menu_principal()
        )

    else:
        await update.message.reply_text(
            "Elige una opción del menú.",
            reply_markup=obtener_menu_principal()
        )

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("saldo", saldo))
app.add_handler(CommandHandler("addcreditos", addcreditos))
app.add_handler(CommandHandler("bloquear", bloquear))
app.add_handler(CommandHandler("desbloquear", desbloquear))
app.add_handler(CommandHandler("historial", ver_historial))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

print("Bot iniciado...")
app.run_polling()
