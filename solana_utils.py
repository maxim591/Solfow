import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction
from solana.rpc.async_api import AsyncClient
from sqlalchemy import update

from config import (
    LAMPORTS, MIN_LAMPORTS, PAYMENT_TTL_MIN, TOTAL_NETWORK_FEE,
    fernet, main_pubkey,
)
from db import SessionLocal
from models import PaymentDB

# Reserve für die allerletzte Transaktion (Rest-Transfer): 1 Signatur Base Fee
FINAL_TX_FEE_RESERVE = 5_000

def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def calc_fee_lamports(amount_sol: float) -> int:
    rate = 0.12 if amount_sol < 1 else 0.085
    return int(round(amount_sol * rate * LAMPORTS))

def calc_network_fee() -> int:
    return TOTAL_NETWORK_FEE

async def _is_confirmed(client: AsyncClient, sig) -> bool:
    try:
        st_resp = await client.get_signature_statuses([sig], search_transaction_history=True)
        st = st_resp.value[0]
        if st and st.confirmation_status:
            cs = str(st.confirmation_status)
            if "confirmed" in cs or "finalized" in cs:
                return True
    except Exception as e:
        print(f"[CONF] get_signature_statuses Fehler: {e}")
    try:
        tx_resp = await client.get_transaction(sig, max_supported_transaction_version=0)
        if tx_resp.value is not None:
            return True
    except Exception as e:
        print(f"[CONF] get_transaction Fehler: {e}")
    return False

async def _send_sol_async(client: AsyncClient, sender: Keypair, to: Pubkey, lamports: int) -> Optional[str]:
    if lamports < MIN_LAMPORTS:
        print(f"[SEND] Betrag zu klein: {lamports} lamports")
        return None
    for attempt in range(3):
        try:
            print(f"[SEND] Versuch {attempt+1}: {lamports} lamports -> {to}")
            bh_resp = await client.get_latest_blockhash()
            bh = bh_resp.value.blockhash
            ix = transfer(TransferParams(from_pubkey=sender.pubkey(), to_pubkey=to, lamports=lamports))
            msg = MessageV0.try_compile(sender.pubkey(), [ix], [], bh)
            tx = VersionedTransaction(msg, [sender])
            sig_resp = await client.send_transaction(tx)
            sig = sig_resp.value
            print(f"[SEND] Signatur: {sig}")
            for i in range(60):
                if await _is_confirmed(client, sig):
                    print(f"[SEND] Bestätigt nach {i+1}s")
                    return str(sig)
                await asyncio.sleep(1)
            print(f"[SEND] Timeout nach 60s")
        except Exception as e:
            print(f"[SEND] Versuch {attempt+1} fehlgeschlagen: {e}")
            await asyncio.sleep(2)
    return None

async def _get_balance(client: AsyncClient, pubkey: Pubkey) -> int:
    for attempt in range(3):
        try:
            resp = await client.get_balance(pubkey)
            if hasattr(resp, "value"):
                bal = resp.value if isinstance(resp.value, int) and resp.value >= 0 else 0
            elif isinstance(resp, int):
                bal = resp if resp >= 0 else 0
            else:
                bal = 0
            print(f"[BAL] {pubkey} = {bal} lamports (Versuch {attempt+1})")
            if bal > 0:
                return bal
            await asyncio.sleep(2)
        except Exception as e:
            print(f"[BAL] Fehler (Versuch {attempt+1}): {e}")
            await asyncio.sleep(2)
    return 0

async def poll_payments(client: AsyncClient):
    while True:
        await asyncio.sleep(30)
        db = SessionLocal()
        try:
            now = _now()
            db.execute(
                update(PaymentDB)
                .where(PaymentDB.status == "pending")
                .where(PaymentDB.created_at < now - timedelta(minutes=PAYMENT_TTL_MIN))
                .values(status="expired", deposit_secret_enc="")
            )
            db.commit()

            pending = db.query(PaymentDB).filter(
                PaymentDB.status.in_(["pending", "fee_sent"]),
                (PaymentDB.lock_until == None) | (PaymentDB.lock_until < now),
            ).all()
            for rec in pending:
                rec.lock_until = now + timedelta(seconds=45)
            db.commit()

            for rec in pending:
                age_min = (now - rec.created_at).total_seconds() / 60
                if not rec.deposit_secret_enc:
                    continue

                deposit_pk = Pubkey.from_string(rec.deposit_address)
                bal = await _get_balance(client, deposit_pk)

                if bal < rec.total_lamports:
                    continue

                secret = fernet.decrypt(rec.deposit_secret_enc.encode()).decode()
                kp = Keypair.from_base58_string(secret)

                if not rec.fee_tx:
                    fee_sig = await _send_sol_async(client, kp, main_pubkey, rec.fee_lamports)
                    if not fee_sig:
                        continue
                    rec.fee_tx = fee_sig
                    rec.status = "fee_sent"
                    db.commit()

                recipient = Pubkey.from_string(rec.address)
                net_sig = await _send_sol_async(client, kp, recipient, rec.net_lamports)
                if not net_sig:
                    continue
                rec.net_tx = net_sig
                db.commit()

                # Restguthaben prüfen und an Main-Wallet senden
                remaining_bal = await _get_balance(client, deposit_pk)
                # Reserve für die letzte Transaktion abziehen (Base Fee)
                if remaining_bal > FINAL_TX_FEE_RESERVE + MIN_LAMPORTS:
                    rest = remaining_bal - FINAL_TX_FEE_RESERVE
                    rest_sig = await _send_sol_async(client, kp, main_pubkey, rest)
                    if rest_sig:
                        print(f"[POLL] {rec.id}: Rest gesendet: {rest_sig}")
                    else:
                        print(f"[POLL] {rec.id}: Rest-Transfer fehlgeschlagen, Rest bleibt auf Deposit")
                else:
                    print(f"[POLL] {rec.id}: kein nennenswerter Rest ({remaining_bal} lamports)")

                rec.status = "forwarded"
                rec.lock_until = None
                rec.deposit_secret_enc = ""
                db.commit()
                print(f"[POLL] {rec.id}: ABGEWICKELT fee={rec.fee_tx}, net={rec.net_tx}")
        except Exception as e:
            print(f"[POLL] Unerwarteter Fehler: {e}")
        finally:
            db.close()