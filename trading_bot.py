#!/usr/bin/env python3
import json
import time
import requests
from web3 import Web3
from eth_account import Account
import os

# ==================== कॉन्फ़िगरेशन ====================
ALCHEMY_API_KEY = "alch_gCLi_mioaMeioXm0yWmWT"
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "0xआपकी_प्राइवेट_की")
CONTRACT_ADDRESS = "0xb97e10Ddfa337883f88804CabF18135FA5CBc937"

RPC_URL = f"https://polygon-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"

# ==================== एड्रेस ====================
PAIR_QS = "0x853ee4b2a13f8a742d64c8f088be7ba2131f670d"
PAIR_SS = "0x34965ba0ac2451a34a0471f04cca3f990b8dea27"
CONTRACT_ABI = [
    {
        "inputs": [{"internalType": "uint256", "name": "amount", "type": "uint256"}],
        "name": "startFlashLoan",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

# ==================== Web3 ====================
w3 = Web3(Web3.HTTPProvider(RPC_URL))
if not w3.is_connected():
    print("❌ Web3 कनेक्ट नहीं हो पाया")
    exit(1)

account = Account.from_key(PRIVATE_KEY)
contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)

def rpc_call(method, params):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    res = requests.post(RPC_URL, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
    return res.json()

def get_reserves(pair):
    data = "0x0902f1ac"
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

def execute_trade(amount_usdc):
    try:
        print(f"  🚀 ट्रेड भेजा जा रहा है ({amount_usdc} USDC)...")
        func_sig = "0xb8845e44"
        amount_hex = format(amount_usdc, '064x')
        call_data = func_sig + amount_hex
        nonce = w3.eth.get_transaction_count(account.address)
        tx = {
            'to': CONTRACT_ADDRESS,
            'data': call_data,
            'gas': 500000,
            'gasPrice': w3.eth.gas_price,
            'nonce': nonce,
            'chainId': 137
        }
        signed_tx = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        print(f"  ✅ ट्रेड भेजा! Tx Hash: {tx_hash.hex()}")
        return True
    except Exception as e:
        print(f"  ❌ ट्रेड फेल: {e}")
        return False

total_checks = 0
profitable_checks = 0

def main():
    global total_checks, profitable_checks
    print("🚀 Trading Bot – WETH/USDC")
    print("📊 0 = No trade, 1 = Trade executed")
    print("=" * 50)
    print(f"✅ Contract: {CONTRACT_ADDRESS}")
    print("=" * 50)

    amount_in = 10**16

    while True:
        try:
            total_checks += 1
            r0_qs, r1_qs = get_reserves(PAIR_QS)
            r0_ss, r1_ss = get_reserves(PAIR_SS)

            if r0_qs and r1_qs and r0_ss and r1_ss:
                qs_out = get_amount_out(amount_in, r1_qs, r0_qs)
                ss_out = get_amount_out(amount_in, r1_ss, r0_ss)
                qs_usdc = qs_out / 1e6
                ss_usdc = ss_out / 1e6
                diff = abs(qs_usdc - ss_usdc)
                avg = (qs_usdc + ss_usdc) / 2
                diff_percent = (diff / avg) * 100 if avg > 0 else 0

                gas_price = rpc_call("eth_gasPrice", [])
                gas_price_num = int(gas_price.get("result", "0x0"), 16)
                gas_cost_matic = (gas_price_num * 300000) / 1e18
                matic_price = 0.0004
                gas_cost_usdc = gas_cost_matic * matic_price

                print(f"\n🔍 Check #{total_checks}: QS={qs_usdc:.4f}, SS={ss_usdc:.4f}, Diff={diff_percent:.3f}%")

                if diff_percent > 0.3 and diff > gas_cost_usdc:
                    profitable_checks += 1
                    profit_usdc = diff - gas_cost_usdc
                    print(f"  ✅ PROFIT! 1 ({profitable_checks}/{total_checks} = {profitable_checks/total_checks*100:.2f}%)")
                    print(f"  💰 संभावित मुनाफा: ${profit_usdc:.4f}")
                    execute_trade(int(100 * 10**6))
                else:
                    print(f"  ❌ 0 ({profitable_checks}/{total_checks} = {profitable_checks/total_checks*100:.2f}%)")
            else:
                print("  ⚠️ Reserves not found")

            time.sleep(30)

        except KeyboardInterrupt:
            print(f"\n🛑 Stopped. Final: {profitable_checks}/{total_checks} = {profitable_checks/total_checks*100:.2f}%")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
