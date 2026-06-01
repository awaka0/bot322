import asyncio
import random
import time
import logging
import aiosqlite
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

# ========== ЗАГРУЗКА ПЕРЕМЕННЫХ ИЗ .env ==========
load_dotenv()

# Получаем токен из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
LOG_CHAT_ID = os.getenv("LOG_CHAT_ID", None)

# Проверка наличия токена
if not BOT_TOKEN:
    print("❌ ОШИБКА: Токен не найден в файле .env!")
    print("Создайте файл .env и добавьте в него строку: BOT_TOKEN=ваш_токен")
    exit(1)

print(f"✅ Токен загружен из .env, длина: {len(BOT_TOKEN)} символов")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
def setup_logging():
    logger = logging.getLogger('CasinoBot')
    logger.setLevel(logging.DEBUG)
    
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    file_handler = logging.FileHandler('casino_bot.log', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    error_handler = logging.FileHandler('casino_bot_errors.log', encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
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
        logger.error(f"❌ Ошибка получения баланса для user_id={user_id}: {e}")
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
        logger.error(f"❌ Ошибка обновления баланса для user_id={user_id}: {e}")
        raise

async def get_last_bonus_time(user_id: int) -> int:
    try:
        async with aiosqlite.connect("casino.db") as db:
            async with db.execute("SELECT last_bonus_time FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0
    except Exception as e:
        logger.error(f"❌ Ошибка получения времени бонуса для user_id={user_id}: {e}")
        return 0

async def update_bonus_time(user_id: int):
    current_time = int(time.time())
    try:
        async with aiosqlite.connect("casino.db") as db:
            await db.execute("UPDATE users SET last_bonus_time = ? WHERE user_id = ?", (current_time, user_id))
            await db.commit()
    except Exception as e:
        logger.error(f"❌ Ошибка обновления времени бонуса для user_id={user_id}: {e}")

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
        logger.debug(f"🃏 Создана игра Блэкджек: {user_name}, ставка={bet}")

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
        logger.debug(f"🎴 Начальные карты {self.user_name}: игрок={[self.card_to_str(c) for c in self.player_hand]}, дилер={[self.card_to_str(c) for c in self.dealer_hand]}")

    def player_hit(self):
        self.player_hand.append(self.deck.pop())
        if self.hand_value(self.player_hand) > 21:
            self.game_over = True
            logger.info(f"❌ Перебор у {self.user_name} в Блэкджек, очки={self.hand_value(self.player_hand)}")
            return False
        logger.debug(f"🃏 {self.user_name} взял карту, очки={self.hand_value(self.player_hand)}")
        return True

    def dealer_play(self):
        logger.debug(f"🤖 Ход дилера для {self.user_name}")
        while self.hand_value(self.dealer_hand) < 17:
            self.dealer_hand.append(self.deck.pop())
        logger.info(f"🤖 Дилер завершил ход для {self.user_name}, очки={self.hand_value(self.dealer_hand)}")

    def determine_winner(self):
        player_val = self.hand_value(self.player_hand)
        dealer_val = self.hand_value(self.dealer_hand)
        if player_val > 21:
            result = "lose"
        elif dealer_val > 21:
            result = "win"
        elif player_val > dealer_val:
            result = "win"
        elif player_val < dealer_val:
            result = "lose"
        else:
            result = "push"
        logger.info(f"🏆 Результат Блэкджек для {self.user_name}: игрок={player_val}, дилер={dealer_val}, результат={result}")
        return result

    def get_result_message(self):
        dealer_cards = " ".join([self.card_to_str(c) for c in self.dealer_hand])
        player_cards = " ".join([self.card_to_str(c) for c in self.player_hand])
        result = self.determine_winner()
        if result == "win":
            win_amount = self.bet * 2
            logger.info(f"✅ Победа в Блэкджек: {self.user_name}, выигрыш={win_amount}")
            return (f"🃏 **BLACKJACK**\n\n👤 Твои карты: {player_cards} (очков: {self.hand_value(self.player_hand)})\n🤖 Карты дилера: {dealer_cards} (очков: {self.hand_value(self.dealer_hand)})\n\n✅ **Ты выиграл!** +{win_amount} монет"), win_amount
        elif result == "lose":
            logger.info(f"❌ Поражение в Блэкджек: {self.user_name}, проигрыш={self.bet}")
            return (f"🃏 **BLACKJACK**\n\n👤 Твои карты: {player_cards} (очков: {self.hand_value(self.player_hand)})\n🤖 Карты дилера: {dealer_cards} (очков: {self.hand_value(self.dealer_hand)})\n\n❌ **Ты проиграл!** -{self.bet} монет"), -self.bet
        else:
            logger.info(f"🤝 Ничья в Блэкджек: {self.user_name}, ставка возвращена")
            return (f"🃏 **BLACKJACK**\n\n👤 Твои карты: {player_cards} (очков: {self.hand_value(self.player_hand)})\n🤖 Карты дилера: {dealer_cards} (очков: {self.hand_value(self.dealer_hand)})\n\n🔄 **Ничья!** Ставка возвращена."), 0

# ========== РУЛЕТКА ==========
class RouletteGame:
    @staticmethod
    def spin():
        result = random.randint(0, 36)
        logger.debug(f"🎡 Спин рулетки: результат={result}")
        return result
    
    @staticmethod
    def get_color(number):
        if number == 0:
            return "зелёное (0)"
        reds = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
        color = "красное" if number in reds else "чёрное"
        return color
    
    @staticmethod
    def check_win(bet_type, bet_value, result):
        if bet_type == "number":
            win = bet_value == result
        elif bet_type == "color":
            color = RouletteGame.get_color(result)
            win = color == bet_value
        elif bet_type == "parity":
            if result == 0:
                win = False
            else:
                win = (result % 2 == 0) if bet_value == "even" else (result % 2 == 1)
        elif bet_type == "dozen":
            if result == 0:
                win = False
            else:
                if bet_value == 1:
                    win = 1 <= result <= 12
                elif bet_value == 2:
                    win = 13 <= result <= 24
                else:
                    win = 25 <= result <= 36
        else:
            win = False
        return win

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
    logger.info(f"👤 {user_name} запустил бота")
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
    logger.info(f"💰 {user_name} проверил баланс: {bal}")
    await callback.answer(f"💰 Баланс: {bal} монет", show_alert=True)

@dp.callback_query(lambda c: c.data == "free_money")
async def free_money(callback: CallbackQuery):
    user_name = callback.from_user.full_name
    user_id = callback.from_user.id
    last_time = await get_last_bonus_time(user_id)
    now = int(time.time())
    if now - last_time < 300:
        remaining = 300 - (now - last_time)
        logger.debug(f"⏳ {user_name} пытался получить бонус, нужно подождать {remaining} сек")
        await callback.answer(f"⏳ Подожди {remaining//60} мин {remaining%60} сек", show_alert=True)
        return
    await update_bonus_time(user_id)
    new_bal = await update_balance(user_id, 1000)
    logger.info(f"💵 {user_name} получил бонус +1000. Новый баланс: {new_bal}")
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
        logger.warning(f"⚠️ {user_name} пытался сделать ставку без активной игры")
        await callback.answer("Ошибка! Начни игру заново.", show_alert=True)
        return
    
    balance = await get_balance(user_id)
    bet_info = pending_bet[user_id]
    
    if data == "bet_cancel":
        logger.info(f"❌ {user_name} отменил ставку")
        del pending_bet[user_id]
        await callback.message.edit_text("❌ Ставка отменена.", reply_markup=main_menu())
        await callback.answer()
        return
    
    elif data == "bet_custom":
        logger.debug(f"✏️ {user_name} выбрал ввод своей ставки")
        await callback.message.answer("✏️ Введи сумму ставки (число):")
        bet_info["awaiting_custom"] = True
        pending_bet[user_id] = bet_info
        await callback.answer()
        return
    
    percent = int(data.split("_")[-1])
    if percent == 100:
        bet_amount = balance
        logger.debug(f"🔥 {user_name} выбрал ALL-IN ставку: {bet_amount}")
    else:
        bet_amount = int(balance * percent / 100)
        logger.debug(f"📊 {user_name} выбрал {percent}% ставку: {bet_amount}")
    
    if bet_amount <= 0:
        logger.warning(f"⚠️ {user_name} пытался сделать ставку {bet_amount} при балансе {balance}")
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
        logger.warning(f"⚠️ {user_name} попытался сделать ставку {bet} при балансе {balance}")
        await message.answer(f"❌ Не хватает! У тебя {balance} монет.", reply_markup=main_menu())
        return
    
    game_type = bet_info["game_type"]
    player_choice = bet_info.get("choice")
    
    logger.info(f"🎮 {user_name} начал игру: {game_type}, ставка={bet}")
    
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
            logger.info(f"✅ Победа в Орёл/Решка: {user_name}, выигрыш={win_amount}")
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
            logger.info(f"❌ Поражение в Орёл/Решка: {user_name}, проигрыш={bet}")
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
            logger.info(f"✅ Победа в Кости: {user_name}, выигрыш={win_amount}")
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
            logger.info(f"❌ Поражение в Кости: {user_name}, проигрыш={bet}")
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
                logger.info(f"✨ ДЖЕКПОТ в Слотах: {user_name}, выигрыш={win_amount}")
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
                logger.info(f"✅ Победа в Слотах: {user_name}, выигрыш={win_amount}")
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
            logger.info(f"❌ Поражение в Слотах: {user_name}, проигрыш={bet}")
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
            logger.info(f"✅ Победа в Рулетке: {user_name}, выигрыш={win_amount}")
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
            logger.info(f"❌ Поражение в Рулетке: {user_name}, проигрыш={bet}")
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
    logger.info(f"🃏 {user_name} выбрал игру Блэкджек")
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
    logger.info(f"🪙 {user_name} выбрал игру Орёл/Решка")
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
    logger.debug(f"🪙 {user_name} выбрал {choice} в игре Орёл/Решка")
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
    logger.info(f"🎲 {user_name} выбрал игру Кости")
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
    logger.debug(f"🎲 {user_name} выбрал {choice_text} в игре Кости")
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
    logger.info(f"🎰 {user_name} выбрал игру Слоты")
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
    logger.info(f"🎡 {user_name} выбрал игру Рулетка")
    await callback.message.edit_text("🎡 **РУЛЕТКА**\n\nВыбери тип ставки:", reply_markup=roulette_menu())
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("roulette_") and c.data != "game_roulette")
async def roulette_bet_type(callback: CallbackQuery):
    user_name = callback.from_user.full_name
    user_id = callback.from_user.id
    data = callback.data
    
    if data == "roulette_number":
        logger.debug(f"🎯 {user_name} выбрал ставку на число в рулетке")
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
        logger.warning(f"⚠️ Неизвестный тип ставки в рулетке от {user_name}: {data}")
        return
    
    logger.debug(f"🎡 {user_name} выбрал ставку в рулетке: {bet_type}/{bet_value}")
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
        logger.warning(f"⚠️ {user_name} пытался совершить действие в Блэкджек, но игра не найдена")
        await callback.answer("Игра не найдена!", show_alert=True)
        return
    game = blackjack_games[user_id]
    logger.debug(f"🎴 Действие в Блэкджек от {user_name}: {callback.data}")
    
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
            await update_balance(user_id, delta)
            del blackjack_games[user_id]
            await callback.message.edit_text(result_msg, reply_markup=main_menu())
    elif callback.data == "bj_stand":
        game.dealer_play()
        result_msg, delta = game.get_result_message()
        await update_balance(user_id, delta)
        del blackjack_games[user_id]
        await callback.message.edit_text(result_msg, reply_markup=main_menu())
    elif callback.data == "bj_cancel":
        logger.info(f"❌ {user_name} отменил игру в Блэкджек")
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
        logger.info(f"🔐 {user_name} ввёл секретный код: {text}")
        if text in SECRET_CODES:
            reward = SECRET_CODES[text]
            new_bal = await update_balance(user_id, reward)
            logger.info(f"✅ Секретный код активирован: {user_name}, код={text}, награда={reward}")
            await message.answer(
                f"🔐 **Код активирован!**\n\n"
                f"✅ Ты получил {reward} монет!\n"
                f"💰 Новый баланс: {new_bal}\n\n"
                f"💡 Этот код можно использовать снова в любое время.",
                reply_markup=main_menu()
            )
        else:
            logger.warning(f"⚠️ {user_name} ввёл неверный секретный код: {text}")
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
                logger.warning(f"⚠️ {user_name} ввёл недопустимую ставку: {bet}")
                await message.answer("❌ Ставка должна быть больше 0!", reply_markup=main_menu())
                del pending_bet[user_id]
                return
            logger.info(f"💰 {user_name} ввёл кастомную ставку: {bet}")
        except:
            logger.warning(f"⚠️ {user_name} ввёл не число в ставке: {text}")
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
                logger.info(f"🎯 {user_name} выбрал число {num} в рулетке")
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
                logger.warning(f"⚠️ {user_name} ввёл число вне диапазона: {num}")
                await message.answer("❌ Число от 0 до 36!")
        except:
            logger.warning(f"⚠️ {user_name} ввёл не число для рулетки: {text}")
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
        logger.info("🎡 В рулетке добавлена ставка на ЗЕЛЁНОЕ (0) x100!")
        logger.info("🎮 Панель ставок: 10%, 20%, 50%, ALL-IN, Своя ставка")
        logger.info("🔐 Секретные коды: wzavoz, shadowfiend, casinogavno (+100000)")
        
        print("\n✅ КАЗИНО-БОТ ЗАПУЩЕН!")
        print("🎡 В рулетке добавлена ставка на ЗЕЛЁНОЕ (0) x100!")
        print("🎮 Панель ставок: 10%, 20%, 50%, ALL-IN, Своя ставка")
        print("🔐 Секретные коды: wzavoz, shadowfiend, casinogavno (+100000)")
        print(f"📝 Логи пишутся в файлы: casino_bot.log и casino_bot_errors.log\n")
        
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"💥 Критическая ошибка при запуске бота: {e}")
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
