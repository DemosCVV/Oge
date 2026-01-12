import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    token: str
    admin_id: int
    alt_pay_username: str

CONFIG = Config(
    token=os.getenv("BOT_TOKEN", "").strip(),
    admin_id=int(os.getenv("ADMIN_ID", "0")),
    alt_pay_username=os.getenv("ALT_PAY_USERNAME", "fepxu").strip().lstrip("@"),
)

if not CONFIG.token or CONFIG.admin_id == 0:
    raise RuntimeError("Заполните BOT_TOKEN и ADMIN_ID в .env")

# Каталог: slug -> name/price/link (ссылку бот выдаёт после подтверждения админом)
PRODUCTS = {
    "math": {"name": "Математика", "price": 499, "link": "https://t.me/your_private_channel_math"},
    "rus": {"name": "Русский язык", "price": 499, "link": "https://t.me/your_private_channel_rus"},
    "bio": {"name": "Биология", "price": 349, "link": "https://t.me/your_private_channel_bio"},
    "info": {"name": "Информатика", "price": 349, "link": "https://t.me/your_private_channel_info"},
    "hist": {"name": "История", "price": 349, "link": "https://t.me/your_private_channel_hist"},
    "soc": {"name": "Обществознание", "price": 349, "link": "https://t.me/your_private_channel_soc"},
    "chem": {"name": "Химия", "price": 349, "link": "https://t.me/your_private_channel_chem"},
    "phys": {"name": "Физика", "price": 349, "link": "https://t.me/your_private_channel_phys"},
}

# Антифлуд (сек)
RATE_LIMIT_SECONDS = 2

# Антифрод: максимум чеков от пользователя на одну заявку
MAX_RECEIPTS_PER_PURCHASE = 3
