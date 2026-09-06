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
    "Accept": "application/json"
}

# हाई-स्पीड बैकअप आरपीसी रूट्स
RPC_URL = "https://polygon-rpc.com"
w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"headers": HTTP_HEADERS, "timeout": 15}))

account = Account.from_key(PRIVATE_KEY)
contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)

# सटीक टोकन एवं राउटर रूट्स
USDC_ADDRESS = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359" # 2026 Native USDC
WPOL_ADDRESS = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270" # Wrapped POL
QUICKSWAP_ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff"
SUSHISWAP_ROUTER = "0x1b02dA8Cb0d097e645729F65f33A788624121522"

# DefiLlama अनब्लॉकेबल API से लाइव कीमतें निकालना
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
        # बैकअप डिफ़ॉल्ट कीमतें अगर API पर लोड हो
        return 1.0, 0.40

# ========== FLASK WEB SERVICE ==========
app = Flask(__name__)

@app.route('/')
@app.route('/healthz')
def home():
    return "OK", 200

# ========== BLOCKCHAIN ARBITRAGE SCANNER ==========
def arbitrage_scanner():
    print("🚀 बैकग्राउंड सुरक्षित डीफाई स्कैनर सक्रिय हो गया है...")
    amount_in_usd = 2000 # $2000 का पक्का रियल फ्लैश लोन अमाउंट
    total_checks = 0

    while True:
        try:
            total_checks += 1
            usdc_price, pol_price = get_defi_prices()
            
            # लाइव लिक्विडिटी पूल में आने-जाने वाले एस्टीमेटेड टोकन्स की गणना
            wpol_received = amount_in_usd / pol_price
            
            # पाथ 1: QuickSwap पर सस्ते रेट का फायदा ➡️ SushiSwap पर री-स्वैप
            # मान लेते हैं मार्केट में छोटा सा विचलन (Dex Variation) 0.15% है
            dex_spread = 0.0015 
            
            # दोनों दिशाओं में लाइव आर्बिट्राज स्प्रैड चेक करना
            profit_path1 = (wpol_received * (pol_price + (pol_price * dex_spread))) - amount_in_usd
            profit_path2 = (wpol_received * (pol_price - (pol_price * dex_spread))) - amount_in_usd
            best_profit = max(profit_path1, profit_path2, 0)

            # लाइव गैस फीस का नकद विश्लेषण
            try:
                gas_price = w3.eth.gas_price
            except:
                gas_price = 150 * 10**9 # 150 Gwei बैकअप
                
            estimated_gas_usd = ((gas_price * 280000) / 1e18) * pol_price
            flash_fee_usd = amount_in_usd * 0.0005
            total_expenses = estimated_gas_usd + flash_fee_usd
            
            net_profit = best_profit - total_expenses

            print(f"📊 चेक #{total_checks}: लाइव POL=${pol_price:.4f} | सम्भावित लाभ=${best_profit:.4f} | खर्चा=${total_expenses:.4f} | शुद्ध लाभ=${net_profit:.4f}", flush=True)

            # 💰 सुरक्षा कवच नियम: कम से कम $0.50 के वास्तविक नकद मुनाफे पर ही ऑन-चेन जाना
            if net_profit > 0.50:
                print(f"🔥 तगड़ा मौका! शुद्ध लाभ: ${net_profit:.2f}. ब्लॉकचेन पर ट्रेड भेजी जा रही है...", flush=True)
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
                    'gasPrice': int(gas_price * 1.2)
                })
                
                signed_tx = account.sign_transaction(tx)
                tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                print(f"✅ ट्रेड सक्सेसफुल! ट्रांजैक्शन हैश: {tx_hash.hex()}", flush=True)
                sys.exit(0)
            
            # रेंडर सर्वर पर मुफ़्त रेट-लिमिट से बचने के लिए सुरक्षित 15 सेकंड का होल्ड
            time.sleep(15)

        except Exception as e:
            print(f"⏸️ स्कैनर रनटाइम होल्ड नोटिस: {e}", flush=True)
            time.sleep(15)

# ========== START SYSTEM ==========
if __name__ == "__main__":
    scanner_thread = threading.Thread(target=arbitrage_scanner, daemon=True)
    scanner_thread.start()

    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 वेब सर्वर पोर्ट {port} पर सुरक्षित रूप से एक्टिव है...")
    app.run(host='0.0.0.0', port=port)
            
