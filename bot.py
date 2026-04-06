import logging
import sqlite3
import requests
import uuid
import random
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ==================== CONFIGURAÇÕES ====================
BOT_TOKEN = "8477706439:AAF1ibc5aI95nM3r2BB6XZpW84GpepYJgiE"
STORE_NAME = "Suppys Store"
SUPPORT_LINK = "https://t.me/suportesuppys7"
GROUP_LINK = "https://t.me/+laIYEeIQuuc1ZWEx"
GROUP_ID = -1003819017548

# Mercado Pago
MERCADOPAGO_ACCESS_TOKEN = "APP_USR-8313019935361645-040523-f5273bbb40e6f8b1cfa385cbb7716aa5-800117337"

# Banco de dados
DB_PATH = "suppys_store.db"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Cache de verificação
verified_cache = {}

# ==================== BANCO DE DADOS ====================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
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
        total_spent REAL DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        amount REAL,
        status TEXT,
        date TEXT,
        payment_id TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS pending_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        payment_id TEXT,
        qr_code TEXT,
        status TEXT,
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bin TEXT,
        level TEXT,
        price REAL,
        card_number TEXT,
        cvv TEXT,
        expiry TEXT,
        cpf TEXT,
        sold INTEGER DEFAULT 0
    )""")
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

def update_spent(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET cards_bought = cards_bought + 1, total_spent = total_spent + ?, balance = balance - ? WHERE user_id = ?", 
              (amount, amount, user_id))
    conn.commit()
    conn.close()

def add_transaction(user_id, type_, amount, status, details="", payment_id=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO transactions (user_id, type, amount, status, date, payment_id) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, type_, amount, status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(payment_id)))
    conn.commit()
    conn.close()

def save_pending_payment(user_id, amount, payment_id, qr_code):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO pending_payments (user_id, amount, payment_id, qr_code, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
              (user_id, amount, str(payment_id), qr_code, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
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

def get_cards_by_bin(bin_num):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM cards WHERE bin = ? AND sold = 0 LIMIT 5", (bin_num,))
    cards = c.fetchall()
    conn.close()
    return cards

def add_sample_cards():
    """Adiciona cartões de exemplo se não existir nenhum"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM cards")
    count = c.fetchone()[0]
    
    if count == 0:
        sample_cards = [
            ("406669", "PLATINUM", 30, "4532 1234 5678 9012", "123", "12/28", "123.456.789-00"),
            ("406669", "GOLD", 25, "4532 2345 6789 0123", "456", "10/27", "234.567.890-11"),
            ("422061", "BLACK", 75, "5221 3456 7890 1234", "789", "08/29", "345.678.901-22"),
            ("422061", "INFINITE", 75, "5221 4567 8901 2345", "234", "06/30", "456.789.012-33"),
            ("407843", "BUSINESS", 30, "4532 5678 9012 3456", "567", "04/28", "567.890.123-44"),
            ("415275", "SIGNATURE", 30, "4532 6789 0123 4567", "890", "02/29", "678.901.234-55"),
            ("406655", "STANDARD", 20, "4532 7890 1234 5678", "123", "11/26", "789.012.345-66"),
            ("546479", "ELO", 30, "6362 8901 2345 6789", "456", "09/27", "890.123.456-77"),
        ]
        for card in sample_cards:
            c.execute("INSERT INTO cards (bin, level, price, card_number, cvv, expiry, cpf) VALUES (?, ?, ?, ?, ?, ?, ?)", card)
        conn.commit()
        logger.info("Adicionados cartões de exemplo")
    
    conn.close()

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
        "description": f"Recarga {STORE_NAME}",
        "payment_method_id": "pix",
        "payer": {"email": email}
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        if response.status_code == 201:
            data = response.json()
            return {
                "success": True,
                "payment_id": data["id"],
                "qr_code": data["point_of_interaction"]["transaction_data"]["qr_code"]
            }
        return {"success": False, "error": "Erro ao gerar PIX"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def verificar_pagamento(payment_id):
    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    headers = {"Authorization": f"Bearer {MERCADOPAGO_ACCESS_TOKEN}"}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json().get("status")
        return None
    except Exception:
        return None

# ==================== VERIFICAÇÃO DE GRUPO ====================

async def check_group(context, user_id):
    try:
        chat_member = await context.bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except:
        return True

# ==================== COMANDOS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or "sem_username"
    
    # Verifica grupo
    in_group = await check_group(context, user_id)
    if not in_group:
        keyboard = [[InlineKeyboardButton("📢 Entrar no Grupo", url=GROUP_LINK)]]
        await update.message.reply_text(
            "⚠️ **Acesso Restrito!**\n\n"
            f"Olá {user.first_name}!\n\n"
            "Você precisa estar no nosso grupo para usar o bot.\n\n"
            "Clique no botão abaixo para entrar:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    # Cria usuário
    if not get_user(user_id):
        referred_by = None
        if context.args and context.args[0].isdigit():
            referred_by = int(context.args[0])
        create_user(user_id, username, user.first_name, referred_by)
    
    user_data = get_user(user_id)
    saldo = user_data[5] if user_data else 0
    
    text = (
        f"@{context.bot.username}\n"
        f"melhores gps só encontra na @{context.bot.username}\n\n"
        f"A VIDA NÃO É BOA PRA NINGUEM, ENTÃO DECIDI FICAR CONTIGO!\n\n"
        f"Olá, @{username}!\n\n"
        f"ID: {user_id}\n"
        f"Saldo: R$ {saldo:.2f}\n"
        f"Grupo: Clique aqui\n\n"
        f"Use o menu abaixo 👇"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔍 Comprar por BIN", callback_data="comprar_bin")],
        [InlineKeyboardButton("🔥 Ofertas do Dia", callback_data="ofertas")],
        [InlineKeyboardButton("💰 Saldo", callback_data="saldo")],
        [InlineKeyboardButton("👤 Perfil", callback_data="perfil")],
        [InlineKeyboardButton("📜 Histórico", callback_data="historico")],
        [InlineKeyboardButton("👥 Afiliado", callback_data="afiliado")],
        [InlineKeyboardButton("📞 Suporte", callback_data="suporte")]
    ]
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    user_data = get_user(user_id)
    saldo = user_data[5] if user_data else 0
    
    if data == "comprar_bin":
        bins = [
            ("406655 | (1)", "406655"),
            ("406669 | (18)", "406669"),
            ("407843 | (19)", "407843"),
            ("415275 | (13)", "415275"),
            ("422061 | (14)", "422061"),
            ("546479 | (2)", "546479")
        ]
        keyboard = [[InlineKeyboardButton(nome, callback_data=f"bin_{bin}")] for nome, bin in bins]
        keyboard.append([InlineKeyboardButton("🏠 Menu", callback_data="voltar")])
        
        await query.edit_message_text(
            f"🔍 **ESCOLHA SUA BIN**\n\nID {user_id} | R$ {saldo:.2f}\n\nPágina 1/1",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith("bin_"):
        bin_num = data.replace("bin_", "")
        cards = get_cards_by_bin(bin_num)
        
        if not cards:
            keyboard = [[InlineKeyboardButton("🔙 Voltar", callback_data="comprar_bin")]]
            await query.edit_message_text(
                f"Nenhum cartão disponível para BIN {bin_num}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        keyboard = []
        for card in cards:
            keyboard.append([InlineKeyboardButton(f"💳 {bin_num}xxxxxx - R$ {card[3]:.2f}", callback_data=f"buy_{card[0]}")])
        keyboard.append([InlineKeyboardButton("🔙 Voltar", callback_data="comprar_bin")])
        
        await query.edit_message_text(
            f"📋 **Cartões BIN {bin_num}**\n\nSelecione um cartão:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith("buy_"):
        card_id = int(data.replace("buy_", ""))
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM cards WHERE id = ? AND sold = 0", (card_id,))
        card = c.fetchone()
        
        if not card:
            await query.edit_message_text("❌ Cartão não disponível!")
            conn.close()
            return
        
        price = card[3]
        
        if saldo < price:
            keyboard = [[InlineKeyboardButton("💰 Adicionar Saldo", callback_data="saldo")]]
            await query.edit_message_text(
                f"❌ **Saldo insuficiente!**\n\nSaldo: R$ {saldo:.2f}\nPreço: R$ {price:.2f}\nFalta: R$ {price - saldo:.2f}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            conn.close()
            return
        
        # Marca como vendido
        c.execute("UPDATE cards SET sold = 1 WHERE id = ?", (card_id,))
        conn.commit()
        conn.close()
        
        update_spent(user_id, price)
        add_transaction(user_id, "compra", price, "completed", f"Cartão {card[2]}")
        
        await query.edit_message_text(
            f"✅ **COMPRA REALIZADA!**\n\n"
            f"💳 {card[5]}\n"
            f"📅 {card[6]}\n"
            f"🔐 {card[7]}\n"
            f"🆔 CPF: {card[8]}\n\n"
            f"💰 Valor: R$ {price:.2f}\n"
            f"💵 Saldo restante: R$ {saldo - price:.2f}\n\n"
            f"⚠️ Garantia de 5 minutos para troca!\n"
            f"📞 Suporte: {SUPPORT_LINK}"
        )
    
    elif data == "ofertas":
        text = (
            "🔥 **OFERTAS ESPECIAIS!**\n\n"
            "1. GG 406669xxxxxx - R$ 7.04 (-12%)\n"
            "2. GG 422061xxxxxx - R$ 3.90 (-22%)\n"
            "3. GG 422061xxxxxx - R$ 4.20 (-16%)\n"
            "4. GG 406669xxxxxx - R$ 6.40 (-20%)\n"
            "5. GG 406669xxxxxx - R$ 6.40 (-20%)\n\n"
            "Use /pix para adicionar saldo!"
        )
        keyboard = [[InlineKeyboardButton("🏠 Menu", callback_data="voltar")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "saldo":
        keyboard = [
            [InlineKeyboardButton("💰 Adicionar Saldo", callback_data="adicionar_saldo")],
            [InlineKeyboardButton("🏠 Menu", callback_data="voltar")]
        ]
        await query.edit_message_text(f"💰 **SALDO**\n\nR$ {saldo:.2f}", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "adicionar_saldo":
        keyboard = [
            [InlineKeyboardButton("R$ 10", callback_data="pix_10"),
             InlineKeyboardButton("R$ 20", callback_data="pix_20"),
             InlineKeyboardButton("R$ 50", callback_data="pix_50")],
            [InlineKeyboardButton("R$ 100", callback_data="pix_100"),
             InlineKeyboardButton("R$ 200", callback_data="pix_200"),
             InlineKeyboardButton("R$ 500", callback_data="pix_500")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="saldo")]
        ]
        await query.edit_message_text(
            "💳 **PIX**\n\nEscolha um valor:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith("pix_"):
        valor = float(data.replace("pix_", ""))
        email = f"user{user_id}@suppystore.com"
        
        await query.edit_message_text("⏱️ Gerando PIX...")
        
        resultado = criar_pix_mercadopago(valor, user_id, email)
        
        if resultado["success"]:
            save_pending_payment(user_id, valor, resultado["payment_id"], resultado["qr_code"])
            
            keyboard = [[InlineKeyboardButton("✅ Verificar Pagamento", callback_data=f"verify_{resultado['payment_id']}")]]
            
            await query.edit_message_text(
                f"✅ **PIX GERADO!**\n\n"
                f"📱 **Código PIX:**\n`{resultado['qr_code']}`\n\n"
                f"💰 Valor: R$ {valor:.2f}\n"
                f"🆔 ID: `{resultado['payment_id']}`\n\n"
                f"⏱️ Expira em 30 minutos!",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(f"❌ Erro: {resultado['error']}")
    
    elif data.startswith("verify_"):
        payment_id = data.replace("verify_", "")
        await query.edit_message_text("⏱️ Verificando...")
        
        status = verificar_pagamento(payment_id)
        
        if status == "approved":
            payment = get_pending_payment(payment_id)
            if payment:
                update_balance(payment[1], payment[2])
                add_transaction(payment[1], "pix", payment[2], "completed", "", payment_id)
                update_payment_status(payment_id, "completed")
                
                # Comissão para afiliado
                user = get_user(payment[1])
                if user and user[9]:
                    commission = payment[2] * 0.25
                    update_balance(user[9], commission)
                    add_transaction(user[9], "commission", commission, "completed", f"Comissão por recarga", payment_id)
                
                await query.edit_message_text(
                    f"✅ **PAGAMENTO CONFIRMADO!**\n\n"
                    f"💰 R$ {payment[2]:.2f} creditado!\n\n"
                    f"🏠 Use o menu para continuar.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="voltar")]])
                )
        elif status == "pending":
            keyboard = [[InlineKeyboardButton("🔄 Verificar Novamente", callback_data=f"verify_{payment_id}")]]
            await query.edit_message_text("⏱️ Pagamento pendente...", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text("❌ Pagamento não encontrado!")
    
    elif data == "perfil":
        user = query.from_user
        total_spent = user_data[10] if user_data and len(user_data) > 10 else 0
        total_spent = user_data[10] if user_data and len(user_data) > 10 else 0
        
        nivel = "Sem nível"
        proximo = "R$ 50.00"
        if total_spent >= 500:
            nivel = "Diamante"
            proximo = "R$ 1000.00"
        elif total_spent >= 200:
            nivel = "Ouro"
            proximo = "R$ 500.00"
        elif total_spent >= 100:
            nivel = "Prata"
            proximo = "R$ 200.00"
        elif total_spent >= 50:
            nivel = "Bronze"
            proximo = "R$ 100.00"
        
        text = (
            f"👤 **PERFIL**\n\n"
            f"ID: {user.id}\n"
            f"User: @{user.username or 'sem_username'}\n"
            f"Nome: {user.first_name}\n"
            f"Saldo: R$ {saldo:.2f}\n"
            f"Compras: {user_data[6] if user_data else 0}\n"
            f"Gasto: R$ {total_spent:.2f}\n"
            f"Nível: {nivel} · Próximo: {proximo}"
        )
        keyboard = [[InlineKeyboardButton("🏠 Menu", callback_data="voltar")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "historico":
        trans = get_user_transactions(user_id)
        
        if not trans:
            text = "📜 **HISTÓRICO**\n\nNenhuma transação encontrada."
        else:
            text = "📜 **HISTÓRICO**\n\n"
            for t in trans[:10]:
                if t[2] == "pix":
                    text += f"💰 Recarga PIX - R$ {t[3]:.2f}\n   📅 {t[5]}\n\n"
                elif t[2] == "compra":
                    text += f"💳 Compra - R$ {t[3]:.2f}\n   📅 {t[5]}\n\n"
                elif t[2] == "commission":
                    text += f"🎁 Comissão - R$ {t[3]:.2f}\n   📅 {t[5]}\n\n"
        
        keyboard = [[InlineKeyboardButton("🏠 Menu", callback_data="voltar")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "afiliado":
        link = f"https://t.me/{context.bot.username}?start={user_id}"
        referrals = get_referred_count(user_id)
        commissions = get_total_commission(user_id)
        
        text = (
            f"👥 **AFILIADO**\n\n"
            f"Ganhe 25% de comissão!\n\n"
            f"🔗 Seu link:\n{link}\n\n"
            f"👥 Indicações: {referrals}\n"
            f"💰 Comissões: R$ {commissions:.2f}"
        )
        keyboard = [[InlineKeyboardButton("🏠 Menu", callback_data="voltar")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "suporte":
        text = f"📞 **SUPORTE**\n\nFale conosco:\n{SUPPORT_LINK}"
        keyboard = [[InlineKeyboardButton("🏠 Menu", callback_data="voltar")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "voltar":
        text = (
            f"@{context.bot.username}\n"
            f"melhores gps só encontra na @{context.bot.username}\n\n"
            f"A VIDA NÃO É BOA PRA NINGUEM, ENTÃO DECIDI FICAR CONTIGO!\n\n"
            f"Olá, @{query.from_user.username or 'usuario'}!\n\n"
            f"ID: {user_id}\n"
            f"Saldo: R$ {saldo:.2f}\n\n"
            f"Use o menu abaixo 👇"
        )
        keyboard = [
            [InlineKeyboardButton("🔍 Comprar por BIN", callback_data="comprar_bin")],
            [InlineKeyboardButton("🔥 Ofertas do Dia", callback_data="ofertas")],
            [InlineKeyboardButton("💰 Saldo", callback_data="saldo")],
            [InlineKeyboardButton("👤 Perfil", callback_data="perfil")],
            [InlineKeyboardButton("📜 Histórico", callback_data="historico")],
            [InlineKeyboardButton("👥 Afiliado", callback_data="afiliado")],
            [InlineKeyboardButton("📞 Suporte", callback_data="suporte")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def pix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Use: /pix 20")
        return
    
    try:
        valor = float(context.args[0])
        if valor < 10:
            await update.message.reply_text("Valor mínimo: R$ 10")
            return
    except:
        await update.message.reply_text("Valor inválido!")
        return
    
    user_id = update.effective_user.id
    email = f"user{user_id}@suppystore.com"
    
    await update.message.reply_text("⏱️ Gerando PIX...")
    
    resultado = criar_pix_mercadopago(valor, user_id, email)
    
    if resultado["success"]:
        save_pending_payment(user_id, valor, resultado["payment_id"], resultado["qr_code"])
        await update.message.reply_text(
            f"✅ **PIX GERADO!**\n\n"
            f"📱 **Código PIX:**\n`{resultado['qr_code']}`\n\n"
            f"💰 Valor: R$ {valor:.2f}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ Erro: {resultado['error']}")

async def bin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Use: /bin 406669")
        return
    
    bin_num = context.args[0]
    cards = get_cards_by_bin(bin_num)
    
    if not cards:
        await update.message.reply_text(f"Nenhum cartão encontrado para BIN {bin_num}")
        return
    
    text = f"🔍 **BIN {bin_num}**\n\n"
    for card in cards[:5]:
        text += f"💳 {card[2]} - R$ {card[3]:.2f}\n"
    
    await update.message.reply_text(text)

# ==================== MAIN ====================

def main():
    init_db()
    add_sample_cards()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pix", pix_command))
    app.add_handler(CommandHandler("bin", bin_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    print("=" * 50)
    print("✅ BOT SUPPS STORE ESTA ONLINE!")
    print(f"📌 Nome: {STORE_NAME}")
    print(f"👥 Grupo: {GROUP_LINK}")
    print(f"📞 Suporte: {SUPPORT_LINK}")
    print(f"💰 Mercado Pago: CONECTADO!")
    print("=" * 50)
    
    app.run_polling(allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    main()