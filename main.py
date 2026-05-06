import asyncio
import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

TZ = ZoneInfo("Europe/Moscow")
DB_PATH = "bot_config.db"
JOIN_BUTTON_ID = "uvedom_join_button"
DEFAULT_DAYS = "0,2,4,5"  # Пн, Ср, Пт, Сб
ROLE_SLOT_LIMIT = 5
EVENT_DELETE_AFTER = 3600  # 1 час
TEST_DELETE_AFTER = 300  # 5 минут

TIME_CHOICES = [f"{h:02d}:00" for h in range(12, 23)]  # 12:00 .. 22:00
EVENT_NAME_CHOICES = ["capt"]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
    c.execute(
        "CREATE TABLE IF NOT EXISTS events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, channel_id INTEGER, "
        "time TEXT, days TEXT, role_ids TEXT, admin_id INTEGER, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS participants ("
        "event_id INTEGER, event_date TEXT, user_id INTEGER, "
        "joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "PRIMARY KEY (event_id, event_date, user_id))"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS pending_deletes ("
        "message_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL, "
        "delete_at TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()


def get_config(key):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key = ?", (key,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None


def set_config(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def get_active_event():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT 1")
    result = c.fetchone()
    conn.close()
    return result


def save_event(name, channel_id, time, days, role_ids, admin_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO events (name, channel_id, time, days, role_ids, admin_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, channel_id, time, days, role_ids, admin_id),
    )
    conn.commit()
    event_id = c.lastrowid
    conn.close()
    return event_id


def clear_events():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM events")
    c.execute("DELETE FROM participants")
    conn.commit()
    conn.close()


def add_participant(event_id, event_date, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO participants (event_id, event_date, user_id) VALUES (?, ?, ?)",
        (event_id, event_date, user_id),
    )
    conn.commit()
    conn.close()


def remove_participant(event_id, event_date, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "DELETE FROM participants WHERE event_id = ? AND event_date = ? AND user_id = ?",
        (event_id, event_date, user_id),
    )
    conn.commit()
    conn.close()


def get_participants(event_id, event_date):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT user_id FROM participants WHERE event_id = ? AND event_date = ? ORDER BY joined_at ASC",
        (event_id, event_date),
    )
    result = [row[0] for row in c.fetchall()]
    conn.close()
    return result


def cleanup_old_keys(today_iso):
    """Чистим прошлые last_2h_/last_30m_ ключи, чтобы не копились в config."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "DELETE FROM config WHERE (key LIKE 'last_2h_%' OR key LIKE 'last_30m_%') "
        "AND key != ? AND key != ?",
        (f"last_2h_{today_iso}", f"last_30m_{today_iso}"),
    )
    conn.commit()
    conn.close()


def add_pending_delete(channel_id, message_id, delete_at_iso):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO pending_deletes (message_id, channel_id, delete_at) VALUES (?, ?, ?)",
        (message_id, channel_id, delete_at_iso),
    )
    conn.commit()
    conn.close()


def remove_pending_delete(message_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM pending_deletes WHERE message_id = ?", (message_id,))
    conn.commit()
    conn.close()


def get_all_pending_deletes():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT channel_id, message_id, delete_at FROM pending_deletes")
    rows = c.fetchall()
    conn.close()
    return rows


async def _delete_after(channel_id, message_id, delay_seconds):
    """Спит delay_seconds, потом удаляет сообщение и чистит запись из БД."""
    try:
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
    except asyncio.CancelledError:
        return
    try:
        channel = client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await client.fetch_channel(channel_id)
            except Exception:
                channel = None
        if channel is not None:
            try:
                msg = await channel.fetch_message(message_id)
                await msg.delete()
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print(f"No permission to delete message {message_id}")
            except Exception as e:
                print(f"Error deleting message {message_id}: {e}")
    finally:
        remove_pending_delete(message_id)


def schedule_message_delete(message, delay_seconds):
    """Сохраняет в БД и запускает фоновую задачу удаления через delay_seconds."""
    delete_at = datetime.now(TZ) + timedelta(seconds=delay_seconds)
    add_pending_delete(message.channel.id, message.id, delete_at.isoformat())
    asyncio.create_task(_delete_after(message.channel.id, message.id, delay_seconds))


def restore_pending_deletes():
    """При старте бота восстанавливает запланированные удаления из БД."""
    rows = get_all_pending_deletes()
    now = datetime.now(TZ)
    restored = 0
    for channel_id, message_id, delete_at_iso in rows:
        try:
            delete_at = datetime.fromisoformat(delete_at_iso)
        except Exception:
            remove_pending_delete(message_id)
            continue
        delay = max(0, (delete_at - now).total_seconds())
        asyncio.create_task(_delete_after(channel_id, message_id, delay))
        restored += 1
    return restored


async def send_event_dms(guild, role_ids_list, event_name, admin_id):
    """Шлёт ЛС админу + всем уникальным членам с любой из упомянутых ролей.
    Один пользователь = одно ЛС, даже если у него несколько подходящих ролей."""
    users_to_notify = {}  # user_id -> User/Member

    if guild is not None:
        for role_id in role_ids_list:
            try:
                role = guild.get_role(int(role_id))
            except (ValueError, TypeError):
                role = None
            if role:
                for member in role.members:
                    if not member.bot:
                        users_to_notify[member.id] = member

    if admin_id:
        try:
            aid = int(admin_id)
            if aid not in users_to_notify:
                admin = await client.fetch_user(aid)
                if admin and not admin.bot:
                    users_to_notify[aid] = admin
        except Exception as e:
            print(f"Error fetching admin: {e}")

    message = f"⏰ Зайди в {event_name}! Событие началось."
    sent = 0
    failed = 0
    for user in users_to_notify.values():
        try:
            await user.send(message)
            sent += 1
        except discord.Forbidden:
            failed += 1
            print(f"DM disabled for user {user.id}")
        except Exception as e:
            failed += 1
            print(f"Error DMing {user.id}: {e}")
    print(f"Event DMs: sent={sent}, failed={failed}, total={len(users_to_notify)}")
    return sent, failed


def build_event_embed(name, event_date_str, event_time, guild, role_ids_list, participants_ids):
    role_info = []
    if guild is not None:
        for role_id in role_ids_list:
            try:
                role = guild.get_role(int(role_id))
            except (ValueError, TypeError):
                role = None
            if role:
                member_count = len([m for m in guild.members if role in m.roles])
                role_info.append(f"🔴 {role.name} [{member_count}/{ROLE_SLOT_LIMIT}]")
            else:
                role_info.append(f"🔴 Неизвестная роль [{role_id}]")

    embed = discord.Embed(title=name, color=0xFE1973)
    embed.add_field(name="📅 Дата", value=event_date_str, inline=True)
    embed.add_field(name="⏰ Время (МСК)", value=event_time, inline=True)
    if role_info:
        embed.add_field(name="👥 Роли", value="\n".join(role_info), inline=False)

    if participants_ids:
        participants_str = "\n".join([f"• <@{uid}>" for uid in participants_ids])
    else:
        participants_str = "_Пока никто не присоединился_"
    embed.add_field(
        name=f"✅ Присоединились ({len(participants_ids)})",
        value=participants_str,
        inline=False,
    )
    return embed


class JoinButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Присоединиться",
        style=discord.ButtonStyle.green,
        emoji="✅",
        custom_id=JOIN_BUTTON_ID,
    )
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        event = get_active_event()
        if not event:
            await interaction.response.send_message(
                "❌ Активного события нет.", ephemeral=True
            )
            return

        event_id, name, _channel_id, event_time, _days, role_ids, _admin_id, _created_at = event
        today_iso = datetime.now(TZ).date().isoformat()

        # toggle: уже в списке — выходит, иначе — вступает
        existing = get_participants(event_id, today_iso)
        if interaction.user.id in existing:
            remove_participant(event_id, today_iso, interaction.user.id)
            action_msg = "❎ Вы покинули событие."
        else:
            add_participant(event_id, today_iso, interaction.user.id)
            action_msg = "✅ Вы присоединились!"

        try:
            role_ids_list = [r.strip() for r in role_ids.split(",") if r.strip()]
            participants_ids = get_participants(event_id, today_iso)
            now = datetime.now(TZ)
            embed = build_event_embed(
                name,
                now.strftime("%d.%m.%Y"),
                event_time,
                interaction.guild,
                role_ids_list,
                participants_ids,
            )
            await interaction.message.edit(embed=embed, view=self)
        except Exception as e:
            print(f"Error updating embed: {e}")

        await interaction.response.send_message(action_msg, ephemeral=True)


@client.event
async def on_ready():
    print(f"Bot logged in as {client.user}")
    print(f"Bot ID: {client.user.id}")
    print(f"Guilds: {len(client.guilds)}")
    for guild in client.guilds:
        print(f"  - {guild.name} (ID: {guild.id})")

    init_db()
    client.add_view(JoinButtonView())

    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"Error syncing commands: {e}")

    restored = restore_pending_deletes()
    if restored:
        print(f"Restored {restored} pending message deletion(s)")

    client.loop.create_task(check_notifications_task())
    print("Bot is ready!")


async def check_notifications_task():
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            now = datetime.now(TZ)
            current_time = now.strftime("%H:%M")
            current_day = now.weekday()
            today_iso = now.date().isoformat()

            event = get_active_event()
            if event:
                event_id, name, channel_id, event_time, days, role_ids, admin_id, _created_at = event
                days_list = [int(d.strip()) for d in days.split(",") if d.strip()]

                if current_day in days_list:
                    event_dt = datetime.strptime(event_time, "%H:%M").replace(
                        year=now.year, month=now.month, day=now.day, tzinfo=TZ
                    )
                    two_hours_before = (event_dt - timedelta(hours=2)).strftime("%H:%M")
                    thirty_minutes_before = (event_dt - timedelta(minutes=30)).strftime("%H:%M")

                    if current_time == two_hours_before and not get_config(f"last_2h_{today_iso}"):
                        try:
                            admin = await client.fetch_user(int(admin_id))
                            await admin.send(
                                "⏰ Напоминание: через 2 часа будет событие. Зайди чтобы не быть в очереди!"
                            )
                            set_config(f"last_2h_{today_iso}", "sent")
                        except Exception as e:
                            print(f"Error sending 2h notification: {e}")

                    if current_time == thirty_minutes_before and not get_config(f"last_30m_{today_iso}"):
                        try:
                            admin = await client.fetch_user(int(admin_id))
                            await admin.send(
                                "⏰ Напоминание: через 30 минут будет событие. Зайди чтобы не быть в очереди!"
                            )
                            set_config(f"last_30m_{today_iso}", "sent")
                        except Exception as e:
                            print(f"Error sending 30m notification: {e}")

                    if current_time == event_time and get_config("last_notification") != today_iso:
                        role_ids_list = [r.strip() for r in role_ids.split(",") if r.strip()]
                        role_mentions = " ".join([f"<@&{rid}>" for rid in role_ids_list])

                        channel = client.get_channel(channel_id)
                        if channel is not None:
                            participants_ids = get_participants(event_id, today_iso)
                            embed = build_event_embed(
                                name,
                                now.strftime("%d.%m.%Y"),
                                event_time,
                                channel.guild,
                                role_ids_list,
                                participants_ids,
                            )
                            try:
                                sent_msg = await channel.send(
                                    content=role_mentions,
                                    embed=embed,
                                    view=JoinButtonView(),
                                )
                                set_config("last_notification", today_iso)
                                cleanup_old_keys(today_iso)
                                schedule_message_delete(sent_msg, EVENT_DELETE_AFTER)
                                await send_event_dms(
                                    channel.guild, role_ids_list, name, admin_id
                                )
                            except Exception as e:
                                print(f"Error sending event message: {e}")
                        else:
                            print(f"Channel {channel_id} not found")
        except Exception as e:
            print(f"Error in notifications loop: {e}")

        await asyncio.sleep(30)


class RoleSelectView(discord.ui.View):
    """Эфемерный view, выводимый после /setup, чтобы выбрать роли через RoleSelect."""

    def __init__(self, time, channel_id, channel_mention, event_name, admin_id, *, timeout=300):
        super().__init__(timeout=timeout)
        self._time = time
        self._channel_id = channel_id
        self._channel_mention = channel_mention
        self._event_name = event_name
        self._admin_id = admin_id

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Выберите роли для упоминания (1–25)…",
        min_values=1,
        max_values=25,
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        roles = select.values
        if not roles:
            await interaction.response.send_message("❌ Не выбрано ни одной роли.", ephemeral=True)
            return

        role_ids = [str(r.id) for r in roles]
        try:
            clear_events()
            save_event(
                self._event_name,
                self._channel_id,
                self._time,
                DEFAULT_DAYS,
                ",".join(role_ids),
                self._admin_id,
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка БД: {str(e)}", ephemeral=True)
            return

        embed = discord.Embed(
            title="✅ Настройка завершена",
            description=f'Событие "{self._event_name}" настроено',
            color=0x00FF00,
        )
        embed.add_field(name="Время (МСК)", value=self._time, inline=True)
        embed.add_field(name="Канал", value=self._channel_mention, inline=True)
        embed.add_field(name="Дни", value="Пн, Ср, Пт, Сб", inline=True)
        embed.add_field(
            name=f"Роли ({len(roles)})",
            value=", ".join(r.mention for r in roles),
            inline=False,
        )
        embed.add_field(name="Администратор", value=f"<@{self._admin_id}>", inline=True)

        # убираем select после выбора
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(content=None, embed=embed, view=self)
        self.stop()


async def _time_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=t, value=t)
        for t in TIME_CHOICES
        if current.lower() in t.lower()
    ][:25]


async def _event_name_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=n, value=n)
        for n in EVENT_NAME_CHOICES
        if current.lower() in n.lower()
    ][:25]


@tree.command(name="setup", description="Настроить уведомления о событии")
@app_commands.describe(
    time="Время события (МСК)",
    channel="Канал для отправки уведомления",
    event_name="Название события",
    admin="(опционально) пользователь-администратор для ЛС-напоминаний",
)
@app_commands.autocomplete(time=_time_autocomplete, event_name=_event_name_autocomplete)
async def setup(
    interaction: discord.Interaction,
    time: str,
    channel: discord.TextChannel,
    event_name: str,
    admin: discord.User = None,
):
    if time not in TIME_CHOICES:
        await interaction.response.send_message(
            f"❌ Время должно быть из списка: {', '.join(TIME_CHOICES)}",
            ephemeral=True,
        )
        return
    if event_name not in EVENT_NAME_CHOICES:
        await interaction.response.send_message(
            f"❌ Название должно быть из списка: {', '.join(EVENT_NAME_CHOICES)}",
            ephemeral=True,
        )
        return

    admin_id = str(admin.id if admin else interaction.user.id)

    view = RoleSelectView(
        time=time,
        channel_id=channel.id,
        channel_mention=channel.mention,
        event_name=event_name,
        admin_id=admin_id,
    )
    await interaction.response.send_message(
        f"🎯 Время: **{time}** • Канал: {channel.mention} • Событие: **{event_name}**\n"
        "Теперь выберите роли для упоминания:",
        view=view,
        ephemeral=True,
    )


@tree.command(name="test", description="Отправить тестовое уведомление")
async def test(interaction: discord.Interaction):
    event = get_active_event()
    if not event:
        await interaction.response.send_message(
            "❌ Событие не настроено! Сначала используйте /setup", ephemeral=True
        )
        return
    try:
        event_id, name, _channel_id, event_time, _days, role_ids, _admin_id, _created_at = event
        role_ids_list = [r.strip() for r in role_ids.split(",") if r.strip()]
        role_mentions = " ".join([f"<@&{rid}>" for rid in role_ids_list])

        now = datetime.now(TZ)
        today_iso = now.date().isoformat()
        participants_ids = get_participants(event_id, today_iso)
        embed = build_event_embed(
            name,
            now.strftime("%d.%m.%Y"),
            event_time,
            interaction.guild,
            role_ids_list,
            participants_ids,
        )
        await interaction.response.send_message(
            content=role_mentions, embed=embed, view=JoinButtonView()
        )
        try:
            sent_msg = await interaction.original_response()
            schedule_message_delete(sent_msg, TEST_DELETE_AFTER)
        except Exception as e:
            print(f"Error scheduling test message delete: {e}")
    except Exception as e:
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ Ошибка: {str(e)}", ephemeral=True)


@tree.command(
    name="test_dm",
    description="Тест ЛС: разослать всем с упомянутыми ролями + админу (один раз на пользователя)",
)
async def test_dm(interaction: discord.Interaction):
    event = get_active_event()
    if not event:
        await interaction.response.send_message(
            "❌ Событие не настроено! Сначала используйте /setup", ephemeral=True
        )
        return
    _eid, name, _ch, _t, _d, role_ids, admin_id, _ca = event
    role_ids_list = [r.strip() for r in role_ids.split(",") if r.strip()]
    await interaction.response.defer(ephemeral=True, thinking=True)
    sent, failed = await send_event_dms(interaction.guild, role_ids_list, name, admin_id)
    await interaction.followup.send(
        f"📨 Тест ЛС завершён: отправлено **{sent}**, не доставлено **{failed}**.",
        ephemeral=True,
    )


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("Error: DISCORD_TOKEN not found in environment variables")
    else:
        client.run(token)
