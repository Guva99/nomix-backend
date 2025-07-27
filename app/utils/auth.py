import secrets

def generate_token() -> str:
    return secrets.token_hex(16)