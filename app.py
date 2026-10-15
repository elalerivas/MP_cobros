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

def to_ar_date(s):
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(AR).date()
    except:
        return None

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

        try:
            desde = datetime.strptime(desde_str, "%Y-%m-%d").date() if desde_str else None
            hasta = datetime.strptime(hasta_str, "%Y-%m-%d").date() if hasta_str else None
        except ValueError:
            desde = hasta = None

        monto_f = None
        if monto_str:
            try:
                monto_f = float(monto_str.replace(",", "."))
            except ValueError:
                pass

        def fetch_endpoint(endpoint):
            results = []
            offset  = 0
            limit   = 100
            while True:
                resp = sdk.payment().search({
                    "offset": offset,
                    "limit":  limit,
                    **({"operation_type": "regular_payment"} if endpoint == "received" else
                       {"operation_type": "money_transfer"}  if endpoint == "sent"     else {})
                })
                data  = resp.get("response", {})
                items = data.get("results", [])
                if not items:
                    break
                results.extend(items)
                paging = data.get("paging", {})
                if offset + limit >= paging.get("total", 0):
                    break
                offset += limit
            return results

        if tipo == "all":
            items = fetch_endpoint("received") + fetch_endpoint("sent")
            items.sort(key=lambda p: p.get("date_created",""), reverse=False)
        else:
            items = fetch_endpoint(tipo)

        rows = []
        for p in items:
            fecha_ar = to_ar_date(p.get("date_created",""))
            if desde and fecha_ar and fecha_ar < desde:
                continue
            if hasta and fecha_ar and fecha_ar > hasta:
                continue
            amt = float(p.get("transaction_amount") or 0)
            if monto_f is not None and abs(amt - monto_f) > 0.01:
                continue
            rows.append({
                "fecha":  fmt_date(p.get("date_created","")),
                "monto":  amt,
                "estado": p.get("status", "-"),
            })

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
