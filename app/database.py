import os
import boto3

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
TABLE_NAME = os.environ.get("TABLE_NAME", "ScrambleBlockchain")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)


def get_table():
    return dynamodb.Table(TABLE_NAME)


def bd_esta_pausada(table) -> bool:
    """Verifica si la base de datos fue pausada desde el menú de control AWS."""
    resp = table.get_item(Key={"pk": "CONFIG#ESTADO_BD"})
    return bool(resp.get("Item", {}).get("pausada", False))


ANIMALES_INICIALES = [
    {"id": 1, "nombre": "TIGRE", "pista": "Felino rayado de gran tamaño habitante de Asia", "dificultad": "Fácil"},
    {"id": 2, "nombre": "DELFIN", "pista": "Mamífero marino muy inteligente que usa ecolocalización", "dificultad": "Fácil"},
    {"id": 3, "nombre": "AGUILA", "pista": "Ave rapaz de visión aguda y gran envergadura", "dificultad": "Fácil"},
    {"id": 4, "nombre": "JAGUAR", "pista": "El felino más grande de América", "dificultad": "Fácil"},
    {"id": 5, "nombre": "TORTUGA", "pista": "Reptil con caparazón duro y movimiento lento", "dificultad": "Fácil"},
    {"id": 6, "nombre": "PINGUINO", "pista": "Ave marina no voladora adaptada al frío extremo", "dificultad": "Media"},
    {"id": 7, "nombre": "COCODRILO", "pista": "Reptil semiacuático prehistórico de mandíbula poderosa", "dificultad": "Media"},
    {"id": 8, "nombre": "CAMALEON", "pista": "Reptil famoso por cambiar de color y mover ojos independientes", "dificultad": "Media"},
    {"id": 9, "nombre": "MURCIELAGO", "pista": "Único mamífero capaz de volar de forma sostenida", "dificultad": "Media"},
    {"id": 10, "nombre": "RINOCERONTE", "pista": "Mamífero herbívoro pesado con uno o dos cuernos en el hocico", "dificultad": "Media"},
    {"id": 11, "nombre": "ORNITORRINCO", "pista": "Mamífero semiacuático australiano que pone huevos y tiene pico de pato", "dificultad": "Difícil"},
    {"id": 12, "nombre": "HIPOPOTAMO", "pista": "Mamífero africano semiacuático muy territorial", "dificultad": "Difícil"},
    {"id": 13, "nombre": "SALAMANDRA", "pista": "Anfibio con cola capaz de regenerar extremidades", "dificultad": "Difícil"},
    {"id": 14, "nombre": "PUERCOESPIN", "pista": "Roedor cubierto de púas afiladas como defensa", "dificultad": "Difícil"},
    {"id": 15, "nombre": "ARMADILLO", "pista": "Mamífero americano protegido por placas óseas", "dificultad": "Difícil"},
]


def inicializar_catalogo_animales():
    """Inserta el catálogo de animales en DynamoDB solo si aún no existen."""
    try:
        table = get_table()
        check = table.get_item(Key={"pk": "ANIMAL#1"})
        if "Item" in check:
            return

        with table.batch_writer() as batch:
            for a in ANIMALES_INICIALES:
                batch.put_item(
                    Item={
                        "pk": f"ANIMAL#{a['id']}",
                        "tipo": "ANIMAL",
                        "animal_id": a["id"],
                        "nombre": a["nombre"],
                        "pista": a["pista"],
                        "dificultad": a["dificultad"],
                        "activo": True,
                    }
                )
    except Exception as e:
        print(f"Aviso inicializando animales en DynamoDB: {e}")