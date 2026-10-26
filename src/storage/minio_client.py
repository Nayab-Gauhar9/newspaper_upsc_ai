from io import BytesIO
import json
import os
import socket
from datetime import datetime
from dotenv import load_dotenv
from minio import Minio
from minio.error import S3Error

load_dotenv()


def is_local_minio_alive(
    host: str = "127.0.0.1", port: int = 9000, timeout: float = 0.5
) -> bool:
    """Quick check to see if local MinIO port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class NewspaperStorage:

    def __init__(self, force_r2: bool = False):
        env_mode = os.getenv("STORAGE_TARGET", "auto").lower()
        use_r2 = force_r2 or env_mode == "r2"

        # Check local MinIO health unless forced to R2
        if not use_r2 and is_local_minio_alive():
            # 1. PRIMARY: Local MinIO
            access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
            secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")
            self.client = Minio(
                "localhost:9000",
                access_key=access_key,
                secret_key=secret_key,
                secure=False,
            )
            self.bucket = os.getenv("MINIO_BUCKET_NAME", "upsc-ai")
            self.target_name = "Local MinIO"
        else:
            # 2. FALLBACK: Cloudflare R2
            r2_endpoint = os.getenv("R2_ENDPOINT_URL")
            r2_access_key = os.getenv("R2_ACCESS_KEY_ID")
            r2_secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
            bucket_name = os.getenv("R2_BUCKET_NAME", "upsc-ai")

            if not (r2_endpoint and r2_access_key and r2_secret_key):
                raise RuntimeError(
                    "Local MinIO is down and R2 credentials are missing from environment."
                )
            clean_endpoint = (
                r2_endpoint.replace("https://", "")
                .replace("http://", "")
                .strip("/")
            )
            self.client = Minio(
                clean_endpoint,
                access_key=r2_access_key,
                secret_key=r2_secret_key,
                secure=True,
                region="auto",
            )
            self.bucket = bucket_name
            self.target_name = "Cloudflare R2"

        self.ensure_bucket_exists()

    def ensure_bucket_exists(self):
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except Exception as e:
            print(f"[!] Warning checking bucket: {e}")

    def upload_json(self, object_name: str, data: dict):
        content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.client.put_object(
            self.bucket,
            object_name,
            BytesIO(content),
            length=len(content),
            content_type="application/json",
        )

    def put_json(self, object_name: str, data: dict):
        """Alias for backward compatibility with existing collectors."""
        self.upload_json(object_name, data)

    def get_json(self, object_name: str) -> dict:
        try:
            response = self.client.get_object(self.bucket, object_name)
            data = response.read()
            return json.loads(data.decode("utf-8"))
        except S3Error as e:
            if e.code == "NoSuchKey":
                return {}
            raise
        finally:
            if "response" in locals():
                response.close()
                response.release_conn()

    def object_exists(self, object_name: str) -> bool:
        try:
            self.client.stat_object(self.bucket, object_name)
            return True
        except S3Error as e:
            if e.code == "NoSuchKey":
                return False
            raise

    def list_objects(self, prefix: str = "") -> list[str]:
        """Returns a list of string object keys matching the prefix."""
        try:
            objects = self.client.list_objects(
                self.bucket, prefix=prefix, recursive=True
            )
            return [obj.object_name for obj in objects]
        except Exception as e:
            print(f"[!] Error listing MinIO objects: {e}")
            return []
    def upload_static_chapter_note(self, chapter_id: int, note_data: dict) -> str:
        """Stores precomputed static Laxmikanth chapter dossier in upsc-ai bucket."""
        object_name = f"static/laxmikanth/chapter_{chapter_id:02d}.json"
        self.upload_json(object_name, note_data)
        return object_name

    def get_static_chapter_note(self, chapter_id: int) -> dict | None:
        """Fetches precomputed static Laxmikanth chapter note from upsc-ai bucket."""
        object_name = f"static/laxmikanth/chapter_{chapter_id:02d}.json"
        try:
            return self.get_json(object_name)
        except Exception:
            return None