"""Async Telegram sender; secrets are read only from environment."""
import os
import aiohttp

async def send(session: aiohttp.ClientSession, message: str):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        return False, 'Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID'
    try:
        async with session.post(f'https://api.telegram.org/bot{token}/sendMessage',
                                json={'chat_id': chat_id, 'text': message},
                                timeout=aiohttp.ClientTimeout(total=8)) as response:
            data = await response.json(content_type=None)
            return (response.status == 200 and data.get('ok') is True,
                    'Sent' if response.status == 200 and data.get('ok') else str(data.get('description', 'Telegram error')))
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        return False, str(exc)
