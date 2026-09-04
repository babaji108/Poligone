import os
import time
import sys
import requests
from web3 import Web3
from eth_account import Account
from flask import Flask
import threading

# ========== CONFIG ==========
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

if not PRIVATE_KEY:
    print("❌ PRIVATE_KEY सेट नहीं है!")
    sys.exit(1)

CONTRACT_ADDRESS = "0xBd6FB986340404B8068Fd14F70662366E3c87999"

CONTRACT_ABI = [
    {"inputs": [{"internalType": "address", "name": "tokenIn", "type": "address"}, {"internalType": "uint256", "name": "amount", "type": "uint256"}, {"internalType": "address", "name": "swapRouter", "type": "address"}, {"internalType": "address", "name": "tokenOut", "type": "address"}, {"internalType": "uint256", "name": "minOutAmount", "type": "uint256"}], "name": "startFlashLoan", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"internalType": "address", "name": "token", "type": "address"}], "name": "withdraw", "outputs": [], "stateMutability": "nonpayable", "type": "function"}
]

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type": "application/json"
}

# 🚀 अनब्लॉकेबल हाई-स्पीड सार्वजनिक रास्ते
RPC_ENDPOINTS = [
    "https://polygon-rpc.com",
    "https://llamarpc.com",
    "https://ankr.com"
]

w3 = None
ACTIVE_RPC = None

for endpoint in RPC_ENDPOINTS:
    try:
        provider = Web3.HTTPProvider(endpoint, request_kwargs={"headers": HTTP_HEADERS, "timeout": 15})
        temp_w3 = Web3(provider)
        if temp_w3.is_connected():
            w3 = temp_w3
            ACTIVE_RPC = endpoint
            print(f"✅ कनेक्टेड नेटवर्क: {ACTIVE_RPC}")
            break
    except:
        continue

if w3 is None:
    ACTIVE_RPC = "https://polygon-rpc.com"
    w3 = Web3(Web3.HTTPProvider(ACTIVE_RPC))

account = Account.from_key(PRIVATE_KEY)
contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)

# 🎯 बिल्कुल सटीक पेयर एड्रेस (दोनों USDC/WMATIC के लिए हैं)
PAIR_QS = "0x6e7a5caf0c99a974df9975c2a3968ad88293c042" # QuickSwap WMATIC/USDC Pool
PAIR_SS = "0xcd353b3b4f65c924cc634289839446d3ad39b56f" # SushiSwap WMATIC/USDC Pool

USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
WMATIC_ADDRESS = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"
QUICKSWAP_ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff"
SUSHISWAP_ROUTER = "0x1b02dA8Cb0d097e645729F65f33A788624121522"

def rpc_call(method, params):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    try:
        res = requests.post(ACTIVE_RPC, json=payload, headers=HTTP_HEADERS, timeout=10)
        return res.json()
    except:
        return {}

def get_reserves(pair):
    data = "0x0902f1ac" # getReserves()
    result = rpc_call("eth_call", [{"to": pair, "data": data}, "latest"])
    if "result" in result and len(result["result"]) >= 192:
        # USDC (6 decimals) और WMATIC (18 decimals) के रिजर्व्स को पहचानना
        r0 = int(result["result"][2:66], 16)
        r1 = int(result["result"][66:130], 16)
        return r0, r1
    return None, None

def get_amount_out(amount_in, reserve_in, reserve_out):
    if reserve_in == 0 or reserve_out == 0:
        return 0
    numerator = reserve_out * amount_in * 997
    denominator = reserve_in * 1000 + amount_in * 997
    return numerator // denominator

def get_pol_price():
    try:
        r0, r1 = get_reserves(PAIR_QS)
        if r0 and r1:
            # 1 POL की लाइव कीमत USD में
            return (r1 / 1e6) / (r0 / 1e18)
    except:
        pass
    return 0.45

# ========== FLASK WEB SERVICE ==========
app = Flask(__name__)

@app.route('/')
@app.route('/healthz')
def home():
    return "OK", 200

# ========== BLOCKCHAIN ARBITRAGE SCANNER ==========
def arbitrage_scanner():
    print("🚀 बैकग्राउंड आर्बिट्राज स्कैनर पूरी तरह सक्रिय हो गया है...")
    amount_in = int(2000 * 10**6) # $2000 का सुरक्षित फ्लैश लोन राशि
    total_checks = 0

    while True:
        try:
            total_checks += 1
            r0_qs, r1_qs = get_reserves(PAIR_QS)
            r0_ss, r1_ss = get_reserves(PAIR_SS)

            if r0_qs and r1_qs and r0_ss and r1_ss:
                # पाथ 1: QuickSwap -> SushiSwap
                wmatic_received_qs = get_amount_out(amount_in, r1_qs, r0_qs) # USDC In, WMATIC Out
                usdc_returned_ss = get_amount_out(wmatic_received_qs, r0_ss, r1_ss) # WMATIC In, USDC Out
                profit_path1 = (usdc_returned_ss - amount_in) / 1e6

                # पाथ 2: SushiSwap -> QuickSwap
                wmatic_received_ss = get_amount_out(amount_in, r1_ss, r0_ss)
                usdc_returned_qs = get_amount_out(wmatic_received_ss, r0_qs, r1_qs)
                profit_path2 = (usdc_returned_qs - amount_in) / 1e6

                best_profit = max(profit_path1, profit_path2)
                
                # लाइव गैस और वास्तविक खर्च गणना
                gas_price = w3.eth.gas_price
                estimated_gas_used = 250000  
                gas_cost_in_pol = (gas_price * estimated_gas_used) / 1e18
                pol_price_usd = get_pol_price()
                gas_cost_in_usd = gas_cost_in_pol * pol_price_usd
                
                flash_loan_fee_usd = (amount_in / 1e6) * 0.0005
                total_expenses = gas_cost_in_usd + flash_loan_fee_usd
                net_profit = best_profit - total_expenses

                print(f"📊 चेक #{total_checks}: सम्भावित प्रॉफिट=${best_profit:.4f}, खर्चा=${total_expenses:.4f}, शुद्ध लाभ=${net_profit:.4f}", flush=True)

                # वास्तविक $0.50 के शुद्ध लाभ पर ही ट्रेड सेंड होगी
                if net_profit > 0.50:
                    print(f"🔥 अवसर मिला! शुद्ध लाभ: ${net_profit:.2f}. ट्रांजैक्शन जा रही है...", flush=True)
                    target_router = QUICKSWAP_ROUTER if profit_path1 > profit_path2 else SUSHISWAP_ROUTER
                    
                    tx = contract.functions.startFlashLoan(
                        USDC_ADDRESS,
                        amount_in,                         
                        target_router, 
                        WMATIC_ADDRESS,
                        0
                    ).build_transaction({
                        'from': account.address,
                        'nonce': w3.eth.get_transaction_count(account.address),
                        'gas': 350000,
                        'gasPrice': int(gas_price * 1.2)
                    })
                    
                    signed_tx = account.sign_transaction(tx)
                    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                    print(f"✅ ट्रेड सक्सेसफुल! हैश: {tx_hash.hex()}", flush=True)
                    sys.exit(0)
                else:
                    if net_profit < 0:
                        print(f"⏳ बाज़ार संतुलित है (शुद्ध लाभ: ${net_profit:.4f})। कोई गैस खर्च नहीं।", flush=True)
                    else:
                        print(f"⏳ लाभ बहुत कम है (${net_profit:.4f})। अवसर की प्रतीक्षा में...", flush=True)
            else:
                print("⏸️ डेटा पुनः प्राप्त करने का प्रयास किया जा रहा है...", flush=True)

            time.sleep(10)

        except Exception as e:
            print(f"⏸️ स्कैनर नोटिस: {e}", flush=True)
            time.sleep(10)

# ========== MAIN SYSTEM ==========
if __name__ == "__main__":
    scanner_thread = threading.Thread(target=arbitrage_scanner, daemon=True)
    scanner_thread.start()

    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 वेब सर्वर पोर्ट {port} पर सुरक्षित रूप से सक्रिय है...")
    app.run(host='0.0.0.0', port=port)
