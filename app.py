import os
import uuid
from datetime import datetime
import boto3
from botocore.exceptions import ClientError
from flask import Flask, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
TABLE_NAME = os.environ.get("TABLE_NAME", "TicketsSoporte")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)


def bd_esta_pausada(table):
    """Verifica si la base de datos fue pausada desde el menu de control."""
    resp = table.get_item(Key={"ticket_id": "__ESTADO_BD__"})
    return resp.get("Item", {}).get("pausada", False)


@app.route("/")
def index():
    tickets = []
    db_conectada = True
    db_pausada = False
    error_msg = None

    try:
        table = dynamodb.Table(TABLE_NAME)
        db_pausada = bd_esta_pausada(table)
        respuesta = table.scan()
        tickets = [
            item for item in respuesta.get("Items", [])
            if item.get("ticket_id") != "__ESTADO_BD__"
        ]
        tickets.sort(key=lambda x: x.get("fecha_creacion", ""), reverse=True)
    except ClientError as e:
        db_conectada = False
        error_msg = e.response["Error"]["Message"]
    except Exception as e:
        db_conectada = False
        error_msg = str(e)

    total = len(tickets)
    abiertos = sum(1 for t in tickets if t.get("estado") == "Abierto")
    en_progreso = sum(1 for t in tickets if t.get("estado") == "En Progreso")
    resueltos = sum(1 for t in tickets if t.get("estado") == "Resuelto")

    return render_template(
        "index.html",
        table_name=TABLE_NAME,
        region=AWS_REGION,
        db_conectada=db_conectada,
        db_pausada=db_pausada,
        error_msg=error_msg,
        tickets=tickets,
        stats={
            "total": total,
            "abiertos": abiertos,
            "en_progreso": en_progreso,
            "resueltos": resueltos,
        },
    )


@app.route("/crear", methods=["POST"])
def crear_ticket():
    table = dynamodb.Table(TABLE_NAME)
    if bd_esta_pausada(table):
        return redirect(url_for("index"))

    titulo = request.form.get("titulo", "").strip()
    solicitante = request.form.get("solicitante", "").strip()
    prioridad = request.form.get("prioridad", "Media").strip()
    descripcion = request.form.get("descripcion", "").strip()

    if titulo and solicitante:
        ticket_id = f"TCK-{uuid.uuid4().hex[:4].upper()}"
        fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        table.put_item(
            Item={
                "ticket_id": ticket_id,
                "titulo": titulo,
                "solicitante": solicitante,
                "prioridad": prioridad,
                "descripcion": descripcion or "Sin detalles adicionales.",
                "estado": "Abierto",
                "fecha_creacion": fecha_actual,
            }
        )

    return redirect(url_for("index"))


@app.route("/estado/<ticket_id>", methods=["POST"])
def cambiar_estado(ticket_id):
    table = dynamodb.Table(TABLE_NAME)
    if bd_esta_pausada(table):
        return redirect(url_for("index"))

    nuevo_estado = request.form.get("nuevo_estado")
    if nuevo_estado in ("Abierto", "En Progreso", "Resuelto"):
        table.update_item(
            Key={"ticket_id": ticket_id},
            UpdateExpression="SET estado = :est",
            ExpressionAttributeValues={":est": nuevo_estado},
        )
    return redirect(url_for("index"))


@app.route("/eliminar/<ticket_id>", methods=["POST"])
def eliminar_ticket(ticket_id):
    table = dynamodb.Table(TABLE_NAME)
    if bd_esta_pausada(table):
        return redirect(url_for("index"))

    table.delete_item(Key={"ticket_id": ticket_id})
    return redirect(url_for("index"))


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "tickets-web"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)