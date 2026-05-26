import base64
import os
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


def _load_dotenv():
    """加载 .env 文件到环境变量"""
    # 从 generated_tests/ 根目录查找 .env
    env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("\"'")
            if key not in os.environ:
                os.environ[key] = value


def _get_key_iv() -> tuple:
    _load_dotenv()
    key = os.environ.get("AES_KEY")
    iv = os.environ.get("AES_IV")
    if not key or not iv:
        raise RuntimeError(
            "AES_KEY 和 AES_IV 必须通过环境变量或 .env 文件设置。\n"
            "创建 generated_tests/.env 文件，内容如下：\n"
            "  AES_KEY=1234567812345678\n"
            "  AES_IV=1234567812345678"
        )
    if len(key) not in (16, 24, 32):
        raise ValueError(f"AES_KEY must be 16/24/32 bytes, got {len(key)}")
    if len(iv) != 16:
        raise ValueError(f"AES_IV must be 16 bytes, got {len(iv)}")
    return key.encode("utf-8"), iv.encode("utf-8")


def aes_encrypt(plain_text: str) -> str:
    key, iv = _get_key_iv()
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded_data = pad(plain_text.encode("utf-8"), AES.block_size)
    encrypted_bytes = cipher.encrypt(padded_data)
    return base64.b64encode(encrypted_bytes).decode("utf-8")
