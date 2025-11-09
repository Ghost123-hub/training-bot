import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import datetime
import os
import traceback
import asyncio
from aiohttp import web

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix='/', intents=intents)

# --- CONSTANTS ---
SCHEDULE_CHANNEL_ID = 1432077759932530839
TRAININGS_CHANNEL_ID = 1432137378008399942
PING_ROLE_ID = 1385368957074276542
GUILD_ID = 1381002127765278740  # Your guild ID

# --- LOAD / INIT DATA ---
DATA_FILE = "slots.json"

if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        print("❌ Error reading slots.json, using fallback default.")
        data = {"available_slots": [], "claimed_slots": []}
else:
    data = {
        "available_slots": [
            {"id": 1, "time": "2025-11-10 12:00 PM", "status": "available"},
            {"id": 2, "time": "2025-11-10 2:00 PM", "status": "available"},
            {"id": 3, "time": "2025-11-10 4:00 PM", "status": "available"},
            {"id": 4, "time": "2025-11-10 6:00 PM", "status": "available"},
            {"id": 5, "time": "2025-11-10 8:00 PM", "status": "available"},
            {"id": 6, "time": "2025-11-10 10:00 PM", "status": "available"}
        ],
        "claimed_slots": []
    }

# --- SAVE DATA ---
def save_data():
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"❌ Error saving data: {e}")

# --- UPDATE SCHEDULE MESSAGE ---
async def update_schedule():
    try:
        channel = bot.get_channel(SCHEDULE_CHANNEL_ID)
        if channel is None:
            print("⚠️ Schedule channel not found.")
            return

        role_ping = f"<@&{PING_ROLE_ID}>"
        schedule_lines = [
            f"**{slot['user']}** — {slot['time']}"
            for slot in data["claimed_slots"]
            if slot.get("status") == "claimed"
        ]
        if schedule_lines:
            schedule_message = f"{role_ping}\n**Upcoming Training Sessions**\n" + "\n".join(schedule_lines)
        else:
            schedule_message = f"{role_ping}\n**Upcoming Training Sessions**\nNo sessions scheduled."

        async for message in channel.history(limit=100):
            if message.author == bot.user and message.content.startswith(f"<@&{PING_ROLE_ID}>"):
                await message.edit(content=schedule_message)
                return

        await channel.send(schedule_message)
    except Exception as e:
        print(f"❌ Error updating schedule: {e}")
        traceback.print_exc()

# --- AUTO CHECK TRAININGS ---
@tasks.loop(minutes=1)
async def check_training_times():
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
        for slot in data["claimed_slots"]:
            if slot.get("time") == now and slot.get("status") == "claimed":
                channel = bot.get_channel(SCHEDULE_CHANNEL_ID)
                if channel:
                    await channel.send(f"<@&{PING_ROLE_ID}> {slot['mention']} has hosted a training @ {now}!")
                    slot["status"] = "completed"
                    save_data()
                    await update_schedule()
    except Exception as e:
        print(f"❌ Error in check_training_times: {e}")

@check_training_times.before_loop
async def before_check_training_times():
    await bot.wait_until_ready()

# --- ON READY ---
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"🌐 Synced {len(synced)} slash commands to guild {GUILD_ID}")
    except Exception as e:
        print(f"❌ Error syncing commands: {e}")
        traceback.print_exc()

    if not check_training_times.is_running():
        check_training_times.start()

# --- /CLAIM COMMAND ---
@bot.tree.command(name="claim", description="Claim or view training session slots.")
@app_commands.describe(slot_id="The ID of the slot you want to claim (leave blank to view slots)")
async def claim(interaction: discord.Interaction, slot_id: int = None):
    try:
        has_role = any(r.name.lower() == "store director" for r in interaction.user.roles)
        if not has_role:
            await interaction.response.send_message("❌ You need the Store Director role.", ephemeral=True)
            return
        if slot_id is None:
            available = [s for s in data["available_slots"] if s["status"] == "available"]
            if not available:
                await interaction.response.send_message("❌ No available time slots.", ephemeral=True)
                return
            msg = "**Available Slots:**\n" + "\n".join(f"ID {s['id']} - {s['time']}" for s in available)
            await interaction.response.send_message(msg, ephemeral=True)
            return
        slot = next((s for s in data["available_slots"] if s["id"] == slot_id and s["status"] == "available"), None)
        if not slot:
            await interaction.response.send_message("❌ Invalid slot.", ephemeral=True)
            return
        slot["status"] = "claimed"
        data["claimed_slots"].append({
            "id": slot["id"], "time": slot["time"],
            "user": interaction.user.name, "mention": interaction.user.mention,
            "status": "claimed"
        })
        save_data()
        await update_schedule()
        await interaction.response.send_message(f"✅ You claimed **{slot['time']}**.", ephemeral=True)
    except Exception as e:
        print(f"❌ Error in claim: {e}")
        traceback.print_exc()

# --- /UNCLAIM COMMAND ---
@bot.tree.command(name="unclaim", description="Unclaim your training session slot.")
async def unclaim(interaction: discord.Interaction):
    try:
        has_role = any(r.name.lower() == "store director" for r in interaction.user.roles)
        if not has_role:
            await interaction.response.send_message("❌ You need the Store Director role.", ephemeral=True)
            return

        user_slot = next((s for s in data["claimed_slots"] if s["mention"] == interaction.user.mention and s["status"] == "claimed"), None)
        if not user_slot:
            await interaction.response.send_message("❌ You don't have any claimed sessions.", ephemeral=True)
            return

        for av_slot in data["available_slots"]:
            if av_slot["id"] == user_slot["id"]:
                av_slot["status"] = "available"

        data["claimed_slots"].remove(user_slot)
        save_data()
        await update_schedule()
        await interaction.response.send_message(f"✅ You unclaimed **{user_slot['time']}**.", ephemeral=True)
    except Exception as e:
        print(f"❌ Error in unclaim: {e}")
        traceback.print_exc()

# --- AIOHTTP WEB SERVER ---
async def handle_root(request):
    return web.Response(text="✅ Training bot is running!")

async def start_web_app():
    app = web.Application()
    app.router.add_get("/", handle_root)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
    await site.start()
    print("🌐 Web server listening on port 3000")

# --- MAIN ENTRYPOINT ---
async def main():
    token = os.environ.get("TRAINING_BOT_TOKEN")
    if not token:
        print("❌ ERROR: TRAINING_BOT_TOKEN not found!")
        return
    await asyncio.gather(start_web_app(), bot.start(token))

if __name__ == "__main__":
    asyncio.run(main())
