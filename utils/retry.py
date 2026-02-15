# utils/retry.py

import time
import random
import socket
from functools import wraps
from googleapiclient.errors import HttpError

def execute_with_retries(
    request_fn,
    max_retries=5,
    logger=None,
    context='',
    exceptions=(TimeoutError, socket.timeout, HttpError),
    initial_wait=1,
    max_wait=30,
    total_timeout=None
):
    """
    Executa uma função de request com tentativas automáticas (retry).
    """
    start_time = time.monotonic()
    for attempt in range(1, max_retries + 1):
        try:
            return request_fn()
        except exceptions as e:
            elapsed = time.monotonic() - start_time
            if total_timeout and elapsed >= total_timeout:
                msg = f"[RETRY] Timeout global ({total_timeout}s) excedido ao executar {context}: {type(e).__name__} - {e}"
                if logger:
                    logger.error(msg)
                else:
                    print(msg)
                raise
            if attempt == max_retries:
                msg = f"[RETRY] Todas as {max_retries} tentativas falharam ao executar {context}: {type(e).__name__} - {e}"
                if logger:
                    logger.error(msg)
                else:
                    print(msg)
                raise

            sleep_time = min(initial_wait * 2 ** (attempt - 1), max_wait)
            sleep_time = sleep_time * (0.7 + 0.6 * random.random())  # jitter

            # Loga explicitamente o retry:
            retry_msg = (
                f"[RETRY] {context}: Tentativa {attempt + 1}/{max_retries} após erro {type(e).__name__}: {e}"
            )
            if logger:
                logger.warning(retry_msg)  # <-- Aqui loga retry
            else:
                print(retry_msg)

            msg = (
                f"[RETRY] Erro ao executar {context}: {type(e).__name__} - {e} "
                f"(tentativa {attempt}/{max_retries}). "
                f"Tentando novamente em {sleep_time:.1f}s..."
            )
            if logger:
                logger.warning(msg)
            else:
                print(msg)
            time.sleep(sleep_time)
