import os
import logging
import sqlite3
import requests
import uuid
import random
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ==================== CONFIGURAÇÕES ====================
BOT_TOKEN = "8477706439:AAF1ibc5aI95nM3r2BB6XZpW84GpepYJgiE"
STORE_NAME = "Suppys Store"
SUPPORT_LINK = "https://t.me/suportesuppys7"
GROUP_LINK = "https://t.me/+laIYEeIQuuc1ZWEx"
GROUP_ID = -1003819017548

# Nome da foto
FOTO_START = "foto_start.png"

# Credenciais do Mercado Pago
MERCADOPAGO_ACCESS_TOKEN = "APP_USR-8313019935361645-040523-f5273bbb40e6f8b1cfa385cbb7716aa5-800117337"

# Banco de dados
DB_PATH = 'suppys_store.db'

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Cache para usuários verificados
verified_cache = {}

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
                 total_spent REAL DEFAULT 0)''')
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
                 status TEXT,
                 created_at TEXT)''')
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

def save_pending_payment(user_id, amount, payment_id, qr_code):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO pending_payments (user_id, amount, payment_id, qr_code, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
              (user_id, amount, str(payment_id), qr_code, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def add_transaction(user_id, type_, amount, status, payment_id=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO transactions (user_id, type, amount, status, date, payment_id) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, type_, amount, status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(payment_id)))
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
                "qr_code": data["point_of_interaction"]["transaction_data"]["qr_code"]
            }
        else:
            return {"success": False, "error": "Erro ao gerar PIX"}
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

# ==================== VERIFICAÇÃO DE GRUPO ====================

async def check_group(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """Verifica se o usuário está no grupo"""
    try:
        chat_member = await context.bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Erro ao verificar grupo: {e}")
        return True  # Se der erro, libera acesso

# ==================== COMANDOS DO BOT ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start"""
    user = update.effective_user
    user_id = user.id
    username = user.username or "sem_username"
    name = user.first_name
    
    # Verifica grupo (opcional)
    in_group = await check_group(context, user_id)
    
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
    
    # Cria usuário se não existir
    existing_user = get_user(user_id)
    if not existing_user:
        referred_by = None
        if context.args and context.args[0].isdigit():
            referred_by = int(context.args[0])
            if referred_by == user_id:
                referred_by = None
        create_user(user_id, username, name, referred_by)
        logger.info(f"Novo usuario: {user_id}")
    
    user_data = get_user(user_id)
    saldo = user_data[5] if user_data else 0
    
    # Texto da mensagem
    caption = (
        f"@{context.bot.username}\n"
        f"melhores gps só encontra na @{context.bot.username}\n\n"
        f"A VIDA NÃO É BOA PRA NINGUEM, ENTÃO DECIDI FICAR CONTIGO!\n\n"
        f"Olá, @{username}!\n\n"
        f"ID: {user_id}\n"
        f"Saldo: R$ {saldo:.2f}\n"
        f"Grupo: Clique aqui\n\n"
        f"Use o menu abaixo 👇"
    )
    
    # Menu
    keyboard = [
        [InlineKeyboardButton("🔍 Comprar por BIN", callback_data='comprar_bin')],
        [InlineKeyboardButton("🔥 Ofertas do Dia", callback_data='ofertas')],
        [InlineKeyboardButton("💰 Saldo", callback_data='saldo')],
        [InlineKeyboardButton("👤 Perfil", callback_data='perfil')],
        [InlineKeyboardButton("📜 Histórico", callback_data='historico')],
        [InlineKeyboardButton("👥 Afiliado", callback_data='afiliado')],
        [InlineKeyboardButton("📞 Suporte", callback_data='suporte')]
    ]
    
    # Tenta enviar com foto
    try:
        if os.path.exists(FOTO_START):
            with open(FOTO_START, 'rb') as photo:
                await update.message.reply_photo(
                    photo=InputFile(photo),
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        else:
            await update.message.reply_text(caption, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Erro ao enviar foto: {e}")
        await update.message.reply_text(caption, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa cliques nos botões"""
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == 'comprar_bin':
        await comprar_bin_menu(query, context)
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
    elif data.startswith('pix_valor_'):
        valor = data.replace('pix_valor_', '')
        await gerar_pix(query, valor)
    elif data.startswith('verificar_'):
        payment_id = data.replace('verificar_', '')
        await verificar_pagamento(query, payment_id)

async def comprar_bin_menu(query, context):
    """Menu de compra por BIN"""
    user = get_user(query.from_user.id)
    saldo = user[5] if user else 0
    
    # Lista de BINs exemplo
    bins = [
        ("406655 | (1)", "406655"),
        ("406669 | (18)", "406669"),
        ("407843 | (19)", "407843"),
        ("415275 | (13)", "415275"),
        ("422061 | (14)", "422061"),
        ("546479 | (2)", "546479")
    ]
    
    keyboard = []
    for nome, bin_num in bins:
        keyboard.append([InlineKeyboardButton(nome, callback_data=f'select_bin_{bin_num}')])
    
    keyboard.append([InlineKeyboardButton("📥 Solicitar BIN", callback_data='solicitar_bin')])
    keyboard.append([InlineKeyboardButton("🏠 Menu", callback_data='voltar_menu')])
    
    await query.edit_message_text(
        f"🔍 **ESCOLHA SUA BIN**\n\n"
        f"ID {query.from_user.id} | R$ {saldo:.2f}\n\n"
        f"Página 1/1",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def ofertas_menu(query):
    """Menu de ofertas do dia"""
    text = (
        "🔥 **Ofertas Especiais!**\n\n"
        "- **GG 406669xxxxxx**\n"
        "  ~~R$ 8.00~~ → R$ 7.04 (-12%)\n\n"
        "- **GG 422061xxxxxx**\n"
        "  ~~R$ 5.00~~ → R$ 3.90 (-22%)\n\n"
        "- **GG 422061xxxxxx**\n"
        "  ~~R$ 5.50~~ → R$ 4.20 (-16%)\n\n"
        "- **GG 406669xxxxxx**\n"
        "  ~~R$ 8.00~~ → R$ 6.40 (-20%)\n\n"
        "- **GG 406669xxxxxx**\n"
        "  ~~R$ 8.50~~ → R$ 6.40 (-20%)\n\n"
        "1. GG 406669xxxxxx — R$ 7.04\n"
        "2. GG 422061xxxxxx — R$ 3.90\n"
        "3. GG 422061xxxxxx — R$ 4.20\n"
        "4. GG 406669xxxxxx — R$ 6.40\n"
        "5. GG 406669xxxxxx — R$ 6.40"
    )
    
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
        save_pending_payment(user_id, valor, resultado["payment_id"], resultado["qr_code"])
        
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

async def verificar_pagamento(query, payment_id):
    """Verifica pagamento"""
    await query.edit_message_text("⏱️ Verificando pagamento...")
    
    status = verificar_pagamento_mp(payment_id)
    
    if status == "approved":
        await query.edit_message_text(
            f"✅ **PAGAMENTO CONFIRMADO!**\n\n"
            f"💰 Saldo creditado na sua carteira!\n\n"
            f"Use o menu para ver seu saldo.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data='voltar_menu')]])
        )
    elif status == "pending":
        keyboard = [[InlineKeyboardButton("🔄 Verificar Novamente", callback_data=f'verificar_{payment_id}')]]
        await query.edit_message_text(
            f"⏱️ **Pagamento pendente**\n\n"
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
    
    total_spent = user[10] if len(user) > 10 else 0
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
        f"{nivel} · Próximo: {proximo}"
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
    keyboard = [
        [InlineKeyboardButton("📞 Falar com Suporte", url=SUPPORT_LINK)],
        [InlineKeyboardButton("🏠 Voltar ao Menu", callback_data='voltar_menu')]
    ]
    
    await query.edit_message_text(
        f"📞 **Suporte**\n\n"
        f"Descreva sua dúvida:\n\n"
        f"Clique no botão abaixo para falar com nosso suporte.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==================== MAIN ====================

def main():
    init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    print("=" * 50)
    print("✅ BOT SUPPS STORE ESTA ONLINE!")
    print(f"📌 Nome: {STORE_NAME}")
    print(f"👥 Grupo: {GROUP_LINK}")
    print(f"📞 Suporte: {SUPPORT_LINK}")
    print("=" * 50)
    
    app.run_polling()

if __name__ == "__main__":
    main()