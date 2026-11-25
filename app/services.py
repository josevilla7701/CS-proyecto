import hashlib
import random


class JuegoService:
    @staticmethod
    def desordenar_palabra(palabra: str) -> str:
        palabra_upper = palabra.upper()
        letras = list(palabra_upper)
        if len(letras) <= 2:
            return palabra_upper
        while True:
            random.shuffle(letras)
            resultado = "".join(letras)
            if resultado != palabra_upper:
                return resultado


class BlockchainService:
    GENESIS_PREV_HASH = "0" * 64

    @staticmethod
    def calcular_hash(
        bloque_id: int,
        timestamp_str: str,
        jugador: str,
        intento_num: int,
        puntuacion: int,
        palabras: int,
        prev_hash: str,
    ) -> str:
        """Implementa: hash_actual = SHA256(ID || timestamp || datos || prev_hash)"""
        datos = f"jugador={jugador}|intento={intento_num}|puntos={puntuacion}|palabras={palabras}"
        cadena_cruda = f"{bloque_id}||{timestamp_str}||{datos}||{prev_hash}"
        return hashlib.sha256(cadena_cruda.encode("utf-8")).hexdigest()