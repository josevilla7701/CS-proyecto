import random
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Attr
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from . import schemas
from .database import (
    AWS_REGION,
    TABLE_NAME,
    bd_esta_pausada,
    get_table,
    inicializar_catalogo_animales,
)
from .services import BlockchainService, JuegoService

app = FastAPI(title="IH063 Criptografía - Mini-Blockchain Scramble (DynamoDB)")


@app.on_event("startup")
def startup_event():
    inicializar_catalogo_animales()


def obtener_todos_los_bloques(table) -> list:
    """Obtiene y ordena ascendentemente todos los bloques almacenados en DynamoDB."""
    resp = table.scan(FilterExpression=Attr("tipo").eq("BLOQUE"))
    items = resp.get("Items", [])
    bloques = []
    for it in items:
        bloques.append({
            "id": int(it["bloque_id"]),
            "timestamp_str": it["timestamp_str"],
            "jugador": it["jugador"],
            "intento_num": int(it["intento_num"]),
            "puntuacion": int(it["puntuacion"]),
            "palabras_adivinadas": int(it["palabras_adivinadas"]),
            "prev_hash": it["prev_hash"],
            "hash_actual": it["hash_actual"],
        })
    bloques.sort(key=lambda x: x["id"])
    return bloques


def verificar_integridad_lista(bloques: list):
    """Audita una lista ordenada de bloques de un mismo jugador."""
    integra = True
    errores = []
    resultado = []

    for i, b in enumerate(bloques):
        prev_esperado = BlockchainService.GENESIS_PREV_HASH if i == 0 else bloques[i - 1]["hash_actual"]
        hash_recalculado = BlockchainService.calcular_hash(
            b["id"],
            b["timestamp_str"],
            b["jugador"],
            b["intento_num"],
            b["puntuacion"],
            b["palabras_adivinadas"],
            b["prev_hash"],
        )
        enlace_valido = b["prev_hash"] == prev_esperado
        contenido_valido = b["hash_actual"] == hash_recalculado
        valido = enlace_valido and contenido_valido

        if not valido:
            integra = False
            motivos = []
            if not contenido_valido:
                motivos.append("datos modificados (SHA-256 no coincide)")
            if not enlace_valido:
                motivos.append("enlace roto con el intento anterior")
            errores.append(
                f"Bloque #{b['id']} ({b['jugador']} - Intento #{b['intento_num']}): " + " y ".join(motivos)
            )

        resultado.append({
            "id": b["id"],
            "timestamp": b["timestamp_str"],
            "jugador": b["jugador"],
            "intento_num": b["intento_num"],
            "puntuacion": b["puntuacion"],
            "palabras_adivinadas": b["palabras_adivinadas"],
            "prev_hash": b["prev_hash"],
            "hash_actual": b["hash_actual"],
            "valido": valido,
        })

    return integra, errores, resultado


@app.get("/health")
def health_check():
    table = get_table()
    return {
        "status": "ok",
        "table": TABLE_NAME,
        "region": AWS_REGION,
        "db_pausada": bd_esta_pausada(table),
    }


@app.get("/api/estado-bd")
def estado_bd():
    table = get_table()
    return {
        "pausada": bd_esta_pausada(table),
        "table_name": TABLE_NAME,
        "region": AWS_REGION,
    }


@app.get("/api/jugador/{nombre}")
def obtener_historial_jugador(nombre: str):
    nombre_limpio = nombre.strip().upper()
    table = get_table()
    todos = obtener_todos_los_bloques(table)
    bloques = [b for b in todos if b["jugador"] == nombre_limpio]

    if not bloques:
        return {
            "existe": False,
            "jugador": nombre_limpio,
            "integra": True,
            "intentos": 0,
            "max_puntuacion": 0,
            "ultimo_intento": None,
        }

    integra, _, _ = verificar_integridad_lista(bloques)
    max_pts = max(b["puntuacion"] for b in bloques)
    ultimo = bloques[-1]
    return {
        "existe": True,
        "jugador": nombre_limpio,
        "integra": integra,
        "intentos": len(bloques),
        "max_puntuacion": max_pts,
        "ultimo_intento": {
            "bloque_id": ultimo["id"],
            "intento_num": ultimo["intento_num"],
            "puntuacion": ultimo["puntuacion"],
            "palabras": ultimo["palabras_adivinadas"],
            "hash": ultimo["hash_actual"],
        },
    }


@app.get("/api/juego/siguiente", response_model=schemas.AnimalOut)
def obtener_siguiente_animal():
    table = get_table()
    resp = table.scan(FilterExpression=Attr("tipo").eq("ANIMAL") & Attr("activo").eq(True))
    animales = resp.get("Items", [])
    if not animales:
        raise HTTPException(status_code=404, detail="No hay animales disponibles en DynamoDB")

    animal = random.choice(animales)
    nombre = animal["nombre"]
    return schemas.AnimalOut(
        id=int(animal["animal_id"]),
        palabra_desordenada=JuegoService.desordenar_palabra(nombre),
        pista=animal["pista"],
        longitud=len(nombre),
        dificultad=animal["dificultad"],
    )


@app.post("/api/juego/validar")
def validar_respuesta(datos: schemas.ValidarRequest):
    table = get_table()
    resp = table.get_item(Key={"pk": f"ANIMAL#{datos.animal_id}"})
    animal = resp.get("Item")
    if not animal:
        raise HTTPException(status_code=404, detail="Animal no encontrado")

    es_correcto = animal["nombre"].upper() == datos.respuesta.strip().upper()
    return {"correcto": es_correcto, "nombre_correcto": animal["nombre"]}


@app.post("/api/blockchain/minar-bloque")
def registrar_bloque_partida(datos: schemas.RegistrarBloqueRequest):
    table = get_table()
    if bd_esta_pausada(table):
        raise HTTPException(
            status_code=503,
            detail="Base de datos PAUSADA por el administrador AWS. Reanúdala desde el menú para guardar partidas.",
        )

    jugador_limpio = datos.jugador.strip().upper()
    todos = obtener_todos_los_bloques(table)
    bloques_jugador = [b for b in todos if b["jugador"] == jugador_limpio]

    integra, _, _ = verificar_integridad_lista(bloques_jugador)
    if not integra:
        raise HTTPException(
            status_code=403,
            detail="Esta cadena fue alterada y no se puede seguir usando.",
        )

    ultimo_del_jugador = bloques_jugador[-1] if bloques_jugador else None
    prev_hash = ultimo_del_jugador["hash_actual"] if ultimo_del_jugador else BlockchainService.GENESIS_PREV_HASH
    intento_num = len(bloques_jugador) + 1

    nuevo_id = (todos[-1]["id"] + 1) if todos else 1
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    hash_calculado = BlockchainService.calcular_hash(
        nuevo_id, ts, jugador_limpio, intento_num, datos.puntuacion, datos.palabras_adivinadas, prev_hash
    )

    pk = f"BLOQUE#{nuevo_id:06d}"
    table.put_item(
        Item={
            "pk": pk,
            "tipo": "BLOQUE",
            "bloque_id": nuevo_id,
            "timestamp_str": ts,
            "jugador": jugador_limpio,
            "intento_num": intento_num,
            "puntuacion": datos.puntuacion,
            "palabras_adivinadas": datos.palabras_adivinadas,
            "prev_hash": prev_hash,
            "hash_actual": hash_calculado,
        }
    )

    return {
        "id": nuevo_id,
        "timestamp_str": ts,
        "jugador": jugador_limpio,
        "intento_num": intento_num,
        "puntuacion": datos.puntuacion,
        "palabras_adivinadas": datos.palabras_adivinadas,
        "prev_hash": prev_hash,
        "hash_actual": hash_calculado,
    }


@app.get("/api/blockchain/cadena")
def obtener_cadena_y_verificar():
    table = get_table()
    todos = obtener_todos_los_bloques(table)

    global_integra = True
    todos_errores = []
    mapa_validez = {}

    jugadores = sorted(set(b["jugador"] for b in todos))
    for jug in jugadores:
        b_jug = [b for b in todos if b["jugador"] == jug]
        ok, errs, res_jug = verificar_integridad_lista(b_jug)
        if not ok:
            global_integra = False
            todos_errores.extend(errs)
        for item in res_jug:
            mapa_validez[item["id"]] = item["valido"]

    bloques_out = [
        {
            "id": b["id"],
            "timestamp": b["timestamp_str"],
            "jugador": b["jugador"],
            "intento_num": b["intento_num"],
            "puntuacion": b["puntuacion"],
            "palabras_adivinadas": b["palabras_adivinadas"],
            "prev_hash": b["prev_hash"],
            "hash_actual": b["hash_actual"],
            "valido": mapa_validez.get(b["id"], True),
        }
        for b in todos
    ]

    return {
        "integra": global_integra,
        "total_bloques": len(todos),
        "errores": todos_errores,
        "bloques": bloques_out,
    }


@app.post("/api/blockchain/simular-ataque")
def simular_ataque(datos: schemas.SimularAtaqueRequest):
    table = get_table()
    if bd_esta_pausada(table):
        raise HTTPException(
            status_code=503,
            detail="Base de datos PAUSADA por el administrador AWS. No se pueden modificar bloques.",
        )

    pk = f"BLOQUE#{datos.bloque_id:06d}"
    resp = table.get_item(Key={"pk": pk})
    bloque = resp.get("Item")
    if not bloque:
        raise HTTPException(status_code=404, detail="Bloque no encontrado")

    todos = obtener_todos_los_bloques(table)
    bloques_jug = [b for b in todos if b["jugador"] == bloque["jugador"]]
    integra, _, _ = verificar_integridad_lista(bloques_jug)
    if not integra:
        raise HTTPException(
            status_code=403,
            detail="Esta cadena ya fue alterada y no se puede volver a alterar ni usar.",
        )

    table.update_item(
        Key={"pk": pk},
        UpdateExpression="SET puntuacion = :p",
        ExpressionAttributeValues={":p": datos.nueva_puntuacion},
    )
    return {"mensaje": f"Ataque ejecutado sobre el Bloque #{datos.bloque_id} ({bloque['jugador']})."}


app.mount("/", StaticFiles(directory="static", html=True), name="static")