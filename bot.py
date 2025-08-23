import asyncio
import json
import random
import threading
from telethon import TelegramClient, events
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
import uvicorn

API_ID = "27460087"       # Ganti dengan API ID Anda dari my.telegram.org
API_HASH = "5b4e25d46c9fadc077991080761fc194"   # Ganti dengan API HASH Anda
SESSION_NAME = "userbot_session"  # Nama file session userbot

CONFIG_FILE = "config.json"
PROMO_FILE = "promo.json"

MSG_RECORDS = {}  # Simpan {group_id: last_msg_id} untuk hapus pesan promosi yang lama

app = FastAPI()

@app.get("/")
async def root():
    return {"status": "ok"}

# Helper untuk load/save config grup
def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"groups": {}}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

# Helper untuk load/save pesan promosi
def load_promos():
    try:
        with open(PROMO_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_promos(data):
    with open(PROMO_FILE, "w") as f:
        json.dump(data, f, indent=2)

# Telegram client init
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# Hapus pesan promo lama di grup jika ada
async def delete_last_promo(group_id):
    if group_id in MSG_RECORDS:
        try:
            await client.delete_messages(int(group_id), MSG_RECORDS[group_id])
        except:
            pass  # Bisa gagal kalau pesan sudah dihapus

# Kirim promo baru ke grup dan simpan pesan ID
async def send_promo(group_id):
    await delete_last_promo(group_id)
    promos = load_promos()
    if not promos:
        return
    promo_msg = random.choice(promos)
    try:
        sent = await client.send_message(int(group_id), promo_msg)
        MSG_RECORDS[group_id] = sent.id
    except Exception as e:
        print(f"Gagal kirim pesan ke {group_id}: {str(e)}")

# Fungsi yang dipanggil scheduler secara asynchronous
def schedule_send_promo(group_id):
    asyncio.create_task(send_promo(group_id))

# Setup scheduler sesuai grup dan tipe
def setup_scheduler():
    scheduler = AsyncIOScheduler()
    config = load_config()
    for group_id, ginfo in config["groups"].items():
        if ginfo.get("type") == "free":
            # Kirim setiap 2 jam untuk grup bebas
            scheduler.add_job(schedule_send_promo, "interval", args=[group_id], hours=2)
        elif ginfo.get("type") == "limit":
            # Kirim tiap hari jam 07:00 & 17:30 untuk grup terbatas
            scheduler.add_job(schedule_send_promo, "cron", args=[group_id], hour=7, minute=0)
            scheduler.add_job(schedule_send_promo, "cron", args=[group_id], hour=17, minute=30)
    scheduler.start()

# Command: set grup jadi bebas (free)
@client.on(events.NewMessage(pattern="^!setfree (.+)$"))
async def setfree(event):
    gid = event.pattern_match.group(1)
    config = load_config()
    config["groups"][gid] = {"type": "free"}
    save_config(config)
    await event.reply(f"Grup {gid} diatur sebagai grup BEBAS (promo tiap 2 jam).")

# Command: set grup jadi terbatas (limit)
@client.on(events.NewMessage(pattern="^!setlimit (.+) 2$"))
async def setlimit(event):
    gid = event.pattern_match.group(1)
    config = load_config()
    config["groups"][gid] = {"type": "limit"}
    save_config(config)
    await event.reply(f"Grup {gid} diatur sebagai grup TERBATAS (promo jam 07:00 & 17:30).")

# Command: list semua grup dan statusnya
@client.on(events.NewMessage(pattern="^!listgroups$"))
async def listgroups(event):
    config = load_config()
    if not config.get("groups"):
        await event.reply("Belum ada grup yang terdaftar.")
        return
    msg = "Daftar Grup:\n"
    for gid, info in config["groups"].items():
        tipe = "FREE (2 jam sekali)" if info.get("type")=="free" else "LIMIT (07:00 & 17:30)"
        msg += f"{gid}: {tipe}\n"
    await event.reply(msg)

# Command: tambah pesan promosi baru
@client.on(events.NewMessage(pattern="^!addpromo (.+)$"))
async def addpromo(event):
    promo = event.pattern_match.group(1).strip()
    promos = load_promos()
    promos.append(promo)
    save_promos(promos)
    await event.reply("Pesan promosi berhasil ditambahkan.")

# Command: hapus pesan promosi berdasarkan nomor index
@client.on(events.NewMessage(pattern="^!removepromo ([0-9]+)$"))
async def removepromo(event):
    idx = int(event.pattern_match.group(1)) - 1
    promos = load_promos()
    if 0 <= idx < len(promos):
        deleted = promos.pop(idx)
        save_promos(promos)
        await event.reply(f"Berhasil menghapus promo:\n{deleted[:50]}...")
    else:
        await event.reply("Nomor promo tidak valid.")

# Command: list semua pesan promosi
@client.on(events.NewMessage(pattern="^!listpromo$"))
async def listpromo(event):
    promos = load_promos()
    if not promos:
        await event.reply("Belum ada pesan promosi.")
        return
    msg = "Daftar Pesan Promosi:\n"
    for i, p in enumerate(promos, start=1):
        preview = p.replace("\n", " ")[:50]
        msg += f"{i}. {preview}...\n"
    await event.reply(msg)

# Command: kirim promo manual ke grup tertentu
@client.on(events.NewMessage(pattern="^!promo (.+)$"))
async def promo(event):
    gid = event.pattern_match.group(1)
    await send_promo(gid)
    await event.reply(f"Promosi dikirim manual ke grup {gid}.")

# Fungsi menjalankan keepalive webserver dan userbot paralel
def run_keepalive():
    uvicorn.run(app, host="0.0.0.0", port=8080)

async def main():
    await client.start()
    setup_scheduler()
    print("Userbot siap dan berjalan. Keepalive & scheduler aktif.")
    await client.run_until_disconnected()

if __name__ == "__main__":
    # Jalankan keepalive server di background thread agar bisa berjalan bersamaan dengan userbot
    threading.Thread(target=run_keepalive, daemon=True).start()
    asyncio.run(main())
