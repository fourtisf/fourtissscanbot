import os
import sqlite3
import asyncio
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Union
from collections import defaultdict
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.helpers import escape_markdown
import aiohttp
import numpy as np
import re
from urllib.parse import quote

# Import dari proyek utama Anda
from main import DexScreenerAPI, CryptoPriceScannerBot
from bot_config import Config
from token_links import get_token_links


# FUNGSI CUSTOM ESCAPE
def escape_all_markdown_v2(text: str) -> str:
    """
    Escapes all characters that have special meaning in MarkdownV2.
    """
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)


def escape_number_for_markdown(number: Union[int, float]) -> str:
    """
    Escapes a number for MarkdownV2 by converting it to string and
    escaping any decimal points.
    """
    return str(number).replace('.', '\\.')


# FUNGSI DATABASE & UTILITAS
DB_PATH = "scans.db"


def list_scans_for_leaderboard(since_date: datetime, chat_id: int):
    """
    Mengambil semua data scan dari database setelah tanggal tertentu, termasuk tanggal scan,
    tergantung pada chat_id yang diberikan.
    """
    from contextlib import closing
    with closing(sqlite3.connect(DB_PATH, timeout=30)) as conn:
        return conn.execute(
            "SELECT user_id, username, token_query, mcap_at_scan, scanned_at FROM scans WHERE scanned_at > ? AND chat_id = ?",
            (since_date.isoformat(), chat_id)).fetchall()


# === DEXSCREENER ONLY ===
async def fetch_current_mcap(query: str) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """
    Hanya ambil data dari DexScreener.
    Return (mcap_usd, token_symbol, chain_id) atau (None,None,None) kalau gagal.
    """
    try:
        if DexScreenerAPI:
            async with DexScreenerAPI() as api:
                results = await api.search_token(query)
                if not results:
                    return None, None, None
                pair = results[0]
                fdv = pair.get("fdv") or pair.get("marketCap") or pair.get("market_cap") or 0
                base = pair.get("baseToken") or {}
                symbol = base.get("symbol") or base.get("name") or query
                chain = pair.get("chainId") or "unknown"
                try:
                    mcap_val = float(fdv or 0)
                except:
                    mcap_val = 0.0
                return mcap_val, symbol, chain
    except Exception as e:
        print("fetch_current_mcap error:", e)
        return None, None, None

    return None, None, None


# LOGIKA PNL LEADERBOARD & STATISTIK
async def get_leaderboard_data(period: str, chat_id: int) -> tuple:
    """
    Mengambil dan menghitung PnL, mengembalikan data lengkap.
    Memastikan hanya satu entri per token per user.
    """
    time_delta = {'1D': 1, '3D': 3, '1W': 7, '3W': 21}.get(period, 1)
    since_date = datetime.now(timezone.utc) - timedelta(days=time_delta)
    rows = await asyncio.to_thread(list_scans_for_leaderboard, since_date, chat_id)

    # Filter data agar hanya ada satu entri per (user_id, token_query)
    unique_scans = {}
    for user_id, username, token_query, mcap_at_scan, scanned_at in rows:
        key = (user_id, token_query)
        if key not in unique_scans or scanned_at < unique_scans[key]['scanned_at']:
            unique_scans[key] = {
                'username': username,
                'user_id': user_id,
                'mcap_at_scan': mcap_at_scan,
                'scanned_at': scanned_at,
                'token_query': token_query
            }

    all_pnl_values = []
    hit_pnl_values = []
    leaderboard_scans = []

    unique_queries = list(set(entry['token_query'] for entry in unique_scans.values()))
    tasks = [fetch_current_mcap(query) for query in unique_queries]
    results = await asyncio.gather(*tasks)

    mcap_cache = dict(zip(unique_queries, results))

    for key, row in unique_scans.items():
        user_id, token_query = key
        username = row['username']
        mcap_at_scan = row['mcap_at_scan']

        current_mcap, cur_sym, chain = mcap_cache.get(token_query, (None, None, None))

        # 🚨 FILTER: skip kalau chain unknown (bukan Dexscreener valid)
        if not chain or chain == "unknown":
            continue

        if current_mcap is not None and mcap_at_scan is not None and mcap_at_scan > 0:
            pnl = (current_mcap / mcap_at_scan)
            all_pnl_values.append(pnl)

            if pnl > 1:
                hit_pnl_values.append(pnl)

                leaderboard_scans.append({
                    'pnl': pnl,
                    'chain': chain or '',
                    'token_query': token_query,
                    'symbol': cur_sym,
                    'username': username,
                    'user_id': user_id
                })

    # ✅ Filter hanya 1 entri per symbol dengan PnL tertinggi
    filtered_scans_by_symbol = {}
    for scan in leaderboard_scans:
        symbol = scan.get('symbol', 'N/A')
        pnl = scan['pnl']
        if symbol not in filtered_scans_by_symbol or pnl > filtered_scans_by_symbol[symbol]['pnl']:
            filtered_scans_by_symbol[symbol] = scan

    leaderboard_scans = list(filtered_scans_by_symbol.values())

    # Urutkan dari PnL terbesar
    leaderboard_scans.sort(key=lambda s: s['pnl'], reverse=True)

    # Ambil top 10
    final_list = leaderboard_scans[:10]

    return final_list, all_pnl_values, hit_pnl_values


def calculate_group_stats(all_pnl: list, hit_pnl: list) -> dict:
    """Menghitung statistik grup dari data PnL yang ada."""
    total_calls = len(all_pnl)
    total_return = sum(hit_pnl)
    hit_calls = len(hit_pnl)

    if total_calls == 0:
        return {'calls': 0, 'hit_rate': 0, 'median': 0, 'return': 0}

    hit_rate = (hit_calls / total_calls) * 100
    median_pnl = np.median(hit_pnl) if hit_pnl else 0

    return {
        'calls': total_calls,
        'hit_rate': round(hit_rate, 1),
        'median': round(median_pnl, 1),
        'return': round(total_return, 1)
    }


# FUNGSI TEMPLATE DAN HANDLER TELEGRAM
async def get_leaderboard_message(period: str, context, update) -> str:
    CE = Config.CUSTOM_EMOJI_IDS
    SUPPORTED_CHAINS = Config.SUPPORTED_CHAINS

    chat_id = update.effective_chat.id

    leaderboard_data, all_pnl_values, hit_pnl_values = await get_leaderboard_data(period, chat_id)

    stats = calculate_group_stats(all_pnl_values, hit_pnl_values)
    stats_avg_return = round(stats['return'] / stats['calls'], 1) if stats['calls'] > 0 else 0

    trophy_char = CE.get('trophy', {}).get('char', '🏆')

    header = f"{escape_markdown(trophy_char, version=2)} *Leaderboard*\n\n"
    header += f"*📊 Group Stats*\n"
    header += f"\\ ├ `Period`\\  {escape_markdown(period, version=2)}\n"
    header += f"\\ ├ `Calls`\\  {escape_markdown(str(stats['calls']), version=2)}\n"
    header += f"\\ ├ `Hit Rate` {escape_markdown(str(stats['hit_rate']), version=2)}\%\n"
    header += f"\\ ├ `Median`\\  {escape_markdown(str(stats['median']), version=2)}x\n"
    header += f"\\ └ `Return`\\  {escape_markdown(str(stats['return']), version=2)}x \(Avg: {escape_markdown(str(stats_avg_return), version=2)}x\)\n\n"

    body = ""
    if not leaderboard_data:
        body = escape_markdown("no calls found.", version=2)
    else:
        for i, scan in enumerate(leaderboard_data):
            rank = i + 1
            name_esc = escape_markdown(scan['username'], version=2)
            user_id = scan['user_id']

            chain_info = SUPPORTED_CHAINS.get(scan['chain'])
            chain_emoji = chain_info['emoji'] if chain_info else '⚪'

            token_symbol = escape_markdown(scan.get('symbol', 'N/A'), version=2)

            pnl_value = f"{scan['pnl']:.1f}"
            pnl_esc = escape_markdown(pnl_value, version=2)

            encoded_token_query = quote(scan['token_query'])
            price_url = f"https://dexscreener.com/{scan['chain']}/{encoded_token_query}"

            body += f"{escape_markdown(str(rank), version=2)}\\. {chain_emoji} [{token_symbol}]({price_url}) ⪢[{name_esc}](tg://user?id={user_id})⪡ `{pnl_esc}x`\n"

    footer = "\n📚 [Fourtis Live](https://t.me/FourtisScan)"
    return header + body + footer


def get_leaderboard_keyboard(current_period: str) -> InlineKeyboardMarkup:
    buttons = []
    periods = ["1D", "3D", "1W", "3W"]
    for period in periods:
        button_text = f"✅ {period}" if period == current_period else period
        buttons.append(
            InlineKeyboardButton(
                button_text,
                callback_data=f"leaderboard_{period}"
            )
        )
    return InlineKeyboardMarkup([buttons])


async def leaderboard_command(update, context):
    query = update.callback_query
    if query:
        await query.answer()
        period = query.data.split('_')[1]
        message = await get_leaderboard_message(period, context, update)
        keyboard = get_leaderboard_keyboard(period)

        await context.bot.edit_message_text(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text=message,
            reply_markup=keyboard,
            parse_mode='MarkdownV2'
        )
    else:
        period = '1D'
        message = await get_leaderboard_message(period, context, update)
        keyboard = get_leaderboard_keyboard(period)

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message,
            reply_markup=keyboard,
            parse_mode='MarkdownV2'
        )
