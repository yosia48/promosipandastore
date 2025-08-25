import asyncio
import json
import random
import threading
from telethon import TelegramClient, events
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
import uvicorn
from datetime import datetime

API_ID = "27460087"       # Ganti dengan API ID Anda dari my.telegram.org
API_HASH = "5b4e25d46c9fadc077991080761fc194"   # Ganti dengan API HASH Anda
SESSION_NAME = "userbot_session"  # Nama file session userbot

CONFIG_FILE = "config.json"
PROMO_FILE = "promo.json"

MSG_RECORDS = {}  # {group_id: last_message_id}
LOG_HISTORY = []  # menyimpan log aktivitas bot (max 20 pesan)

app = FastAPI()

def add_log(msg: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{now}] {msg}"
    LOG_HISTORY.append(log_msg)
    if len(LOG_HISTORY) > 20:
        LOG_HISTORY.pop(0)
    print(log_msg)

@app.get("/")
async def root():
    return {"status": "ok"}

def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"groups": {}}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_promos():
    try:
        with open(PROMO_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_promos(data):
    with open(PROMO_FILE, "w") as f:
        json.dump(data, f, indent=2)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

async def delete_last_promo(group_id):
    if group_id in MSG_RECORDS:
        try:
            await client.delete_messages(int(group_id), MSG_RECORDS[group_id])
            add_log(f"Pesan lama di grup {group_id} dihapus.")
        except Exception as e:
            add_log(f"Gagal hapus pesan lama di grup {group_id}: {e}")

async def send_promo(group_id, topic_id=None):
    add_log(f"Mulai mengirim promo ke grup {group_id} topic {topic_id}")
    await delete_last_promo(group_id)
    promos = load_promos()
    if not promos:
        add_log("Tidak ada pesan promosi di promo.json")
        return
    promo_msg = random.choice(promos)
    try:
        if topic_id:
            sent = await client.send_message(
                entity=int(group_id),
                message=promo_msg,
                message_thread_id=topic_id
            )
        else:
            sent = await client.send_message(
                entity=int(group_id),
                message=promo_msg
            )
        MSG_RECORDS[group_id] = sent.id
        add_log(f"Promo terkirim ke grup {group_id} message_id {sent.id}")
    except Exception as e:
        add_log(f"Gagal kirim promo ke grup {group_id} topic {topic_id}: {e}")

def schedule_send_promo(group_id, topic_id=None):
    add_log(f"Scheduler trigger grup {group_id} topic {topic_id}")
    asyncio.create_task(send_promo(group_id, topic_id))

def setup_scheduler():
    scheduler = AsyncIOScheduler()
    config = load_config()
    add_log("Memulai setup scheduler...")
    for group_id, ginfo in config["groups"].items():
        t_id = ginfo.get("topic_id")
        tipe = ginfo.get("type")
        if tipe == "free":
            scheduler.add_job(schedule_send_promo, "interval", args=[group_id, t_id], hours=2)
            add_log(f"Scheduler tambah job FREE ke grup {group_id} tiap 2 jam")
        elif tipe == "limit":
            scheduler.add_job(schedule_send_promo, "cron", args=[group_id, t_id], hour=7, minute=0)
            scheduler.add_job(schedule_send_promo, "cron", args=[group_id, t_id], hour=17, minute=30)
            add_log(f"Scheduler tambah job LIMIT ke grup {group_id} jam 07:00 & 17:30")
    scheduler.start()
    add_log("Scheduler sudah berjalan.")

# Command untuk set grup bebas dengan optional topic_id
@client.on(events.NewMessage(pattern="^!setfree (\\-?\\d+)(?: (\\d+))?$"))
async def setfree(event):
    args = event.text.split()
    gid = args[1]
    topic_id = int(args[2]) if len(args) > 2 else None
    config = load_config()
    config["groups"][gid] = {"type": "free"}
    if topic_id:
        config["groups"][gid]["topic_id"] = topic_id
    else:
        config["groups"][gid].pop("topic_id", None)
    save_config(config)
    msg = f"Grup {gid} diatur sebagai grup BEBAS (promo tiap 2 jam)"
    if topic_id:
        msg += f" di topic ID {topic_id}."
    else:
        msg += "."
    add_log(msg)
    await event.reply(msg)

# Command untuk set grup terbatas dengan optional topic_id
@client.on(events.NewMessage(pattern="^!setlimit (\\-?\\d+) 2(?: (\\d+))?$"))
async def setlimit(event):
    args = event.text.split()
    gid = args[1]
    topic_id = int(args[3]) if len(args) > 3 else None
    config = load_config()
    config["groups"][gid] = {"type": "limit"}
    if topic_id:
        config["groups"][gid]["topic_id"] = topic_id
    else:
        config["groups"][gid].pop("topic_id", None)
    save_config(config)
    msg = f"Grup {gid} diatur sebagai grup TERBATAS (promo jam 07:00 & 17:30)"
    if topic_id:
        msg += f" di topic ID {topic_id}."
    else:
        msg += "."
    add_log(msg)
    await event.reply(msg)

# Command untuk list semua grup dan status
@client.on(events.NewMessage(pattern="^!listgroups$"))
async def listgroups(event):
    config = load_config()
    if not config.get("groups"):
        await event.reply("Belum ada grup yang terdaftar.")
        return
    msg = "Daftar Grup:\n"
    for gid, info in config["groups"].items():
        tipe = "FREE (2 jam sekali)" if info.get("type") == "free" else "LIMIT (07:00 & 17:30)"
        if "topic_id" in info:
            msg += f"{gid} (topic {info['topic_id']}): {tipe}\n"
        else:
            msg += f"{gid}: {tipe}\n"
    await event.reply(msg)

# Command untuk reset daftar promo
@client.on(events.NewMessage(pattern="^!resetpromo$"))
async def resetpromo(event):
    save_promos([])
    add_log("Daftar pesan promosi direset.")
    await event.reply("Daftar pesan promosi sudah direset, silakan tambah pesan baru menggunakan !addpromo.")

# Command untuk mulai proses tambah promo multi-line
@client.on(events.NewMessage(pattern="^!addpromo$"))
async def addpromo_request(event):
    await event.reply("Silakan balas pesan ini dengan isi promo yang ingin ditambahkan, format bebas dan bisa multiline.")

# Command untuk menerima pesan balasan sebagai promo baru
@client.on(events.NewMessage(func=lambda e: e.is_reply and e.reply_to_msg and "Silakan balas pesan ini dengan isi promo yang ingin ditambahkan" in e.reply_to_msg.text))
async def addpromo_receive(event):
    promo_text = event.text
    promos = load_promos()
    promos.append(promo_text)
    save_promos(promos)
    add_log(f"Promo baru ditambahkan: {promo_text[:30]}...")
    await event.reply("Promo berhasil ditambahkan.")

# Command untuk hapus promo berdasar nomor
@client.on(events.NewMessage(pattern="^!removepromo ([0-9]+)$"))
async def removepromo(event):
    idx = int(event.pattern_match.group(1)) - 1
    promos = load_promos()
    if 0 <= idx < len(promos):
        deleted = promos.pop(idx)
        save_promos(promos)
        add_log(f"Promo dihapus: {deleted[:30]}...")
        await event.reply(f"Berhasil menghapus promo nomor {idx+1}.")
    else:
        await event.reply("Nomor promo tidak valid.")

# Command untuk list semua promo
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

# Command kirim promo manual ke grup (opsional topic_id)
@client.on(events.NewMessage(pattern="^!promo (\\-?\\d+)(?: (\\d+))?$"))
async def promo(event):
    args = event.text.split()
    gid = args[1]
    topic_id = int(args[2]) if len(args) > 2 else None
    await send_promo(gid, topic_id)
    msg = f"Promosi dikirim manual ke grup {gid}"
    if topic_id:
        msg += f" di topic ID {topic_id}."
    else:
        msg += "."
    add_log(msg)
    await event.reply(msg)

# Command cek log aktivitas
@client.on(events.NewMessage(pattern="^!ceklog$"))
async def ceklog(event):
    if not LOG_HISTORY:
        await event.reply("Log kosong.")
        return
    msg = "Log terakhir:\n" + "\n".join(LOG_HISTORY[-10:])
    await event.reply(msg)

def run_keepalive():
    uvicorn.run(app, host="0.0.0.0", port=8080)

async def main():
    add_log("Memulai userbot...")
    await client.start()
    add_log("Userbot sudah aktif.")
    setup_scheduler()
    add_log("Scheduler sudah disiapkan dan berjalan.")
    await client.run_until_disconnected()

if __name__ == "__main__":
    threading.Thread(target=run_keepalive, daemon=True).start()
    asyncio.run(main())
