import os
import logging
import sqlite3
import requests
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
                 referred_by INTEGER,
                 monthly_deposit REAL DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER,
                 type TEXT,
                 amount REAL,
                 status TEXT,
                 date TEXT,
                 payment_id TEXT,
                 details TEXT)''')
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
    c.execute('''CREATE TABLE IF NOT EXISTS user_cards (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER,
                 level TEXT,
                 price REAL,
                 card_data TEXT,
                 purchase_date TEXT)''')
    conn.commit()
    conn.close()
    logger.info("✅ Banco de dados inicializado")

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
        add_transaction(referred_by, "bonus", 5, "completed", f"Bônus por indicar @{username}")
        logger.info(f"🎁 Bônus de R$5 para {referred_by} por indicar {user_id}")
    conn.commit()
    conn.close()

def update_balance(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def update_user_stats(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET pix_recharges = pix_recharges + 1, total_recharged = total_recharged + ?, monthly_deposit = monthly_deposit + ? WHERE user_id = ?", 
              (amount, amount, user_id))
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
    logger.info(f"💾 Pagamento salvo: {payment_id}")

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

def add_transaction(user_id, type_, amount, status, details="", payment_id=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO transactions (user_id, type, amount, status, date, details, payment_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (user_id, type_, amount, status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), details, str(payment_id)))
    conn.commit()
    conn.close()

def get_user_purchases(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM user_cards WHERE user_id = ? ORDER BY purchase_date DESC LIMIT 10", (user_id,))
    purchases = c.fetchall()
    conn.close()
    return purchases

def get_user_recharges(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM transactions WHERE user_id = ? AND type = 'pix' AND status = 'completed' ORDER BY date DESC", (user_id,))
    recharges = c.fetchall()
    conn.close()
    return recharges

def get_referred_count(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_total_commission(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT SUM(amount) FROM transactions WHERE user_id = ? AND type = 'commission' AND status = 'completed'", (user_id,))
    total = c.fetchone()[0]
    conn.close()
    return total or 0

def get_monthly_deposit(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT monthly_deposit FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

# ==================== MERCADO PAGO ====================

def criar_pix_mercadopago(valor, user_id, email):
    """Cria um PIX dinâmico no Mercado Pago usando UUID"""
    
    url = "https://api.mercadopago.com/v1/payments"
    
    # Usando UUID para o X-Idempotency-Key
    headers = {
        "Authorization": f"Bearer {MERCADOPAGO_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Idempotency-Key": str(uuid.uuid4())
    }
    
    payload = {
        "transaction_amount": float(valor),
        "description": f"Recarga Suppys Store - Usuário {user_id}",
        "payment_method_id": "pix",
        "payer": {
            "email": email,
            "first_name": f"Usuario{user_id}"
        }
    }
    
    logger.info(f"💰 Criando PIX de R$ {valor} para usuário {user_id}")
    logger.info(f"🔑 Idempotency Key: {headers['X-Idempotency-Key']}")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        logger.info(f"📡 Status code: {response.status_code}")
        
        if response.status_code == 201:
            data = response.json()
            logger.info(f"✅ PIX criado! ID: {data['id']}")
            return {
                "success": True,
                "payment_id": data["id"],
                "qr_code": data["point_of_interaction"]["transaction_data"]["qr_code"],
                "qr_code_base64": data["point_of_interaction"]["transaction_data"]["qr_code_base64"],
                "ticket_url": data["point_of_interaction"]["transaction_data"]["ticket_url"]
            }
        else:
            error = response.json()
            logger.error(f"❌ Erro do Mercado Pago: {error}")
            return {"success": False, "error": error.get("message", "Erro desconhecido")}
            
    except Exception as e:
        logger.error(f"❌ Erro na requisição: {str(e)}")
        return {"success": False, "error": str(e)}

def verificar_pagamento_mp(payment_id):
    """Verifica o status do pagamento no Mercado Pago"""
    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    headers = {"Authorization": f"Bearer {MERCADOPAGO_ACCESS_TOKEN}"}
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            status = data.get("status")
            logger.info(f"📊 Status do pagamento {payment_id}: {status}")
            return status
        return None
    except Exception as e:
        logger.error(f"❌ Erro ao verificar pagamento: {e}")
        return None

def processar_pagamento_aprovado(payment_id, user_id, amount):
    """Processa o pagamento aprovado e credita saldo"""
    logger.info(f"💰 Processando pagamento aprovado: {payment_id} - R$ {amount}")
    
    # Atualiza saldo
    update_balance(user_id, amount)
    update_user_stats(user_id, amount)
    
    # Registra transação
    add_transaction(user_id, "pix", amount, "completed", f"Recarga via PIX", payment_id)
    update_payment_status(payment_id, "completed")
    
    # Verifica comissão para afiliado (25%)
    user = get_user(user_id)
    if user and user[9]:  # referred_by
        referred_by = user[9]
        commission = amount * 0.25
        update_balance(referred_by, commission)
        add_transaction(referred_by, "commission", commission, "completed", f"Comissão 25% por recarga de @{user[1]}", payment_id)
        logger.info(f"🎁 Comissão de R$ {commission:.2f} creditada para {referred_by}")
    
    return True

# ==================== COMANDOS DO BOT ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or "sem_username"
    name = user.first_name
    
    existing_user = get_user(user_id)
    if not existing_user:
        referred_by = None
        if context.args and context.args[0].isdigit():
            referred_by = int(context.args[0])
            if referred_by == user_id:
                referred_by = None
        create_user(user_id, username, name, referred_by)
        logger.info(f"✨ Novo usuário: {user_id} - @{username}")
    
    keyboard = [
        [InlineKeyboardButton("🛒 Comprar", callback_data='comprar')],
        [InlineKeyboardButton("🔓 Desbloquear CPF", callback_data='desbloquear_cpf')],
        [InlineKeyboardButton("🎁 Saldo Grátis", callback_data='saldo_gratis')],
        [InlineKeyboardButton("👤 Minha Conta", callback_data='minha_conta')],
        [InlineKeyboardButton("💰 ADICIONAR SALDO VIA PIX", callback_data='adicionar_saldo')],
        [InlineKeyboardButton("👥 Sistema de Afiliados", callback_data='afiliados')]
    ]
    
    welcome_text = (
        f"🎉 **Bem-vindo(a) à {STORE_NAME}!** 🎉\n\n"
        f"✨ Líderes em vendas diretas de FULL de alta qualidade.\n"
        f"📋 Material de alta qualidade a preços acessíveis.\n"
        f"👥 Cartões 100% virgens, 0 reteste.\n\n"
        f"💡 **Garantia:** Cartões live com troca em até 5 minutos pelo BOT.\n"
        f"🔗 Recarregue rapidamente com o comando `/pix`.\n\n"
        f"📌 **Grupo:** {GROUP_LINK}\n"
        f"📍 **Suporte:** {SUPPORT_LINK}"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == 'comprar':
        await mostrar_niveis(query)
    elif data == 'adicionar_saldo':
        await mostrar_valores_pix(query)
    elif data == 'minha_conta':
        await minha_conta(query)
    elif data == 'afiliados':
        await mostrar_afiliados(query, context)
    elif data == 'desbloquear_cpf':
        await desbloquear_cpf(query)
    elif data == 'saldo_gratis':
        await saldo_gratis(query)
    elif data == 'voltar':
        await start(update, context)
    elif data == 'historico_ccs':
        await historico_ccs(query)
    elif data == 'recargas_pix':
        await recargas_pix(query)
    elif data.startswith('pix_'):
        valor = data.replace('pix_', '')
        await gerar_pix(query, valor)
    elif data.startswith('verificar_'):
        payment_id = data.replace('verificar_', '')
        await verificar_pagamento_callback(query, payment_id)
    elif data.startswith('nivel_'):
        nivel = data.replace('nivel_', '')
        await comprar_cartao(query, nivel)

async def mostrar_niveis(query):
    niveis = [
        ("💰 R$ 20 - Standard", "STANDARD"),
        ("🏆 R$ 20 - Award", "AWARD"),
        ("⚫ R$ 75 - Black", "BLACK"),
        ("💼 R$ 30 - Business", "BUSINESS"),
        ("💳 R$ 20 - Classic", "CLASSIC"),
        ("💎 R$ 30 - Elo", "ELO"),
        ("🥇 R$ 25 - Gold", "GOLD"),
        ("♾️ R$ 75 - Infinite", "INFINITE"),
        ("💛 R$ 7 - Nu Gold", "NU_GOLD"),
        ("💜 R$ 15 - Nu Platinum", "NU_PLATINUM"),
        ("🖤 R$ 75 - Nubank Black", "NUBANK_BLACK"),
        ("💳 R$ 30 - Platinum", "PLATINUM"),
        ("💚 R$ 20 - Prepaid", "PREPAID"),
        ("✍️ R$ 30 - Signature", "SIGNATURE")
    ]
    
    keyboard = [[InlineKeyboardButton(nome, callback_data=f'nivel_{codigo}')] for nome, codigo in niveis]
    keyboard.append([InlineKeyboardButton("« Voltar", callback_data='voltar')])
    
    await query.edit_message_text(
        "📌 **Escolha um nível para continuar sua compra**\n\n"
        "🎯 **Há 1056 cartões disponíveis**\n\n"
        "✅ CHECKER NA COMPRA (ZERO-AUTH)!\n"
        "✅ CHECKER NA TROCA (ZERO-AUTH)!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def comprar_cartao(query, nivel):
    precos = {
        "STANDARD": 20, "AWARD": 20, "BLACK": 75, "BUSINESS": 30,
        "CLASSIC": 20, "ELO": 30, "GOLD": 25, "INFINITE": 75,
        "NU_GOLD": 7, "NU_PLATINUM": 15, "NUBANK_BLACK": 75,
        "PLATINUM": 30, "PREPAID": 20, "SIGNATURE": 30
    }
    
    preco = precos.get(nivel, 20)
    user = get_user(query.from_user.id)
    
    if not user:
        await query.edit_message_text("❌ Use /start primeiro")
        return
    
    saldo = user[5]
    if saldo < preco:
        falta = preco - saldo
        keyboard = [[InlineKeyboardButton(f"💰 Adicionar R$ {falta:.2f}", callback_data='adicionar_saldo')],
                    [InlineKeyboardButton("« Voltar", callback_data='comprar')]]
        await query.edit_message_text(
            f"❌ **Saldo insuficiente!**\n\n"
            f"💰 Seu saldo: R$ {saldo:.2f}\n"
            f"💳 Preço do cartão {nivel}: R$ {preco:.2f}\n"
            f"📌 Falta: R$ {falta:.2f}\n\n"
            f"Clique abaixo para adicionar saldo:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return
    
    # Gerar cartão fictício (aqui você integra com sua base de cartões)
    import random
    card_num = f"{random.randint(4000, 4999)} {random.randint(1000, 9999)} {random.randint(1000, 9999)} {random.randint(1000, 9999)}"
    cvv = random.randint(100, 999)
    
    # Verifica se o usuário tem CPF desbloqueado (depósito mensal >= 100)
    monthly_deposit = get_monthly_deposit(query.from_user.id)
    mostrar_cpf = monthly_deposit >= 100
    cpf_text = "123.456.789-00" if mostrar_cpf else "***.***.***-** (desbloqueie com R$100/mês)"
    
    await query.edit_message_text(
        f"✅ **Compra realizada com sucesso!**\n\n"
        f"💳 Nível: {nivel}\n"
        f"💰 Valor: R$ {preco:.2f}\n"
        f"💵 Saldo restante: R$ {saldo - preco:.2f}\n\n"
        f"📋 **Dados do cartão:**\n"
        f"`{card_num}`\n"
        f"`12/28`\n"
        f"`{cvv}`\n"
        f"`CPF: {cpf_text}`\n\n"
        f"⚠️ **Garantia de 5 minutos para troca!**\n"
        f"📍 Suporte: {SUPPORT_LINK}",
        parse_mode='Markdown'
    )
    
    update_balance(query.from_user.id, -preco)
    add_transaction(query.from_user.id, "compra", preco, "completed", f"Cartão {nivel}")

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
        "✅ Pagamento seguro com Mercado Pago\n"
        "✅ Saldo disponível em até 30 minutos",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def gerar_pix(query, valor):
    valor = float(valor)
    user_id = query.from_user.id
    email = f"user{user_id}@suppystore.com"
    
    await query.edit_message_text("⏱️ Gerando PIX... Aguarde...")
    
    resultado = criar_pix_mercadopago(valor, user_id, email)
    
    if resultado["success"]:
        save_pending_payment(user_id, valor, resultado["payment_id"], resultado["qr_code"], resultado["qr_code_base64"])
        
        mensagem = (
            f"✅ **Sua transação foi criada!**\n\n"
            f"📱 **Código PIX (copia e cola):**\n"
            f"`{resultado['qr_code']}`\n\n"
            f"💰 **Valor:** R$ {valor:.2f}\n"
            f"🆔 **ID Transação:** `{resultado['payment_id']}`\n\n"
            f"⏱️ **A transação expira em 30 minutos!**\n\n"
            f"✅ *Dica: para copiar o código basta clicar em cima dele*\n\n"
            f"⚠️ Caso realize o pagamento e não receba seu saldo, chame o suporte!\n\n"
            f"📍 **Suporte:** {SUPPORT_LINK}"
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
    
    status = verificar_pagamento_mp(payment_id)
    
    if status == "approved":
        processar_pagamento_aprovado(payment_id, payment[1], payment[2])
        
        await query.edit_message_text(
            f"✅ **PAGAMENTO CONFIRMADO!**\n\n"
            f"💰 Valor: R$ {payment[2]:.2f}\n"
            f"💵 Saldo creditado na sua carteira!\n\n"
            f"Use o menu 'Minha Conta' para ver seu saldo.",
            parse_mode='Markdown'
        )
    elif status == "pending":
        await query.edit_message_text(
            f"⏱️ **Pagamento pendente**\n\n"
            f"💰 Valor: R$ {payment[2]:.2f}\n\n"
            f"✅ Ainda não identificamos seu pagamento.\n"
            f"Assim que fizer o PIX, clique em verificar novamente.\n\n"
            f"📌 O código PIX está na mensagem anterior.",
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
    
    referrals = get_referred_count(query.from_user.id)
    commissions = get_total_commission(query.from_user.id)
    monthly_deposit = get_monthly_deposit(query.from_user.id)
    
    text = (
        f"👤 **MINHA CONTA**\n\n"
        f"📋 **Nome:** {user[2]}\n"
        f"👤 **User:** @{user[1]}\n"
        f"📅 **Cadastro:** {user[3]}\n\n"
        f"🆔 **ID da carteira:** `{user[4]}`\n"
        f"💰 **Saldo:** R$ {user[5]:.2f}\n\n"
        f"💳 **Cartões comprados:** {user[6]}\n"
        f"🔄 **Recargas Pix:** {user[7]}\n"
        f"📊 **Total recarregado:** R$ {user[8]:.2f}\n"
        f"📈 **Depósito mensal:** R$ {monthly_deposit:.2f}\n\n"
        f"👥 **Indicações:** {referrals}\n"
        f"🎁 **Comissões ganhas:** R$ {commissions:.2f}"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔄 Recargas Pix", callback_data='recargas_pix')],
        [InlineKeyboardButton("📜 Histórico de CC's", callback_data='historico_ccs')],
        [InlineKeyboardButton("« Voltar", callback_data='voltar')]
    ]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def mostrar_afiliados(query, context):
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("❌ Use /start primeiro")
        return
    
    link = f"https://t.me/{context.bot.username}?start={user[4]}"
    referrals = get_referred_count(query.from_user.id)
    commissions = get_total_commission(query.from_user.id)
    
    text = (
        f"🎁 **SISTEMA DE AFILIADOS**\n\n"
        f"💰 **Ganhe 25% de comissão!**\n\n"
        f"👥 **Seus indicados:** {referrals}\n"
        f"🎁 **Comissões totais:** R$ {commissions:.2f}\n\n"
        f"🔗 **Seu link exclusivo:**\n"
        f"`{link}`\n\n"
        f"📊 **Como funciona:**\n"
        f"1️⃣ Compartilhe seu link\n"
        f"2️⃣ Seu amigo se cadastra\n"
        f"3️⃣ Ele adiciona saldo\n"
        f"4️⃣ Você ganha 25% do valor!\n\n"
        f"✅ **Bônus:** R$5 por cada amigo indicado!"
    )
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def desbloquear_cpf(query):
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("❌ Use /start primeiro")
        return
    
    monthly_deposit = get_monthly_deposit(query.from_user.id)
    
    if monthly_deposit >= 100:
        text = (
            f"✅ **CPF ANTECIPADO - DESBLOQUEADO!**\n\n"
            f"Você já depositou R$ {monthly_deposit:.2f} neste mês.\n"
            f"🔓 Agora você pode ver o CPF das FULL antes de comprar!\n\n"
            f"💡 Ao comprar um cartão, o CPF será mostrado automaticamente."
        )
    else:
        falta = 100 - monthly_deposit
        text = (
            f"🔒 **ACESSO AO CPF ANTECIPADO**\n\n"
            f"Para visualizar o CPF das FULL antes da compra, é necessário um depósito mínimo de R$ 100 no mês.\n\n"
            f"📊 **Seu depósito mensal:** R$ {monthly_deposit:.2f}\n"
            f"💰 **Falta:** R$ {falta:.2f}\n\n"
            f"📌 **Regras:**\n"
            f"• O sistema reseta todo mês\n"
            f"• A liberação é imediata e automática\n"
            f"• Válido apenas para FULLs\n\n"
            f"✅ **Clique abaixo para adicionar saldo:**"
        )
        
        keyboard = [[InlineKeyboardButton("💰 Adicionar Saldo", callback_data='adicionar_saldo')],
                    [InlineKeyboardButton("« Voltar", callback_data='voltar')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def saldo_gratis(query):
    await query.edit_message_text(
        f"🎁 **SALDO GRÁTIS**\n\n"
        f"💰 **Promoções ativas:**\n\n"
        f"✅ **Indique amigos:** R$5 por indicação + 25% das recargas!\n"
        f"✅ **Primeira recarga:** 10% de bônus (em breve)\n\n"
        f"📌 **Em breve mais promoções!**\n"
        f"Fique de olho no grupo: {GROUP_LINK}",
        parse_mode='Markdown'
    )

async def historico_ccs(query):
    purchases = get_user_purchases(query.from_user.id)
    
    if not purchases:
        await query.edit_message_text(
            "📜 **HISTÓRICO DE CARTÕES**\n\n"
            "Ops, você ainda não tem nenhum cartão comprado!\n\n"
            "💳 Use o menu 'Comprar' para adquirir seu primeiro cartão.",
            parse_mode='Markdown'
        )
        return
    
    text = "📜 **HISTÓRICO DE CARTÕES COMPRADOS**\n\n"
    for purchase in purchases[:10]:
        text += f"💳 {purchase[2]} - R$ {purchase[3]:.2f}\n"
        text += f"   📅 {purchase[5]}\n\n"
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def recargas_pix(query):
    recharges = get_user_recharges(query.from_user.id)
    
    if not recharges:
        await query.edit_message_text(
            "🔄 **RECARGAS PIX**\n\n"
            "Ops, você ainda não tem nenhuma recarga Pix!\n\n"
            "💰 Use o menu 'Adicionar Saldo' para fazer sua primeira recarga.",
            parse_mode='Markdown'
        )
        return
    
    text = "🔄 **HISTÓRICO DE RECARGAS PIX**\n\n"
    for recharge in recharges[:10]:
        text += f"💰 R$ {recharge[3]:.2f} - {recharge[5]}\n\n"
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def pix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /pix VALOR"""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "❌ **Use:** `/pix VALOR`\n"
            "📝 **Exemplo:** `/pix 50`\n\n"
            "💰 Valores disponíveis: 10, 20, 50, 100, 200, 500",
            parse_mode='Markdown'
        )
        return
    
    try:
        valor = float(context.args[0])
        if valor < 10 or valor > 1000:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Valor inválido! Use valores entre R$10 e R$1000.")
        return
    
    user_id = update.effective_user.id
    email = f"user{user_id}@suppystore.com"
    
    await update.message.reply_text("⏱️ Gerando PIX... Aguarde...")
    
    resultado = criar_pix_mercadopago(valor, user_id, email)
    
    if resultado["success"]:
        save_pending_payment(user_id, valor, resultado["payment_id"], resultado["qr_code"], resultado["qr_code_base64"])
        
        mensagem = (
            f"✅ **Sua transação foi criada!**\n\n"
            f"📱 **Código PIX (copia e cola):**\n"
            f"`{resultado['qr_code']}`\n\n"
            f"💰 **Valor:** R$ {valor:.2f}\n"
            f"🆔 **ID Transação:** `{resultado['payment_id']}`\n\n"
            f"⏱️ **A transação expira em 30 minutos!**\n\n"
            f"✅ *Dica: para copiar o código basta clicar em cima dele*\n\n"
            f"⚠️ Caso realize o pagamento e não receba seu saldo, chame o suporte!"
        )
        
        keyboard = [[InlineKeyboardButton("✅ Verificar Pagamento", callback_data=f'verificar_{resultado["payment_id"]}')]]
        
        await update.message.reply_text(
            mensagem,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"❌ **Erro ao gerar PIX**\n\n"
            f"Motivo: {resultado.get('error', 'Erro desconhecido')}\n\n"
            f"📍 Suporte: {SUPPORT_LINK}",
            parse_mode='Markdown'
        )

async def bank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /bank NOME_DO_BANCO"""
    if not context.args:
        await update.message.reply_text(
            "🏦 **Buscar por Banco**\n\n"
            "Use: `/bank NOME_DO_BANCO`\n"
            "📝 Exemplo: `/bank nubank`\n"
            "📝 Exemplo: `/bank itau`\n\n"
            "💡 Listaremos todos os cartões disponíveis do banco escolhido.",
            parse_mode='Markdown'
        )
        return
    
    banco = ' '.join(context.args)
    await update.message.reply_text(
        f"🔍 **Buscando cartões do banco:** {banco}\n\n"
        f"📋 **Exemplo de resultados:**\n"
        f"• {banco.title()} Platinum - R$ 30\n"
        f"• {banco.title()} Gold - R$ 25\n"
        f"• {banco.title()} Black - R$ 75\n\n"
        f"💡 Use o menu 'Comprar' para adquirir seu cartão.",
        parse_mode='Markdown'
    )

async def bin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /bin NUMERO_BIN"""
    if not context.args:
        await update.message.reply_text(
            "🔍 **Buscar por BIN**\n\n"
            "Use: `/bin NUMERO_BIN`\n"
            "📝 Exemplo: `/bin 406669`\n\n"
            "💡 Envie apenas os 6 primeiros números do cartão.",
            parse_mode='Markdown'
        )
        return
    
    bin_num = context.args[0]
    await update.message.reply_text(
        f"🔎 **Buscando cartões com BIN:** {bin_num}\n\n"
        f"📋 **Resultados encontrados:**\n"
        f"• Visa Platinum - R$ 30\n"
        f"• Visa Infinite - R$ 75\n"
        f"• Visa Signature - R$ 30\n\n"
        f"💡 Use o menu 'Comprar' para adquirir seu cartão.",
        parse_mode='Markdown'
    )

async def saldo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /saldo"""
    user = get_user(update.effective_user.id)
    if user:
        await update.message.reply_text(
            f"💰 **SEU SALDO**\n\n"
            f"💵 Saldo disponível: **R$ {user[5]:.2f}**\n\n"
            f"📌 Use `/pix VALOR` para adicionar saldo.",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ Use /start primeiro!")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa mensagens de texto (para busca por BIN)"""
    text = update.message.text.strip()
    
    # Se for apenas números e tiver 6 dígitos ou mais, é uma BIN
    if text.isdigit() and len(text) >= 6:
        bin_num = text[:6]
        await update.message.reply_text(
            f"🔎 **Buscando BIN:** {bin_num}\n\n"
            f"📋 **Cartões encontrados com essa BIN:**\n"
            f"• Cartão 1 - R$ XX\n"
            f"• Cartão 2 - R$ XX\n\n"
            f"💡 Use o menu 'Comprar' para ver todos os níveis disponíveis.",
            parse_mode='Markdown'
        )

# ==================== MAIN ====================

def main():
    """Função principal"""
    init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Handlers de comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pix", pix_command))
    app.add_handler(CommandHandler("bank", bank_command))
    app.add_handler(CommandHandler("bin", bin_command))
    app.add_handler(CommandHandler("saldo", saldo_command))
    
    # Handler de callbacks (botões)
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Handler para mensagens de texto (busca por BIN)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    print("=" * 50)
    print("✅ BOT SUPPS STORE ESTÁ ONLINE!")
    print(f"📌 Nome: {STORE_NAME}")
    print(f"🔗 Grupo: {GROUP_LINK}")
    print(f"👤 Suporte: {SUPPORT_LINK}")
    print(f"💰 Mercado Pago: CONECTADO!")
    print(f"🔑 Token: {MERCADOPAGO_ACCESS_TOKEN[:20]}...")
    print("=" * 50)
    
    app.run_polling()

if __name__ == "__main__":
    main()