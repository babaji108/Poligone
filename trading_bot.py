import os
import time
import sys
import requests
from web3 import Web3
from eth_account import Account
from flask import Flask
import threading

# ========== CONFIG ==========
ALCHEMY_API_KEY = "JD8Ipwo3WY8dpAi4MVQMX"
RPC_URL = f"https://polygon-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

if not PRIVATE_KEY:
    print("❌ PRIVATE_KEY सेट नहीं है!")
    sys.exit(1)

CONTRACT_ADDRESS = "0xBd6FB986340404B8068Fd14F70662366E3c87999"
CONTRACT_ABI = [
    {"inputs": [{"internalType": "address", "name": "tokenIn", "type": "address"}, {"internalType": "uint256", "name": "amount", "type": "uint256"}, {"internalType": "address", "name": "swapRouter", "type": "address"}, {"internalType": "address", "name": "tokenOut", "type": "address"}, {"internalType": "uint256", "name": "minOutAmount", "type": "uint256"}], "name": "startFlashLoan", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"internalType": "address", "name": "token", "type": "address"}], "name": "withdraw", "outputs": [], "stateMutability": "nonpayable", "type": "function"}
]

# ========== WEB3 SETUP ==========
w3 = Web3(Web3.HTTPProvider(RPC_URL))
if not w3.is_connected():
    print("❌ Alchemy से कनेक्ट नहीं हो पा रहा.")
    sys.exit(1)

account = Account.from_key(PRIVATE_KEY)
contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)

# ========== PAIRS (USDC/WMATIC) ==========
PAIR_QS = "0x853ee4b2a13f8a742d64c8f088be7ba2131f670d"
PAIR_SS = "0x34965ba0ac2451a34a0471f04cca3f990b8dea27"

# ========== RPC CALL FUNCTION ==========
def rpc_call(method, params):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    res = requests.post(RPC_URL, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
    return res.json()

# ========== GET RESERVES ==========
def get_reserves(pair):
    data = "0x0902f1ac"  # getReserves() function signature
    result = rpc_call("eth_call", [{"to": pair, "data": data}, "latest"])
    if "result" in result and len(result["result"]) >= 192:
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

# ========== FLASK ==========
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot is running!"

# ========== MAIN LOOP ==========
def run_flask():
    app.run(host='0.0.0.0', port=10003)

if __name__ == "__main__":
    print("✅ बॉट तैयार है! USDC/WMATIC (सही गणना के साथ) स्कैन शुरू...")
    threading.Thread(target=run_flask, daemon=True).start()

    amount_in = int(100 * 10**6) # 100 USDC
    total_checks = 0

    while True:
        try:
            total_checks += 1
            r0_qs, r1_qs = get_reserves(PAIR_QS)
            r0_ss, r1_ss = get_reserves(PAIR_SS)

            if r0_qs and r1_qs and r0_ss and r1_ss:
                qs_out = get_amount_out(amount_in, r0_qs, r1_qs)
                ss_out = get_amount_out(amount_in, r0_ss, r1_ss)

                qs_usdc = qs_out / 1e6
                ss_usdc = ss_out / 1e6

                diff = abs(qs_usdc - ss_usdc)
                avg = (qs_usdc + ss_usdc) / 2
                diff_percent = (diff / avg) * 100 if avg > 0 else 0

                print(f"📊 चेक #{total_checks}: QS={qs_usdc:.4f}, SS={ss_usdc:.4f}, अंतर={diff_percent:.3f}%", flush=True)

                # ⚠️ यहाँ थ्रेशोल्ड बदल सकते हैं. 0.3, 0.5 या 1.0 डाल सकते हैं.
                if diff_percent > 1.0:
                    print("💰 असली प्रॉफिट निश्चित है! ट्रांजैक्शन भेजी जा रही है...", flush=True)
                    
                    tx = contract.functions.startFlashLoan(
                        "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", # USDC
                        int(100 * 10**6),                         
                        "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff", # QuickSwap
                        "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270", # WMATIC
                        0
                    ).build_transaction({
                        'from': account.address,
                        'nonce': w3.eth.get_transaction_count(account.address),
                        'gas': 300000,
                        'gasPrice': w3.eth.gas_price
                    })
                    signed_tx = account.sign_transaction(tx)
                    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                    print(f"✅ ट्रेड भेजी गई! हैश: {tx_hash.hex()}", flush=True)
                    sys.exit(0)
                else:
                    print(f"⏳ प्रॉफिट कम ({diff_percent:.3f}%), 0 गैस खर्च।", flush=True)
            else:
                print("⏸️ रिज़र्व डेटा नहीं मिला।", flush=True)

            time.sleep(15)

        except Exception as e:
            print(f"⏸️ एरर: {e}", flush=True)
            time.sleep(15)
