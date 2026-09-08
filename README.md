# Monitor de billeteras OrionX

**Página en vivo: https://arigatodon.github.io/orionx-monitor/**

Muestra saldo, valor en pesos y última actividad de las billeteras vinculadas a OrionX en Bitcoin, XRP, Tron, Litecoin, Ethereum, BSC y Polygon, y registra cada movimiento con fecha y hora. Se actualiza sola cada hora. Lo mantienen clientes afectados por el cierre del 3 de septiembre de 2026; no tiene relación con la empresa.

Todo es verificable: cada dirección enlaza a su explorador público y `billeteras.json` anota qué transacción la vincula a OrionX.

## Ten tu propia copia (10 minutos, gratis, sin servidor)

Cuantas más copias existan, más difícil es que el registro desaparezca. Cada copia consulta y guarda los datos por su cuenta.

1. Crea una cuenta en github.com si no tienes.
2. Arriba a la derecha de esta página pulsa **Fork** y confirma. Ya tienes tu copia en `github.com/TU_USUARIO/orionx-monitor`.
3. En tu copia: **Settings → Pages → Source: "Deploy from a branch" → Branch: `main`, carpeta `/ (root)` → Save**. En dos minutos tu página estará en `https://TU_USUARIO.github.io/orionx-monitor/`.
4. **Settings → Actions → General → Workflow permissions → marca "Read and write permissions" → Save.** Sin esto el robot no puede guardar los datos.
5. Pestaña **Actions**. Si aparece un aviso para habilitar workflows, acéptalo. Entra en **monitor → Run workflow → Run workflow**. Desde ahí corre sola cada hora.

Opcional, avisos a Discord: un administrador del servidor crea un webhook (Ajustes del canal → Integraciones → Webhooks → Nuevo webhook → Copiar URL). En tu copia: **Settings → Secrets and variables → Actions → New repository secret**, nombre `DISCORD_WEBHOOK`, valor la URL. Cada movimiento detectado se publicará en ese canal.

Para recibir las billeteras nuevas que se agreguen aquí, en tu copia pulsa **Sync fork → Update branch** de vez en cuando.

## Aportar una billetera

Solo se agregan direcciones con una transacción pública que las ancle a OrionX (un retiro que la empresa te pagó, un depósito que le hiciste, o una salida desde una billetera ya confirmada). Abre un **Issue** en este repositorio con: red, dirección, el hash de esa transacción y una frase de qué es. No pongas datos personales.

Si sabes editar JSON, puedes proponer el cambio directamente en `billeteras.json` con un Pull Request. Campos: `red` (BTC, XRP, TRX, LTC, ETH, BSC, POLYGON), `direccion`, `etiqueta`, `tipo` (`orionx`, `desvio`, `querella`), `vigilar` (true/false), `nota`.

## Historia completa y grafo de flujo

`index.html` muestra el estado de hoy; `historia.html` muestra de dónde vino cada peso. `fetch_historia.py` baja **todas** las transacciones de cada dirección desde su primer bloque y deja tres cosas en `historia/`:

- `raw/<red>_<direccion>.jsonl.gz` — la respuesta cruda del explorador, una transacción por línea. Es el archivo de evidencia: sirve para rehacer el análisis sin volver a consultar a nadie.
- `mov/<red>_<direccion>.jsonl` — un movimiento normalizado por línea (`fecha`, `contra`, `sentido`, `monto`, `moneda`), fácil de abrir con `grep`, `jq`, Excel o pandas.
- `grafo.json` — el agregado que dibuja la página: quién le envió cuánto a quién, con la primera y la última vez.

```bash
python3 fetch_historia.py                 # todo (reanudable: la segunda corrida solo baja lo nuevo)
python3 fetch_historia.py --red BTC,XRP   # una o varias redes
python3 fetch_historia.py --dir bc1q…     # una sola dirección
python3 fetch_historia.py --solo-grafo    # rehace grafo.json sin volver a consultar
```

BTC, LTC, XRP, TRON y (sin key) ETH y Polygon salen de APIs públicas gratis. **BSC necesita una API key gratuita de etherscan.io** en la variable `ETHERSCAN_KEY`; la misma key acelera ETH y Polygon. En GitHub Actions ponla como secreto con ese nombre.

En el grafo, cada flecha va del que envía al que recibe y engorda con el monto acumulado; las contrapartes menores de cada dirección se agrupan en un nodo punteado para que el dibujo se entienda (están todas en `mov/`). Un aviso importante: cuando una transacción de Bitcoin o Litecoin paga a varios destinos, el reparto del monto entre ellos es la convención proporcional habitual, o sea una aproximación — el enlace al explorador de cada fila permite verificar el original.

## Cómo funciona

- `monitor.py` (Python, sin dependencias) consulta mempool.space, xrpscan, tronscan, blockcypher y nodos RPC públicos, más precios de CoinGecko. Compara con el `data.json` anterior y anota los cambios en `historial.jsonl`.
- `.github/workflows/monitor.yml` lo ejecuta cada hora en GitHub Actions y guarda el resultado en el repositorio.
- `index.html` lee `data.json` y dibuja la página. No hay servidor ni base de datos.
- `fetch_historia.py` + `historia.html` reconstruyen y dibujan la historia completa (ver arriba).
- Si una API falla, se conserva el último dato y la página lo indica. Las APIs gratuitas aguantan sin problema una consulta por hora; no bajes el cron a menos de 30 minutos.

Probarlo en tu computador:

```bash
python3 monitor.py            # genera data.json
python3 -m http.server 8000   # abre http://localhost:8000
```

## Advertencia

Las direcciones marcadas como "desvío" son destinos de fondos que salieron de billeteras de OrionX. Quién las controla solo puede establecerlo la Fiscalía. Este monitor no acusa a nadie: documenta movimientos públicos para que los afectados y las autoridades tengan la misma información.

Licencia: dominio público (CC0). Copia, modifica y comparte sin pedir permiso.
