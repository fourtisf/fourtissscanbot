import aiohttp
import asyncio
import os
import re
from dotenv import load_dotenv
from typing import Any, Dict, List, Optional

# ==========================
# Load environment variables
# ==========================
load_dotenv()
# Gunakan kembali API key terpisah sesuai permintaan
# Satu key Etherscan (API V2) dipakai untuk ETH, BSC dan Base
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
COVALENT_API_KEY = os.getenv("COVALENT_API_KEY")

# ==========================
# API and RPC URLs & Chain IDs
# ==========================
API_URLS = {
    "etherscan_v2": "https://api.etherscan.io/v2/api",
    "helius_rpc": "https://mainnet.helius-rpc.com/",
    "dexscreener": "https://api.dexscreener.com/latest/dex/tokens/",
    "geckoterminal": "https://api.geckoterminal.com/api/v2/networks/solana/tokens/",
    "rugcheck": "https://api.rugcheck.xyz/v1/tokens/"
}

API_KEYS = {
    "helius": HELIUS_API_KEY
}

CHAIN_IDS = {
    "ethereum": 1,
    "bsc": 56,
    "base": 8453
}


# ==========================
# Helper Functions
# ==========================
def dbg(*args: Any) -> None:
    """Debug helper to print messages."""
    try:
        print(*args)
    except Exception:
        pass


def get_explorer_link(chain: str, address: str) -> str:
    """Generates explorer link for a given chain and address."""
    if not address or address == "N/A":
        return "#"

    chain = chain.lower()
    links = {
        "ethereum": f"https://etherscan.io/address/{address}",
        "bsc": f"https://bscscan.com/address/{address}",
        "base": f"https://basescan.org/address/{address}",
        "solana": f"https://solscan.io/account/{address}",
        "tron": f"https://tronscan.io/#/address/{address}",
    }
    return links.get(chain, "#")


def _redact(url: str) -> str:
    """Sembunyikan API key di URL sebelum ditulis ke log."""
    return re.sub(r"((?:api[-_]?key|key)=)[^&]+", r"\1***", url, flags=re.IGNORECASE)


async def safe_json(session: aiohttp.ClientSession, method: str, url: str, **kwargs) -> Optional[Dict[str, Any]]:
    """Safe wrapper for API requests, returns JSON data."""
    try:
        async with session.request(method, url, **kwargs) as r:
            txt = await r.text()
            dbg(f"[DEBUG {method.upper()}] {_redact(url)} -> {r.status} {txt[:200]}")
            r.raise_for_status()
            return await r.json()
    except Exception as e:
        dbg(f"[!] safe_json error {_redact(url)}: {e}")
        return None


async def fetch_pair_address(session: aiohttp.ClientSession, chain: str, token_address: str) -> Optional[str]:
    """
    Fetches the pair address for a given token from Dexscreener API.
    """
    url = f"{API_URLS['dexscreener']}{chain}/{token_address}"
    data = await safe_json(session, "get", url)

    if data and data.get("pairs"):
        pair_data = data["pairs"][0]
        return pair_data.get("pairAddress")

    dbg(f"[!] Gagal menemukan pair address untuk {token_address}")
    return None


async def is_address_a_contract(session: aiohttp.ClientSession, chain: str, address: str) -> bool:
    """Checks if an address is a contract by looking at its code."""
    chain_id = CHAIN_IDS.get(chain)

    if not ETHERSCAN_API_KEY or not chain_id:
        return False

    url = f"{API_URLS['etherscan_v2']}?chainid={chain_id}&module=proxy&action=eth_getCode&address={address}&tag=latest&apikey={ETHERSCAN_API_KEY}"
    data = await safe_json(session, "get", url)

    if data and data.get("result") and data["result"] != "0x":
        return True

    return False


# ==========================
# Core Security Functions (EVM)
# ==========================
async def check_dexpaid_api(session: aiohttp.ClientSession, chain: str, token_address: str) -> str:
    """Checks DexPaid status for a token."""
    url = f"https://api.dexscreener.com/orders/v1/{chain}/{token_address}"
    data = await safe_json(session, "get", url)

    if data and isinstance(data, list) and data[0].get("status") == "approved":
        dbg(f"[DEXPAID] {chain}:{token_address} -> 🟢 PAID")
        return "🟢 PAID"

    dbg(f"[DEXPAID] {chain}:{token_address} -> 🔴 UNPAID")
    return "🔴 UNPAID"


async def fetch_evm_info(session: aiohttp.ClientSession, chain: str, contract: str) -> Dict[str, Any]:
    """Fetches creator and holders for EVM chains (ETH, BSC, Base)."""
    creator = "N/A"
    chain_id = CHAIN_IDS.get(chain)

    if ETHERSCAN_API_KEY and chain_id:
        base_url = f"{API_URLS['etherscan_v2']}?chainid={chain_id}"
        try:
            url_creator = f"{base_url}&module=contract&action=getcontractcreation&contractaddresses={contract}&apikey={ETHERSCAN_API_KEY}"
            data = await safe_json(session, "get", url_creator)
            if data and data.get("status") == "1":
                res = data.get("result", [])
                if res:
                    creator = res[0].get("contractCreator", "N/A")
                    dbg(f"[DEBUG] Creator ditemukan dari Etherscan V2 ({chain}): {creator}")
            elif data:
                dbg(f"[!] Etherscan V2 ({chain}) getcontractcreation: {data.get('result')}")
        except Exception as e:
            dbg(f"[!] Error fetching {chain} creator with Etherscan V2 API: {e}")

        if creator == "N/A":
            try:
                url_txs = f"{base_url}&module=account&action=txlist&address={contract}&startblock=0&endblock=99999999&page=1&offset=1&sort=asc&apikey={ETHERSCAN_API_KEY}"
                data_txs = await safe_json(session, "get", url_txs)
                if data_txs and data_txs.get("status") == "1":
                    txs = data_txs.get("result", [])
                    if txs:
                        creator = txs[0].get("from", "N/A")
                        dbg(f"[DEBUG] Creator ditemukan dari Etherscan V2 txlist ({chain}): {creator}")
            except Exception as e:
                dbg(f"[!] Error fetching {chain} creator from Etherscan V2 txlist: {e}")

    # --- Perubahan di sini: Mengubah page-size dari 5 ke 10 ---
    holders = []
    try:
        # Covalent opsional: tanpa key, top holders dilewati
        if chain_id and COVALENT_API_KEY:
            url_holders = f"https://api.covalenthq.com/v1/{chain_id}/tokens/{contract}/token_holders/?page-size=10&key={COVALENT_API_KEY}"
            data = await safe_json(session, "get", url_holders)
            if data and "data" in data and "items" in data["data"]:
                for h in data["data"]["items"][:10]:
                    addr = h.get("address", "N/A")
                    bal = int(h.get("balance", 0))
                    total_supply = float(h.get("total_supply", 1))
                    perc = round((bal / total_supply) * 100, 4) if total_supply else 0
                    holders.append({"address": addr, "percentage": perc})
    except Exception as e:
        dbg(f"[!] Error fetching {chain} holders: {e}")
    while len(holders) < 10:
        holders.append({"address": "N/A", "percentage": 0})
    return {"holders": holders, "creator": creator}


# ==========================
# Core Security Functions (Solana)
# ==========================
async def fetch_solana_info(session: aiohttp.ClientSession, token_mint: str) -> Dict[str, Any]:
    """Fetches creator and holders for Solana using a tiered approach."""
    helius_key = API_KEYS.get("helius")
    if not helius_key:
        dbg("[!] Helius API key not found.")
        return {"holders": [], "creator": "N/A"}

    creator = "N/A"
    holders = []
    url_rpc = f"https://mainnet.helius-rpc.com/?api-key={helius_key}"

    # Strategi 1: Cek getAsset (DAS API)
    try:
        payload_get_asset = {
            "jsonrpc": "2.0",
            "id": "get-asset",
            "method": "getAsset",
            "params": {"id": token_mint}
        }
        data_asset = await safe_json(session, "post", url_rpc, json=payload_get_asset)
        if data_asset and "result" in data_asset and data_asset["result"] and "ownership" in data_asset["result"]:
            creator = data_asset["result"]["ownership"].get("owner")
            if creator:
                dbg(f"[DEBUG] Creator ditemukan dari getAsset: {creator}")
    except Exception as e:
        dbg(f"[!] Gagal mencari pencipta dari getAsset: {e}")

    # Strategi 2: Cek getTokenLargestAccounts
    if not creator or creator == "N/A":
        try:
            payload_largest = {
                "jsonrpc": "2.0",
                "id": "get-token-largest-accounts",
                "method": "getTokenLargestAccounts",
                "params": [token_mint]
            }
            data_largest = await safe_json(session, "post", url_rpc, json=payload_largest)

            if data_largest and "result" in data_largest and data_largest["result"]["value"]:
                first_largest_account_address = data_largest["result"]["value"][0].get("address")
                if first_largest_account_address:
                    payload_owner = {
                        "jsonrpc": "2.0",
                        "id": "get-account-info",
                        "method": "getAccountInfo",
                        "params": [first_largest_account_address, {"encoding": "jsonParsed"}]
                    }
                    data_owner = await safe_json(session, "post", url_rpc, json=payload_owner)
                    if data_owner and "result" in data_owner and data_owner["result"]["value"]:
                        owner_address = data_owner["result"]["value"]["data"]["parsed"]["info"].get("owner")
                        if owner_address:
                            creator = owner_address
                            dbg(f"[DEBUG] Creator ditemukan dari getTokenLargestAccounts: {creator}")
        except Exception as e:
            dbg(f"[!] Gagal mencari pencipta dari getTokenLargestAccounts: {e}")

    # Strategi 3: Fallback ke pencarian transaksi mint token
    if not creator or creator == "N/A":
        try:
            payload_sig = {
                "jsonrpc": "2.0",
                "id": "get-first-signature",
                "method": "getSignaturesForAddress",
                "params": [token_mint, {"limit": 1}],
            }
            data_sig = await safe_json(session, "post", url_rpc, json=payload_sig)

            if data_sig and "result" in data_sig and data_sig["result"]:
                first_signature = data_sig["result"][0].get("signature")

                if first_signature:
                    payload_tx = {
                        "jsonrpc": "2.0",
                        "id": "get-tx-details",
                        "method": "getTransaction",
                        "params": [first_signature, {"maxSupportedTransactionVersion": 0, "commitment": "finalized"}],
                    }
                    data_tx = await safe_json(session, "post", url_rpc, json=payload_tx)

                    if data_tx and "result" in data_tx:
                        tx_result = data_tx["result"]
                        meta = tx_result["meta"]

                        if meta and meta.get("err"):
                            dbg(f"[!] Transaction has an error. Falling back to balance analysis.")
                            balance_changes = {}
                            account_keys = tx_result["transaction"]["message"].get("accountKeys", [])
                            for i, (pre_bal, post_bal) in enumerate(
                                    zip(meta.get("preBalances", []), meta.get("postBalances", []))):
                                diff = pre_bal - post_bal
                                if diff > 1000000 and i < len(account_keys):
                                    balance_changes[account_keys[i]] = diff

                            if balance_changes:
                                creator = max(balance_changes, key=balance_changes.get)

                        else:
                            tx_message = tx_result["transaction"]["message"]
                            account_keys = tx_message.get("accountKeys", [])
                            if account_keys:
                                creator = account_keys[0]

                    if creator and creator != "N/A":
                        dbg(f"[DEBUG] Creator ditemukan dari fallback transaksi mint: {creator}")
        except Exception as e:
            dbg(f"[!] Gagal menemukan pencipta: {e}")

    # Bagian Holder: Ambil holders setelah mencari creator
    try:
        payload_supply = {
            "jsonrpc": "2.0",
            "id": "get-token-supply",
            "method": "getTokenSupply",
            "params": [token_mint],
        }
        data_supply = await safe_json(session, "post", url_rpc, json=payload_supply)
        if data_supply and "result" in data_supply and "value" in data_supply["result"]:
            total_supply = float(data_supply["result"]["value"]["amount"])
        else:
            total_supply = 1

        payload_largest = {
            "jsonrpc": "2.0",
            "id": "get-token-largest-accounts",
            "method": "getTokenLargestAccounts",
            "params": [token_mint],
        }
        data_largest = await safe_json(session, "post", url_rpc, json=payload_largest)

        if data_largest and "result" in data_largest and "value" in data_largest["result"]:
            # --- Perubahan di sini: Mengubah batasan dari 5 ke 10 ---
            top_accounts = data_largest["result"]["value"][:10]

            for item in top_accounts:
                account_address = item.get("address", "N/A")
                balance = float(item.get("amount", 0))
                percentage = 0.0
                if total_supply > 0:
                    percentage = (balance / total_supply) * 100

                owner_address = "N/A"
                if account_address != "N/A":
                    payload_owner = {
                        "jsonrpc": "2.0",
                        "id": "get-account-info",
                        "method": "getAccountInfo",
                        "params": [account_address, {"encoding": "jsonParsed"}],
                    }
                    data_owner = await safe_json(session, "post", url_rpc, json=payload_owner)

                    if data_owner and "result" in data_owner and "value" in data_owner["result"] and \
                            data_owner["result"]["value"]:
                        parsed_data = data_owner["result"]["value"].get("data", {}).get("parsed", {})
                        if "info" in parsed_data:
                            owner_address = parsed_data["info"].get("owner", "N/A")

                holders.append({
                    "address": owner_address,
                    "percentage": round(percentage, 4)
                })
    except Exception as e:
        dbg(f"[!] Gagal mengambil pemegang dari Helius: {e}")
    # Pastikan daftar holders berisi 10 item, jika kurang
    while len(holders) < 10:
        holders.append({"address": "N/A", "percentage": 0})

    return {"holders": holders, "creator": creator}


# ==========================
# Off-Chain Search Function
# ==========================
async def find_creator_off_chain(session: aiohttp.ClientSession, token_address: str) -> str:
    """
    Mencari alamat pencipta token di luar blockchain menggunakan pencarian web.
    """
    try:
        # A placeholder function for web scraping or search API calls
        return "N/A"
    except Exception as e:
        dbg(f"[!] Error saat mencari data off-chain: {e}")
        return "N/A"


# ==========================
# Pencarian via GeckoTerminal
# ==========================
async def find_creator_via_geckoterminal(session: aiohttp.ClientSession, token_address: str) -> str:
    """Finds the token creator via GeckoTerminal API."""
    try:
        url = f"{API_URLS['geckoterminal']}{token_address}?include=creator"
        data = await safe_json(session, "get", url)

        if data and "included" in data and len(data["included"]) > 0:
            creator_data = data["included"][0]
            if creator_data and creator_data.get("id"):
                dbg(f"[DEBUG] Creator ditemukan dari GeckoTerminal: {creator_data['id']}")
                return creator_data["id"]
    except Exception as e:
        dbg(f"[!] Gagal mengambil data dari GeckoTerminal: {e}")

    dbg("[!] Gagal menemukan creator dari GeckoTerminal.")
    return "N/A"


# ==========================
# Pencarian via RugCheck.xyz
# ==========================
async def find_creator_via_rugcheck(session: aiohttp.ClientSession, token_address: str) -> str:
    """Finds the token creator via RugCheck.xyz API."""
    try:
        url = f"{API_URLS['rugcheck']}{token_address}/report"
        data = await safe_json(session, "get", url)

        if data and "creator" in data:
            creator_address = data["creator"]
            dbg(f"[DEBUG] Creator ditemukan dari RugCheck: {creator_address}")
            return creator_address
    except Exception as e:
        dbg(f"[!] Gagal mengambil data dari RugCheck: {e}")

    dbg("[!] Gagal menemukan creator dari RugCheck.")
    return "N/A"


# ==========================
# Main Security Info Function
# ==========================
async def get_security_info(session: aiohttp.ClientSession, address: str, chain: str) -> str:
    """Main function to get security info for a token."""
    chain = chain.lower()
    dex_status = await check_dexpaid_api(session, chain, address)

    dex_link = f"https://dexscreener.com/{chain}/{address}"
    lens_link = f"https://lens.google.com/uploadbyurl?url=https://dd.dexscreener.com/ds-data/tokens/{chain}/{address}/header.png?key=d05bfe"

    lines = ["🔒 Security"]
    lines.append(f" └ Dex Paid: {dex_status} [info]({dex_link}) • [lens]({lens_link})")

    if chain == "solana":
        pair_address = await fetch_pair_address(session, chain, address)
        if pair_address:
            lines.append(f" ├ Pair: [🅟]({get_explorer_link(chain, pair_address)})")

    if dex_status == "🔴 UNPAID":
        return "\n".join(lines)

    creator = "N/A"
    holders = []

    if chain == "solana":
        creator = await find_creator_via_geckoterminal(session, address)
        if not creator or creator == "N/A":
            dbg("[*] Pencarian GeckoTerminal gagal. Beralih ke RugCheck...")
            creator = await find_creator_via_rugcheck(session, address)

        if not creator or creator == "N/A":
            dbg("[*] Pencarian RugCheck gagal. Beralih ke on-chain (Helius)...")
            info = await fetch_solana_info(session, address)
            creator = info["creator"]
            holders = info["holders"]

        if not creator or creator == "N/A":
            dbg("[*] Pencarian on-chain gagal. Beralih ke pencarian off-chain...")
            creator = await find_creator_off_chain(session, address)

        info = await fetch_solana_info(session, address)
        holders = info["holders"]

    elif chain in ["ethereum", "bsc", "base"]:
        info = await fetch_evm_info(session, chain, address)
        creator = info["creator"]
        holders = info["holders"]

        if not creator or creator == "N/A":
            dbg("[*] Pencarian on-chain gagal. Beralih ke off-chain untuk EVM...")
            creator = await find_creator_off_chain(session, address)

    elif chain == "tron":
        pass

    if holders:
        # --- Perubahan di sini: Mengubah batasan dari 5 ke 10 ---
        holder_links = [f"[{h.get('percentage', 0):.1f}]({get_explorer_link(chain, h.get('address', 'N/A'))})" for h in
                        holders[:10]]
        lines.append(" ├ Top 10 Holders:\n └ " + " • ".join(holder_links))

    if creator and creator != "N/A":
        lines.append(f" ├ Dev : [🅳]({get_explorer_link(chain, creator)})")

    return "\n".join(lines)


# ==========================
# Test Run
# ==========================
if __name__ == "__main__":
    async def test():
        tests = [
            ("0xEc2A4820026e737E039f545CB070be338CB23DF2", "ethereum"),
            ("0x26C98b27aB51Af12C616d2D2Eb99909B6BDE6dde", "bsc"),
            ("0x11a53Fda83739285029099e33FacB282B3C1dBB2", "base"),
            ("4JPyh4ATbE8hfcH7LqhxF3YThsECZm6htmLvMUyrbonk", "solana"),
            ("TXL6rJbvmjD46zeN1JssfgxvSo99qC8MRT", "tron"),
        ]

        async with aiohttp.ClientSession() as session:
            for addr, chain in tests:
                print("==============================================")
                print(f"Test {chain} {addr}")
                try:
                    res = await get_security_info(session, addr, chain)
                    print(res)
                except Exception as e:
                    print(f"Error for {chain}: {e}")


    asyncio.run(test())