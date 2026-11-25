from pydantic import BaseModel


class AnimalOut(BaseModel):
    id: int
    palabra_desordenada: str
    pista: str
    longitud: int
    dificultad: str


class ValidarRequest(BaseModel):
    animal_id: int
    respuesta: str


class RegistrarBloqueRequest(BaseModel):
    jugador: str
    puntuacion: int
    palabras_adivinadas: int


class SimularAtaqueRequest(BaseModel):
    bloque_id: int
    nueva_puntuacion: int