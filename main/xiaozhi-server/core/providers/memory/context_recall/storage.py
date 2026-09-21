# -*- coding: utf-8 -*-
"""本地存储：raw turns（证据源，服务端不落 turns）+ outbox（推送失败重试队列）。

设计文档：docs/singleton-mode-plan.md §4.2 第 2 步 / 降级链。
目录约定：``{项目根}/data/context_recall/{safe_role}/turns.jsonl`` 与
``{项目根}/data/context_recall/{safe_role}/outbox/{session_id}.json``。

所有磁盘操作都静默失败（记日志）：本地存储不可用时不能阻断对话与关连接流程。
"""

import json
import os
import re

from config.config_loader import get_project_dir

from ..base import logger

TAG = __name__

RAW_TURNS_FILE = "turns.jsonl"
OUTBOX_DIR_NAME = "outbox"


def safe_role_name(role_id: str) -> str:
    """role_id → 可作为目录名的安全字符串。"""
    return re.sub(r"[^0-9A-Za-z_\-]", "_", role_id or "unknown")


def storage_base_dir(role_id: str) -> str:
    """按角色隔离的存储根目录。"""
    return os.path.join(
        get_project_dir(), "data", "context_recall", safe_role_name(role_id)
    )


def _safe_file_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z._\-]", "_", value or "unknown")


def _session_id_of(snapshot: dict) -> str:
    sessions = snapshot.get("sessions") if isinstance(snapshot, dict) else None
    if isinstance(sessions, list) and sessions and isinstance(sessions[0], dict):
        session_id = sessions[0].get("id")
        if session_id:
            return str(session_id)
    return str((snapshot or {}).get("sessionId") or "unknown")


class RawTurnStore:
    """raw turns 追加存储：每行一个 JSON（ensure_ascii=False，保留中文原文）。"""

    def __init__(self, base_dir: str, role_id: str):
        self.base_dir = base_dir
        self.role_id = role_id
        self.path = os.path.join(base_dir, RAW_TURNS_FILE)

    def append_turns(self, turns: list) -> int:
        """追加写入；返回写入条数（失败返回 0，不抛异常）。"""
        if not turns:
            return 0
        try:
            os.makedirs(self.base_dir, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as file:
                for turn in turns:
                    file.write(json.dumps(turn, ensure_ascii=False) + "\n")
            return len(turns)
        except Exception as e:  # noqa: BLE001 - 本地存储失败不影响主流程
            logger.bind(tag=TAG).warning(f"raw turns 写入失败（忽略）: {e}")
            return 0

    def read_turns(self) -> list:
        """读取全部 raw turns（调试/测试用；文件不存在返回空列表）。"""
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                return [json.loads(line) for line in file if line.strip()]
        except FileNotFoundError:
            return []
        except Exception as e:  # noqa: BLE001
            logger.bind(tag=TAG).warning(f"raw turns 读取失败（忽略）: {e}")
            return []


class Outbox:
    """待推送快照队列：``put`` 落盘，``flush`` 逐个重投，成功即删除。"""

    def __init__(self, base_dir: str, role_id: str):
        self.base_dir = base_dir
        self.role_id = role_id
        self.dir = os.path.join(base_dir, OUTBOX_DIR_NAME)

    def _path(self, session_id: str) -> str:
        return os.path.join(self.dir, f"{_safe_file_name(session_id)}.json")

    def put(self, snapshot: dict) -> bool:
        """原子写入快照（先写 .tmp 再 os.replace）；失败返回 False。"""
        try:
            os.makedirs(self.dir, exist_ok=True)
            path = self._path(_session_id_of(snapshot))
            tmp_path = path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as file:
                json.dump(snapshot, file, ensure_ascii=False)
            os.replace(tmp_path, path)
            return True
        except Exception as e:  # noqa: BLE001 - outbox 落盘失败只能记日志
            logger.bind(tag=TAG).warning(f"outbox 写入失败（忽略）: {e}")
            return False

    def pending_count(self) -> int:
        """待推送快照数。"""
        try:
            return len(
                [
                    name
                    for name in os.listdir(self.dir)
                    if name.endswith(".json") and not name.endswith(".tmp")
                ]
            )
        except FileNotFoundError:
            return 0
        except Exception as e:  # noqa: BLE001
            logger.bind(tag=TAG).warning(f"outbox 计数失败（忽略）: {e}")
            return 0

    async def flush(self, client) -> int:
        """逐个 ``client.import_snapshot``；成功删除文件、失败保留；返回成功条数。"""
        try:
            names = sorted(
                name
                for name in os.listdir(self.dir)
                if name.endswith(".json") and not name.endswith(".tmp")
            )
        except FileNotFoundError:
            return 0
        except Exception as e:  # noqa: BLE001
            logger.bind(tag=TAG).warning(f"outbox 扫描失败（忽略）: {e}")
            return 0

        sent = 0
        for name in names:
            path = os.path.join(self.dir, name)
            try:
                with open(path, "r", encoding="utf-8") as file:
                    snapshot = json.load(file)
            except Exception as e:  # noqa: BLE001 - 损坏文件保留，人工排查
                logger.bind(tag=TAG).warning(f"outbox 文件无法解析，跳过: {name}: {e}")
                continue

            response = None
            try:
                response = await client.import_snapshot(snapshot)
            except Exception as e:  # noqa: BLE001 - 客户端异常同样视为失败
                logger.bind(tag=TAG).warning(f"outbox 重投异常: {name}: {e}")

            if response is None:
                continue  # 失败保留，等下次 flush
            try:
                os.remove(path)
            except OSError as e:
                logger.bind(tag=TAG).warning(f"outbox 删除失败: {name}: {e}")
                continue
            sent += 1
        if sent:
            logger.bind(tag=TAG).info(f"outbox 补投成功 {sent} 条（角色 {self.role_id}）")
        return sent
