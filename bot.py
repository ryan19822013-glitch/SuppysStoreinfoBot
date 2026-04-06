import os
import logging
import sqlite3
import re
import json
import requests
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

# Configurações do bot
BOT_TOKEN = "8477706439:AAF1ibc5aI95nM3r2BB6XZpW84GpepYJgiE"
STORE_NAME = "Suppys Store"
SUPPORT_LINK = "https://t.me/suportesuppys7"
GROUP_LINK = "https://t.me/+laIYEeIQuuc1ZWEx"

# Configuração do Mercado Pago (ATUALIZADO!)
MERCADOPAGO_ACCESS_TOKEN = "APP_USR-8313019935361645-040523-f5273bbb40e6f8b1cfa385cbb7716aa5-800117337"
MERCADOPAGO_PUBLIC_KEY = "APP_USR-405fcaea-03f8-4fbe-abfb-65e112756083"

# Chave Pix manual (fallback)
PIX_KEY = os.getenv('PIX_KEY', 'sua-chave-pix-aqui')

# Configuração do banco de dados
DB_PATH = '/app/data/suppys_store.db' if os.path.exists('/app/data') else 'suppys_store.db'

# Configuração do logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== BANCO DE DADOS ====================

def init_db():
    """Inicializa o banco de dados"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Tabela de usuários
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                 user_id INTEGER PRIMARY KEY,
                 username TEXT,
                 name TEXT,
                 register_date TEXT,
                 wallet_id TEXT,
                 balance REAL DEFAULT 0,
                 cards_bought INTEGER DEFAULT 0,
                 pix_recharges INTEGER DEFAULT 0,
                 gift_recharges INTEGER DEFAULT 0,
                 total_recharged REAL DEFAULT 0,
                 referred_by INTEGER,
                 monthly_deposit REAL DEFAULT 0)''')
    
    # Tabela de transações
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER,
                 type TEXT,
                 amount REAL,
                 status TEXT,
                 date TEXT,
                 payment_id TEXT,
                 details TEXT)''')
    
    # Tabela de cartões
    c.execute('''CREATE TABLE IF NOT EXISTS cards (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 level TEXT,
                 price REAL,
                 card_data TEXT,
                 bank TEXT,
                 bin TEXT,
                 cpf TEXT,
                 sold INTEGER DEFAULT 0,
                 sold_to INTEGER,
                 sold_date TEXT)''')
    
    # Tabela de compras dos usuários
    c.execute('''CREATE TABLE IF NOT EXISTS user_cards (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER,
                 card_id INTEGER,
                 level TEXT,
                 price REAL,
                 card_data TEXT,
                 purchase_date TEXT)''')
    
    # Tabela de pagamentos pendentes
    c.execute('''CREATE TABLE IF NOT EXISTS pending_payments (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER,
                 amount REAL,
                 payment_id TEXT,
                 qr_code TEXT,
                 qr_code_base64 TEXT,
                 ticket_url TEXT,
                 status TEXT,
                 created_at TEXT,
                 expires_at TEXT,
                 checked INTEGER DEFAULT 0)''')
    
    conn.commit()
    conn.close()
    logger.info("Banco de dados inicializado em: %s", DB_PATH)

def get_user(user_id):
    """Retorna dados do usuário"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def create_user(user_id, username, name, referred_by=None):
    """Cria novo usuário"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    wallet_id = str(user_id) + str(datetime.now().strftime("%m%d"))
    register_date = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    c.execute("INSERT INTO users (user_id, username, name, register_date, wallet_id, referred_by) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, username, name, register_date, wallet_id, referred_by))
    
    # Se foi indicado por alguém, dá bônus de R$5
    if referred_by:
        c.execute("UPDATE users SET balance = balance + 5 WHERE user_id = ?", (referred_by,))
        add_transaction(referred_by, "bonus", 5, "completed", f"Bônus por indicar @{username}")
        logger.info(f"Bônus de R$5 para {referred_by} por indicar {user_id}")
    
    conn.commit()
    conn.close()

def update_user_balance(user_id, amount):
    """Atualiza saldo do usuário"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def update_user_monthly_deposit(user_id, amount):
    """Atualiza depósito mensal do usuário"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET monthly_deposit = monthly_deposit + ?, total_recharged = total_recharged + ?, pix_recharges = pix_recharges + 1 WHERE user_id = ?", 
              (amount, amount, user_id))
    conn.commit()
    conn.close()

def add_transaction(user_id, type_, amount, status, details="", payment_id=""):
    """Adiciona uma transação"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO transactions (user_id, type, amount, status, date, details, payment_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (user_id, type_, amount, status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), details, payment_id))
    conn.commit()
    conn.close()

def save_pending_payment(user_id, amount, payment_id, qr_code, qr_code_base64, ticket_url):
    """Salva pagamento pendente"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    expires_at = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO pending_payments (user_id, amount, payment_id, qr_code, qr_code_base64, ticket_url, status, created_at, expires_at, checked) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
              (user_id, amount, str(payment_id), qr_code, qr_code_base64, ticket_url, "pending", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), expires_at))
    conn.commit()
    conn.close()
    logger.info(f"Pagamento pendente salvo: {payment_id} para usuário {user_id}")
    return payment_id

def get_pending_payment(payment_id):
    """Busca pagamento pendente"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM pending_payments WHERE payment_id = ?", (str(payment_id),))
    payment = c.fetchone()
    conn.close()
    return payment

def update_payment_status(payment_id, status):
    """Atualiza status do pagamento"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE pending_payments SET status = ? WHERE payment_id = ?", (status, str(payment_id)))
    conn.commit()
    conn.close()

def mark_payment_checked(payment_id):
    """Marca pagamento como verificado"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE pending_payments SET checked = 1 WHERE payment_id = ?", (str(payment_id),))
    conn.commit()
    conn.close()

def get_user_purchases(user_id):
    """Retorna histórico de compras do usuário"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM user_cards WHERE user_id = ? ORDER BY purchase_date DESC LIMIT 10", (user_id,))
    purchases = c.fetchall()
    conn.close()
    return purchases

def get_user_recharges(user_id):
    """Retorna recargas do usuário"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM transactions WHERE user_id = ? AND type = 'pix' AND status = 'completed' ORDER BY date DESC", (user_id,))
    recharges = c.fetchall()
    conn.close()
    return recharges

def get_referred_users_count(user_id):
    """Conta quantos usuários foram indicados"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_total_commission(user_id):
    """Retorna total de comissões ganhas"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT SUM(amount) FROM transactions WHERE user_id = ? AND type = 'commission' AND status = 'completed'", (user_id,))
    result = c.fetchone()[0]
    conn.close()
    return result or 0

# ==================== MERCADO PAGO INTEGRAÇÃO ====================

def create_mercadopago_payment(amount, user_id, description):
    """Cria pagamento no Mercado Pago via PIX"""
    url = "https://api.mercadopago.com/v1/payments"
    headers = {
        "Authorization": f"Bearer {MERCADOPAGO_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    data = {
        "transaction_amount": float(amount),
        "description": description,
        "payment_method_id": "pix",
        "payer": {
            "email": f"user{user_id}@suppystore.com.br",
            "first_name": f"Usuario{user_id}"
        }
    }
    
    try:
        logger.info(f"Criando pagamento de R$ {amount} para usuário {user_id}")
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        if result.get("status") == "pending":
            payment_data = {
                "id": result["id"],
                "qr_code": result["point_of_interaction"]["transaction_data"]["qr_code"],
                "qr_code_base64": result["point_of_interaction"]["transaction_data"]["qr_code_base64"],
                "ticket_url": result["point_of_interaction"]["transaction_data"]["ticket_url"]
            }
            logger.info(f"✅ Pagamento criado! ID: {result['id']}")
            return payment_data
        else:
            logger.error(f"❌ Erro ao criar pagamento: {result}")
            return None
    except Exception as e:
        logger.error(f"❌ Erro na requisição: {e}")
        return None

def check_payment_status(payment_id):
    """Verifica status do pagamento no Mercado Pago"""
    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    headers = {"Authorization": f"Bearer {MERCADOPAGO_ACCESS_TOKEN}"}
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        status = result.get("status")
        logger.info(f"Status do pagamento {payment_id}: {status}")
        return status
    except Exception as e:
        logger.error(f"Erro ao verificar pagamento {payment_id}: {e}")
        return None

def process_paid_payment(payment_id, user_id, amount):
    """Processa pagamento confirmado"""
    logger.info(f"💰 Processando pagamento {payment_id} - Usuário {user_id} - R$ {amount}")
    
    # Atualiza saldo do usuário
    update_user_balance(user_id, amount)
    update_user_monthly_deposit(user_id, amount)
    
    # Registra transação
    add_transaction(user_id, "pix", amount, "completed", f"Recarga via PIX automático", str(payment_id))
    
    # Atualiza status do pagamento
    update_payment_status(str(payment_id), "completed")
    
    # Verifica se tem indicação para dar comissão
    user = get_user(user_id)
    if user and user[10]:  # referred_by
        referred_by = user[10]
        commission = amount * 0.25  # 25% de comissão
        update_user_balance(referred_by, commission)
        add_transaction(referred_by, "commission", commission, "completed", f"Comissão 25% por recarga de @{user[1]}", str(payment_id))
        logger.info(f"🎁 Comissão de R$ {commission:.2f} creditada para {referred_by}")
    
    return True

# ==================== COMANDOS E CALLBACKS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start"""
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
    reply_markup = InlineKeyboardMarkup(keyboard)
    
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
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa callbacks dos botões"""
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == 'comprar':
        await comprar_menu(query)
    elif data == 'adicionar_saldo':
        await adicionar_saldo_menu(query)
    elif data == 'minha_conta':
        await minha_conta(query)
    elif data == 'afiliados':
        await sistema_afiliados(query, context)
    elif data.startswith('nivel_'):
        nivel = data.replace('nivel_', '')
        await comprar_cartao_por_nivel(query, nivel)
    elif data == 'voltar':
        await start(update, context)
    elif data == 'desbloquear_cpf':
        await desbloquear_cpf(query)
    elif data == 'saldo_gratis':
        await saldo_gratis(query)
    elif data == 'pix_auto':
        await gerar_pix_auto(query)
    elif data == 'buscar_bin':
        await buscar_bin_menu(query)
    elif data == 'buscar_banco':
        await buscar_banco_menu(query)
    elif data == 'niveis':
        await niveis_menu(query)
    elif data == 'historico_ccs':
        await historico_ccs(query)
    elif data == 'recargas_pix':
        await recargas_pix(query)
    elif data == 'recargas_gift':
        await recargas_gift(query)
    elif data.startswith('pix_valor_'):
        valor = data.replace('pix_valor_', '')
        await gerar_pagamento_pix(query, valor)
    elif data.startswith('verificar_pagamento_'):
        payment_id = data.replace('verificar_pagamento_', '')
        await verificar_pagamento(query, payment_id)

async def comprar_menu(query):
    """Menu de compras"""
    keyboard = [
        [InlineKeyboardButton("🔍 Buscar por BIN", callback_data='buscar_bin')],
        [InlineKeyboardButton("🏦 Buscar por Banco", callback_data='buscar_banco')],
        [InlineKeyboardButton("📋 Ver todos os níveis", callback_data='niveis')],
        [InlineKeyboardButton("« Voltar", callback_data='voltar')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "📌 **Escolha como deseja comprar:**\n\n"
        "💳 Temos cartões de todos os bancos e níveis!\n"
        "✅ Garantia de 5 minutos para troca.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def niveis_menu(query):
    """Mostra níveis de cartões disponíveis"""
    niveis = [
        ("💰 R$ 20 - Standard", "nivel_STANDARD"),
        ("🏆 R$ 20 - Award", "nivel_AWARD"),
        ("⚫ R$ 75 - Black", "nivel_BLACK"),
        ("💼 R$ 30 - Business", "nivel_BUSINESS"),
        ("💳 R$ 20 - Classic", "nivel_CLASSIC"),
        ("💎 R$ 30 - Elo", "nivel_ELO"),
        ("🥇 R$ 25 - Gold", "nivel_GOLD"),
        ("♾️ R$ 75 - Infinite", "nivel_INFINITE"),
        ("💛 R$ 7 - Nu Gold", "nivel_NU_GOLD"),
        ("💜 R$ 15 - Nu Platinum", "nivel_NU_PLATINUM"),
        ("🖤 R$ 75 - Nubank Black", "nivel_NUBANK_BLACK"),
        ("💳 R$ 30 - Platinum", "nivel_PLATINUM"),
        ("💚 R$ 20 - Prepaid", "nivel_PREPAID"),
        ("✍️ R$ 30 - Signature", "nivel_SIGNATURE")
    ]
    
    keyboard = [[InlineKeyboardButton(nome, callback_data=callback)] for nome, callback in niveis]
    keyboard.append([InlineKeyboardButton("« Voltar", callback_data='comprar')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📌 **Escolha um nível para continuar sua compra**\n\n"
        "🎯 **Há 1056 cartões disponíveis**\n\n"
        "✅ CHECKER NA COMPRA (ZERO-AUTH)!\n"
        "✅ CHECKER NA TROCA (ZERO-AUTH)!",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def comprar_cartao_por_nivel(query, nivel):
    """Processa compra por nível"""
    precos = {
        "STANDARD": 20, "AWARD": 20, "BLACK": 75, "BUSINESS": 30,
        "CLASSIC": 20, "ELO": 30, "GOLD": 25, "INFINITE": 75,
        "NU_GOLD": 7, "NU_PLATINUM": 15, "NUBANK_BLACK": 75,
        "PLATINUM": 30, "PREPAID": 20, "SIGNATURE": 30
    }
    
    preco = precos.get(nivel, 20)
    user = get_user(query.from_user.id)
    
    if not user:
        await query.edit_message_text("❌ Usuário não encontrado. Use /start")
        return
    
    saldo = user[5]
    if saldo < preco:
        falta = preco - saldo
        keyboard = [[InlineKeyboardButton(f"💰 Adicionar R$ {falta:.2f}", callback_data='adicionar_saldo')],
                    [InlineKeyboardButton("« Voltar", callback_data='niveis')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"❌ **Saldo insuficiente!**\n\n"
            f"💰 Seu saldo: R$ {saldo:.2f}\n"
            f"💳 Preço: R$ {preco:.2f}\n"
            f"📌 Falta: R$ {falta:.2f}",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    # Aqui você vai integrar com sua base de cartões
    # Exemplo de cartão gerado
    card_number = f"{hash(query.from_user.id + len(nivel)) % 1000000000000:012d}"
    
    await query.edit_message_text(
        f"✅ **Compra realizada!**\n\n"
        f"💳 Nível: {nivel}\n"
        f"💰 Valor: R$ {preco:.2f}\n"
        f"💵 Saldo restante: R$ {saldo - preco:.2f}\n\n"
        f"📋 **Dados do cartão:**\n"
        f"`{card_number[:4]} {card_number[4:8]} {card_number[8:12]} 1234`\n"
        f"`12/28`\n"
        f"`123`\n"
        f"`CPF: ***.***.***-**`\n\n"
        f"⚠️ **Garantia de 5 minutos para troca!**\n"
        f"📍 Suporte: {SUPPORT_LINK}",
        parse_mode='Markdown'
    )
    
    update_user_balance(query.from_user.id, -preco)
    add_transaction(query.from_user.id, "compra", preco, "completed", f"Compra de cartão {nivel}")
    logger.info(f"Compra: {query.from_user.id} - {nivel} - R$ {preco}")

async def adicionar_saldo_menu(query):
    """Menu de adicionar saldo"""
    keyboard = [
        [InlineKeyboardButton("💰 R$ 10", callback_data='pix_valor_10'),
         InlineKeyboardButton("💰 R$ 20", callback_data='pix_valor_20'),
         InlineKeyboardButton("💰 R$ 50", callback_data='pix_valor_50')],
        [InlineKeyboardButton("💰 R$ 100", callback_data='pix_valor_100'),
         InlineKeyboardButton("💰 R$ 200", callback_data='pix_valor_200'),
         InlineKeyboardButton("💰 R$ 500", callback_data='pix_valor_500')],
        [InlineKeyboardButton("💳 Outro valor", callback_data='pix_auto')],
        [InlineKeyboardButton("« Voltar", callback_data='voltar')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "💰 **Adicionar Saldo**\n\n"
        "Escolha o valor para recarga via PIX:\n"
        "✅ Saldo disponível em até 30 minutos\n"
        "✅ Pagamento seguro com Mercado Pago",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def gerar_pagamento_pix(query, valor):
    """Gera pagamento PIX via Mercado Pago"""
    valor = float(valor)
    user_id = query.from_user.id
    
    # Cria pagamento no Mercado Pago
    payment = create_mercadopago_payment(valor, user_id, f"Recarga Suppys Store - {user_id}")
    
    if payment:
        save_pending_payment(user_id, valor, payment["id"], payment["qr_code"], payment["qr_code_base64"], payment["ticket_url"])
        
        keyboard = [[InlineKeyboardButton("✅ Verificar Pagamento", callback_data=f'verificar_pagamento_{payment["id"]}')],
                    [InlineKeyboardButton("« Voltar", callback_data='adicionar_saldo')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"💳 **Pagamento PIX - R$ {valor:.2f}**\n\n"
            f"📱 **Código PIX (copia e cola):**\n"
            f"`{payment['qr_code']}`\n\n"
            f"🔗 **Link para pagamento:**\n"
            f"{payment['ticket_url']}\n\n"
            f"⏱️ **Expira em:** 30 minutos\n\n"
            f"✅ **Após fazer o PIX, clique no botão abaixo para verificar!**",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        # Fallback manual
        await query.edit_message_text(
            f"💰 **Pagamento PIX - R$ {valor:.2f}**\n\n"
            f"🔑 **Chave Pix:** `{PIX_KEY}`\n\n"
            f"📝 **Instruções:**\n"
            f"1. Faça o PIX para a chave acima\n"
            f"2. Envie o comprovante para {SUPPORT_LINK}\n"
            f"3. Seu saldo será creditado em até 30 minutos",
            parse_mode='Markdown'
        )

async def verificar_pagamento(query, payment_id):
    """Verifica status do pagamento"""
    payment = get_pending_payment(payment_id)
    
    if not payment:
        await query.edit_message_text("❌ Pagamento não encontrado!")
        return
    
    if payment[7] == "completed":
        await query.edit_message_text(
            "✅ **Pagamento já foi confirmado!**\n\n"
            f"💰 Saldo creditado: R$ {payment[2]:.2f}\n\n"
            f"Use /saldo para ver seu saldo atual.",
            parse_mode='Markdown'
        )
        return
    
    # Verifica status no Mercado Pago
    status = check_payment_status(payment_id)
    
    if status == "approved" or status == "completed":
        # Processa pagamento
        process_paid_payment(payment_id, payment[1], payment[2])
        mark_payment_checked(payment_id)
        
        await query.edit_message_text(
            f"✅ **PAGAMENTO CONFIRMADO!**\n\n"
            f"💰 Valor: R$ {payment[2]:.2f}\n"
            f"💵 Saldo creditado na sua carteira!\n\n"
            f"Use o menu 'Minha Conta' para ver seu saldo.",
            parse_mode='Markdown'
        )
        logger.info(f"✅ Pagamento {payment_id} confirmado para usuário {payment[1]}")
    elif status == "pending":
        await query.edit_message_text(
            f"⏱️ **Pagamento pendente**\n\n"
            f"💰 Valor: R$ {payment[2]:.2f}\n\n"
            f"📌 Ainda não identificamos seu pagamento.\n"
            f"✅ Certifique-se de que:\n"
            f"• Você fez o PIX corretamente\n"
            f"• O valor está exato\n\n"
            f"Clique em verificar novamente em alguns minutos.",
            parse_mode='Markdown'
        )
    else:
        await query.edit_message_text(
            f"❌ **Problema no pagamento**\n\n"
            f"Status: {status}\n\n"
            f"Entre em contato com o suporte: {SUPPORT_LINK}",
            parse_mode='Markdown'
        )

async def gerar_pix_auto(query):
    """Gera Pix automático com valor personalizado"""
    await query.edit_message_text(
        f"💳 **Pix Automático**\n\n"
        f"Use o comando `/pix VALOR` para gerar um PIX\n\n"
        f"📝 Exemplo: `/pix 50`\n\n"
        f"✅ Valores de R$ 10 a R$ 1000",
        parse_mode='Markdown'
    )

async def minha_conta(query):
    """Mostra informações da conta"""
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("❌ Use /start primeiro")
        return
    
    referrals = get_referred_users_count(query.from_user.id)
    commissions = get_total_commission(query.from_user.id)
    
    text = (
        f"👤 **MINHA CONTA**\n\n"
        f"📋 **Nome:** {user[2]}\n"
        f"👤 **User:** @{user[1]}\n"
        f"📅 **Cadastro:** {user[3]}\n\n"
        f"🆔 **ID da carteira:** `{user[4]}`\n"
        f"💰 **Saldo:** R$ {user[5]:.2f}\n\n"
        f"💳 **Cartões comprados:** {user[6]}\n"
        f"🔄 **Recargas Pix:** {user[7]}\n"
        f"📊 **Total recarregado:** R$ {user[9]:.2f}\n"
        f"📈 **Depósito mensal:** R$ {user[11]:.2f}\n\n"
        f"👥 **Indicações:** {referrals}\n"
        f"🎁 **Comissões ganhas:** R$ {commissions:.2f}\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔄 Recargas Pix", callback_data='recargas_pix')],
        [InlineKeyboardButton("📜 Histórico de CC's", callback_data='historico_ccs')],
        [InlineKeyboardButton("« Voltar", callback_data='voltar')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def sistema_afiliados(query, context):
    """Mostra sistema de afiliados"""
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("❌ Use /start primeiro")
        return
    
    link = f"https://t.me/{context.bot.username}?start={user[4]}"
    referrals = get_referred_users_count(query.from_user.id)
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
    """Informações sobre desbloqueio de CPF"""
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("❌ Use /start primeiro")
        return
    
    monthly_deposit = user[11] if len(user) > 11 else 0
    
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
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        return
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def saldo_gratis(query):
    """Saldo grátis (promoções)"""
    await query.edit_message_text(
        f"🎁 **SALDO GRÁTIS**\n\n"
        f"💰 **Promoções ativas:**\n\n"
        f"✅ Indique amigos: R$5 por indicação + 25% das recargas!\n"
        f"✅ Primeira recarga: 10% de bônus!\n\n"
        f"📌 **Em breve mais promoções!**\n"
        f"Fique de olho no grupo: {GROUP_LINK}",
        parse_mode='Markdown'
    )

async def historico_ccs(query):
    """Histórico de cartões comprados"""
    purchases = get_user_purchases(query.from_user.id)
    
    if not purchases:
        await query.edit_message_text(
            "📜 **HISTÓRICO DE CARTÕES**\n\n"
            "Ops, você ainda não tem nenhum cartão comprado!\n\n"
            "💳 Use o menu 'Comprar' para adquirir seu primeiro cartão.",
            parse_mode='Markdown'
        )
        return
    
    text = "📜 **HISTÓRICO DE CARTÕES**\n\n"
    for purchase in purchases[:10]:
        text += f"💳 {purchase[3]} - R$ {purchase[4]:.2f}\n"
        text += f"   📅 {purchase[6]}\n\n"
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def recargas_pix(query):
    """Histórico de recargas Pix"""
    recharges = get_user_recharges(query.from_user.id)
    
    if not recharges:
        await query.edit_message_text(
            "🔄 **RECARGAS PIX**\n\n"
            "Ops, você ainda não tem nenhuma recarga Pix!\n\n"
            "💰 Use o menu 'Adicionar Saldo' para fazer sua primeira recarga.",
            parse_mode='Markdown'
        )
        return
    
    text = "🔄 **RECARGAS PIX**\n\n"
    for recharge in recharges[:10]:
        text += f"💰 R$ {recharge[3]:.2f} - {recharge[5]}\n\n"
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def recargas_gift(query):
    """Histórico de recargas GIFT"""
    await query.edit_message_text(
        "🎁 **RECARGAS GIFT**\n\n"
        "Ops, você ainda não tem nenhuma recarga por GIFT!\n\n"
        "💡 Recargas GIFT serão disponibilizadas em breve.",
        parse_mode='Markdown'
    )

async def buscar_bin_menu(query):
    """Menu de busca por BIN"""
    await query.edit_message_text(
        "🔍 **BUSCAR POR BIN**\n\n"
        "Digite os 6 primeiros números do cartão (BIN).\n\n"
        "📝 **Exemplo:** `/bin 406669`\n\n"
        "💡 Ou simplesmente envie os 6 números para o bot!",
        parse_mode='Markdown'
    )

async def buscar_banco_menu(query):
    """Menu de busca por banco"""
    await query.edit_message_text(
        "🏦 **BUSCAR POR BANCO**\n\n"
        "Digite o nome do banco que deseja.\n\n"
        "📝 **Exemplo:** `/bank nubank`\n"
        "📝 **Exemplo:** `/bank itau`",
        parse_mode='Markdown'
    )

# ==================== COMANDOS POR TEXTO ====================

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
    
    # Cria pagamento no Mercado Pago
    payment = create_mercadopago_payment(valor, user_id, f"Recarga Suppys Store - {user_id}")
    
    if payment:
        save_pending_payment(user_id, valor, payment["id"], payment["qr_code"], payment["qr_code_base64"], payment["ticket_url"])
        
        keyboard = [[InlineKeyboardButton("✅ Verificar Pagamento", callback_data=f'verificar_pagamento_{payment["id"]}')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"💳 **Pagamento PIX - R$ {valor:.2f}**\n\n"
            f"📱 **Código PIX (copia e cola):**\n"
            f"`{payment['qr_code']}`\n\n"
            f"🔗 **Link:** {payment['ticket_url']}\n\n"
            f"⏱️ Expira em 30 minutos\n"
            f"✅ **Clique em verificar após o pagamento!**",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"❌ **Erro ao gerar pagamento**\n\n"
            f"Por favor, tente novamente ou use o suporte: {SUPPORT_LINK}",
            parse_mode='Markdown'
        )

async def bank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /bank NOME_DO_BANCO"""
    if not context.args:
        await update.message.reply_text(
            "🏦 **Buscar por Banco**\n\n"
            "Use: `/bank NOME_DO_BANCO`\n"
            "📝 Exemplo: `/bank nubank`",
            parse_mode='Markdown'
        )
        return
    
    banco = ' '.join(context.args)
    await update.message.reply_text(
        f"🔍 **Buscando cartões do banco:** {banco}\n\n"
        f"📋 **Exemplo de resultados:**\n"
        f"• Nubank Platinum - R$ 15\n"
        f"• Nubank Gold - R$ 7\n"
        f"• Nubank Black - R$ 75\n\n"
        f"💡 Use o menu 'Comprar' para adquirir.",
        parse_mode='Markdown'
    )

async def bin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /bin NUMERO_BIN"""
    if not context.args:
        await update.message.reply_text(
            "🔍 **Buscar por BIN**\n\n"
            "Use: `/bin NUMERO_BIN`\n"
            "📝 Exemplo: `/bin 406669`",
            parse_mode='Markdown'
        )
        return
    
    bin_num = context.args[0]
    await update.message.reply_text(
        f"🔎 **Buscando cartões com BIN:** {bin_num}\n\n"
        f"📋 **Resultados encontrados:**\n"
        f"• Visa Platinum - R$ 30\n"
        f"• Visa Infinite - R$ 75\n\n"
        f"💡 Use o menu 'Comprar' para adquirir.",
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
    
    if text.isdigit() and len(text) >= 6:
        bin_num = text[:6]
        await update.message.reply_text(
            f"🔎 **Buscando BIN:** {bin_num}\n\n"
            f"📋 **Cartões encontrados:**\n"
            f"• Cartão 1 - R$ XX\n\n"
            f"💡 Use o menu 'Comprar' para ver todos os níveis.",
            parse_mode='Markdown'
        )

# ==================== MAIN ====================

async def check_pending_payments(app: Application):
    """Verifica pagamentos pendentes periodicamente"""
    while True:
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT * FROM pending_payments WHERE status = 'pending' AND checked = 0")
            payments = c.fetchall()
            conn.close()
            
            for payment in payments:
                payment_id = payment[3]
                status = check_payment_status(payment_id)
                
                if status == "approved" or status == "completed":
                    process_paid_payment(payment_id, payment[1], payment[2])
                    mark_payment_checked(payment_id)
                    logger.info(f"✅ Pagamento automático {payment_id} confirmado!")
                    
                    # Notifica o usuário
                    try:
                        await app.bot.send_message(
                            payment[1],
                            f"✅ **PAGAMENTO CONFIRMADO!**\n\n"
                            f"💰 Valor: R$ {payment[2]:.2f}\n"
                            f"💵 Saldo creditado na sua carteira!",
                            parse_mode='Markdown'
                        )
                    except:
                        pass
        except Exception as e:
            logger.error(f"Erro ao verificar pagamentos: {e}")
        
        await asyncio.sleep(30)  # Verifica a cada 30 segundos

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
    
    # Handler de callbacks
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Handler para texto (busca por BIN)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    # Inicia verificação automática de pagamentos
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(check_pending_payments(app))
    
    logger.info("🚀 Bot Suppys Store rodando...")
    print("=" * 50)
    print("✅ BOT SUPPS STORE ESTÁ ONLINE!")
    print(f"📌 Nome: {STORE_NAME}")
    print(f"🔗 Grupo: {GROUP_LINK}")
    print(f"👤 Suporte: {SUPPORT_LINK}")
    print(f"💰 Mercado Pago: CONECTADO!")
    print("=" * 50)
    
    app.run_polling()

if __name__ == "__main__":
    main()