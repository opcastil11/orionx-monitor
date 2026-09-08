#!/usr/bin/env python3
"""Reconstruye la historia completa de cada dirección de billeteras.json. Solo librería estándar.

Escribe tres cosas dentro de historia/:
  raw/<red>_<dir>.jsonl.gz  la respuesta cruda del explorador, una tx por línea (el archivo de evidencia)
  mov/<red>_<dir>.jsonl     un movimiento normalizado por línea (fecha, contraparte, monto, sentido)
  grafo.json                nodos y aristas agregadas para historia.html
  _estado.json              cursor de cada dirección: la próxima corrida sigue donde quedó

Uso:  python3 fetch_historia.py [--red BTC,XRP] [--dir <direccion>] [--max-tx N] [--rehacer]
EVM (ETH/BSC/POLYGON) necesita una API key gratis de etherscan.io en $ETHERSCAN_KEY (una sola sirve
para las tres redes con la API v2). Sin ella esas redes se saltan y se avisa.
"""
import json, os, sys, gzip, time, argparse, datetime as dt, urllib.request, urllib.parse, urllib.error
from pathlib import Path
from collections import defaultdict

HERE = Path(__file__).resolve().parent
HIST = HERE / "historia"; RAW = HIST / "raw"; MOV = HIST / "mov"
UA = {"User-Agent": "orionx-monitor/historia (github pages; afectados)"}
RIPPLE_EPOCH = 946684800          # 2000-01-01, base de los timestamps del XRPL
PAUSA = {"mempool.space": 0.35, "litecoinspace.org": 0.35, "s2.ripple.com": 0.2, "xrplcluster.com": 0.2,
         "api.trongrid.io": 0.25, "api.etherscan.io": 0.25, "eth.blockscout.com": 1.2, "polygon.blockscout.com": 1.2}   # sin llave el límite es estrecho
_ultimo = {}

def iso(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if ts else None

def get(url, data=None, headers=None, tries=6):
    """GET/POST con reintentos y una pausa por host para no gatillar rate limits."""
    host = urllib.parse.urlparse(url).netloc
    esperar = PAUSA.get(host, 0.3) - (time.time() - _ultimo.get(host, 0))
    if esperar > 0: time.sleep(esperar)
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                         headers={**UA, **({"content-type": "application/json"} if data is not None else {}), **(headers or {})})
            with urllib.request.urlopen(req, timeout=60) as r:
                _ultimo[host] = time.time(); return json.load(r)
        except Exception as e:
            err = e; _ultimo[host] = time.time()
            lento = isinstance(e, urllib.error.HTTPError) and e.code in (429, 503)
            time.sleep(min(120, 20 * (i + 1)) if lento else 3 + 4 * i)   # un 429 se destraba esperando, no insistiendo
    raise RuntimeError(f"{url[:80]}: {err}")

# ---------------------------------------------------------------- almacenamiento
def slug(red, direccion): return f"{red}_{direccion}"

def leer_raw(red, direccion):
    """Devuelve los hashes ya guardados; sirve para no volver a pedir lo mismo."""
    f = RAW / f"{slug(red, direccion)}.jsonl.gz"
    if not f.exists(): return set()
    vistos = set()
    with gzip.open(f, "rt", encoding="utf-8") as fh:
        for l in fh:
            if l.strip():
                try: vistos.add(json.loads(l).get("_hash"))
                except Exception: pass
    return vistos

def guardar(red, direccion, crudas, movs):
    RAW.mkdir(parents=True, exist_ok=True); MOV.mkdir(parents=True, exist_ok=True)
    if crudas:
        with gzip.open(RAW / f"{slug(red, direccion)}.jsonl.gz", "at", encoding="utf-8") as fh:
            for c in crudas: fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    if movs:
        with open(MOV / f"{slug(red, direccion)}.jsonl", "a", encoding="utf-8") as fh:
            for m in movs: fh.write(json.dumps(m, ensure_ascii=False) + "\n")

def estado_leer():
    f = HIST / "_estado.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

def estado_guardar(e):
    HIST.mkdir(parents=True, exist_ok=True)
    (HIST / "_estado.json").write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")

# Solo estos contratos cuentan como dinero: las billeteras reciben cientos de tokens
# de estafa que se hacen pasar por USDT o ETH, y sumarlos falsea cualquier total.
TOKENS = {
    "ETH": {"0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
            "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
            "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
            "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": "WBTC",
            "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH"},
    "BSC": {"0x55d398326f99059ff775485246999027b3197955": "USDT",
            "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": "USDC",
            "0xe9e7cea3dedca5984780bafc599bd69add087d56": "BUSD"},
    "POLYGON": {"0xc2132d05d31c914a87c6611c10748aeb04b58e8f": "USDT",
                "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": "USDC",
                "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": "USDC",
                "0x8f3cf7ad23cd3cadbd9735aff958023239c6a063": "DAI",
                "0x7ceb23fd6bc0add59e62ac25578270cff1b9f619": "WETH",
                "0x1bfd67037b42cf73acf2047067bd4f2c47d9bfd6": "WBTC"},
    "TRX": {"TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t": "USDT",
            "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8": "USDC"},
}
_descartados = defaultdict(int)

def leer_movs(red, direccion):
    """Movimientos normalizados de una dirección, ya sin los tokens de estafa."""
    f = MOV / f"{slug(red, direccion)}.jsonl"
    if not f.exists(): return []
    fuera = []
    for l in f.read_text(encoding="utf-8").splitlines():
        if not l.strip(): continue
        try: m = json.loads(l)
        except json.JSONDecodeError: continue     # línea a medio escribir si se lee durante una descarga
        c = m.get("contrato")
        if not c and m.get("moneda") in ("TRC20", "ERC20"):
            _descartados[f"{red}:{m.get('moneda')} sin contrato"] += 1; continue
        if c:
            bueno = (TOKENS.get(red) or {}).get(c if red == "TRX" else c.lower())
            if not bueno:
                _descartados[f"{red}:{m.get('moneda')}"] += 1; continue
            m["moneda"] = bueno
        fuera.append(m)
    return fuera

def mov(red, h, ts, dir_, contra, sentido, monto, moneda, extra=None):
    m = {"red": red, "hash": h, "ts": int(ts or 0), "fecha": iso(ts), "dir": dir_, "contra": contra,
         "sentido": sentido, "monto": round(float(monto), 12), "moneda": moneda}
    if extra: m.update(extra)
    return m

# ---------------------------------------------------------------- BTC / LTC (esplora)
ESPLORA = {"BTC": ("https://mempool.space/api", 1e8), "LTC": ("https://litecoinspace.org/api", 1e8)}

def _esplora_movs(red, a, tx, div):
    """Reparte el valor de la tx entre contrapartes en proporción a su participación (convención habitual)."""
    def juntar(pares):                                 # varias entradas/salidas de la misma dirección = una sola contraparte
        acc = defaultdict(int)
        for d, v in pares: acc[d] += v or 0
        return list(acc.items())
    entradas = juntar(((v.get("prevout") or {}).get("scriptpubkey_address"), (v.get("prevout") or {}).get("value") or 0) for v in tx.get("vin", []))
    salidas = juntar((o.get("scriptpubkey_address"), o.get("value") or 0) for o in tx.get("vout", []))
    ts = (tx.get("status") or {}).get("block_time") or 0
    mio_in = sum(v for d, v in entradas if d == a); mio_out = sum(v for d, v in salidas if d == a)
    out = []
    if mio_in > mio_out:                                   # la dirección envía
        gastado = mio_in - mio_out
        destinos = [(d, v) for d, v in salidas if d and d != a]
        tot = sum(v for _, v in destinos) or 1
        for d, v in destinos:
            out.append(mov(red, tx["txid"], ts, a, d, "out", gastado * (v / tot) / div, red, {"bloque": (tx.get("status") or {}).get("block_height")}))
    elif mio_out > mio_in:                                 # la dirección recibe
        recibido = mio_out - mio_in
        origenes = [(d, v) for d, v in entradas if d and d != a]
        tot = sum(v for _, v in origenes) or 1
        for d, v in (origenes or [(None, 1)]):
            out.append(mov(red, tx["txid"], ts, a, d, "in", recibido * (v / tot) / div, red, {"bloque": (tx.get("status") or {}).get("block_height")}))
    return out

def bajar_esplora(red, a, vistos, tope, cursor=None, flush=None):
    """Recorre la cadena de tx de la dirección de la más nueva a la más vieja.
    `pendiente` guarda dónde quedó para reanudar; una vez `completo`, las corridas siguientes
    solo miran la punta y paran en la primera página sin novedades."""
    base, div = ESPLORA[red]; cur = dict(cursor or {})
    ultimo = cur.get("pendiente"); completo = cur.get("completo", False); total = 0
    while True:
        url = f"{base}/address/{a}/txs" if ultimo is None else f"{base}/address/{a}/txs/chain/{ultimo}"
        pag = get(url)
        if not pag:
            completo = True; ultimo = None
            flush([], [], {"pendiente": None, "completo": True}); break
        crudas, movs, nuevas = [], [], 0
        for tx in pag:
            if tx["txid"] in vistos: continue
            vistos.add(tx["txid"]); nuevas += 1
            crudas.append({**tx, "_hash": tx["txid"]}); movs += _esplora_movs(red, a, tx, div)
        ultimo = pag[-1]["txid"]; total += nuevas
        fin = (completo and nuevas == 0) or (tope and total >= tope)
        flush(crudas, movs, {"pendiente": None if fin else ultimo, "completo": completo or fin})
        print(f"    {red} {a[:12]}… {total} tx nuevas", flush=True)
        if fin: break
    return total

# ---------------------------------------------------------------- XRP
XRPL = ["https://s2.ripple.com:51234/", "https://xrplcluster.com/"]   # s2 = full history

def bajar_xrp(red, a, vistos, tope, cursor=None, flush=None):
    marker = None; desde = (cursor or {}).get("ledger", -1); total = 0
    desde_req = desde                       # el marker del XRPL solo vale con el mismo rango de ledgers
    while True:
        p = {"account": a, "ledger_index_min": desde_req, "ledger_index_max": -1, "limit": 200, "forward": True}
        if marker: p["marker"] = marker
        r = None
        for nodo in XRPL:
            try:
                r = get(nodo, {"method": "account_tx", "params": [p]}).get("result") or {}
                if r.get("transactions") is not None: break
            except Exception as e: r = None
        if not r: raise RuntimeError("XRPL sin respuesta")
        crudas, movs = [], []; devueltas = r.get("transactions", [])
        for t in devueltas:
            tx = t.get("tx") or t.get("tx_json") or {}; meta = t.get("meta") or {}
            h = tx.get("hash") or t.get("hash")
            if not h or h in vistos: continue
            vistos.add(h); crudas.append({**t, "_hash": h})
            ts = (tx.get("date", 0) or 0) + RIPPLE_EPOCH if tx.get("date") else 0
            if tx.get("TransactionType") == "Payment":
                ent = meta.get("delivered_amount", tx.get("Amount"))
                if isinstance(ent, str):
                    monto = int(ent) / 1e6; moneda = "XRP"
                elif isinstance(ent, dict):
                    monto = float(ent.get("value") or 0); moneda = ent.get("currency", "?")
                else: monto = 0; moneda = "XRP"
                envia = tx.get("Account") == a
                movs.append(mov(red, h, ts, a, tx.get("Destination") if envia else tx.get("Account"),
                                "out" if envia else "in", monto, moneda,
                                {"bloque": t.get("ledger_index") or tx.get("ledger_index"), "tag": tx.get("DestinationTag")}))
            else:
                movs.append(mov(red, h, ts, a, None, "meta", 0, "XRP", {"tipo_tx": tx.get("TransactionType")}))
        marker = r.get("marker"); total += len(crudas)
        def _led(c):   # el número de ledger viene en la envoltura o dentro de tx, según el servidor
            return c.get("ledger_index") or (c.get("tx") or {}).get("ledger_index") or (c.get("tx_json") or {}).get("ledger_index") or 0
        ult = max((_led(c) for c in devueltas), default=0)
        if ult: desde = ult                     # el próximo tramo arranca en el último ledger visto
        flush(crudas, movs, {"ledger": desde, "marker": None})
        print(f"    XRP {a[:12]}… {total} tx", flush=True)
        if not marker or (tope and total >= tope): break
    return total

# ---------------------------------------------------------------- TRON
def bajar_trx(red, a, vistos, tope, cursor=None, flush=None):
    total = 0; key = os.environ.get("TRONGRID_KEY")
    hdr = {"TRON-PRO-API-KEY": key} if key else {}
    for ruta, es_token in (("transactions", False), ("transactions/trc20", True)):
        desde = int((cursor or {}).get("ts_" + ruta.replace("/", "_"), 0))
        finger = None
        while True:
            q = {"limit": 200, "order_by": "block_timestamp,asc", "min_timestamp": desde}
            if finger: q["fingerprint"] = finger
            r = get(f"https://api.trongrid.io/v1/accounts/{a}/{ruta}?" + urllib.parse.urlencode(q), headers=hdr)
            datos = r.get("data") or []
            crudas, movs = [], []
            for t in datos:
                h = t.get("txID") or t.get("transaction_id")
                if not h or h in vistos: continue
                vistos.add(h); crudas.append({**t, "_hash": h, "_fuente": ruta})
                ts = (t.get("block_timestamp") or t.get("raw_data", {}).get("timestamp") or 0) / 1000
                if es_token:
                    info = t.get("token_info") or {}
                    dec = int(info.get("decimals") or 6); monto = int(t.get("value") or 0) / 10 ** dec
                    envia = t.get("from") == a
                    movs.append(mov(red, h, ts, a, t.get("to") if envia else t.get("from"), "out" if envia else "in",
                                    monto, info.get("symbol") or "TRC20", {"contrato": info.get("address")}))
                else:
                    c = ((t.get("raw_data") or {}).get("contract") or [{}])[0]
                    val = ((c.get("parameter") or {}).get("value") or {})
                    if c.get("type") != "TransferContract":
                        movs.append(mov(red, h, ts, a, None, "meta", 0, "TRX", {"tipo_tx": c.get("type")})); continue
                    de = val.get("owner_address"); para = val.get("to_address"); envia = (de == a)
                    movs.append(mov(red, h, ts, a, para if envia else de, "out" if envia else "in",
                                    (val.get("amount") or 0) / 1e6, "TRX", {"bloque": t.get("blockNumber")}))
            finger = (r.get("meta") or {}).get("fingerprint"); total += len(crudas)
            ult = max((t.get("block_timestamp") or 0 for t in datos), default=0)
            flush(crudas, movs, {"ts_" + ruta.replace("/", "_"): ult or desde})
            print(f"    TRX {a[:12]}… {ruta} {total} tx", flush=True)
            if not finger or not datos or (tope and total >= tope): break
    return total

# ---------------------------------------------------------------- EVM (Etherscan v2)
CHAIN = {"ETH": 1, "BSC": 56, "POLYGON": 137}
NAT = {"ETH": "ETH", "BSC": "BNB", "POLYGON": "POL"}

BLOCKSCOUT = {"ETH": "https://eth.blockscout.com/api", "POLYGON": "https://polygon.blockscout.com/api"}

def _evm_pagina(red, accion, a, bloque, key):
    """Etherscan v2 si hay key (cubre las tres redes); si no, Blockscout sin key (no cubre BSC)."""
    if key:
        q = {"chainid": CHAIN[red], "module": "account", "action": accion, "address": a, "startblock": bloque,
             "endblock": 99999999, "page": 1, "offset": 10000, "sort": "asc", "apikey": key}
        return get("https://api.etherscan.io/v2/api?" + urllib.parse.urlencode(q)), 10000
    base = BLOCKSCOUT.get(red)
    if not base: raise RuntimeError(f"{red} necesita $ETHERSCAN_KEY (gratis en etherscan.io; Blockscout no cubre BSC)")
    q = {"module": "account", "action": accion, "address": a, "startblock": bloque, "endblock": 99999999,
         "page": 1, "offset": 1000, "sort": "asc"}
    return get(f"{base}?" + urllib.parse.urlencode(q)), 1000

def bajar_evm(red, a, vistos, tope, cursor=None, flush=None):
    key = os.environ.get("ETHERSCAN_KEY"); total = 0
    for accion in ("txlist", "txlistinternal", "tokentx"):
        bloque = int((cursor or {}).get("bloque_" + accion, 0))
        while True:
            r, pag = _evm_pagina(red, accion, a, bloque, key)
            res = r.get("result")
            if not isinstance(res, list) or not res:
                if res and "No transactions found" not in str(res) and r.get("status") == "0" and "not yet been processed" not in str(r.get("message", "")):
                    raise RuntimeError(f"{red} {accion}: {str(res)[:120]}")
                break
            nuevas = 0; crudas, movs = [], []
            for t in res:
                h = "_".join(str(x) for x in (t.get("hash") or t.get("transactionHash") or "", accion,
                                              t.get("logIndex") or "", t.get("traceId") or t.get("index") or ""))
                if h in vistos: continue
                vistos.add(h); nuevas += 1; crudas.append({**t, "_hash": h, "_fuente": accion})
                if t.get("isError") == "1": continue
                ts = int(t.get("timeStamp") or t.get("timestamp") or 0)
                de = (t.get("from") or "").lower(); para = (t.get("to") or "").lower(); envia = de == a.lower()
                if accion == "tokentx":
                    dec = int(t.get("tokenDecimal") or 18); monto = int(t.get("value") or 0) / 10 ** dec
                    moneda = t.get("tokenSymbol") or "ERC20"
                else:
                    monto = int(t.get("value") or 0) / 1e18; moneda = NAT[red]
                if monto == 0 and accion != "txlist": continue
                movs.append(mov(red, t.get("hash") or t.get("transactionHash"), ts, a, para if envia else de,
                                "out" if envia else "in", monto, moneda,
                                {"bloque": int(t.get("blockNumber") or 0), "clase": accion,
                                 "contrato": t.get("contractAddress") or None}))
            total += nuevas
            ultimo_bloque = int(res[-1].get("blockNumber") or bloque)
            fin = len(res) < pag or nuevas == 0 or ultimo_bloque <= bloque or (tope and total >= tope)
            flush(crudas, movs, {"bloque_" + accion: ultimo_bloque})
            print(f"    {red} {a[:12]}… {accion} {total} filas", flush=True)
            if fin: break
            bloque = ultimo_bloque              # sigue desde el último bloque devuelto (se re-pide, vistos deduplica)
    return total

BAJAR = {"BTC": bajar_esplora, "LTC": bajar_esplora, "XRP": bajar_xrp, "TRX": bajar_trx,
         "ETH": bajar_evm, "BSC": bajar_evm, "POLYGON": bajar_evm}

# ---------------------------------------------------------------- agregación para el grafo
TOPE_ARISTAS = 20   # contrapartes por dirección que se dibujan; el resto se resume en un nodo "otras"

def construir_grafo(wallets):
    conocidas = {(w["red"], w["direccion"].lower()): w for w in wallets}
    nodos, aristas = {}, defaultdict(lambda: {"monto": defaultdict(float), "n": 0, "primera": None, "ultima": None})
    for w in wallets:
        red, a = w["red"], w["direccion"]
        f = MOV / f"{slug(red, a)}.jsonl"
        if not f.exists(): continue
        yo = f"{red}:{a.lower()}"
        nodos.setdefault(yo, {"id": yo, "red": red, "dir": a, "etiqueta": w["etiqueta"], "tipo": w["tipo"],
                              "nota": w.get("nota", ""), "conocida": True, "n": 0, "in": defaultdict(float), "out": defaultdict(float)})
        ultimos, meses = [], defaultdict(lambda: defaultdict(float))
        for m in leer_movs(red, a):
            if m.get("fecha") and m["sentido"] != "meta":
                ultimos.append(m); meses[m["fecha"][:7]][m["moneda"] + "|" + m["sentido"]] += m["monto"]
            if m["sentido"] == "meta" or not m.get("contra"):
                nodos[yo]["n"] += 1; continue
            otro = f"{red}:{m['contra'].lower()}"
            k = conocidas.get((red, m["contra"].lower()))
            nodos.setdefault(otro, {"id": otro, "red": red, "dir": m["contra"], "etiqueta": k["etiqueta"] if k else "",
                                    "tipo": k["tipo"] if k else "externa", "nota": k.get("nota", "") if k else "",
                                    "conocida": bool(k), "n": 0, "in": defaultdict(float), "out": defaultdict(float)})
            nodos[yo]["n"] += 1
            de, para = (yo, otro) if m["sentido"] == "out" else (otro, yo)
            nodos[yo][m["sentido"]][m["moneda"]] += m["monto"]
            ar = aristas[(de, para)]; ar["monto"][m["moneda"]] += m["monto"]; ar["n"] += 1
            for c, cmp_ in (("primera", min), ("ultima", max)):
                ar[c] = m["fecha"] if ar[c] is None else cmp_(ar[c], m["fecha"])
        ultimos.sort(key=lambda x: -x["ts"])
        nodos[yo]["ultimos"] = ultimos[:300]           # para la tabla del panel, sin bajar el jsonl entero
        nodos[yo]["meses"] = {k: {kk: round(vv, 8) for kk, vv in v.items()} for k, v in sorted(meses.items())}
        nodos[yo]["total_mov"] = len(ultimos)
    # poda: se conservan todas las aristas entre direcciones conocidas y las TOPE_ARISTAS mayores por nodo
    por_nodo = defaultdict(list)
    for (de, para), v in aristas.items():
        peso = max(v["monto"].values()) if v["monto"] else 0
        por_nodo[de].append(((de, para), peso)); por_nodo[para].append(((de, para), peso))
    conservar = set()
    for nid, n in nodos.items():          # el recorte se decide desde la dirección vigilada, no desde la contraparte
        if not n["conocida"]: continue
        for k, _ in sorted(por_nodo.get(nid, []), key=lambda x: -x[1])[:TOPE_ARISTAS]: conservar.add(k)
    for k, v in aristas.items():
        if nodos[k[0]]["conocida"] and nodos[k[1]]["conocida"]: conservar.add(k)
    resumen = defaultdict(lambda: {"n": 0, "monto": defaultdict(float), "dirs": set()})
    salida_ar = []
    for (de, para), v in aristas.items():
        if (de, para) in conservar:
            salida_ar.append({"de": de, "a": para, "monto": dict(v["monto"]), "n": v["n"], "primera": v["primera"], "ultima": v["ultima"]})
        else:
            base = de if nodos[de]["conocida"] else para
            r = resumen[(base, "in" if base == para else "out")]
            r["n"] += v["n"]; r["dirs"].add(para if base == de else de)
            for mo, x in v["monto"].items(): r["monto"][mo] += x
    for (base, sent), r in resumen.items():
        otras = f"{base}|otras_{sent}"
        nodos[otras] = {"id": otras, "red": nodos[base]["red"], "dir": f"{len(r['dirs'])} direcciones",
                        "etiqueta": f"otras {len(r['dirs'])} contrapartes", "tipo": "resumen", "nota": "",
                        "conocida": False, "n": r["n"], "in": {}, "out": {}}
        salida_ar.append({"de": base if sent == "out" else otras, "a": otras if sent == "out" else base,
                          "monto": dict(r["monto"]), "n": r["n"], "primera": None, "ultima": None, "resumen": True})
    usados = {e["de"] for e in salida_ar} | {e["a"] for e in salida_ar}
    nodos = {k: v for k, v in nodos.items() if v["conocida"] or k in usados}   # las contrapartes resumidas no van al json
    for n in nodos.values():
        n["in"] = {k: round(v, 8) for k, v in dict(n["in"]).items()}; n["out"] = {k: round(v, 8) for k, v in dict(n["out"]).items()}
    g = {"generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
         "nodos": list(nodos.values()), "aristas": salida_ar,
         "archivos": {f"{w['red']}:{w['direccion'].lower()}": f"historia/mov/{slug(w['red'], w['direccion'])}.jsonl"
                      for w in wallets if (MOV / f"{slug(w['red'], w['direccion'])}.jsonl").exists()}}
    (HIST / "grafo.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    return g


# ---------------------------------------------------------------- series, saldos y destinos
HITO_MIN = {"BTC": 0.5, "LTC": 50, "XRP": 10000, "TRX": 50000, "ETH": 1, "BNB": 5, "POL": 20000, "USDT": 10000}

def _saldos_hoy():
    """saldo actual de cada billetera vigilada, tal como lo dejó monitor.py en data.json"""
    f = HERE / "data.json"
    if not f.exists(): return {}, {}, None
    d = json.loads(f.read_text(encoding="utf-8"))
    out = {}
    for b in d.get("billeteras", []):
        s = {b.get("moneda"): b.get("saldo") or 0}
        for k, v in (b.get("tokens") or {}).items():
            if k != "pendiente": s[k] = v
        out[f"{b['red']}:{b['direccion'].lower()}"] = s
    return out, d.get("precios", {}), d.get("actualizado")

def construir_series(wallets):
    """Reconstruye el saldo de cada dirección a lo largo del tiempo: se parte del saldo de hoy y se
    deshacen los movimientos hacia atrás. Deja historia/series.json para la línea de tiempo y los saldos."""
    saldos, precios, cuando = _saldos_hoy()
    fuera = []
    for w in wallets:
        red, a = w["red"], w["direccion"]; yo = f"{red}:{a.lower()}"
        movs = [m for m in leer_movs(red, a) if m["sentido"] in ("in", "out") and m["ts"]]
        if not movs: continue
        movs.sort(key=lambda m: m["ts"])
        por_moneda = defaultdict(list)
        for m in movs: por_moneda[m["moneda"]].append(m)
        series, recibido, enviado, picos = {}, {}, {}, {}
        for moneda, ms in por_moneda.items():
            recibido[moneda] = round(sum(m["monto"] for m in ms if m["sentido"] == "in"), 8)
            enviado[moneda] = round(sum(m["monto"] for m in ms if m["sentido"] == "out"), 8)
            hoy = (saldos.get(yo) or {}).get(moneda)
            neto_total = recibido[moneda] - enviado[moneda]
            base = (hoy if hoy is not None else neto_total) - neto_total   # saldo antes del primer movimiento (≈0)
            cum, serie = base, [[ms[0]["ts"] - 86400, round(base, 8)]]
            for m in ms:
                cum += m["monto"] if m["sentido"] == "in" else -m["monto"]
                if serie and serie[-1][0] == m["ts"]: serie[-1][1] = round(cum, 8)
                else: serie.append([m["ts"], round(cum, 8)])
            if len(serie) > 4000:                                          # una muestra por día basta para dibujar
                comp, ult = [], None
                for t, v in serie:
                    d = t // 86400
                    if d != ult: comp.append([t, v]); ult = d
                    else: comp[-1] = [t, v]
                serie = comp
            series[moneda] = serie
            pico = max(serie, key=lambda x: x[1])
            picos[moneda] = {"monto": pico[1], "fecha": iso(pico[0])}
        umbral = {k: HITO_MIN.get(k, 0) for k in por_moneda}
        hitos = sorted([m for m in movs if m["monto"] >= umbral.get(m["moneda"], 0)], key=lambda m: -m["monto"])[:400]
        fuera.append({"id": yo, "red": red, "dir": a, "etiqueta": w["etiqueta"], "tipo": w["tipo"],
                      "vigilar": w.get("vigilar", False), "nota": w.get("nota", ""),
                      "saldo_hoy": saldos.get(yo) or {}, "recibido": recibido, "enviado": enviado,
                      "picos": picos, "series": series, "n": len(movs),
                      "primera": iso(movs[0]["ts"]) if movs else None, "ultima": iso(movs[-1]["ts"]) if movs else None,
                      "hitos": sorted(hitos, key=lambda m: m["ts"])})
    basura = sorted(_descartados.items(), key=lambda x: -x[1])
    datos = {"generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
             "saldos_de": cuando, "precios": precios, "billeteras": fuera,
             "descartados": {"n": sum(_descartados.values()), "tokens": len(_descartados),
                             "ejemplos": [k for k, _ in basura[:12]]}}
    (HIST / "series.json").write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return datos

def construir_destinos(wallets, top=40, consultar_saldos=True):
    """A dónde salió la plata de las billeteras de OrionX y qué queda hoy en esos destinos.
    El saldo de cada destino se consulta con el mismo código de monitor.py."""
    conocidas = {(w["red"], w["direccion"].lower()): w for w in wallets}
    agg = defaultdict(lambda: {"monto": defaultdict(float), "n": 0, "primera": None, "ultima": None, "desde": set()})
    for w in wallets:
        if w["tipo"] != "orionx": continue
        red, a = w["red"], w["direccion"]
        for m in leer_movs(red, a):
            if m["sentido"] != "out" or not m.get("contra"): continue
            if (red, m["contra"].lower()) in conocidas and conocidas[(red, m["contra"].lower())]["tipo"] == "orionx":
                continue                                    # movimientos entre billeteras de la propia OrionX
            d = agg[(red, m["contra"])]
            d["monto"][m["moneda"]] += m["monto"]; d["n"] += 1; d["desde"].add(w["etiqueta"])
            for c, cmp_ in (("primera", min), ("ultima", max)):
                d[c] = m["fecha"] if d[c] is None else cmp_(d[c], m["fecha"])
    filas = []
    for (red, dirn), v in agg.items():
        k = conocidas.get((red, dirn.lower()))
        filas.append({"red": red, "dir": dirn, "recibido": {m: round(x, 8) for m, x in v["monto"].items()},
                      "n": v["n"], "primera": v["primera"], "ultima": v["ultima"], "desde": sorted(v["desde"]),
                      "etiqueta": k["etiqueta"] if k else "", "tipo": k["tipo"] if k else "externa",
                      "nota": k.get("nota", "") if k else "", "vigilada": bool(k)})
    orden = {"BTC": 1, "LTC": 1e-3, "ETH": 1, "BNB": 1e-2, "POL": 1e-6, "XRP": 1e-5, "TRX": 1e-6, "USDT": 1e-5}
    filas.sort(key=lambda f: -sum(v * orden.get(m, 1e-6) for m, v in f["recibido"].items()))
    if consultar_saldos:
        import monitor                                       # reutiliza el consultor de saldos del monitor horario
        for f in filas[:top]:
            try:
                r = monitor.consultar({"red": f["red"], "direccion": f["dir"]})
                f["saldo_hoy"] = {monitor.NATIVO[f["red"]]: r.get("saldo"), **{k: v for k, v in (r.get("tokens") or {}).items() if k != "pendiente"}}
                f["tx"] = r.get("tx"); f["ultima_actividad"] = r.get("ultima")
            except Exception as e:
                f["error"] = str(e)[:120]
            print(f"    saldo destino {f['red']} {f['dir'][:14]}… {f.get('saldo_hoy')}", flush=True)
            time.sleep(0.6)
    resto = filas[300:]                                      # el archivo se queda con los 300 mayores + un resumen
    resumen = {"n_direcciones": len(resto), "n_tx": sum(f["n"] for f in resto), "monto": defaultdict(float)}
    for f in resto:
        for m, v in f["recibido"].items(): resumen["monto"][m] += v
    resumen["monto"] = {m: round(v, 8) for m, v in resumen["monto"].items()}
    datos = {"generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
             "destinos": filas[:300], "resto": resumen, "total_destinos": len(filas)}
    (HIST / "destinos.json").write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return datos

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--red"); ap.add_argument("--dir"); ap.add_argument("--max-tx", type=int, default=0)
    ap.add_argument("--rehacer", action="store_true", help="ignora lo ya bajado y empieza de cero")
    ap.add_argument("--solo-grafo", action="store_true")
    ap.add_argument("--sin-destinos", action="store_true", help="no consulta el saldo actual de los destinos")
    a = ap.parse_args()
    wallets = json.loads((HERE / "billeteras.json").read_text(encoding="utf-8"))
    HIST.mkdir(exist_ok=True); RAW.mkdir(exist_ok=True); MOV.mkdir(exist_ok=True)
    if not a.solo_grafo:
        redes = set((a.red or "").upper().split(",")) if a.red else None
        estado = {} if a.rehacer else estado_leer()
        t0 = time.time()
        for w in wallets:
            red, d = w["red"], w["direccion"]
            if redes and red not in redes: continue
            if a.dir and a.dir.lower() != d.lower(): continue
            clave = slug(red, d)
            if a.rehacer:
                for p in (RAW / f"{clave}.jsonl.gz", MOV / f"{clave}.jsonl"): p.unlink(missing_ok=True)
            print(f"[{red}] {d}  {w['etiqueta']}", flush=True)
            vistos = set() if a.rehacer else leer_raw(red, d)
            def flush(crudas, movs, cur, _red=red, _d=d, _clave=clave):
                """cada página va a disco con su cursor: un corte no obliga a empezar de nuevo"""
                guardar(_red, _d, crudas, movs)
                estado[_clave] = {**(estado.get(_clave) or {}), **cur, "tx": len(vistos),
                                  "actualizado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
                estado_guardar(estado)
            try:
                n = BAJAR[red](red, d, vistos, a.max_tx, estado.get(clave), flush)
                estado.setdefault(clave, {}).pop("error", None); estado_guardar(estado)
                print(f"  -> {n} tx nuevas ({len(vistos)} en total)", flush=True)
            except Exception as e:
                print(f"  !! {e}", flush=True); estado.setdefault(clave, {})["error"] = str(e)[:200]
            estado_guardar(estado)
        print(f"descarga en {time.time()-t0:.0f}s", flush=True)
    g = construir_grafo(wallets)
    print(f"grafo: {len(g['nodos'])} nodos, {len(g['aristas'])} aristas -> historia/grafo.json")
    se = construir_series(wallets)
    print(f"series: {len(se['billeteras'])} billeteras -> historia/series.json")
    de = construir_destinos(wallets, consultar_saldos=not a.sin_destinos)
    print(f"destinos: {len(de['destinos'])} contrapartes -> historia/destinos.json")

if __name__ == "__main__":
    main()
