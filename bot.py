import os
import logging
import sqlite3
import requests
import uuid
import random
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ==================== CONFIGURAÇÕES ====================
BOT_TOKEN = "8477706439:AAF1ibc5aI95nM3r2BB6XZpW84GpepYJgiE"
STORE_NAME = "Suppys Store"
SUPPORT_LINK = "https://t.me/suportesuppys7"
GROUP_LINK = "https://t.me/+laIYEeIQuuc1ZWEx"
GROUP_USERNAME = "laIYEeIQuuc1ZWEx"  # ID do grupo

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
                 gift_recharges INTEGER DEFAULT 0,
                 total_recharged REAL DEFAULT 0,
                 referred_by INTEGER,
                 monthly_deposit REAL DEFAULT 0,
                 total_spent REAL DEFAULT 0)''')
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
                 bin TEXT,
                 purchase_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS ofertas (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 bin TEXT,
                 card_data TEXT,
                 price REAL,
                 old_price REAL,
                 discount INTEGER,
                 active INTEGER DEFAULT 1)''')
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
    wallet_id = str(user_id)
    register_date = datetime.now().strftime("%d/%m/%Y")
    c.execute("INSERT INTO users (user_id, username, name, register_date, wallet_id, referred_by) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, username, name, register_date, wallet_id, referred_by))
    if referred_by:
        c.execute("UPDATE users SET balance = balance + 5 WHERE user_id = ?", (referred_by,))
        add_transaction(referred_by, "bonus", 5, "completed", f"Bonus por indicar @{username}")
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

def update_spent(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET cards_bought = cards_bought + 1, total_spent = total_spent + ?, balance = balance - ? WHERE user_id = ?", 
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

def get_user_transactions(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM transactions WHERE user_id = ? AND status = 'completed' ORDER BY date DESC LIMIT 20", (user_id,))
    trans = c.fetchall()
    conn.close()
    return trans

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

def get_user_cards(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM user_cards WHERE user_id = ? ORDER BY purchase_date DESC", (user_id,))
    cards = c.fetchall()
    conn.close()
    return cards

def get_ofertas():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM ofertas WHERE active = 1 LIMIT 5")
    ofertas = c.fetchall()
    conn.close()
    return ofertas

def get_bins():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT bin, COUNT(*) FROM cards WHERE sold = 0 GROUP BY bin LIMIT 10")
    bins = c.fetchall()
    conn.close()
    return bins

def get_cards_by_bin(bin_num):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM cards WHERE bin = ? AND sold = 0 LIMIT 10", (bin_num,))
    cards = c.fetchall()
    conn.close()
    return cards

def get_nivel(total_spent):
    if total_spent >= 500:
        return "Diamante", "R$ 1000.00"
    elif total_spent >= 200:
        return "Ouro", "R$ 500.00"
    elif total_spent >= 100:
        return "Prata", "R$ 200.00"
    elif total_spent >= 50:
        return "Bronze", "R$ 100.00"
    else:
        return "Sem nível", "R$ 50.00"

# ==================== MERCADO PAGO ====================

def criar_pix_mercadopago(valor, user_id, email):
    url = "https://api.mercadopago.com/v1/payments"
    
    headers = {
        "Authorization": f"Bearer {MERCADOPAGO_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Idempotency-Key": str(uuid.uuid4())
    }
    
    payload = {
        "transaction_amount": float(valor),
        "description": f"Recarga {STORE_NAME} - Usuario {user_id}",
        "payment_method_id": "pix",
        "payer": {"email": email, "first_name": f"Usuario{user_id}"}
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
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
            return {"success": False, "error": error.get("message", "Erro desconhecido")}
    except Exception as e:
        return {"success": False, "error": str(e)}

def verificar_pagamento_mp(payment_id):
    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    headers = {"Authorization": f"Bearer {MERCADOPAGO_ACCESS_TOKEN}"}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json().get("status")
        return None
    except Exception:
        return None

def processar_pagamento_aprovado(payment_id, user_id, amount):
    update_balance(user_id, amount)
    update_user_stats(user_id, amount)
    add_transaction(user_id, "pix", amount, "completed", f"Recarga via PIX", payment_id)
    update_payment_status(payment_id, "completed")
    
    user = get_user(user_id)
    if user and user[10]:
        referred_by = user[10]
        commission = amount * 0.25
        update_balance(referred_by, commission)
        add_transaction(referred_by, "commission", commission, "completed", f"Comissao 25% por recarga de @{user[1]}", payment_id)
    return True

# ==================== VERIFICAÇÃO DE GRUPO ====================

async def check_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verifica se o usuário está no grupo"""
    user_id = update.effective_user.id
    
    try:
        # Tenta obter o membro do grupo
        chat_member = await context.bot.get_chat_member(chat_id=f"@{GROUP_USERNAME}", user_id=user_id)
        
        if chat_member.status in ["member", "administrator", "creator"]:
            return True
        else:
            return False
    except Exception as e:
        logger.error(f"Erro ao verificar grupo: {e}")
        return False

# ==================== COMANDOS DO BOT ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start com verificação de grupo"""
    user = update.effective_user
    user_id = user.id
    username = user.username or "sem_username"
    name = user.first_name
    
    # Verifica se está no grupo
    in_group = await check_group(update, context)
    
    if not in_group:
        keyboard = [[InlineKeyboardButton("📢 Entrar no Grupo", url=GROUP_LINK)]]
        await update.message.reply_text(
            f"⚠️ **Acesso Restrito!**\n\n"
            f"Olá {name}!\n\n"
            f"Você precisa estar no nosso grupo para usar o bot.\n\n"
            f"📌 **Clique no botão abaixo para entrar no grupo e depois use /start novamente.**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return
    
    # Usuário está no grupo, prossegue
    existing_user = get_user(user_id)
    if not existing_user:
        referred_by = None
        if context.args and context.args[0].isdigit():
            referred_by = int(context.args[0])
            if referred_by == user_id:
                referred_by = None
        create_user(user_id, username, name, referred_by)
        logger.info(f"Novo usuario: {user_id} - @{username}")
    
    # Menu principal estilo Rick Morning Store
    keyboard = [
        [InlineKeyboardButton("🔍 Comprar por BIN", callback_data='comprar_bin')],
        [InlineKeyboardButton("🔥 Ofertas do Dia", callback_data='ofertas')],
        [InlineKeyboardButton("💰 Saldo", callback_data='saldo')],
        [InlineKeyboardButton("👤 Perfil", callback_data='perfil')],
        [InlineKeyboardButton("📜 Histórico", callback_data='historico')],
        [InlineKeyboardButton("👥 Afiliado", callback_data='afiliado')],
        [InlineKeyboardButton("📞 Suporte", callback_data='suporte')]
    ]
    
    user_data = get_user(user_id)
    saldo = user_data[5] if user_data else 0
    
    welcome_text = (
        f"@{context.bot.username}\n"
        f"melhores gps só encontra\n"
        f"na @{context.bot.username}\n\n"
        f"A VIDA NÃO É BOA PRA NINGUEM, ENTÃO DECIDI FICAR CONTIGO!\n\n"
        f"Olá, @{username}!\n\n"
        f"ID: {user_id}\n"
        f"Saldo: R$ {saldo:.2f}\n"
        f"Grupo: Clique aqui\n\n"
        f"Use o menu abaixo 👇"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == 'comprar_bin':
        await comprar_bin_menu(query)
    elif data == 'ofertas':
        await ofertas_menu(query)
    elif data == 'saldo':
        await saldo_menu(query)
    elif data == 'perfil':
        await perfil_menu(query)
    elif data == 'historico':
        await historico_menu(query)
    elif data == 'afiliado':
        await afiliado_menu(query, context)
    elif data == 'suporte':
        await suporte_menu(query)
    elif data == 'voltar_menu':
        await start(update, context)
    elif data == 'adicionar_saldo':
        await adicionar_saldo(query)
    elif data.startswith('bin_'):
        bin_num = data.replace('bin_', '')
        await mostrar_cartoes_por_bin(query, bin_num)
    elif data.startswith('comprar_cartao_'):
        card_id = data.replace('comprar_cartao_', '')
        await comprar_cartao_por_id(query, card_id)
    elif data.startswith('pix_valor_'):
        valor = data.replace('pix_valor_', '')
        await gerar_pix(query, valor)
    elif data.startswith('verificar_'):
        payment_id = data.replace('verificar_', '')
        await verificar_pagamento_callback(query, payment_id)
    elif data == 'voltar_bins':
        await comprar_bin_menu(query)
    elif data == 'voltar_ofertas':
        await ofertas_menu(query)

async def comprar_bin_menu(query):
    """Menu de compra por BIN"""
    bins = get_bins()
    
    if not bins:
        await query.edit_message_text("Nenhuma BIN disponível no momento.")
        return
    
    keyboard = []
    for bin_num, qtd in bins:
        keyboard.append([InlineKeyboardButton(f"{bin_num} | ({qtd})", callback_data=f'bin_{bin_num}')])
    
    keyboard.append([InlineKeyboardButton("📥 Solicitar BIN", callback_data='solicitar_bin')])
    keyboard.append([InlineKeyboardButton("🏠 Menu", callback_data='voltar_menu')])
    
    user = get_user(query.from_user.id)
    saldo = user[5] if user else 0
    
    await query.edit_message_text(
        f"🔍 **ESCOLHA SUA BIN**\n\n"
        f"ID {query.from_user.id} | R$ {saldo:.2f}\n\n"
        f"Página 1/1",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def mostrar_cartoes_por_bin(query, bin_num):
    """Mostra cartões de uma BIN específica"""
    cards = get_cards_by_bin(bin_num)
    
    if not cards:
        await query.edit_message_text(f"Nenhum cartão disponível para BIN {bin_num}")
        return
    
    keyboard = []
    for card in cards[:5]:
        keyboard.append([InlineKeyboardButton(f"💳 {bin_num}xxxxxx - R$ {card[2]:.2f}", callback_data=f'comprar_cartao_{card[0]}')])
    
    keyboard.append([InlineKeyboardButton("🔙 Voltar", callback_data='voltar_bins')])
    keyboard.append([InlineKeyboardButton("🏠 Menu", callback_data='voltar_menu')])
    
    await query.edit_message_text(
        f"📋 **Cartões BIN {bin_num}**\n\n"
        f"Selecione um cartão para comprar:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def comprar_cartao_por_id(query, card_id):
    """Compra um cartão específico"""
    # Buscar cartão no banco (simplificado)
    preco = 20.00  # Valor padrão
    
    user = get_user(query.from_user.id)
    saldo = user[5] if user else 0
    
    if saldo < preco:
        await query.edit_message_text(
            f"❌ Saldo insuficiente!\n\n"
            f"Saldo: R$ {saldo:.2f}\n"
            f"Preço: R$ {preco:.2f}\n\n"
            f"Use /pix para adicionar saldo."
        )
        return
    
    # Gerar cartão fictício
    card_num = f"{random.randint(4000, 4999)} {random.randint(1000, 9999)} {random.randint(1000, 9999)} {random.randint(1000, 9999)}"
    cvv = random.randint(100, 999)
    
    update_spent(query.from_user.id, preco)
    
    await query.edit_message_text(
        f"✅ **Compra realizada!**\n\n"
        f"💳 {card_num}\n"
        f"📅 12/28\n"
        f"🔐 {cvv}\n\n"
        f"💰 Valor: R$ {preco:.2f}\n"
        f"💵 Saldo restante: R$ {saldo - preco:.2f}"
    )

async def ofertas_menu(query):
    """Menu de ofertas do dia"""
    ofertas = get_ofertas()
    
    if not ofertas:
        await query.edit_message_text("Nenhuma oferta disponível no momento.")
        return
    
    text = "🔥 **Ofertas Especiais!**\n\n"
    for i, oferta in enumerate(ofertas[:5], 1):
        text += f"- **{oferta[1]}**\n"
        text += f"  ~~R$ {oferta[3]:.2f}~~ → R$ {oferta[2]:.2f} (-{oferta[4]}%)\n\n"
    
    text += "\n" + "\n".join([f"{i}. {o[1]} — R$ {o[2]:.2f}" for i, o in enumerate(ofertas[:5], 1)])
    
    keyboard = [
        [InlineKeyboardButton("🔄 Atualizar", callback_data='ofertas')],
        [InlineKeyboardButton("🏠 Menu", callback_data='voltar_menu')]
    ]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def saldo_menu(query):
    """Menu de saldo"""
    user = get_user(query.from_user.id)
    saldo = user[5] if user else 0
    
    keyboard = [
        [InlineKeyboardButton("💰 Adicionar Saldo via PIX", callback_data='adicionar_saldo')],
        [InlineKeyboardButton("🏠 Voltar ao Menu", callback_data='voltar_menu')]
    ]
    
    await query.edit_message_text(
        f"💰 **Saldo**\n\n"
        f"R$ {saldo:.2f}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def adicionar_saldo(query):
    """Menu para adicionar saldo"""
    keyboard = [
        [InlineKeyboardButton("R$ 10", callback_data='pix_valor_10'),
         InlineKeyboardButton("R$ 20", callback_data='pix_valor_20'),
         InlineKeyboardButton("R$ 50", callback_data='pix_valor_50')],
        [InlineKeyboardButton("R$ 100", callback_data='pix_valor_100'),
         InlineKeyboardButton("R$ 200", callback_data='pix_valor_200'),
         InlineKeyboardButton("R$ 500", callback_data='pix_valor_500')],
        [InlineKeyboardButton("🔙 Voltar", callback_data='saldo')]
    ]
    
    await query.edit_message_text(
        f"💳 **PIX**\n\n"
        f"Digite o valor (mín R$ 10,00):\n"
        f"Ex: 50.00\n\n"
        f"Ou escolha um valor abaixo:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def gerar_pix(query, valor):
    """Gera PIX para o valor selecionado"""
    valor = float(valor)
    user_id = query.from_user.id
    email = f"user{user_id}@suppystore.com"
    
    await query.edit_message_text("⏱️ Gerando PIX... Aguarde...")
    
    resultado = criar_pix_mercadopago(valor, user_id, email)
    
    if resultado["success"]:
        save_pending_payment(user_id, valor, resultado["payment_id"], resultado["qr_code"], resultado["qr_code_base64"])
        
        mensagem = (
            f"✅ **PIX gerado!**\n\n"
            f"📱 **Código PIX:**\n"
            f"`{resultado['qr_code']}`\n\n"
            f"💰 **Valor:** R$ {valor:.2f}\n"
            f"🆔 **ID:** `{resultado['payment_id']}`\n\n"
            f"⏱️ Expira em 30 minutos!\n\n"
            f"⚠️ Após o pagamento, clique em verificar."
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ Verificar Pagamento", callback_data=f'verificar_{resultado["payment_id"]}')],
            [InlineKeyboardButton("🔙 Voltar", callback_data='saldo')]
        ]
        
        await query.edit_message_text(mensagem, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await query.edit_message_text(
            f"❌ Erro ao gerar PIX\n\n"
            f"Motivo: {resultado.get('error', 'Erro desconhecido')}\n\n"
            f"Suporte: {SUPPORT_LINK}"
        )

async def verificar_pagamento_callback(query, payment_id):
    """Verifica pagamento"""
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
            f"Use o menu para ver seu saldo.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data='voltar_menu')]])
        )
    elif status == "pending":
        keyboard = [[InlineKeyboardButton("🔄 Verificar Novamente", callback_data=f'verificar_{payment_id}')]]
        await query.edit_message_text(
            f"⏱️ **Pagamento pendente**\n\n"
            f"💰 Valor: R$ {payment[2]:.2f}\n\n"
            f"Ainda não identificamos seu pagamento.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.edit_message_text(
            f"❌ Pagamento não encontrado ou expirado\n\n"
            f"Suporte: {SUPPORT_LINK}"
        )

async def perfil_menu(query):
    """Menu de perfil do usuário"""
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("Use /start primeiro")
        return
    
    total_spent = user[12] if len(user) > 12 else 0
    nivel, proximo = get_nivel(total_spent)
    
    text = (
        f"👤 **Perfil**\n\n"
        f"ID {user[4]}\n"
        f"{user[2]}\n"
        f"@{user[1]}\n"
        f"{user[3]}\n"
        f"R$ {user[5]:.2f}\n"
        f"Compras: {user[6]}\n"
        f"Gasto: R$ {total_spent:.2f}\n"
        f"{nivel} · Próximo: {nivel} (R$ {proximo})"
    )
    
    keyboard = [[InlineKeyboardButton("🏠 Voltar ao Menu", callback_data='voltar_menu')]]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def historico_menu(query):
    """Menu de histórico de transações"""
    trans = get_user_transactions(query.from_user.id)
    
    if not trans:
        keyboard = [[InlineKeyboardButton("🔙 Voltar", callback_data='voltar_menu')]]
        await query.edit_message_text(
            "📜 **Histórico**\n\nNenhuma transação.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    text = "📜 **Histórico**\n\n"
    for t in trans[:10]:
        if t[2] == "pix":
            text += f"💰 Recarga PIX - R$ {t[3]:.2f}\n   📅 {t[5]}\n\n"
        elif t[2] == "compra":
            text += f"💳 Compra - R$ {t[3]:.2f}\n   📅 {t[5]}\n\n"
        elif t[2] == "commission":
            text += f"🎁 Comissão - R$ {t[3]:.2f}\n   📅 {t[5]}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Voltar", callback_data='voltar_menu')]]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def afiliado_menu(query, context):
    """Menu de afiliados"""
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("Use /start primeiro")
        return
    
    link = f"https://t.me/{context.bot.username}?start={user[4]}"
    referrals = get_referred_count(query.from_user.id)
    commissions = get_total_commission(query.from_user.id)
    
    text = (
        f"👥 **Afiliado**\n\n"
        f"Ganhe 25% de comissão!\n\n"
        f"🔗 Seu link:\n"
        f"{link}\n\n"
        f"👥 Indicações: {referrals}\n"
        f"💰 Comissões: R$ {commissions:.2f}"
    )
    
    keyboard = [[InlineKeyboardButton("🏠 Voltar ao Menu", callback_data='voltar_menu')]]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def suporte_menu(query):
    """Menu de suporte"""
    keyboard = [[InlineKeyboardButton("📞 Falar com Suporte", url=SUPPORT_LINK)],
                [InlineKeyboardButton("🏠 Voltar ao Menu", callback_data='voltar_menu')]]
    
    await query.edit_message_text(
        f"📞 **Suporte**\n\n"
        f"Descreva sua dúvida:\n\n"
        f"Clique no botão abaixo para falar com nosso suporte.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def pix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /pix VALOR"""
    # Verifica grupo primeiro
    in_group = await check_group(update, context)
    if not in_group:
        keyboard = [[InlineKeyboardButton("📢 Entrar no Grupo", url=GROUP_LINK)]]
        await update.message.reply_text(
            "⚠️ Você precisa estar no grupo para usar o bot!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "💳 **PIX**\n\n"
            "Digite o valor (mín R$ 10,00):\n"
            "Ex: 50.00"
        )
        return
    
    try:
        valor = float(context.args[0])
        if valor < 10 or valor > 1000:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Valor inválido! Use valores entre R$10 e R$1000.")
        return
    
    user_id = update.effective_user.id
    email = f"user{user_id}@suppystore.com"
    
    await update.message.reply_text("⏱️ Gerando PIX... Aguarde...")
    
    resultado = criar_pix_mercadopago(valor, user_id, email)
    
    if resultado["success"]:
        save_pending_payment(user_id, valor, resultado["payment_id"], resultado["qr_code"], resultado["qr_code_base64"])
        
        mensagem = (
            f"✅ **PIX gerado!**\n\n"
            f"📱 **Código PIX:**\n"
            f"`{resultado['qr_code']}`\n\n"
            f"💰 **Valor:** R$ {valor:.2f}\n"
            f"🆔 **ID:** `{resultado['payment_id']}`\n\n"
            f"⏱️ Expira em 30 minutos!\n\n"
            f"⚠️ Após o pagamento, use /verificar {resultado['payment_id']}"
        )
        
        await update.message.reply_text(mensagem, parse_mode='Markdown')
    else:
        await update.message.reply_text(
            f"❌ Erro ao gerar PIX\n\n"
            f"Motivo: {resultado.get('error', 'Erro desconhecido')}\n\n"
            f"Suporte: {SUPPORT_LINK}"
        )

async def saldo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /saldo"""
    in_group = await check_group(update, context)
    if not in_group:
        keyboard = [[InlineKeyboardButton("📢 Entrar no Grupo", url=GROUP_LINK)]]
        await update.message.reply_text(
            "⚠️ Você precisa estar no grupo para usar o bot!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    user = get_user(update.effective_user.id)
    if user:
        await update.message.reply_text(f"💰 Saldo: R$ {user[5]:.2f}")
    else:
        await update.message.reply_text("Use /start primeiro!")

async def bank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /bank (placeholder)"""
    await update.message.reply_text(
        "🏦 **Buscar por Banco**\n\n"
        "Use: /bank NOME_DO_BANCO\n"
        "exemplo: /bank nubank"
    )

async def bin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /bin (placeholder)"""
    await update.message.reply_text(
        "🔍 **Buscar por BIN**\n\n"
        "Use: /bin NUMERO_BIN\n"
        "exemplo: /bin 406669"
    )

# ==================== MAIN ====================

def main():
    init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Handlers de comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pix", pix_command))
    app.add_handler(CommandHandler("saldo", saldo_command))
    app.add_handler(CommandHandler("bank", bank_command))
    app.add_handler(CommandHandler("bin", bin_command))
    
    # Handler de callbacks
    app.add_handler(CallbackQueryHandler(button_callback))
    
    print("=" * 50)
    print("✅ BOT SUPPS STORE ESTA ONLINE!")
    print(f"📌 Nome: {STORE_NAME}")
    print(f"👥 Grupo: {GROUP_LINK}")
    print(f"📞 Suporte: {SUPPORT_LINK}")
    print(f"💰 Mercado Pago: CONECTADO!")
    print("=" * 50)
    
    app.run_polling()

if __name__ == "__main__":
    main()