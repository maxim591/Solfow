import base64
import hashlib
import os
import re

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from solders.keypair import Keypair
from solders.pubkey import Pubkey

load_dotenv()

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:8000/auth/callback")

if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
    raise RuntimeError("DISCORD_CLIENT_ID / DISCORD_CLIENT_SECRET fehlen in .env")

SOL_ADDR_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
LAMPORTS = 1_000_000_000
MIN_LAMPORTS = 5000
PAYMENT_TTL_MIN = 60
RPC_URL = os.getenv("SOLANA_RPC", "https://api.devnet.solana.com")
SUCCESS_REDIRECT = os.getenv("SUCCESS_REDIRECT_URL", "")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

_raw_key = os.getenv("DB_ENC_KEY")
if not _raw_key:
    raise RuntimeError("DB_ENC_KEY fehlt in .env")
_key = base64.urlsafe_b64encode(hashlib.sha256(_raw_key.encode()).digest())
fernet = Fernet(_key)

_main_pub = os.getenv("MAIN_WALLET_PUBLIC")
if not _main_pub:
    raise RuntimeError("MAIN_WALLET_PUBLIC fehlt in .env")
main_pubkey = Pubkey.from_string(_main_pub)

_main_secret = os.getenv("MAIN_WALLET_SECRET")
if not _main_secret:
    raise RuntimeError("MAIN_WALLET_SECRET fehlt in .env")
main_keypair = Keypair.from_base58_string(_main_secret)
if main_keypair.pubkey() != main_pubkey:
    raise RuntimeError("MAIN_WALLET_PUBLIC passt nicht zu MAIN_WALLET_SECRET")

BASE_FEE_PER_SIGNATURE = 5_000
TOTAL_NETWORK_FEE = BASE_FEE_PER_SIGNATURE * 2