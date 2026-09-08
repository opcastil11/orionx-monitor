#!/usr/bin/env python3
"""Monitor de billeteras vinculadas a OrionX. Solo librería estándar.
Lee billeteras.json, consulta exploradores públicos, compara con data.json anterior,
registra movimientos en historial.jsonl, reescribe data.json y avisa por Discord (env DISCORD_WEBHOOK) si hubo cambios.
"""
import json, os, sys, time, datetime as dt, urllib.request, urllib.parse
from pathlib import Path
HERE = Path(__file__).resolve().parent
UA = {"User-Agent": "orionx-monitor/1.0 (github pages; afectados)"}
RPC = {"ETH": ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org", "https://cloudflare-eth.com"],
       "BSC": ["https://bsc-dataseed.binance.org", "https://bsc-rpc.publicnode.com", "https://bsc.drpc.org"],
       "POLYGON": ["https://polygon-bor-rpc.publicnode.com", "https://polygon.drpc.org"]}
USDT = {"ETH": "0xdac17f958d2ee523a2206206994597c13d831ec7", "BSC": "0x55d398326f99059ff775485246999027b3197955", "POLYGON": "0xc2132d05d31c914a87c6611c10748aeb04b58e8f"}
USDT_DEC = {"ETH": 6, "BSC": 18, "POLYGON": 6}
NATIVO = {"BTC": "BTC", "XRP": "XRP", "TRX": "TRX", "LTC": "LTC", "ETH": "ETH", "BSC": "BNB", "POLYGON": "POL"}
COINGECKO = {"BTC": "bitcoin", "XRP": "ripple", "TRX": "tron", "LTC": "litecoin", "ETH": "ethereum", "BNB": "binancecoin", "POL": "polygon-ecosystem-token", "USDT": "tether"}
EXPLORER = {"BTC": "https://mempool.space/address/{a}", "XRP": "https://xrpscan.com/account/{a}", "TRX": "https://tronscan.org/#/address/{a}",
            "LTC": "https://litecoinspace.org/address/{a}", "ETH": "https://etherscan.io/address/{a}", "BSC": "https://bscscan.com/address/{a}", "POLYGON": "https://polygonscan.com/address/{a}"}

def get(url, data=None, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None, headers={**UA, "content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as r: return json.load(r)
        except Exception as e:
            err = e; time.sleep(3 + 4 * i)
    raise RuntimeError(f"{url[:60]}: {err}")

def rpc(red, m, p):
    """prueba cada nodo público de la lista hasta que uno responda"""
    time.sleep(0.8); err = None
    for url in RPC[red]:
        try:
            r = get(url, {"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, tries=2)
            if r.get("result") is not None: return r["result"]
            err = r.get("error")
        except Exception as e: err = e
    raise RuntimeError(f"RPC {red}: {err}")
def iso(ts): return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else None

def consultar(w):
    red, a = w["red"], w["direccion"]; out = {"saldo": None, "tokens": {}, "tx": None, "ultima": None}
    if red == "BTC":
        j = get(f"https://mempool.space/api/address/{a}"); c = j["chain_stats"]
        out["saldo"] = (c["funded_txo_sum"] - c["spent_txo_sum"]) / 1e8; out["tx"] = c["tx_count"]
        if j["mempool_stats"]["tx_count"]: out["tokens"]["pendiente"] = (j["mempool_stats"]["funded_txo_sum"] - j["mempool_stats"]["spent_txo_sum"]) / 1e8
        txs = get(f"https://mempool.space/api/address/{a}/txs")
        if txs: out["ultima"] = iso(txs[0]["status"].get("block_time")) or "en mempool"
    elif red == "XRP":
        j = get(f"https://api.xrpscan.com/api/v1/account/{a}"); out["saldo"] = float(j.get("xrpBalance") or 0); out["tx"] = j.get("Sequence")
        t = get(f"https://api.xrpscan.com/api/v1/account/{a}/transactions?limit=1").get("transactions") or []
        if t: out["ultima"] = t[0]["date"][:16].replace("T", " ") + " UTC"
    elif red == "TRX":
        j = get(f"https://apilist.tronscanapi.com/api/account?address={a}"); out["saldo"] = (j.get("balance") or 0) / 1e6; out["tx"] = j.get("totalTransactionCount")
        for tk in j.get("trc20token_balances", []):
            if tk.get("tokenAbbr") == "USDT": out["tokens"]["USDT"] = float(tk["balance"]) / 10 ** int(tk.get("tokenDecimal", 6))
        t = get(f"https://apilist.tronscanapi.com/api/transaction?address={a}&limit=1&start=0&sort=-timestamp").get("data") or []
        if t: out["ultima"] = iso(t[0]["timestamp"] / 1000)
    elif red == "LTC":
        j = get(f"https://api.blockcypher.com/v1/ltc/main/addrs/{a}?limit=1"); out["saldo"] = j["final_balance"] / 1e8; out["tx"] = j["n_tx"]
        if j.get("txrefs"): out["ultima"] = j["txrefs"][0].get("confirmed", "")[:16].replace("T", " ") + " UTC"
    elif red in RPC:
        out["saldo"] = int(rpc(red, "eth_getBalance", [a, "latest"]), 16) / 1e18; out["tx"] = int(rpc(red, "eth_getTransactionCount", [a, "latest"]), 16)
        bal = rpc(red, "eth_call", [{"to": USDT[red], "data": "0x70a08231" + a[2:].lower().rjust(64, "0")}, "latest"])
        out["tokens"]["USDT"] = int(bal, 16) / 10 ** USDT_DEC[red]
        out["ultima"] = f"{out['tx']} tx enviadas (nonce)"   # sin indexador no hay fecha; el nonce delata salidas
    return out

def precios():
    ids = ",".join(sorted(set(COINGECKO.values())))
    try:
        j = get(f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=clp,usd")
        return {sym: j.get(cg, {}) for sym, cg in COINGECKO.items()}
    except Exception as e:
        print("precios:", e); return {}

def discord(webhook, eventos, data):
    lineas = [f"**Monitor OrionX: {len(eventos)} movimiento(s) nuevo(s)** ({data['actualizado']})"]
    for e in eventos[:15]:
        lineas.append(f"• [{e['red']}] {e['etiqueta']}: {e['detalle']}  <{EXPLORER[e['red']].format(a=e['direccion'])}>")
    try: get(webhook, {"content": "\n".join(lineas)[:1900]})
    except Exception as ex: print("discord:", ex)

def main():
    wallets = json.loads((HERE / "billeteras.json").read_text(encoding="utf-8"))
    prev = {}
    if (HERE / "data.json").exists():
        for b in json.loads((HERE / "data.json").read_text(encoding="utf-8")).get("billeteras", []): prev[(b["red"], b["direccion"])] = b
    px = precios(); ahora = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    filas, eventos, errores = [], [], []
    for w in wallets:
        fila = {**w, "explorer": EXPLORER[w["red"]].format(a=w["direccion"]), "moneda": NATIVO[w["red"]]}
        try:
            fila.update(consultar(w))
        except Exception as e:
            errores.append(f"{w['red']} {w['direccion'][:12]}: {e}"); p = prev.get((w["red"], w["direccion"]), {})
            fila.update({k: p.get(k) for k in ("saldo", "tokens", "tx", "ultima")}); fila["error"] = str(e)[:120]
        s = fila.get("saldo"); pr = px.get(fila["moneda"], {})
        fila["valor_clp"] = (s or 0) * pr.get("clp", 0) + sum(v * px.get(k, {}).get("clp", 0) for k, v in (fila.get("tokens") or {}).items() if k in px)
        fila["valor_usd"] = (s or 0) * pr.get("usd", 0) + sum(v * px.get(k, {}).get("usd", 0) for k, v in (fila.get("tokens") or {}).items() if k in px)
        p = prev.get((w["red"], w["direccion"]))
        if p and not fila.get("error") and p.get("saldo") is not None:
            d = (s or 0) - p["saldo"]; dt_usdt = (fila.get("tokens") or {}).get("USDT", 0) - (p.get("tokens") or {}).get("USDT", 0)
            partes = []
            if abs(d) > 1e-9: partes.append(f"{'+' if d > 0 else ''}{d:,.6f} {fila['moneda']} (saldo {s:,.6f})")
            if abs(dt_usdt) > 1e-6: partes.append(f"{'+' if dt_usdt > 0 else ''}{dt_usdt:,.2f} USDT")
            if not partes and fila.get("tx") and p.get("tx") and fila["tx"] != p["tx"]: partes.append(f"nuevas transacciones ({p['tx']} → {fila['tx']}) sin cambio de saldo")
            if partes:
                ev = {"fecha": ahora, "red": w["red"], "direccion": w["direccion"], "etiqueta": w["etiqueta"], "detalle": "; ".join(partes), "saldo_antes": p["saldo"], "saldo_despues": s}
                eventos.append(ev)
        filas.append(fila); time.sleep(0.7)
    hist = HERE / "historial.jsonl"
    with open(hist, "a", encoding="utf-8") as fh:
        for e in eventos: fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    todos = [json.loads(l) for l in hist.read_text(encoding="utf-8").splitlines() if l.strip()] if hist.exists() else []
    data = {"actualizado": ahora, "precios": px, "billeteras": filas, "eventos": todos[-200:][::-1], "errores": errores,
            "total_clp": sum(f["valor_clp"] for f in filas), "total_usd": sum(f["valor_usd"] for f in filas)}
    (HERE / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{ahora}: {len(filas)} billeteras, {len(eventos)} movimientos nuevos, {len(errores)} errores; total ≈ {data['total_clp']:,.0f} CLP")
    for e in eventos: print("  MOV", e["red"], e["etiqueta"], e["detalle"])
    for e in errores: print("  ERR", e)
    wh = os.environ.get("DISCORD_WEBHOOK")
    if wh and eventos: discord(wh, eventos, data)
    if wh and errores and os.environ.get("AVISAR_ERRORES"): get(wh, {"content": "Monitor OrionX: errores de consulta\n" + "\n".join(errores)[:1800]})

if __name__ == "__main__":
    main()
