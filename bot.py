import os
import logging
import sqlite3
import requests
import json
import uuid
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ==================== CONFIGURAÇÕES ====================
BOT_TOKEN = "8477706439:AAF1ibc5aI95nM3r2BB6XZpW84GpepYJgiE"
STORE_NAME = "Suppys Store"
SUPPORT_LINK = "https://t.me/suportesuppys7"
GROUP_LINK = "https://t.me/+laIYEeIQuuc1ZWEx"

# Credenciais do Mercado Pago
MERCADOPAGO_ACCESS_TOKEN = "APP_USR-8313019935361645-040523-f5273bbb40e6f8b1cfa385cbb7716aa5-800117337"
MERCADOPAGO_PUBLIC_KEY = "APP_USR-405fcaea-03f8-4fbe-abfb-65e112756083"

# Banco de dados
DB_PATH = 'suppys_store.db'

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== BANCO DE DADOS ====================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                 user_id INTEGER PRIMARY KEY,
                 username TEXT,
                 name TEXT,
                 register_date TEXT,
                 wallet_id TEXT,
                 balance REAL DEFAULT 0,
                 cards_bought INTEGER DEFAULT 0,
                 pix_recharges INTEGER DEFAULT 0,
                 total_recharged REAL DEFAULT 0,
                 referred_by INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER,
                 type TEXT,
                 amount REAL,
                 status TEXT,
                 date TEXT,
                 payment_id TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pending_payments (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER,
                 amount REAL,
                 payment_id TEXT,
                 qr_code TEXT,
                 qr_code_base64 TEXT,
                 status TEXT,
                 created_at TEXT,
                 expires_at TEXT)''')
    conn.commit()
    conn.close()
    logger.info("Banco de dados inicializado")

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def create_user(user_id, username, name, referred_by=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    wallet_id = str(user_id) + str(datetime.now().strftime("%m%d"))
    register_date = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    c.execute("INSERT INTO users (user_id, username, name, register_date, wallet_id, referred_by) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, username, name, register_date, wallet_id, referred_by))
    if referred_by:
        c.execute("UPDATE users SET balance = balance + 5 WHERE user_id = ?", (referred_by,))
    conn.commit()
    conn.close()

def update_balance(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def save_pending_payment(user_id, amount, payment_id, qr_code, qr_code_base64):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    expires_at = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO pending_payments (user_id, amount, payment_id, qr_code, qr_code_base64, status, created_at, expires_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
              (user_id, amount, str(payment_id), qr_code, qr_code_base64, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), expires_at))
    conn.commit()
    conn.close()

def get_pending_payment(payment_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM pending_payments WHERE payment_id = ?", (str(payment_id),))
    payment = c.fetchone()
    conn.close()
    return payment

def update_payment_status(payment_id, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE pending_payments SET status = ? WHERE payment_id = ?", (status, str(payment_id)))
    conn.commit()
    conn.close()

def add_transaction(user_id, type_, amount, status, payment_id=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO transactions (user_id, type, amount, status, date, payment_id) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, type_, amount, status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(payment_id)))
    conn.commit()
    conn.close()

# ==================== MERCADO PAGO ====================

def criar_pix_mercadopago(valor, user_id, email):
    """Cria um PIX dinâmico no Mercado Pago"""
    
    url = "https://api.mercadopago.com/v1/payments"
    
    headers = {
        "Authorization": f"Bearer {MERCADOPAGO_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "transaction_amount": float(valor),
        "description": f"Recarga Suppys Store - Usuário {user_id}",
        "payment_method_id": "pix",
        "payer": {
            "email": email,
            "first_name": f"Usuario{user_id}"
        },
        "notification_url": "https://webhook.site/"  # Opcional
    }
    
    logger.info(f"Enviando requisição para Mercado Pago: {payload}")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        logger.info(f"Status code: {response.status_code}")
        logger.info(f"Resposta: {response.text}")
        
        if response.status_code == 201:
            data = response.json()
            return {
                "success": True,
                "payment_id": data["id"],
                "qr_code": data["point_of_interaction"]["transaction_data"]["qr_code"],
                "qr_code_base64": data["point_of_interaction"]["transaction_data"]["qr_code_base64"],
                "ticket_url": data["point_of_interaction"]["transaction_data"]["ticket_url"]
            }
        else:
            error = response.json()
            logger.error(f"Erro do Mercado Pago: {error}")
            return {"success": False, "error": error.get("message", "Erro desconhecido")}
            
    except Exception as e:
        logger.error(f"Erro na requisição: {str(e)}")
        return {"success": False, "error": str(e)}

def verificar_pagamento(payment_id):
    """Verifica o status do pagamento"""
    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    headers = {"Authorization": f"Bearer {MERCADOPAGO_ACCESS_TOKEN}"}
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            status = data.get("status")
            return status
        return None
    except Exception as e:
        logger.error(f"Erro ao verificar: {e}")
        return None

# ==================== COMANDOS DO BOT ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    if not get_user(user_id):
        referred_by = None
        if context.args and context.args[0].isdigit():
            referred_by = int(context.args[0])
        create_user(user_id, user.username or "sem_username", user.first_name, referred_by)
    
    keyboard = [
        [InlineKeyboardButton("🛒 Comprar", callback_data='comprar')],
        [InlineKeyboardButton("👤 Minha Conta", callback_data='minha_conta')],
        [InlineKeyboardButton("💰 Adicionar Saldo", callback_data='adicionar_saldo')],
        [InlineKeyboardButton("👥 Afiliados", callback_data='afiliados')]
    ]
    
    await update.message.reply_text(
        f"🎉 **Bem-vindo à {STORE_NAME}!** 🎉\n\n"
        f"💳 Cartões FULL de alta qualidade\n"
        f"✅ Garantia de troca em 5 minutos\n"
        f"📍 Suporte: {SUPPORT_LINK}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == 'comprar':
        await mostrar_niveis(query)
    elif data == 'minha_conta':
        await minha_conta(query)
    elif data == 'adicionar_saldo':
        await mostrar_valores_pix(query)
    elif data == 'afiliados':
        await mostrar_afiliados(query, context)
    elif data.startswith('pix_'):
        valor = data.replace('pix_', '')
        await gerar_pix(query, valor)
    elif data.startswith('verificar_'):
        payment_id = data.replace('verificar_', '')
        await verificar_pagamento_callback(query, payment_id)

async def mostrar_niveis(query):
    niveis = [
        ("💰 R$ 20", "STANDARD"),
        ("⚫ R$ 75", "BLACK"),
        ("💎 R$ 30", "ELO"),
        ("🥇 R$ 25", "GOLD"),
        ("💛 R$ 7", "NU_GOLD"),
        ("💜 R$ 15", "NU_PLATINUM"),
    ]
    
    keyboard = [[InlineKeyboardButton(nome, callback_data=f'nivel_{cod}')] for nome, cod in niveis]
    keyboard.append([InlineKeyboardButton("« Voltar", callback_data='voltar')])
    
    await query.edit_message_text(
        "📌 **Escolha um nível:**\n\n"
        "✅ 1056 cartões disponíveis\n"
        "✅ Checker na compra",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def mostrar_valores_pix(query):
    keyboard = [
        [InlineKeyboardButton("💰 R$ 10", callback_data='pix_10'),
         InlineKeyboardButton("💰 R$ 20", callback_data='pix_20'),
         InlineKeyboardButton("💰 R$ 50", callback_data='pix_50')],
        [InlineKeyboardButton("💰 R$ 100", callback_data='pix_100'),
         InlineKeyboardButton("💰 R$ 200", callback_data='pix_200'),
         InlineKeyboardButton("💰 R$ 500", callback_data='pix_500')],
        [InlineKeyboardButton("« Voltar", callback_data='voltar')]
    ]
    
    await query.edit_message_text(
        "💰 **Adicionar Saldo via PIX**\n\n"
        "Escolha o valor para recarga:\n"
        "✅ Saldo em até 30 minutos",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def gerar_pix(query, valor):
    valor = float(valor)
    user_id = query.from_user.id
    email = f"user{user_id}@suppystore.com"
    
    # Mostra mensagem de loading
    await query.edit_message_text("⏱️ Gerando PIX... Aguarde...")
    
    # Cria PIX no Mercado Pago
    resultado = criar_pix_mercadopago(valor, user_id, email)
    
    if resultado["success"]:
        # Salva no banco
        save_pending_payment(user_id, valor, resultado["payment_id"], resultado["qr_code"], resultado["qr_code_base64"])
        
        # Formata a mensagem igual ao exemplo
        mensagem = (
            f"✅ **Suas transações foi criada!**\n\n"
            f"📱 **Código cópia e cola:**\n"
            f"`{resultado['qr_code']}`\n\n"
            f"💰 **Valor:** R$ {valor:.2f}\n"
            f"🆔 **Id transação:** `{resultado['payment_id']}`\n\n"
            f"⏱️ **A transação expira em 30 minutos!**\n\n"
            f"✅ *Dica: para copiar o código basta clicar encima dele*\n\n"
            f"⚠️ Caso você realize o pagamento e não receba seu saldo, chame o suporte!"
        )
        
        keyboard = [[InlineKeyboardButton("✅ Verificar Pagamento", callback_data=f'verificar_{resultado["payment_id"]}')]]
        
        await query.edit_message_text(
            mensagem,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    else:
        await query.edit_message_text(
            f"❌ **Erro ao gerar PIX**\n\n"
            f"Motivo: {resultado.get('error', 'Erro desconhecido')}\n\n"
            f"📍 Suporte: {SUPPORT_LINK}",
            parse_mode='Markdown'
        )

async def verificar_pagamento_callback(query, payment_id):
    await query.edit_message_text("⏱️ Verificando pagamento...")
    
    payment = get_pending_payment(payment_id)
    if not payment:
        await query.edit_message_text("❌ Transação não encontrada!")
        return
    
    status = verificar_pagamento(payment_id)
    
    if status == "approved":
        # Credita saldo
        update_balance(payment[1], payment[2])
        add_transaction(payment[1], "pix", payment[2], "completed", payment_id)
        update_payment_status(payment_id, "completed")
        
        await query.edit_message_text(
            f"✅ **PAGAMENTO CONFIRMADO!**\n\n"
            f"💰 Valor: R$ {payment[2]:.2f}\n"
            f"💵 Saldo creditado na sua carteira!\n\n"
            f"Use /start para voltar ao menu.",
            parse_mode='Markdown'
        )
    elif status == "pending":
        await query.edit_message_text(
            f"⏱️ **Pagamento pendente**\n\n"
            f"💰 Valor: R$ {payment[2]:.2f}\n\n"
            f"✅ Ainda não identificamos seu pagamento.\n"
            f"Assim que confirmar, clique em verificar novamente.",
            parse_mode='Markdown'
        )
    else:
        await query.edit_message_text(
            f"❌ **Pagamento não encontrado ou expirado**\n\n"
            f"Status: {status}\n\n"
            f"📍 Suporte: {SUPPORT_LINK}",
            parse_mode='Markdown'
        )

async def minha_conta(query):
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("❌ Use /start primeiro")
        return
    
    text = (
        f"👤 **MINHA CONTA**\n\n"
        f"📋 Nome: {user[2]}\n"
        f"👤 User: @{user[1]}\n"
        f"📅 Cadastro: {user[3]}\n\n"
        f"🆔 Wallet: `{user[4]}`\n"
        f"💰 Saldo: **R$ {user[5]:.2f}**\n\n"
        f"💳 Cartões: {user[6]}\n"
        f"🔄 Recargas: {user[7]}\n"
        f"📊 Total recarregado: R$ {user[8]:.2f}"
    )
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def mostrar_afiliados(query, context):
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("❌ Use /start primeiro")
        return
    
    link = f"https://t.me/{context.bot.username}?start={user[4]}"
    
    text = (
        f"🎁 **SISTEMA DE AFILIADOS**\n\n"
        f"💰 Ganhe **25% de comissão**!\n\n"
        f"🔗 **Seu link:**\n"
        f"`{link}`\n\n"
        f"📊 Como funciona:\n"
        f"• Compartilhe o link\n"
        f"• Seu amigo se cadastra\n"
        f"• Ele adiciona saldo\n"
        f"• Você ganha 25% automático!\n\n"
        f"✅ Bônus: R$5 por indicação!"
    )
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def voltar_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ==================== MAIN ====================

def main():
    init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    print("=" * 50)
    print("✅ BOT SUPPS STORE ESTÁ ONLINE!")
    print(f"📌 Nome: {STORE_NAME}")
    print(f"💰 Mercado Pago: CONFIGURADO!")
    print("=" * 50)
    
    app.run_polling()

if __name__ == "__main__":
    main()