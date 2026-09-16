"""環境変数(.env)からの設定読み込み。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    majsoul_email: str | None
    majsoul_password: str | None
    majsoul_yostar_token: str | None
    majsoul_yostar_uid: str | None
    majsoul_device_id: str | None
    majsoul_server: str
    data_dir: Path
    mortal_binary_path: Path
    mortal_model_path: Path
    my_account_id: int | None

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def parsed_dir(self) -> Path:
        return self.data_dir / "parsed"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "mahjong_analyzer.db"

    def require_credentials(self) -> tuple[str, str]:
        if not self.majsoul_email or not self.majsoul_password:
            raise RuntimeError(
                "MAJSOUL_EMAIL / MAJSOUL_PASSWORD が設定されていません。"
                ".env.example を .env にコピーして値を入力してください。"
            )
        return self.majsoul_email, self.majsoul_password


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or _PROJECT_ROOT / ".env")

    data_dir = Path(os.environ.get("MAHJONG_ANALYZER_DATA_DIR", "data"))
    if not data_dir.is_absolute():
        data_dir = _PROJECT_ROOT / data_dir

    mortal_binary_path = Path(
        os.environ.get("MORTAL_BINARY_PATH", str(_PROJECT_ROOT / "mortal" / "target" / "release" / "mortal"))
    )
    mortal_model_path = Path(
        os.environ.get("MORTAL_MODEL_PATH", str(_PROJECT_ROOT / "mortal" / "model" / "mortal_298k.pth"))
    )
    # 注意: MAJSOUL_YOSTAR_UIDはログイン用のYostar内部uidであり、牌譜内の
    # account_id(players.account_id)とは別の値なので流用しない。
    my_account_id_str = os.environ.get("MY_ACCOUNT_ID")

    settings = Settings(
        majsoul_email=os.environ.get("MAJSOUL_EMAIL") or None,
        majsoul_password=os.environ.get("MAJSOUL_PASSWORD") or None,
        majsoul_yostar_token=os.environ.get("MAJSOUL_YOSTAR_TOKEN") or None,
        majsoul_yostar_uid=os.environ.get("MAJSOUL_YOSTAR_UID") or None,
        majsoul_device_id=os.environ.get("MAJSOUL_DEVICE_ID") or None,
        majsoul_server=os.environ.get("MAJSOUL_SERVER", "jp"),
        data_dir=data_dir,
        mortal_binary_path=mortal_binary_path,
        mortal_model_path=mortal_model_path,
        my_account_id=int(my_account_id_str) if my_account_id_str else None,
    )
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    settings.parsed_dir.mkdir(parents=True, exist_ok=True)
    return settings
