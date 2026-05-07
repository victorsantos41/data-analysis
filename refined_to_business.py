from datetime import datetime


def process_refined_to_business():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Etapa desativada.")
    print(
        "A camada business deixou de existir operacionalmente. "
        "A agregacao agora ocorre dentro de trusted_to_refined.py, "
        "e a camada refined ja sai consolidada para o consumo de IBGE."
    )


if __name__ == "__main__":
    process_refined_to_business()
