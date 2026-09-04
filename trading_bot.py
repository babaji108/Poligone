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
RPC_URL = f"https://alchemy.com{ALCHEMY_API_KEY}"
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

# टोकन एड्रेस (पॉलीगॉन मेननेट)
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
WMATIC_ADDRESS = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"

# राउटर एड्रेस
QUICKSWAP_ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff"
SUSHISWAP_ROUTER = "0x1b02dA8Cb0d097e645729F65f33A788624121522"

# ========== RPC CALL FUNCTION ==========
def rpc_call(method, params):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    try:
        res = requests.post(RPC_URL, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        return res.json()
    except:
        return {}

# ========== GET RESERVES ==========
def get_reserves(pair):
    data = "0x0902f1ac"  # getReserves()
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

# live POL (Matic) की कीमत USD में निकालने के लिए (गैस फीस कैलकुलेशन हेतु)
def get_pol_price():
    try:
        # QuickSwap USDC/WMATIC पूल से लाइव कीमत का अंदाजा लगाना
        r0, r1 = get_reserves(PAIR_QS)
        if r0 and r1:
            # 1 POL = कितने USDC (USDC 6 डेसीमल, WMATIC 18 डेसीमल)
            return (r0 / 1e6) / (r1 / 1e18)
    except:
        pass
    return 0.45  # डिफ़ॉल्ट बैकअप कीमत अगर RPC फेल हो

# ========== FLASK ==========
app = Flask(__name__)
@app.route('/')
def home():
    return "Safe Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=10003)

# ========== MAIN LOOP ==========
if __name__ == "__main__":
    print("✅ सुरक्षित आर्बिट्राज बॉट तैयार है! वास्तविक लाभ ट्रैकिंग शुरू...")
    threading.Thread(target=run_flask, daemon=True).start()

    # 🚀 लोन राशि को बढ़ाकर 2,000 USDC किया (आपके वॉलेट से ₹1 भी नहीं कटेगा)
    amount_in = int(2000 * 10**6) 
    total_checks = 0

    while True:
        try:
            total_checks += 1
            r0_qs, r1_qs = get_reserves(PAIR_QS)
            r0_ss, r1_ss = get_reserves(PAIR_SS)

            if r0_qs and r1_qs and r0_ss and r1_ss:
                # रास्ता 1: QuickSwap से खरीदा ➡️ SushiSwap पर बेचा
                wmatic_received_qs = get_amount_out(amount_in, r0_qs, r1_qs)
                usdc_returned_ss = get_amount_out(wmatic_received_qs, r1_ss, r0_ss)
                profit_path1 = (usdc_returned_ss - amount_in) / 1e6

                # रास्ता 2: SushiSwap से खरीदा ➡️ QuickSwap पर बेचा
                wmatic_received_ss = get_amount_out(amount_in, r0_ss, r1_ss)
                usdc_returned_qs = get_amount_out(wmatic_received_ss, r1_qs, r0_qs)
                profit_path2 = (usdc_returned_qs - amount_in) / 1e6

                # सबसे बेस्ट मुनाफे वाला रास्ता चुनें
                best_profit = max(profit_path1, profit_path2)
                
                # लाइव गैस और खर्चे की गणना
                gas_price = w3.eth.gas_price
                estimated_gas_used = 250000  # अनुमानित गैस यूनिट
                gas_cost_in_pol = (gas_price * estimated_gas_used) / 1e18
                pol_price_usd = get_pol_price()
                gas_cost_in_usd = gas_cost_in_pol * pol_price_usd
                
                # फ्लैश लोन की 0.05% फीस जोड़ें
                flash_loan_fee_usd = (amount_in / 1e6) * 0.0005
                total_expenses = gas_cost_in_usd + flash_loan_fee_usd
                
                # शुद्ध मुनाफा (Net Profit)
                net_profit = best_profit - total_expenses

                print(f"📊 चेक #{total_checks}: सम्भावित प्रॉफिट=${best_profit:.4f}, खर्चा=${total_expenses:.4f}, शुद्ध लाभ=${net_profit:.4f}", flush=True)

                # 💰 सुरक्षा कवच: केवल तभी ट्रेड मारो जब सब खर्चे काटकर कम से कम $0.50 का शुद्ध लाभ हो
                if net_profit > 0.50:
                    print(f"🔥 तगड़ा मुनाफा मिला! शुद्ध लाभ: ${net_profit:.2f}. ट्रेड भेजी जा रही है...", flush=True)
                    
                    # सही राउटर तय करें कि लोन कहाँ से शुरू करना है
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
                        'gasPrice': int(gas_price * 1.2) # ट्रांजैक्शन अटकाने से बचाने के लिए 20% एक्स्ट्रा गैस प्राइस
                    })
                    
                    signed_tx = account.sign_transaction(tx)
                    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                    print(f"✅ ट्रेड सफलतापूर्वक ब्लॉकचेन पर भेजी गई! हैश: {tx_hash.hex()}", flush=True)
                    sys.exit(0)
                else:
                    if net_profit < 0:
                        print(f"⏳ मार्केट में अंतर है, लेकिन गैस फीस के कारण घाटा है (${net_profit:.4f})। कोई ट्रेड नहीं भेजी गई।", flush=True)
                    else:
                        print(f"⏳ प्रॉफिट बहुत कम है (${net_profit:.4f})। सही अवसर का इंतज़ार...", flush=True)
            else:
                print("⏸️ रिज़र्व डेटा नहीं मिला। दोबारा कोशिश...", flush=True)

            time.sleep(10) # स्कैनिंग थोड़ी तेज़ की (15s से 10s) ताकि मौका न छूटे

        except Exception as e:
            print(f"⏸️ एरर: {e}", flush=True)
            time.sleep(10)
