import base64
import threading


class AuthSession:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._authorization = None
                    cls._instance._session_id = None
                    cls._instance._credentials = {}
        return cls._instance

    @property
    def authorization(self) -> str:
        with self._lock:
            return self._authorization

    @authorization.setter
    def authorization(self, value: str):
        with self._lock:
            self._authorization = value

    @property
    def session_id(self) -> str:
        with self._lock:
            return self._session_id

    @session_id.setter
    def session_id(self, value: str):
        with self._lock:
            self._session_id = value

    @property
    def is_logged_in(self) -> bool:
        with self._lock:
            return self._authorization is not None

    def set_credentials(self, username: str, password: str, host: str = None):
        with self._lock:
            self._credentials = {
                "username": username,
                "password": password,
                "host": host,
            }

    def get_credentials(self) -> dict:
        with self._lock:
            return self._credentials.copy()

    @staticmethod
    def convert_session_id_to_auth(session_id: str) -> str:
        raw = f"{session_id}:session"
        encoded = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
        return f"Basic {encoded}"

    def login_from_response(self, response_json: dict) -> str:
        session_id = response_json.get("session_id")
        if not session_id:
            raise ValueError(f"登录响应中未找到 session_id，响应: {response_json}")
        with self._lock:
            self._session_id = session_id
            self._authorization = self.convert_session_id_to_auth(session_id)
            return self._authorization

    def clear(self):
        with self._lock:
            self._authorization = None
            self._session_id = None
            self._credentials = {}
