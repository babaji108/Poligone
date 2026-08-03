import os
import time
import sys
from web3 import Web3
from web3.exceptions import ContractLogicError
from flask import Flask
import threading

# ========== CONFIG ==========
# Alchemy URL (अब आप इसे env से भी ले सकते हैं)
ALCHEMY_URL = "https://polygon-mainnet.g.alchemy.com/v2/JD8Ipwo3WY8dpAi4MVQMX"
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
if not PRIVATE_KEY:
    print("❌ PRIVATE_KEY सेट नहीं है!", flush=True)
    sys.exit(1)

# आपका असली, नया कॉन्ट्रैक्ट एड्रेस
CONTRACT_ADDRESS = "0xBd6FB986340404B8068Fd14F70662366E3c87999"

CONTRACT_ABI = [
    {"inputs": [], "stateMutability": "nonpayable", "type": "constructor"},
    {"inputs": [{"internalType": "address", "name": "tokenIn", "type": "address"}, {"internalType": "uint256", "name": "amount", "type": "uint256"}, {"internalType": "address", "name": "swapRouter", "type": "address"}, {"internalType": "address", "name": "tokenOut", "type": "address"}, {"internalType": "uint256", "name": "minOutAmount", "type": "uint256"}], "name": "startFlashLoan", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"internalType": "address", "name": "token", "type": "address"}], "name": "withdraw", "outputs": [], "stateMutability": "nonpayable", "type": "function"}
]
# ==================================

w3 = Web3(Web3.HTTPProvider(ALCHEMY_URL))
if not w3.is_connected():
    print("❌ Alchemy से कनेक्ट नहीं हो पा रहा.", flush=True)
    sys.exit(1)

account = w3.eth.account.from_key(PRIVATE_KEY)
contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)

TOKEN_IN = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174" # Polygon USDC
AMOUNT = 1000
SWAP_ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff" # QuickSwap Router
TOKEN_OUT = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270" # WMATIC
MIN_OUT = 0

# ========== FLASK ==========
app = Flask(__name__)

@app.route('/')
def home():
    return "Safe Arbitrage Bot is running!"

@app.route('/status')
def status():
    return f"Bot is alive and scanning the market."

# ========== MAIN LOOP ==========
def run_flask():
    app.run(host='0.0.0.0', port=10000)

if __name__ == "__main__":
    print("✅ सुरक्षित बॉट शुरू हो गया है, 0 गैस में स्कैन चालू...", flush=True)
    
    # Flask को बैकग्राउंड में चलाएँ (Cron-job के लिए जरूरी)
    threading.Thread(target=run_flask, daemon=True).start()

    while True:
        try:
            # बिना गैस के सिम्युलेशन (0 गैस)
            contract.functions.startFlashLoan(
                TOKEN_IN, AMOUNT, SWAP_ROUTER, TOKEN_OUT, MIN_OUT
            ).call({'from': account.address})
            
            print("✅ सिम्युलेशन सफल! असली ट्रांजैक्शन भेजी जा रही है...", flush=True)
            
            # असली ट्रांजैक्शन (यहीं 0.01 POL कटेगी)
            tx = contract.functions.startFlashLoan(
                TOKEN_IN, AMOUNT, SWAP_ROUTER, TOKEN_OUT, MIN_OUT
            ).build_transaction({
                'from': account.address,
                'nonce': w3.eth.get_transaction_count(account.address),
                'gas': 300000,
                'gasPrice': w3.eth.gas_price
            })
            signed_tx = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            print(f"💰 असली ट्रेड भेजी गई! हैश: {tx_hash.hex()}", flush=True)
            sys.exit(0) # एक बार ट्रेड होने के बाद बॉट बंद

        except ContractLogicError:
            # बाजार में अभी प्रॉफिट नहीं, लेकिन लॉग में "हार्टबीट" दिखेगा
            print("⏳ बाज़ार स्कैन हो रहा है, अभी कोई प्रॉफिट नहीं...", flush=True)
        except Exception as e:
            print(f"⏸️ कोई और एरर: {e}", flush=True)
        
        # हर 30 सेकंड में चेक करे (Render की मेमोरी कम खर्च हो)
        time.sleep(30)
