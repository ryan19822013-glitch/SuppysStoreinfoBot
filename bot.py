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
CHANNEL_LINK = "@CanalSuppysStore"

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
    register_date = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
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

def increment_cards_bought(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET cards_bought = cards_bought + 1 WHERE user_id = ?", (user_id,))
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

def get_user_cards(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM user_cards WHERE user_id = ? ORDER BY purchase_date DESC", (user_id,))
    cards = c.fetchall()
    conn.close()
    return cards

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
    
    keyboard = [
        [InlineKeyboardButton("Comprar", callback_data='comprar')],
        [InlineKeyboardButton("Desbloquear CPF", callback_data='desbloquear_cpf')],
        [InlineKeyboardButton("Saldo Grátis", callback_data='saldo_gratis')],
        [InlineKeyboardButton("Minha Conta", callback_data='minha_conta')],
        [InlineKeyboardButton("ADICIONAR SALDO VIA PIX", callback_data='adicionar_saldo')]
    ]
    
    welcome_text = (
        f"Bem-vindo(a) a {STORE_NAME}!\n\n"
        f"Lideres em vendas diretas de FULL de alta qualidade.\n"
        f"Material de alta qualidade a precos acessiveis.\n"
        f"Cartoes 100% virgens, 0 reteste.\n\n"
        f"Garantia de cartoes live, com troca em ate 5 minutos pelo BOT.\n"
        f"Recarregue rapidamente com o comando /pix.\n\n"
        f"Referencias: {CHANNEL_LINK}\n"
        f"Suporte: {SUPPORT_LINK}"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == 'comprar':
        await comprar_menu(query)
    elif data == 'desbloquear_cpf':
        await desbloquear_cpf(query)
    elif data == 'saldo_gratis':
        await saldo_gratis(query)
    elif data == 'minha_conta':
        await minha_conta(query)
    elif data == 'adicionar_saldo':
        await adicionar_saldo_menu(query)
    elif data == 'voltar':
        await start(update, context)
    elif data == 'pix_auto':
        await pix_auto(query)
    elif data == 'buscar_bin':
        await buscar_bin(query)
    elif data == 'buscar_banco':
        await buscar_banco(query)
    elif data == 'meus_cartoes':
        await meus_cartoes(query)
    elif data == 'saldo_comprado':
        await saldo_comprado(query)
    elif data == 'recargas_pix':
        await recargas_pix(query)
    elif data == 'recargas_gift':
        await recargas_gift(query)
    elif data == 'historico_ccs':
        await historico_ccs(query)
    elif data == 'sistema_afiliados':
        await sistema_afiliados(query, context)
    elif data.startswith('nivel_'):
        nivel = data.replace('nivel_', '')
        await comprar_cartao(query, nivel)
    elif data.startswith('pix_valor_'):
        valor = data.replace('pix_valor_', '')
        await gerar_pix(query, valor)
    elif data.startswith('verificar_'):
        payment_id = data.replace('verificar_', '')
        await verificar_pagamento_callback(query, payment_id)

async def comprar_menu(query):
    keyboard = [
        [InlineKeyboardButton("Busca bin", callback_data='buscar_bin')],
        [InlineKeyboardButton("Busca banco", callback_data='buscar_banco')],
        [InlineKeyboardButton("Ver niveis", callback_data='niveis')],
        [InlineKeyboardButton("volta", callback_data='voltar')]
    ]
    
    text = (
        "Compre apenas se voce estiver de acordo com as regras:\n\n"
        "GARANTIMOS LIVE! Nao asseguramos saldo especifico ou aprovacao.\n\n"
        "Direito de troca em ate 5 minutos atraves do bot. Caso a troca nao seja efetuada, por favor, nao insista!\n\n"
        "CC + CPF REAL"
    )
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def niveis_menu(query):
    niveis = [
        ("- R$ 20", "nivel_20"),
        ("- AWARD - R$ 20", "nivel_AWARD"),
        ("- BLACK - R$ 75", "nivel_BLACK"),
        ("- BUSINESS - R$ 30", "nivel_BUSINESS"),
        ("- CLASSIC - R$ 20", "nivel_CLASSIC"),
        ("- ELO - R$ 30", "nivel_ELO"),
        ("- GOLD - R$ 25", "nivel_GOLD"),
        ("- INFINITE - R$ 75", "nivel_INFINITE"),
        ("- NU GOLD - R$ 7", "nivel_NU_GOLD"),
        ("- NU PLATINUM - R$ 15", "nivel_NU_PLATINUM"),
        ("- NUBANK BLACK - R$ 75", "nivel_NUBANK_BLACK"),
        ("- PLATINUM - R$ 30", "nivel_PLATINUM"),
        ("- PREPAID - R$ 20", "nivel_PREPAID"),
        ("- SIGNATURE - R$ 30", "nivel_SIGNATURE"),
        ("- STANDARD - R$ 20", "nivel_STANDARD")
    ]
    
    keyboard = [[InlineKeyboardButton(nome, callback_data=callback)] for nome, callback in niveis]
    keyboard.append([InlineKeyboardButton("volta", callback_data='comprar')])
    
    await query.edit_message_text(
        "Escolha um nivel para continuar sua compra\n\n"
        "Ha 1056 cartoes disponiveis\n\n"
        "CHECKER NA COMPRA (ZERO-AUTH)!\n"
        "CHECKER NA TROCA (ZERO-AUTH)!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def comprar_cartao(query, nivel):
    precos = {
        "20": 20, "AWARD": 20, "BLACK": 75, "BUSINESS": 30,
        "CLASSIC": 20, "ELO": 30, "GOLD": 25, "INFINITE": 75,
        "NU_GOLD": 7, "NU_PLATINUM": 15, "NUBANK_BLACK": 75,
        "PLATINUM": 30, "PREPAID": 20, "SIGNATURE": 30, "STANDARD": 20
    }
    
    preco = precos.get(nivel, 20)
    user = get_user(query.from_user.id)
    
    if not user:
        await query.edit_message_text("Use /start primeiro")
        return
    
    saldo = user[5]
    if saldo < preco:
        await query.edit_message_text(
            f"Saldo insuficiente!\n\n"
            f"Seu saldo: R$ {saldo:.2f}\n"
            f"Preco: R$ {preco:.2f}\n\n"
            f"Use o menu 'ADICIONAR SALDO VIA PIX' para recarregar."
        )
        return
    
    import random
    card_num = f"{random.randint(4000, 4999)} {random.randint(1000, 9999)} {random.randint(1000, 9999)} {random.randint(1000, 9999)}"
    cvv = random.randint(100, 999)
    
    monthly_deposit = get_monthly_deposit(query.from_user.id)
    cpf_text = "123.456.789-00" if monthly_deposit >= 100 else "***.***.***-**"
    
    await query.edit_message_text(
        f"Compra realizada!\n\n"
        f"Nivel: {nivel}\n"
        f"Valor: R$ {preco:.2f}\n"
        f"Saldo restante: R$ {saldo - preco:.2f}\n\n"
        f"Dados do cartao:\n"
        f"{card_num}\n"
        f"12/28\n"
        f"{cvv}\n"
        f"CPF: {cpf_text}\n\n"
        f"Garantia de 5 minutos para troca!\n"
        f"Suporte: {SUPPORT_LINK}"
    )
    
    update_balance(query.from_user.id, -preco)
    increment_cards_bought(query.from_user.id)
    add_transaction(query.from_user.id, "compra", preco, "completed", f"Cartao {nivel}")

async def adicionar_saldo_menu(query):
    keyboard = [
        [InlineKeyboardButton("Pix automatico", callback_data='pix_auto')],
        [InlineKeyboardButton("volta", callback_data='voltar')]
    ]
    
    await query.edit_message_text(
        "Adicione saldo na STORE\n\n"
        "Voce pode adicionar saldo na store utilizando o pix automatico (copia e cola).",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def pix_auto(query):
    keyboard = [
        [InlineKeyboardButton("R$ 10", callback_data='pix_valor_10'),
         InlineKeyboardButton("R$ 20", callback_data='pix_valor_20'),
         InlineKeyboardButton("R$ 50", callback_data='pix_valor_50')],
        [InlineKeyboardButton("R$ 100", callback_data='pix_valor_100'),
         InlineKeyboardButton("R$ 200", callback_data='pix_valor_200'),
         InlineKeyboardButton("R$ 500", callback_data='pix_valor_500')],
        [InlineKeyboardButton("volta", callback_data='adicionar_saldo')]
    ]
    
    await query.edit_message_text(
        "Adicao de saldo via pix\n\n"
        "tornou-se mais facil! agora os seus pagamentos serao processados de forma automatica pelo bot.\n\n"
        "para criar uma transacao pelo bot use:\n"
        "/pix valor\n\n"
        "exemplo: /pix 20\n\n"
        "o seu saldo estara disponivel em ate 30 minutos apos o pagamento!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def gerar_pix(query, valor):
    valor = float(valor)
    user_id = query.from_user.id
    email = f"user{user_id}@suppystore.com"
    
    await query.edit_message_text("Gerando PIX... Aguarde...")
    
    resultado = criar_pix_mercadopago(valor, user_id, email)
    
    if resultado["success"]:
        save_pending_payment(user_id, valor, resultado["payment_id"], resultado["qr_code"], resultado["qr_code_base64"])
        
        mensagem = (
            f"Codigo copia e cola:\n"
            f"{resultado['qr_code']}\n\n"
            f"Dica: para copiar o codigo basta clicar em cima dele\n\n"
            f"valor: R$ {valor:.2f}\n\n"
            f"Id transacao: {resultado['payment_id']}\n\n"
            f"A transacao expira em 30 minutos!\n\n"
            f"Caso voce realize o pagamento e nao receba seu saldo chame o suporte!"
        )
        
        keyboard = [[InlineKeyboardButton("Verificar Pagamento", callback_data=f'verificar_{resultado["payment_id"]}')]]
        
        await query.edit_message_text(mensagem, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.edit_message_text(
            f"Erro ao gerar PIX\n\n"
            f"Motivo: {resultado.get('error', 'Erro desconhecido')}\n\n"
            f"Suporte: {SUPPORT_LINK}"
        )

async def verificar_pagamento_callback(query, payment_id):
    await query.edit_message_text("Verificando pagamento...")
    
    payment = get_pending_payment(payment_id)
    if not payment:
        await query.edit_message_text("Transacao nao encontrada!")
        return
    
    status = verificar_pagamento_mp(payment_id)
    
    if status == "approved":
        processar_pagamento_aprovado(payment_id, payment[1], payment[2])
        await query.edit_message_text(
            f"PAGAMENTO CONFIRMADO!\n\n"
            f"Valor: R$ {payment[2]:.2f}\n"
            f"Saldo creditado na sua carteira!"
        )
    elif status == "pending":
        await query.edit_message_text(
            f"Pagamento pendente\n\n"
            f"Valor: R$ {payment[2]:.2f}\n\n"
            f"Ainda nao identificamos seu pagamento.\n"
            f"Assim que fizer o PIX, clique em verificar novamente."
        )
    else:
        await query.edit_message_text(
            f"Pagamento nao encontrado ou expirado\n\n"
            f"Suporte: {SUPPORT_LINK}"
        )

async def minha_conta(query):
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("Use /start primeiro")
        return
    
    keyboard = [
        [InlineKeyboardButton("Recargas Pix", callback_data='recargas_pix'),
         InlineKeyboardButton("Recargas por GIFT", callback_data='recargas_gift')],
        [InlineKeyboardButton("Historico de cc's", callback_data='historico_ccs')],
        [InlineKeyboardButton("Sistema de Afiliados", callback_data='sistema_afiliados')],
        [InlineKeyboardButton("volta", callback_data='voltar')]
    ]
    
    text = (
        f"Nome: {user[2]}\n"
        f"User: @{user[1]}\n"
        f"Data de cadastro: {user[3]}\n\n"
        f"ID da carteira: {user[4]}\n"
        f"Saldo: R$ {user[5]:.2f}\n\n"
        f"- Cartoes comprados: {user[6]}\n"
        f"- Recargas com pix's: {user[7]}\n"
        f"- Recargas por GIFT: {user[8]}"
    )
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def meus_cartoes(query):
    cards = get_user_cards(query.from_user.id)
    
    if not cards:
        await query.edit_message_text(
            "+ Seus cartoes\n\n"
            "Ops, voce ainda nao tem nenhum cartao comprado!"
        )
        return
    
    text = "+ SEUS CARTOES\n\n"
    for card in cards:
        text += f"{card[2]} - R$ {card[3]:.2f}\n"
        text += f"   {card[5]}\n\n"
    
    await query.edit_message_text(text)

async def saldo_comprado(query):
    recharges = get_user_recharges(query.from_user.id)
    
    if not recharges:
        await query.edit_message_text(
            "+ Saldo comprado\n\n"
            "Ops, voce ainda nao tem nenhuma compra de saldo!"
        )
        return
    
    text = "+ SALDO COMPRADO\n\n"
    for r in recharges[:10]:
        text += f"R$ {r[3]:.2f} - {r[5]}\n\n"
    
    await query.edit_message_text(text)

async def recargas_pix(query):
    recharges = get_user_recharges(query.from_user.id)
    
    if not recharges:
        await query.edit_message_text(
            "Recargas Pix\n\n"
            "Ops, voce ainda nao tem nenhuma recarga Pix!"
        )
        return
    
    text = "RECARGAS PIX\n\n"
    for r in recharges[:10]:
        text += f"R$ {r[3]:.2f} - {r[5]}\n\n"
    
    await query.edit_message_text(text)

async def recargas_gift(query):
    await query.edit_message_text(
        "Recargas por GIFT\n\n"
        "Ops, voce ainda nao tem nenhuma recarga por GIFT!"
    )

async def historico_ccs(query):
    cards = get_user_cards(query.from_user.id)
    
    if not cards:
        await query.edit_message_text(
            "Historico de cc's\n\n"
            "Ops, voce ainda nao tem nenhum cartao comprado!"
        )
        return
    
    text = "HISTORICO DE CC'S\n\n"
    for card in cards[:10]:
        text += f"{card[2]} - R$ {card[3]:.2f}\n"
        text += f"   {card[5]}\n\n"
    
    await query.edit_message_text(text)

async def sistema_afiliados(query, context):
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("Use /start primeiro")
        return
    
    link = f"https://t.me/{context.bot.username}?start={user[4]}"
    referrals = get_referred_count(query.from_user.id)
    commissions = get_total_commission(query.from_user.id)
    
    text = (
        f"Sistema de Afiliados\n\n"
        f"Ganhe bonus ao indicar a store para seus amigos!\n\n"
        f"Quando seu amigo fizer uma recarga voce ganhara 25% (saldo) do valor recarregado!\n\n"
        f"Seu link: {link}\n\n"
        f"Indicacoes: {referrals}\n"
        f"Comissoes: R$ {commissions:.2f}"
    )
    
    await query.edit_message_text(text)

async def desbloquear_cpf(query):
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("Use /start primeiro")
        return
    
    monthly_deposit = get_monthly_deposit(query.from_user.id)
    
    if monthly_deposit >= 100:
        text = (
            f"CPF ANTECIPADO - DESBLOQUEADO!\n\n"
            f"Voce ja depositou R$ {monthly_deposit:.2f} neste mes.\n"
            f"Agora voce pode ver o CPF das FULL antes de comprar!"
        )
    else:
        falta = 100 - monthly_deposit
        text = (
            f"Acesso ao CPF ANTECIPADO\n\n"
            f"Para visualizar o CPF das FULL antes da compra, e necessario um deposito minimo de R$ 100 no mes.\n\n"
            f"Por exemplo: Quando inicia um novo mes, como dezembro, o sistema reseta e voce precisa adicionar um total de R$ 100 para visualizar novamente.\n\n"
            f"Seu deposito mensal: R$ {monthly_deposit:.2f}\n"
            f"Falta: R$ {falta:.2f}\n\n"
            f"A LIBERACAO E IMEDIATA E AUTOMATICA APOS ATINGIR O VALOR DE R$ 100 MENSAL."
        )
    
    await query.edit_message_text(text)

async def saldo_gratis(query):
    await query.edit_message_text(
        "SALDO GRATIS\n\n"
        "Promocoes disponiveis:\n\n"
        "Indique amigos: Ganhe R$5 por indicacao + 25% das recargas!\n"
        "Primeira recarga: Em breve\n\n"
        "Fique de olho no grupo oficial para futuras promocoes!"
    )

async def buscar_bin(query):
    await query.edit_message_text(
        "Buscar por BIN\n\n"
        "Voce pode buscar por cartoes em nossa base pela bin\n\n"
        "Use o comando /bin junto da bin que voce quer comprar.\n\n"
        "Exemplo: /bin 406669\n\n"
        "ou simplesmente mande a bin para o bot."
    )

async def buscar_banco(query):
    await query.edit_message_text(
        "Buscar por banco\n\n"
        "caso esteja procurando por um cartao de um banco especifico, use a busca por banco\n\n"
        "exemplo de uso: /bank banco do brasil\n\n"
        "bom uso"
    )

async def pix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "Use: /pix valor\n"
            "exemplo: /pix 20"
        )
        return
    
    try:
        valor = float(context.args[0])
        if valor < 10 or valor > 1000:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Valor invalido! Use valores entre R$10 e R$1000.")
        return
    
    user_id = update.effective_user.id
    email = f"user{user_id}@suppystore.com"
    
    await update.message.reply_text("Gerando PIX... Aguarde...")
    
    resultado = criar_pix_mercadopago(valor, user_id, email)
    
    if resultado["success"]:
        save_pending_payment(user_id, valor, resultado["payment_id"], resultado["qr_code"], resultado["qr_code_base64"])
        
        mensagem = (
            f"Codigo copia e cola:\n"
            f"{resultado['qr_code']}\n\n"
            f"Dica: para copiar o codigo basta clicar em cima dele\n\n"
            f"valor: R$ {valor:.2f}\n\n"
            f"Id transacao: {resultado['payment_id']}\n\n"
            f"A transacao expira em 30 minutos!\n\n"
            f"Caso voce realize o pagamento e nao receba seu saldo chame o suporte!"
        )
        
        keyboard = [[InlineKeyboardButton("Verificar Pagamento", callback_data=f'verificar_{resultado["payment_id"]}')]]
        
        await update.message.reply_text(mensagem, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(
            f"Erro ao gerar PIX\n\n"
            f"Motivo: {resultado.get('error', 'Erro desconhecido')}\n\n"
            f"Suporte: {SUPPORT_LINK}"
        )

async def bank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Buscar por banco\n\n"
            "Use: /bank NOME_DO_BANCO\n"
            "exemplo: /bank banco do brasil"
        )
        return
    
    banco = ' '.join(context.args)
    await update.message.reply_text(
        f"Buscando cartoes do banco: {banco}\n\n"
        f"Exemplo de resultados:\n"
        f"{banco.title()} Platinum - R$ 30\n"
        f"{banco.title()} Gold - R$ 25\n"
        f"{banco.title()} Black - R$ 75\n\n"
        f"Use o menu 'Comprar' para adquirir seu cartao."
    )

async def bin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Buscar por BIN\n\n"
            "Use: /bin NUMERO_BIN\n"
            "exemplo: /bin 406669"
        )
        return
    
    bin_num = context.args[0]
    await update.message.reply_text(
        f"Buscando cartoes com BIN: {bin_num}\n\n"
        f"Resultados encontrados:\n"
        f"Visa Platinum - R$ 30\n"
        f"Visa Infinite - R$ 75\n"
        f"Visa Signature - R$ 30\n\n"
        f"Use o menu 'Comprar' para adquirir seu cartao."
    )

async def saldo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if user:
        await update.message.reply_text(
            f"SEU SALDO\n\n"
            f"Saldo disponivel: R$ {user[5]:.2f}\n\n"
            f"Use /pix VALOR para adicionar saldo."
        )
    else:
        await update.message.reply_text("Use /start primeiro!")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text.isdigit() and len(text) >= 6:
        bin_num = text[:6]
        await update.message.reply_text(
            f"Buscando BIN: {bin_num}\n\n"
            f"Cartoes encontrados com essa BIN:\n"
            f"Cartao 1 - R$ XX\n"
            f"Cartao 2 - R$ XX\n\n"
            f"Use o menu 'Comprar' para ver todos os niveis disponiveis."
        )

# ==================== MAIN ====================

def main():
    init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pix", pix_command))
    app.add_handler(CommandHandler("bank", bank_command))
    app.add_handler(CommandHandler("bin", bin_command))
    app.add_handler(CommandHandler("saldo", saldo_command))
    
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    print("=" * 50)
    print("BOT SUPPS STORE ESTA ONLINE!")
    print(f"Nome: {STORE_NAME}")
    print(f"Grupo: {GROUP_LINK}")
    print(f"Suporte: {SUPPORT_LINK}")
    print(f"Mercado Pago: CONECTADO!")
    print("=" * 50)
    
    app.run_polling()

if __name__ == "__main__":
    main()