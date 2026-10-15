from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime, timezone, timedelta
import mercadopago
import os

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

AR = timezone(timedelta(hours=-3))

def fmt_date(s):
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(AR).strftime("%d/%m/%Y %H:%M")
    except:
        return s or "-"

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/pagos")
def pagos():
    token     = request.args.get("token", "").strip()
    tipo      = request.args.get("tipo", "received")
    desde_str = request.args.get("desde", "")
    hasta_str = request.args.get("hasta", "")
    monto_str = request.args.get("monto", "").strip()

    if not token:
        return jsonify({"error": "Token requerido"}), 400

    try:
        sdk = mercadopago.SDK(token)

        # Obtener user_id del token
        user_resp = sdk.user().get()
        user_data = user_resp.get("response", {})
        user_id   = str(user_data.get("id", ""))
        if not user_id:
            return jsonify({"error": "No se pudo obtener el user_id del token"}), 400

        monto_f = None
        if monto_str:
            try:
                monto_f = float(monto_str.replace(",", "."))
            except ValueError:
                pass

        # Fechas en formato ISO con zona horaria AR
        desde_dt = datetime.strptime(desde_str, "%Y-%m-%d") if desde_str else (datetime.now(AR) - timedelta(days=30))
        hasta_dt = datetime.strptime(hasta_str, "%Y-%m-%d") if hasta_str else datetime.now(AR)

        begin_date = desde_dt.strftime("%Y-%m-%dT00:00:00.000-03:00")
        end_date   = hasta_dt.strftime("%Y-%m-%dT23:59:59.999-03:00")

        all_items = []
        offset = 0
        limit  = 200
        while True:
            resp = sdk.payment().search(filters={
                "sort":       "date_created",
                "criteria":   "desc",
                "limit":      limit,
                "offset":     offset,
                "begin_date": begin_date,
                "end_date":   end_date,
            })
            data  = resp.get("response", {})
            items = data.get("results", [])
            if not items:
                break
            all_items.extend(items)
            paging = data.get("paging", {})
            if offset + limit >= paging.get("total", 0):
                break
            offset += limit

        # Filtrar
        def is_received(p):
            col        = str(p.get("collector_id", ""))
            root_payer = str(p.get("payer_id", ""))
            return col == user_id and root_payer != user_id

        def is_sent(p):
            return str(p.get("payer_id", "")) == user_id

        rows = []
        for p in all_items:
            if tipo == "received" and not is_received(p):
                continue
            if tipo == "sent" and not is_sent(p):
                continue

            amt = float(p.get("transaction_amount") or 0)
            if monto_f is not None and abs(amt - monto_f) > 0.01:
                continue

            rows.append({
                "fecha":  fmt_date(p.get("date_created", "")),
                "monto":  amt,
                "estado": p.get("status", "-"),
            })

        rows.sort(key=lambda r: r["fecha"])

        acum = 0.0
        for r in rows:
            if r["estado"] == "approved":
                acum += r["monto"]
                r["acumulado"] = acum
            else:
                r["acumulado"] = None

        return jsonify({"rows": rows, "total": acum})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
