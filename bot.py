import asyncio
import random
import time
import logging
import aiosqlite
import os
import sys
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage

# ========== ТОКЕН ==========
TOKEN = "8826297295:AAEnlz3hQHw6sfSEoDxo7Nfq8-_sY4E7E3Q"

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
def setup_logging():
    """Настройка системы логирования"""
    
    # Создаём папку для логов, если её нет
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Настройка корневого логгера
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(f'{log_dir}/casino_bot.log', encoding='utf-8'),
            logging.FileHandler(f'{log_dir}/casino_bot_errors.log', encoding='utf-8')
        ]
    )
    
    error_handler = logging.FileHandler(f'{log_dir}/casino_bot_errors.log', encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    
    logger = logging.getLogger('CasinoBot')
    logger.setLevel(logging.DEBUG)
    logger.addHandler(error_handler)
    
    return logger

logger = setup_logging()

# Секретные коды
SECRET_CODES = {
    "wzavoz": 100000,
    "shadowfiend": 100000,
    "casinogavno": 100000
}

# Хранилища
blackjack_games = {}
roulette_bets = {}
game_data = {}
pending_bet = {}

# ========== БАЗА ДАННЫХ ==========
async def init_db():
    logger.info("🔧 Инициализация базы данных...")
    try:
        async with aiosqlite.connect("casino.db") as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER DEFAULT 1000,
                    last_bonus_time INTEGER DEFAULT 0
                )
            """)
            await db.commit()
        logger.info("✅ База данных успешно инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка при инициализации БД: {e}")
        raise

async def get_balance(user_id: int) -> int:
    try:
        async with aiosqlite.connect("casino.db") as db:
            async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return row[0]
                else:
                    await db.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, 1000))
                    await db.commit()
                    return 1000
    except Exception as e:
        logger.error(f"❌ Ошибка получения баланса: {e}")
        return 1000

async def update_balance(user_id: int, delta: int) -> int:
    try:
        async with aiosqlite.connect("casino.db") as db:
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, user_id))
            await db.commit()
            async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0]
    except Exception as e:
        logger.error(f"❌ Ошибка обновления баланса: {e}")
        raise

async def get_last_bonus_time(user_id: int) -> int:
    try:
        async with aiosqlite.connect("casino.db") as db:
            async with db.execute("SELECT last_bonus_time FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0
    except Exception as e:
        logger.error(f"❌ Ошибка получения времени бонуса: {e}")
        return 0

async def update_bonus_time(user_id: int):
    current_time = int(time.time())
    try:
        async with aiosqlite.connect("casino.db") as db:
            await db.execute("UPDATE users SET last_bonus_time = ? WHERE user_id = ?", (current_time, user_id))
            await db.commit()
    except Exception as e:
        logger.error(f"❌ Ошибка обновления времени бонуса: {e}")

# ========== КЛАВИАТУРА СТАВОК ==========
def bet_percent_menu(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔟 10%", callback_data="bet_percent_10"),
         InlineKeyboardButton(text="2️⃣0️⃣ 20%", callback_data="bet_percent_20"),
         InlineKeyboardButton(text="5️⃣0️⃣ 50%", callback_data="bet_percent_50")],
        [InlineKeyboardButton(text="🔥 ALL-IN (100%)", callback_data="bet_percent_100"),
         InlineKeyboardButton(text="✏️ Своя ставка", callback_data="bet_custom")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="bet_cancel")]
    ])

# ========== BLACKJACK ==========
class BlackjackGame:
    def __init__(self, user_id, bet, user_name):
        self.user_id = user_id
        self.user_name = user_name
        self.bet = bet
        self.deck = self.create_deck()
        random.shuffle(self.deck)
        self.player_hand = []
        self.dealer_hand = []
        self.game_over = False

    def create_deck(self):
        cards = []
        for _ in range(6):
            for suit in ['♥', '♦', '♣', '♠']:
                for value in ['2','3','4','5','6','7','8','9','10','J','Q','K','A']:
                    cards.append((value, suit))
        return cards

    def card_value(self, card):
        value = card[0]
        if value in ['J', 'Q', 'K']:
            return 10
        elif value == 'A':
            return 11
        else:
            return int(value)

    def hand_value(self, hand):
        value = sum(self.card_value(card) for card in hand)
        aces = sum(1 for card in hand if card[0] == 'A')
        while value > 21 and aces > 0:
            value -= 10
            aces -= 1
        return value

    def card_to_str(self, card):
        return f"{card[0]}{card[1]}"

    def deal_initial(self):
        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]

    def player_hit(self):
        self.player_hand.append(self.deck.pop())
        if self.hand_value(self.player_hand) > 21:
            self.game_over = True
            return False
        return True

    def dealer_play(self):
        while self.hand_value(self.dealer_hand) < 17:
            self.dealer_hand.append(self.deck.pop())

    def determine_winner(self):
        player_val = self.hand_value(self.player_hand)
        dealer_val = self.hand_value(self.dealer_hand)
        if player_val > 21:
            return "lose"
        elif dealer_val > 21:
            return "win"
        elif player_val > dealer_val:
            return "win"
        elif player_val < dealer_val:
            return "lose"
        else:
            return "push"

    def get_result_message(self):
        dealer_cards = " ".join([self.card_to_str(c) for c in self.dealer_hand])
        player_cards = " ".join([self.card_to_str(c) for c in self.player_hand])
        result = self.determine_winner()
        if result == "win":
            win_amount = self.bet * 2
            return (f"🃏 **BLACKJACK**\n\n👤 Твои карты: {player_cards} (очков: {self.hand_value(self.player_hand)})\n🤖 Карты дилера: {dealer_cards} (очков: {self.hand_value(self.dealer_hand)})\n\n✅ **Ты выиграл!** +{win_amount} монет"), win_amount
        elif result == "lose":
            return (f"🃏 **BLACKJACK**\n\n👤 Твои карты: {player_cards} (очков: {self.hand_value(self.player_hand)})\n🤖 Карты дилера: {dealer_cards} (очков: {self.hand_value(self.dealer_hand)})\n\n❌ **Ты проиграл!** -{self.bet} монет"), -self.bet
        else:
            return (f"🃏 **BLACKJACK**\n\n👤 Твои карты: {player_cards} (очков: {self.hand_value(self.player_hand)})\n🤖 Карты дилера: {dealer_cards} (очков: {self.hand_value(self.dealer_hand)})\n\n🔄 **Ничья!** Ставка возвращена."), 0

# ========== РУЛЕТКА ==========
class RouletteGame:
    @staticmethod
    def spin():
        return random.randint(0, 36)
    
    @staticmethod
    def get_color(number):
        if number == 0:
            return "зелёное (0)"
        reds = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
        return "красное" if number in reds else "чёрное"
    
    @staticmethod
    def check_win(bet_type, bet_value, result):
        num = result
        if bet_type == "number":
            return bet_value == num
        elif bet_type == "color":
            color = RouletteGame.get_color(num)
            return color == bet_value
        elif bet_type == "parity":
            if num == 0:
                return False
            return (num % 2 == 0) if bet_value == "even" else (num % 2 == 1)
        elif bet_type == "dozen":
            if num == 0:
                return False
            if bet_value == 1:
                return 1 <= num <= 12
            elif bet_value == 2:
                return 13 <= num <= 24
            else:
                return 25 <= num <= 36
        return False

# ========== КЛАВИАТУРЫ МЕНЮ ==========
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎡 РУЛЕТКА", callback_data="game_roulette")],
        [InlineKeyboardButton(text="🃏 21 (Блэкджек)", callback_data="game_blackjack")],
        [InlineKeyboardButton(text="🎲 Кости (чёт/нечет)", callback_data="game_dice")],
        [InlineKeyboardButton(text="🪙 Орёл/Решка", callback_data="game_coin")],
        [InlineKeyboardButton(text="🎰 Слоты (x5/x10)", callback_data="game_slots")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="💵 +1000$ (раз в 5 мин)", callback_data="free_money")],
        [InlineKeyboardButton(text="🔐 Ввести секретный код", callback_data="secret_code")]
    ])

def roulette_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Красное (x2)", callback_data="roulette_color_red"),
         InlineKeyboardButton(text="⚫ Чёрное (x2)", callback_data="roulette_color_black"),
         InlineKeyboardButton(text="🟢 Зелёное (0) (x100)", callback_data="roulette_color_green")],
        [InlineKeyboardButton(text="📈 Чёт (x2)", callback_data="roulette_parity_even"),
         InlineKeyboardButton(text="📉 Нечёт (x2)", callback_data="roulette_parity_odd")],
        [InlineKeyboardButton(text="1️⃣ 1-12 (x3)", callback_data="roulette_dozen_1"),
         InlineKeyboardButton(text="2️⃣ 13-24 (x3)", callback_data="roulette_dozen_2"),
         InlineKeyboardButton(text="3️⃣ 25-36 (x3)", callback_data="roulette_dozen_3")],
        [InlineKeyboardButton(text="🎯 Число (x36)", callback_data="roulette_number")],
        [InlineKeyboardButton(text="◀ Назад в меню", callback_data="back_to_menu")]
    ])

def blackjack_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🃏 Взять карту", callback_data="bj_hit")],
        [InlineKeyboardButton(text="✋ Остановиться", callback_data="bj_stand")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="bj_cancel")]
    ])

def coin_choice_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪙 ОРЁЛ", callback_data="coin_choice_eagle"),
         InlineKeyboardButton(text="🪙 РЕШКА", callback_data="coin_choice_tails")]
    ])

def dice_choice_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 ЧЁТ (x2)", callback_data="dice_choice_even"),
         InlineKeyboardButton(text="🎲 НЕЧЁТ (x2)", callback_data="dice_choice_odd")]
    ])

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    username = f"@{message.from_user.username}" if message.from_user.username else "нет username"
    logger.info(f"👤 НОВЫЙ ПОЛЬЗОВАТЕЛЬ: {user_name} | {username} | ID: {user_id}")
    await get_balance(user_id)
    await message.answer(
        f"🍀 Добро пожаловать в КАЗИНО, {message.from_user.full_name}!\n"
        f"🎲 Баланс: {await get_balance(message.from_user.id)} монет\n\n"
        f"🎮 Игры: Рулетка | Блэкджек | Кости | Орёл/Решка | Слоты\n"
        f"💵 +1000 монет каждые 5 минут\n"
        f"🔐 Секретные коды дают +100000 монет\n"
        f"🟢 В рулетке появилась ставка на ЗЕЛЁНОЕ (0) x100!\n\n"
        f"Выбери игру:",
        reply_markup=main_menu()
    )

@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    user_name = callback.from_user.full_name
    logger.debug(f"🏠 {user_name} вернулся в главное меню")
    await callback.message.edit_text("🏠 Главное меню:", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "balance")
async def show_balance(callback: CallbackQuery):
    user_name = callback.from_user.full_name
    bal = await get_balance(callback.from_user.id)
    logger.info(f"💰 {user_name} | Баланс: {bal} монет")
    await callback.answer(f"💰 Баланс: {bal} монет", show_alert=True)

@dp.callback_query(lambda c: c.data == "free_money")
async def free_money(callback: CallbackQuery):
    user_name = callback.from_user.full_name
    user_id = callback.from_user.id
    last_time = await get_last_bonus_time(user_id)
    now = int(time.time())
    if now - last_time < 300:
        remaining = 300 - (now - last_time)
        logger.debug(f"⏳ {user_name} | Бонус ещё не доступен, осталось {remaining} сек")
        await callback.answer(f"⏳ Подожди {remaining//60} мин {remaining%60} сек", show_alert=True)
        return
    await update_bonus_time(user_id)
    new_bal = await update_balance(user_id, 1000)
    logger.info(f"💵 {user_name} | ПОЛУЧИЛ БОНУС: +1000 монет | Новый баланс: {new_bal}")
    await callback.answer("💵 +1000 монет!", show_alert=True)
    await callback.message.edit_text(f"✅ +1000 монет!\n💰 Новый баланс: {new_bal}", reply_markup=main_menu())

@dp.callback_query(lambda c: c.data == "secret_code")
async def secret_code_prompt(callback: CallbackQuery):
    user_name = callback.from_user.full_name
    logger.info(f"🔐 {user_name} запросил ввод секретного кода")
    await callback.message.answer("🔐 **Введи секретный код:**\n\n(Коды можно использовать без ограничений)")
    await callback.answer()
    game_data[callback.from_user.id] = {"game": "secret_code"}

# ----- ОБРАБОТКА СТАВОК -----
@dp.callback_query(lambda c: c.data.startswith("bet_"))
async def handle_bet_selection(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_name = callback.from_user.full_name
    data = callback.data
    
    if user_id not in pending_bet:
        logger.warning(f"⚠️ {user_name} | Попытка сделать ставку без активной игры")
        await callback.answer("Ошибка! Начни игру заново.", show_alert=True)
        return
    
    balance = await get_balance(user_id)
    bet_info = pending_bet[user_id]
    
    if data == "bet_cancel":
        logger.info(f"❌ {user_name} | Ставка ОТМЕНЕНА")
        del pending_bet[user_id]
        await callback.message.edit_text("❌ Ставка отменена.", reply_markup=main_menu())
        await callback.answer()
        return
    
    elif data == "bet_custom":
        logger.debug(f"✏️ {user_name} | Выбрал ввод своей ставки")
        await callback.message.answer("✏️ Введи сумму ставки (число):")
        bet_info["awaiting_custom"] = True
        pending_bet[user_id] = bet_info
        await callback.answer()
        return
    
    percent = int(data.split("_")[-1])
    if percent == 100:
        bet_amount = balance
        logger.debug(f"🔥 {user_name} | ALL-IN ставка: {bet_amount} монет")
    else:
        bet_amount = int(balance * percent / 100)
        logger.debug(f"📊 {user_name} | {percent}% ставка: {bet_amount} монет")
    
    if bet_amount <= 0:
        logger.warning(f"⚠️ {user_name} | Недостаточно средств для ставки {bet_amount} (баланс: {balance})")
        await callback.message.answer("❌ Недостаточно средств для этой ставки!", reply_markup=main_menu())
        del pending_bet[user_id]
        await callback.answer()
        return
    
    del pending_bet[user_id]
    await execute_game(callback.message, user_id, bet_amount, bet_info)

async def execute_game(message: Message, user_id: int, bet: int, bet_info: dict):
    user_name = message.from_user.full_name if message.from_user else f"User_{user_id}"
    balance = await get_balance(user_id)
    if bet > balance:
        logger.warning(f"⚠️ {user_name} | Ставка {bet} > баланса {balance}")
        await message.answer(f"❌ Не хватает! У тебя {balance} монет.", reply_markup=main_menu())
        return
    
    game_type = bet_info["game_type"]
    player_choice = bet_info.get("choice")
    
    logger.info(f"🎮 {user_name} | НАЧАЛ ИГРУ: {game_type} | СТАВКА: {bet} монет")
    
    # ----- БЛЭКДЖЕК -----
    if game_type == "blackjack":
        game = BlackjackGame(user_id, bet, user_name)
        game.deal_initial()
        blackjack_games[user_id] = game
        await message.answer(
            f"🃏 **BLACKJACK**\n\n💰 Ставка: {bet} монет\n\n"
            f"👤 Твои карты: {' '.join([game.card_to_str(c) for c in game.player_hand])} (очков: {game.hand_value(game.player_hand)})\n"
            f"🤖 Карта дилера: {game.card_to_str(game.dealer_hand[0])} | ❓\n\n"
            f"Твой ход:",
            reply_markup=blackjack_buttons()
        )
        return
    
    # ----- ОРЁЛ/РЕШКА -----
    if game_type == "coin":
        result = random.choice(["Орёл", "Решка"])
        if player_choice == result:
            win_amount = bet * 2
            new_bal = await update_balance(user_id, win_amount)
            logger.info(f"🪙 {user_name} | ОРЁЛ/РЕШКА | СТАВКА: {bet} | ВЫИГРЫШ: +{win_amount} (x2) | Баланс: {new_bal}")
            await message.answer(
                f"🪙 **ОРЁЛ/РЕШКА**\n\n"
                f"💰 Ставка: {bet} монет\n"
                f"Твой выбор: {player_choice}\n"
                f"Выпало: {result}\n\n"
                f"✅ **Ты выиграл!** +{win_amount} монет\n"
                f"💰 Баланс: {new_bal}",
                reply_markup=main_menu()
            )
        else:
            new_bal = await update_balance(user_id, -bet)
            logger.info(f"🪙 {user_name} | ОРЁЛ/РЕШКА | СТАВКА: {bet} | ПРОИГРЫШ: -{bet} | Баланс: {new_bal}")
            await message.answer(
                f"🪙 **ОРЁЛ/РЕШКА**\n\n"
                f"💰 Ставка: {bet} монет\n"
                f"Твой выбор: {player_choice}\n"
                f"Выпало: {result}\n\n"
                f"❌ **Ты проиграл!** -{bet} монет\n"
                f"💰 Баланс: {new_bal}",
                reply_markup=main_menu()
            )
        return
    
    # ----- КОСТИ -----
    if game_type == "dice":
        dice = random.randint(1, 6)
        is_even = (dice % 2 == 0)
        choice_text = "ЧЁТ" if player_choice == "even" else "НЕЧЁТ"
        result_text = "чётное" if is_even else "нечётное"
        
        if (player_choice == "even" and is_even) or (player_choice == "odd" and not is_even):
            win_amount = bet * 2
            new_bal = await update_balance(user_id, win_amount)
            logger.info(f"🎲 {user_name} | КОСТИ | СТАВКА: {bet} | ВЫИГРЫШ: +{win_amount} (x2) | Выпало: {dice} ({result_text}) | Баланс: {new_bal}")
            await message.answer(
                f"🎲 **КОСТИ**\n\n"
                f"💰 Ставка: {bet} монет\n"
                f"Твой выбор: {choice_text}\n"
                f"Выпало: {dice} ({result_text})\n\n"
                f"✅ **Ты выиграл!** +{win_amount} монет (x2)\n"
                f"💰 Баланс: {new_bal}",
                reply_markup=main_menu()
            )
        else:
            new_bal = await update_balance(user_id, -bet)
            logger.info(f"🎲 {user_name} | КОСТИ | СТАВКА: {bet} | ПРОИГРЫШ: -{bet} | Выпало: {dice} ({result_text}) | Баланс: {new_bal}")
            await message.answer(
                f"🎲 **КОСТИ**\n\n"
                f"💰 Ставка: {bet} монет\n"
                f"Твой выбор: {choice_text}\n"
                f"Выпало: {dice} ({result_text})\n\n"
                f"❌ **Ты проиграл!** -{bet} монет\n"
                f"💰 Баланс: {new_bal}",
                reply_markup=main_menu()
            )
        return
    
    # ----- СЛОТЫ -----
    if game_type == "slots":
        emojis = ["🍒", "🍋", "🍊", "💎", "7️⃣"]
        reel1, reel2, reel3 = random.choice(emojis), random.choice(emojis), random.choice(emojis)
        result_line = f"{reel1} | {reel2} | {reel3}"
        
        if reel1 == reel2 == reel3:
            if reel1 == "7️⃣":
                win_amount = bet * 10
                new_bal = await update_balance(user_id, win_amount)
                logger.info(f"🎰 {user_name} | СЛОТЫ | СТАВКА: {bet} | ДЖЕКПОТ! +{win_amount} (x10) | {result_line} | Баланс: {new_bal}")
                await message.answer(
                    f"🎰 **СЛОТЫ**\n\n"
                    f"💰 Ставка: {bet} монет\n"
                    f"{result_line}\n"
                    f"✨ **ДЖЕКПОТ! ТРИ СЕМЁРКИ!** ✨\n"
                    f"✅ +{win_amount} монет (x10)\n"
                    f"💰 Баланс: {new_bal}",
                    reply_markup=main_menu()
                )
            else:
                win_amount = bet * 5
                new_bal = await update_balance(user_id, win_amount)
                logger.info(f"🎰 {user_name} | СЛОТЫ | СТАВКА: {bet} | ВЫИГРЫШ: +{win_amount} (x5) | {result_line} | Баланс: {new_bal}")
                await message.answer(
                    f"🎰 **СЛОТЫ**\n\n"
                    f"💰 Ставка: {bet} монет\n"
                    f"{result_line}\n"
                    f"✅ Три одинаковых! +{win_amount} монет (x5)\n"
                    f"💰 Баланс: {new_bal}",
                    reply_markup=main_menu()
                )
        else:
            new_bal = await update_balance(user_id, -bet)
            logger.info(f"🎰 {user_name} | СЛОТЫ | СТАВКА: {bet} | ПРОИГРЫШ: -{bet} | {result_line} | Баланс: {new_bal}")
            await message.answer(
                f"🎰 **СЛОТЫ**\n\n"
                f"💰 Ставка: {bet} монет\n"
                f"{result_line}\n"
                f"❌ Проигрыш! -{bet} монет\n"
                f"💰 Баланс: {new_bal}",
                reply_markup=main_menu()
            )
        return
    
    # ----- РУЛЕТКА -----
    if game_type == "roulette":
        roulette_type = bet_info["roulette_bet_type"]
        roulette_value = bet_info["roulette_bet_value"]
        multiplier = bet_info["roulette_multiplier"]
        
        result = RouletteGame.spin()
        win = RouletteGame.check_win(roulette_type, roulette_value, result)
        
        if win:
            win_amount = bet * multiplier
            new_bal = await update_balance(user_id, win_amount)
            logger.info(f"🎡 {user_name} | РУЛЕТКА | СТАВКА: {bet} на {roulette_value} | ВЫПАЛО: {result} | ВЫИГРЫШ: +{win_amount} (x{multiplier}) | Баланс: {new_bal}")
            await message.answer(
                f"🎡 **РУЛЕТКА**\n\n"
                f"💰 Ставка: {bet} монет\n"
                f"Твоя ставка: {roulette_value}\n"
                f"Выпало: {result} ({RouletteGame.get_color(result)})\n\n"
                f"✅ **ПОБЕДА!** +{win_amount} монет (x{multiplier})\n"
                f"💰 Баланс: {new_bal}",
                reply_markup=main_menu()
            )
        else:
            new_bal = await update_balance(user_id, -bet)
            logger.info(f"🎡 {user_name} | РУЛЕТКА | СТАВКА: {bet} на {roulette_value} | ВЫПАЛО: {result} | ПРОИГРЫШ: -{bet} | Баланс: {new_bal}")
            await message.answer(
                f"🎡 **РУЛЕТКА**\n\n"
                f"💰 Ставка: {bet} монет\n"
                f"Твоя ставка: {roulette_value}\n"
                f"Выпало: {result} ({RouletteGame.get_color(result)})\n\n"
                f"❌ **ПРОИГРЫШ** -{bet} монет\n"
                f"💰 Баланс: {new_bal}",
                reply_markup=main_menu()
            )
        return

# ----- ОБРАБОТЧИКИ ВЫБОРА ИГР -----
@dp.callback_query(lambda c: c.data == "game_blackjack")
async def game_blackjack(callback: CallbackQuery):
    user_name = callback.from_user.full_name
    user_id = callback.from_user.id
    logger.info(f"🃏 {user_name} | ВЫБРАЛ ИГРУ: Блэкджек")
    balance = await get_balance(user_id)
    pending_bet[user_id] = {"game_type": "blackjack"}
    await callback.message.answer(
        f"🃏 **БЛЭКДЖЕК (21)**\n\n"
        f"💰 Твой баланс: {balance} монет\n\n"
        f"Выбери размер ставки:",
        reply_markup=bet_percent_menu(user_id)
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "game_coin")
async def game_coin(callback: CallbackQuery):
    user_name = callback.from_user.full_name
    logger.info(f"🪙 {user_name} | ВЫБРАЛ ИГРУ: Орёл/Решка")
    await callback.message.answer(
        "🪙 **ОРЁЛ/РЕШКА**\n\nВыбери, на что ставишь:",
        reply_markup=coin_choice_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("coin_choice_"))
async def coin_choice(callback: CallbackQuery):
    user_name = callback.from_user.full_name
    user_id = callback.from_user.id
    choice = "Орёл" if callback.data == "coin_choice_eagle" else "Решка"
    logger.debug(f"🪙 {user_name} | Выбрал: {choice}")
    balance = await get_balance(user_id)
    
    pending_bet[user_id] = {"game_type": "coin", "choice": choice}
    await callback.message.answer(
        f"🪙 Ты выбрал **{choice}**\n\n"
        f"💰 Твой баланс: {balance} монет\n\n"
        f"Выбери размер ставки:",
        reply_markup=bet_percent_menu(user_id)
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "game_dice")
async def game_dice(callback: CallbackQuery):
    user_name = callback.from_user.full_name
    logger.info(f"🎲 {user_name} | ВЫБРАЛ ИГРУ: Кости")
    await callback.message.answer(
        "🎲 **КОСТИ**\n\nВыбери, на что ставишь:",
        reply_markup=dice_choice_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("dice_choice_"))
async def dice_choice(callback: CallbackQuery):
    user_name = callback.from_user.full_name
    user_id = callback.from_user.id
    choice = "even" if callback.data == "dice_choice_even" else "odd"
    choice_text = "ЧЁТ" if choice == "even" else "НЕЧЁТ"
    logger.debug(f"🎲 {user_name} | Выбрал: {choice_text}")
    balance = await get_balance(user_id)
    
    pending_bet[user_id] = {"game_type": "dice", "choice": choice}
    await callback.message.answer(
        f"🎲 Ты выбрал **{choice_text}** (x2)\n\n"
        f"💰 Твой баланс: {balance} монет\n\n"
        f"Выбери размер ставки:",
        reply_markup=bet_percent_menu(user_id)
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "game_slots")
async def game_slots(callback: CallbackQuery):
    user_name = callback.from_user.full_name
    user_id = callback.from_user.id
    logger.info(f"🎰 {user_name} | ВЫБРАЛ ИГРУ: Слоты")
    balance = await get_balance(user_id)
    pending_bet[user_id] = {"game_type": "slots"}
    await callback.message.answer(
        f"🎰 **СЛОТЫ**\n\n"
        f"💰 Твой баланс: {balance} монет\n\n"
        f"Выбери размер ставки:",
        reply_markup=bet_percent_menu(user_id)
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "game_roulette")
async def start_roulette(callback: CallbackQuery):
    user_name = callback.from_user.full_name
    logger.info(f"🎡 {user_name} | ВЫБРАЛ ИГРУ: Рулетка")
    await callback.message.edit_text("🎡 **РУЛЕТКА**\n\nВыбери тип ставки:", reply_markup=roulette_menu())
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("roulette_") and c.data != "game_roulette")
async def roulette_bet_type(callback: CallbackQuery):
    user_name = callback.from_user.full_name
    user_id = callback.from_user.id
    data = callback.data
    
    if data == "roulette_number":
        logger.debug(f"🎯 {user_name} | Выбрал ставку на число")
        await callback.message.answer("🎯 Введи число от 0 до 36:")
        roulette_bets[user_id] = {"type": "number", "awaiting": True}
        await callback.answer()
        return
    
    if data == "roulette_color_green":
        bet_type, bet_value, multiplier = "color", "зелёное (0)", 100
    elif data.startswith("roulette_color_"):
        bet_type, bet_value, multiplier = "color", ("красное" if "red" in data else "чёрное"), 2
    elif data.startswith("roulette_parity_"):
        bet_type, bet_value, multiplier = "parity", ("even" if "even" in data else "odd"), 2
    elif data.startswith("roulette_dozen_"):
        bet_type, bet_value, multiplier = "dozen", int(data.split("_")[-1]), 3
    else:
        logger.warning(f"⚠️ {user_name} | Неизвестный тип ставки: {data}")
        return
    
    logger.debug(f"🎡 {user_name} | Выбрал ставку: {bet_value} (x{multiplier})")
    balance = await get_balance(user_id)
    pending_bet[user_id] = {
        "game_type": "roulette",
        "roulette_bet_type": bet_type,
        "roulette_bet_value": bet_value,
        "roulette_multiplier": multiplier
    }
    await callback.message.answer(
        f"🎡 Ставка: {bet_value}\n💰 Множитель: x{multiplier}\n\n"
        f"💰 Твой баланс: {balance} монет\n\n"
        f"Выбери размер ставки:",
        reply_markup=bet_percent_menu(user_id)
    )
    await callback.answer()

# ----- БЛЭКДЖЕК ДЕЙСТВИЯ -----
@dp.callback_query(lambda c: c.data.startswith("bj_"))
async def blackjack_action(callback: CallbackQuery):
    user_name = callback.from_user.full_name
    user_id = callback.from_user.id
    if user_id not in blackjack_games:
        logger.warning(f"⚠️ {user_name} | Попытка действия без активной игры")
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    game = blackjack_games[user_id]
    
    if callback.data == "bj_hit":
        if game.player_hit():
            player_cards = " ".join([game.card_to_str(c) for c in game.player_hand])
            await callback.message.edit_text(
                f"🃏 **BLACKJACK**\n\n💰 Ставка: {game.bet} монет\n\n"
                f"👤 Твои карты: {player_cards} (очков: {game.hand_value(game.player_hand)})\n"
                f"🤖 Карта дилера: {game.card_to_str(game.dealer_hand[0])} | ❓\n\n"
                f"Твой ход:",
                reply_markup=blackjack_buttons()
            )
        else:
            result_msg, delta = game.get_result_message()
            new_bal = await update_balance(user_id, delta)
            if delta > 0:
                logger.info(f"🃏 {user_name} | БЛЭКДЖЕК | СТАВКА: {game.bet} | ВЫИГРЫШ: +{delta} | Баланс: {new_bal}")
            elif delta < 0:
                logger.info(f"🃏 {user_name} | БЛЭКДЖЕК | СТАВКА: {game.bet} | ПРОИГРЫШ: {delta} | Баланс: {new_bal}")
            else:
                logger.info(f"🃏 {user_name} | БЛЭКДЖЕК | СТАВКА: {game.bet} | НИЧЬЯ | Баланс: {new_bal}")
            del blackjack_games[user_id]
            await callback.message.edit_text(result_msg, reply_markup=main_menu())
    elif callback.data == "bj_stand":
        game.dealer_play()
        result_msg, delta = game.get_result_message()
        new_bal = await update_balance(user_id, delta)
        if delta > 0:
            logger.info(f"🃏 {user_name} | БЛЭКДЖЕК | СТАВКА: {game.bet} | ВЫИГРЫШ: +{delta} | Баланс: {new_bal}")
        elif delta < 0:
            logger.info(f"🃏 {user_name} | БЛЭКДЖЕК | СТАВКА: {game.bet} | ПРОИГРЫШ: {delta} | Баланс: {new_bal}")
        else:
            logger.info(f"🃏 {user_name} | БЛЭКДЖЕК | СТАВКА: {game.bet} | НИЧЬЯ | Баланс: {new_bal}")
        del blackjack_games[user_id]
        await callback.message.edit_text(result_msg, reply_markup=main_menu())
    elif callback.data == "bj_cancel":
        logger.info(f"❌ {user_name} | ОТМЕНИЛ игру в Блэкджек")
        await update_balance(user_id, game.bet)
        del blackjack_games[user_id]
        await callback.message.edit_text("❌ Игра отменена.", reply_markup=main_menu())
    await callback.answer()

# ========== ГЛАВНЫЙ ОБРАБОТЧИК СООБЩЕНИЙ ==========
@dp.message()
async def handle_all_messages(message: Message):
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    text = message.text.strip().lower()
    
    # Секретный код
    if user_id in game_data and game_data[user_id].get("game") == "secret_code":
        logger.info(f"🔐 {user_name} | Ввёл секретный код: {text}")
        if text in SECRET_CODES:
            reward = SECRET_CODES[text]
            new_bal = await update_balance(user_id, reward)
            logger.info(f"✅ {user_name} | СЕКРЕТНЫЙ КОД АКТИВИРОВАН! +{reward} монет | Баланс: {new_bal}")
            await message.answer(
                f"🔐 **Код активирован!**\n\n"
                f"✅ Ты получил {reward} монет!\n"
                f"💰 Новый баланс: {new_bal}\n\n"
                f"💡 Этот код можно использовать снова в любое время.",
                reply_markup=main_menu()
            )
        else:
            logger.warning(f"⚠️ {user_name} | Неверный секретный код: {text}")
            await message.answer(
                f"❌ **Неверный код!**\n\n"
                f"Попробуй другой код или вернись в меню.",
                reply_markup=main_menu()
            )
        del game_data[user_id]
        return
    
    # Кастомная ставка
    if user_id in pending_bet and pending_bet[user_id].get("awaiting_custom"):
        try:
            bet = int(text)
            if bet <= 0:
                logger.warning(f"⚠️ {user_name} | Недопустимая ставка: {bet}")
                await message.answer("❌ Ставка должна быть больше 0!", reply_markup=main_menu())
                del pending_bet[user_id]
                return
            logger.info(f"💰 {user_name} | Кастомная ставка: {bet} монет")
        except:
            logger.warning(f"⚠️ {user_name} | Ввёл не число: {text}")
            await message.answer("❌ Введи ЧИСЛО!", reply_markup=main_menu())
            del pending_bet[user_id]
            return
        
        bet_info = pending_bet[user_id]
        del pending_bet[user_id]
        await execute_game(message, user_id, bet, bet_info)
        return
    
    # Рулетка: ожидание числа
    if user_id in roulette_bets and roulette_bets[user_id].get("type") == "number" and not roulette_bets[user_id].get("number_value"):
        try:
            num = int(text)
            if 0 <= num <= 36:
                logger.info(f"🎯 {user_name} | Выбрал число {num} в рулетке")
                roulette_bets[user_id]["number_value"] = num
                balance = await get_balance(user_id)
                pending_bet[user_id] = {
                    "game_type": "roulette",
                    "roulette_bet_type": "number",
                    "roulette_bet_value": num,
                    "roulette_multiplier": 36
                }
                await message.answer(
                    f"🎯 Число {num}\n💰 Множитель: x36\n\n"
                    f"💰 Твой баланс: {balance} монет\n\n"
                    f"Выбери размер ставки:",
                    reply_markup=bet_percent_menu(user_id)
                )
                del roulette_bets[user_id]
            else:
                logger.warning(f"⚠️ {user_name} | Число вне диапазона: {num}")
                await message.answer("❌ Число от 0 до 36!")
        except:
            logger.warning(f"⚠️ {user_name} | Ввёл не число: {text}")
            await message.answer("❌ Введи ЧИСЛО!")
        return

# ========== ЗАПУСК ==========
async def main():
    logger.info("=" * 60)
    logger.info("🚀 ЗАПУСК КАЗИНО-БОТА")
    logger.info(f"📅 Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    
    try:
        await init_db()
        logger.info("✅ База данных инициализирована")
        
        print("\n✅ КАЗИНО-БОТ ЗАПУЩЕН!")
        print("🎡 В рулетке добавлена ставка на ЗЕЛЁНОЕ (0) x100!")
        print("🎮 Панель ставок: 10%, 20%, 50%, ALL-IN, Своя ставка")
        print("🔐 Секретные коды: wzavoz, shadowfiend, casinogavno (+100000)")
        print(f"📝 Логи пишутся в папку: logs/")
        print(f"   - logs/casino_bot.log (все события)")
        print(f"   - logs/casino_bot_errors.log (только ошибки)\n")
        
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"💥 Критическая ошибка при запуске: {e}")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен пользователем")
        print("\n👋 Бот остановлен")
    except Exception as e:
        logger.critical(f"💥 Необработанная ошибка: {e}")
        print(f"\n❌ Критическая ошибка: {e}")
