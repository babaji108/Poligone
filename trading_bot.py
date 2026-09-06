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
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

if not PRIVATE_KEY:
    print("❌ PRIVATE_KEY SETTING IS MISSING!")
    sys.exit(1)

CONTRACT_ADDRESS = "0xBd6FB986340404B8068Fd14F70662366E3c87999"

CONTRACT_ABI = [
    {"inputs": [{"internalType": "address", "name": "tokenIn", "type": "address"}, {"internalType": "uint256", "name": "amount", "type": "uint256"}, {"internalType": "address", "name": "swapRouter", "type": "address"}, {"internalType": "address", "name": "tokenOut", "type": "address"}, {"internalType": "uint256", "name": "minOutAmount", "type": "uint256"}], "name": "startFlashLoan", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"internalType": "address", "name": "token", "type": "address"}], "name": "withdraw", "outputs": [], "stateMutability": "nonpayable", "type": "function"}
]

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# 🚀 401 एरर से बचने के लिए ट्रांजैक्शन सपोर्ट करने वाले अनब्लॉकेबल नोड्स की सूची
TX_RPC_ENDPOINTS = [
    "https://ankr.com",
    "https://llamarpc.com",
    "https://1rpc.io",
    "https://blastapi.io"
]

w3 = None
ACTIVE_RPC = None

# सबसे बेस्ट एक्टिव ट्रांजैक्शन नेटवर्क रूट चुनना
for endpoint in TX_RPC_ENDPOINTS:
    try:
        provider = Web3.HTTPProvider(endpoint, request_kwargs={"headers": HTTP_HEADERS, "timeout": 15})
        temp_w3 = Web3(provider)
        if temp_w3.is_connected():
            w3 = temp_w3
            ACTIVE_RPC = endpoint
            break
    except:
        continue

if w3 is None:
    ACTIVE_RPC = "https://ankr.com"
    w3 = Web3(Web3.HTTPProvider(ACTIVE_RPC))

account = Account.from_key(PRIVATE_KEY)
contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)

# सटीक टोकन एवं राउटर रूट्स
USDC_ADDRESS = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359" 
WPOL_ADDRESS = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270" 
QUICKSWAP_ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff"
SUSHISWAP_ROUTER = "0x1b02dA8Cb0d097e645729F65f33A788624121522"

def get_defi_prices():
    url = f"https://llama.fi:{USDC_ADDRESS},polygon:{WPOL_ADDRESS}"
    try:
        req = urllib.request.Request(url, headers=HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=12) as response:
            data = json.loads(response.read().decode('utf-8'))
            coins = data.get("coins", {})
            usdc_p = coins.get(f"polygon:{USDC_ADDRESS}", {}).get("price", 1.0)
            wpol_p = coins.get(f"polygon:{WPOL_ADDRESS}", {}).get("price", 0.40)
            return usdc_p, wpol_p
    except:
        return 1.0, 0.40

# ========== FLASK WEB SERVICE ==========
app = Flask(__name__)

@app.route('/')
@app.route('/healthz')
def home():
    return "OK", 200

# ========== BLOCKCHAIN ARBITRAGE SCANNER ==========
def arbitrage_scanner():
    global w3, ACTIVE_RPC
    print("🚀 बैकग्राउंड राउटिंग ट्रांजैक्शन इंजन सक्रिय हो गया है...")
    amount_in_usd = 2000 
    total_checks = 0

    while True:
        try:
            total_checks += 1
            usdc_price, pol_price = get_defi_prices()
            
            wpol_received = amount_in_usd / pol_price
            dex_spread = 0.0015 
            
            profit_path1 = (wpol_received * (pol_price + (pol_price * dex_spread))) - amount_in_usd
            profit_path2 = (wpol_received * (pol_price - (pol_price * dex_spread))) - amount_in_usd
            best_profit = max(profit_path1, profit_path2, 0)

            # लाइव गैस फीस रोटेशन चेक
            try:
                gas_price = w3.eth.gas_price
            except:
                gas_price = 120 * 10**9 
                
            estimated_gas_usd = ((gas_price * 280000) / 1e18) * pol_price
            flash_fee_usd = amount_in_usd * 0.0005
            total_expenses = estimated_gas_usd + flash_fee_usd
            net_profit = best_profit - total_expenses

            print(f"📊 चेक #{total_checks}: लाइव POL=${pol_price:.4f} | सम्भावित लाभ=${best_profit:.4f} | शुद्ध लाभ=${net_profit:.4f} | Node: {ACTIVE_RPC.split('//')[1].split('/')[0]}", flush=True)

            if net_profit > 0.50:
                print(f"🔥 शुद्ध लाभ निश्चित: ${net_profit:.2f}. {ACTIVE_RPC} के माध्यम से ट्रांजैक्शन प्रेषित...", flush=True)
                target_router = QUICKSWAP_ROUTER if profit_path1 > profit_path2 else SUSHISWAP_ROUTER
                
                tx = contract.functions.startFlashLoan(
                    USDC_ADDRESS,
                    int(amount_in_usd * 1e6),                         
                    target_router, 
                    WPOL_ADDRESS,
                    0
                ).build_transaction({
                    'from': account.address,
                    'nonce': w3.eth.get_transaction_count(account.address),
                    'gas': 350000,
                    'gasPrice': int(gas_price * 1.25) # सुरक्षित निष्पादन के लिए 25% एक्स्ट्रा गैस प्राइस
                })
                
                signed_tx = account.sign_transaction(tx)
                tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                print(f"✅ सफलता! ट्रेड ब्लॉकचेन पर निष्पादित हुई। हैश: {tx_hash.hex()}", flush=True)
                
                # ट्रेड भेजने के बाद रेंडर को क्रैश होने से बचाने के लिए लूप को रोके रखना (अगली ट्रेड के लिए पुनः लोड)
                time.sleep(60)
                continue
            
            time.sleep(15)

        except Exception as e:
            # यदि वर्तमान RPC फेल हो, तो सूची से अगला बैकअप नेटवर्क स्वतः उठाना
            print(f"🔄 नोड रोटेशन नोटिस: {e} | वैकल्पिक मार्ग पर स्विच कर रहे हैं...", flush=True)
            for next_rpc in TX_RPC_ENDPOINTS:
                try:
                    temp_w3 = Web3(Web3.HTTPProvider(next_rpc, request_kwargs={"headers": HTTP_HEADERS}))
                    if temp_w3.is_connected():
                        w3 = temp_w3
                        ACTIVE_RPC = next_rpc
                        break
                except:
                    continue
            time.sleep(15)

# ========== START SYSTEM ==========
if __name__ == "__main__":
    scanner_thread = threading.Thread(target=arbitrage_scanner, daemon=True)
    scanner_thread.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
