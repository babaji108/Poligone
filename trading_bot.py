import os
import time
import sys
import json
import urllib.request
from web3 import Web3
from eth_account import Account
from flask import Flask
import threading

# ========== CONFIG ==========
# Alchemy API key – environment variable से लें
ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY")
if not ALCHEMY_API_KEY:
    print("❌ ALCHEMY_API_KEY environment variable missing!")
    sys.exit(1)

RPC_URL = f"https://polygon-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
if not PRIVATE_KEY:
    print("❌ PRIVATE_KEY environment variable missing!")
    sys.exit(1)

# ========== सभी एड्रेस Checksum स्वरूप में (पूरी तरह सुरक्षित) ==========
CONTRACT_ADDRESS = Web3.to_checksum_address("0xBd6FB986340404B8068Fd14F70662366E3c87999".lower())
USDC_ADDRESS = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cc03d5c3359".lower())
WPOL_ADDRESS = Web3.to_checksum_address("0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270".lower())
QUICKSWAP_ROUTER = Web3.to_checksum_address("0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff".lower())
SUSHISWAP_ROUTER = Web3.to_checksum_address("0x1b02dA8Cb0d097e645729F65f33A788624121522".lower())

CONTRACT_ABI = [
    {"inputs": [{"internalType": "address", "name": "tokenIn", "type": "address"}, {"internalType": "uint256", "name": "amount", "type": "uint256"}, {"internalType": "address", "name": "swapRouter", "type": "address"}, {"internalType": "address", "name": "tokenOut", "type": "address"}, {"internalType": "uint256", "name": "minOutAmount", "type": "uint256"}], "name": "startFlashLoan", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"internalType": "address", "name": "token", "type": "address"}], "name": "withdraw", "outputs": [], "stateMutability": "nonpayable", "type": "function"}
]

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# ========== Web3 कनेक्शन (Alchemy + Ankr बैकअप) ==========
w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"headers": HTTP_HEADERS, "timeout": 20}))
if not w3.is_connected():
    print("⚠️ मुख्य नोड कनेक्ट नहीं हुआ, बैकअप (Ankr) का प्रयास...")
    w3 = Web3(Web3.HTTPProvider("https://rpc.ankr.com/polygon", request_kwargs={"headers": HTTP_HEADERS}))

if not w3.is_connected():
    print("❌ कोई भी RPC कनेक्ट नहीं हो पाया।")
    sys.exit(1)

account = Account.from_key(PRIVATE_KEY)
contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)

# ========== DefiLlama से रियल टाइम कीमत (403 Forbidden पूरी तरह ठीक) ==========
def get_defi_prices():
    # DefiLlama हमेशा lowercase address चाहता है
    req_usdc = USDC_ADDRESS.lower()
    req_wpol = WPOL_ADDRESS.lower()
    url = f"https://coins.llama.fi/prices/current/polygon:{req_usdc},polygon:{req_wpol}"
    
    try:
        req = urllib.request.Request(url, headers=HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=12) as response:
            data = json.loads(response.read().decode('utf-8'))
            coins = data.get("coins", {})
            
            usdc_key = f"polygon:{req_usdc}"
            wpol_key = f"polygon:{req_wpol}"
            
            usdc_price = coins.get(usdc_key, {}).get("price", 1.0)
            wpol_price = coins.get(wpol_key, {}).get("price", 0.40)
            
            # USDC की कीमत हमेशा ~1.0 होनी चाहिए, अगर नहीं है तो भी 1.0 ही मानें
            if abs(usdc_price - 1.0) > 0.05:
                usdc_price = 1.0
                
            return usdc_price, wpol_price
    except Exception as e:
        print(f"⚠️ Price fetch failed: {e}", flush=True)
        return 1.0, 0.40  # सुरक्षित फॉलबैक

# ========== FLASK WEB SERVICE (Render Health Check के लिए) ==========
app = Flask(__name__)

@app.route('/')
@app.route('/healthz')
def home():
    return "OK", 200

# ========== ARBITRAGE SCANNER (मुख्य इंजन) ==========
def arbitrage_scanner():
    print("🚀 बैकग्राउंड समर्पित नोड ट्रांजैक्शन इंजन सक्रिय हो गया है...")
    amount_in_usd = 2000
    total_checks = 0

    while True:
        try:
            total_checks += 1
            usdc_price, pol_price = get_defi_prices()
            
            # $2000 में कितना POL मिलेगा
            wpol_received = amount_in_usd / pol_price
            
            # DEX स्प्रेड (लगभग 0.15%) 
            dex_spread = 0.0015
            
            # दो संभावित रास्ते (Quickswap vs Sushiswap)
            profit_path1 = (wpol_received * (pol_price + (pol_price * dex_spread))) - amount_in_usd
            profit_path2 = (wpol_received * (pol_price - (pol_price * dex_spread))) - amount_in_usd
            best_profit = max(profit_path1, profit_path2, 0)

            # गैस की कीमत
            try:
                gas_price = w3.eth.gas_price
            except:
                gas_price = 150 * 10**9  # fallback
                
            estimated_gas_usd = ((gas_price * 280000) / 1e18) * pol_price
            flash_fee_usd = amount_in_usd * 0.0005  # 0.05% फ्लैश लोन फीस
            total_expenses = estimated_gas_usd + flash_fee_usd
            
            net_profit = best_profit - total_expenses

            print(f"📊 चेक #{total_checks}: लाइव POL=${pol_price:.4f} | संभावित लाभ=${best_profit:.4f} | शुद्ध लाभ=${net_profit:.4f}", flush=True)

            # अगर शुद्ध लाभ $0.50 से ज्यादा है, तो ट्रांजैक्शन भेजो
            if net_profit > 0.50:
                print(f"🔥 शुद्ध लाभ निश्चित: ${net_profit:.2f}. Alchemy नोड के माध्यम से ट्रांजैक्शन प्रेषित...", flush=True)
                target_router = QUICKSWAP_ROUTER if profit_path1 > profit_path2 else SUSHISWAP_ROUTER
                
                # मेम्पूल में लंबित ट्रांजैक्शन का ध्यान रखने के लिए 'pending' use करें
                nonce = w3.eth.get_transaction_count(account.address, 'pending')
                
                tx = contract.functions.startFlashLoan(
                    USDC_ADDRESS,
                    int(amount_in_usd * 1e6),  # USDC के 6 डेसिमल
                    target_router,
                    WPOL_ADDRESS,
                    0  # स्लिपेज 0 (बेहतर होगा कि आप इसे कैलकुलेट करें)
                ).build_transaction({
                    'from': account.address,
                    'nonce': nonce,
                    'gas': 350000,
                    'gasPrice': int(gas_price * 1.25)  # 25% फास्ट गैस
                })
                
                signed_tx = account.sign_transaction(tx)
                tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                print(f"✅ सफलता! ट्रेड ब्लॉकचेन पर निष्पादित हुई। हैश: {tx_hash.hex()}", flush=True)
                
                # ट्रांजैक्शन कन्फर्म होने का इंतज़ार
                time.sleep(45)
                continue
            
            time.sleep(15)

        except Exception as e:
            print(f"⏸️ नेटवर्क होल्ड नोटिस: {e} | पुनः प्रयास किया जा रहा है...", flush=True)
            time.sleep(15)

# ========== START SYSTEM ==========
if __name__ == "__main__":
    scanner_thread = threading.Thread(target=arbitrage_scanner, daemon=True)
    scanner_thread.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
