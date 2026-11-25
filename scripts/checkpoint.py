#!/usr/bin/env python3
"""创建、查看和恢复 vibe-code 的项目检查点。"""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager, nullcontext
from datetime import datetime
from pathlib import Path


VIBE = "docs/vibe"
STORE = Path(VIBE) / "checkpoints"
CACHE_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache",
}
CHECKPOINT_ID = re.compile(r"cp-(\d+)")
OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


class CheckpointError(Exception):
    pass


def git(root, *args, env=None, **streams):
    git_env = {
        key: value for key, value in os.environ.items()
        if key not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"}
    }
    git_env.update(LC_ALL="C", GIT_OPTIONAL_LOCKS="0")
    git_env.update(env or {})
    return subprocess.run(
        ["git", *args], cwd=root, env=git_env, stderr=subprocess.PIPE,
        timeout=60, **({"stdout": subprocess.PIPE} | streams),
    )


def git_checked(root, *args, **kwargs):
    result = git(root, *args, **kwargs)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise CheckpointError(f"git {args[0]} 失败：{detail}")
    return result.stdout


def git_index(root):
    if shutil.which("git") is None:
        if lstat(root / ".git") is not None:
            raise CheckpointError("项目有 Git 元数据，但找不到 git 命令。")
        return None
    result = git(root, "rev-parse", "--show-toplevel")
    if result.returncode:
        if b"not a git repository" in result.stderr and lstat(root / ".git") is None:
            return None
        raise CheckpointError(result.stderr.decode("utf-8", errors="replace").strip())
    if Path(os.fsdecode(result.stdout.rstrip(b"\r\n"))).resolve() != root:
        return None
    location = git_checked(root, "rev-parse", "--path-format=absolute", "--git-path", "index")
    return Path(os.fsdecode(location.rstrip(b"\r\n")))


def lstat(path):
    try:
        return path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return None


def plain_directory(info):
    return (
        info is not None and stat.S_ISDIR(info.st_mode)
        and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def link_info(info):
    return info is not None and stat.S_ISLNK(info.st_mode)


def excluded(rel):
    parts = rel.lower().split("/")
    return parts[:2] == ["docs", "vibe"] or ".git" in parts


def validate_path(rel):
    if not isinstance(rel, str) or not rel or any(
        part in {"", ".", ".."} or "\x00" in part or "\\" in part
        or (os.name == "nt" and (":" in part or part.endswith((".", " "))))
        for part in rel.split("/")
    ):
        raise CheckpointError(f"无效的项目相对路径：{rel!r}")
    return rel


def relative_child(root, path):
    return path.relative_to(root).as_posix()


def path_at(root, rel):
    """查看相对路径，遇到链接或重解析点时不穿过。"""
    path = root
    parts = rel.split("/")
    for part in parts[:-1]:
        path = path / part
        if not plain_directory(lstat(path)):
            return None
    return lstat(path / parts[-1])


def safe_store(root):
    path = root
    for part in STORE.parts:
        path /= part
        info = lstat(path)
        if info is not None and not plain_directory(info):
            raise CheckpointError(f"检查点目录必须是普通目录：{path}")
    return path


def scan_tree(root, directory, *, project_scope=False):
    for child in sorted(directory.iterdir()):
        rel = relative_child(root, child)
        if project_scope and excluded(rel):
            continue
        info = lstat(child)
        if info is None:
            raise CheckpointError(f"扫描期间路径消失：{rel}")
        if plain_directory(info):
            if project_scope and (child.name.lower() in CACHE_DIRS or lstat(child / ".git") is not None):
                continue
            yield from scan_tree(root, child, project_scope=project_scope)
        else:
            yield validate_path(rel), info


def contains_nested_repo(root, rel):
    path = root
    for part in rel.split("/")[:-1]:
        path /= part
        if not plain_directory(lstat(path)):
            break
        if lstat(path / ".git") is not None:
            return True
    return False


def parse_index(raw):
    entries = {}
    for line in os.fsdecode(raw).split("\0"):
        if not line:
            continue
        header, sep, rel = line.partition("\t")
        fields = header.split()
        if not sep or len(fields) != 3:
            raise CheckpointError("Git 暂存区记录格式无效。")
        mode, oid, stage = fields
        if mode not in {"100644", "100755", "120000", "160000"} or not OBJECT_ID.fullmatch(oid) or stage not in "0123" or len(stage) != 1:
            raise CheckpointError("Git 暂存区记录格式无效。")
        entries.setdefault(validate_path(rel), []).append(line)
    return entries


def scoped_index(root, entries):
    return {
        rel: lines for rel, lines in entries.items()
        if not excluded(rel) and not lines[0].startswith("160000 ")
        and not contains_nested_repo(root, rel)
    }


def live_index(root):
    entries = parse_index(git_checked(root, "ls-files", "--stage", "-z"))
    check_index_flags(root, scoped_index(root, entries))
    return entries



def check_index_flags(root, entries):
    if not entries:
        return
    # --stage omits flags such as intent-to-add. Don't turn them into ordinary staged files.
    debug = git_checked(root, "ls-files", "--debug", "-z")
    flag_line = re.compile(rb"\tflags: ([0-9a-fA-F]+)\r?\n")
    offset = 0
    while offset < len(debug):
        end = debug.find(b"\0", offset)
        match = flag_line.search(debug, end + 1) if end != -1 else None
        if match is None:
            raise CheckpointError("无法读取 Git 暂存区的扩展标记。")
        rel = os.fsdecode(debug[offset:end])
        flags = int(match.group(1), 16)
        if rel in entries and flags & (0x8000 | 0x20000000 | 0x40000000):
            raise CheckpointError(
                f"此检查点无法完整保存 Git 暂存标记（intent-to-add、assume-unchanged 或 skip-worktree）：{rel}"
            )
        offset = match.end()



def project_files(root, entries):
    if entries is None:
        return dict(scan_tree(root, root, project_scope=True))
    other = git_checked(root, "ls-files", "--others", "--exclude-standard", "-z")
    managed = set(scoped_index(root, entries))
    submodules = {rel for rel, lines in entries.items() if lines[0].startswith("160000 ")}
    for rel in os.fsdecode(other).split("\0"):
        if not rel or rel.endswith("/") or excluded(rel):
            continue
        rel = validate_path(rel)
        parts = rel.split("/")
        if not any("/".join(parts[:i]) in submodules for i in range(1, len(parts) + 1)):
            if not contains_nested_repo(root, rel):
                managed.add(rel)
    files = {}
    for rel in sorted(managed):
        info = path_at(root, rel)
        if info is not None and not plain_directory(info):
            files[rel] = info
    return files


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def same_file_version(first, second):
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    return second is not None and all(getattr(first, key) == getattr(second, key) for key in fields)


def describe(path, info):
    if link_info(info):
        return {
            "link": os.readlink(path),
            "directory": bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_DIRECTORY),
        }
    if not stat.S_ISREG(info.st_mode):
        raise CheckpointError(f"无法对特殊文件或目录联接建立检查点：{path}")
    return {"sha256": digest(path), "mode": stat.S_IMODE(info.st_mode)}


def empty_index():
    return {"checkpoints": [], "next_id": 0}


def load_index(store):
    path = store / "index.json"
    info = lstat(path)
    if info is None:
        return empty_index()
    if not stat.S_ISREG(info.st_mode):
        raise CheckpointError(f"检查点索引不是普通文件：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("checkpoints"), list):
        raise CheckpointError(f"检查点索引格式无效：{path}")
    records = data["checkpoints"]
    if any(not isinstance(cp, dict) or not isinstance(cp.get("id"), str)
           or not CHECKPOINT_ID.fullmatch(cp["id"]) for cp in records):
        raise CheckpointError(f"检查点编号无效：{path}")
    if len({cp["id"] for cp in records}) != len(records):
        raise CheckpointError(f"检查点编号重复：{path}")
    if type(data.get("next_id", 0)) is not int or data.get("next_id", 0) < 0:
        raise CheckpointError(f"检查点索引的下一个编号无效：{path}")
    return data


def store_subdir(store, name):
    path = store / name
    info = lstat(path)
    if info is not None and not plain_directory(info):
        raise CheckpointError(f"检查点存储目录不是普通目录：{path}")
    return path


def save_index(store, data):
    with tempfile.NamedTemporaryFile(dir=store, delete=False, mode="w", encoding="utf-8") as file:
        pending = Path(file.name)
        try:
            json.dump(data, file, ensure_ascii=True, indent=2)
            file.write("\n")
        except BaseException:
            file.close()
            pending.unlink(missing_ok=True)
            raise
    try:
        os.replace(pending, store / "index.json")
    finally:
        pending.unlink(missing_ok=True)


@contextmanager
def exclusive_file(path):
    try:
        lock = path.open("xb")
    except FileExistsError:
        raise CheckpointError(f"有另一项操作正在进行，锁文件已存在：{path}") from None
    try:
        lock.close()
        yield path
    finally:
        path.unlink(missing_ok=True)


def reserved_ids(root, store, data):
    names = [cp["id"] for cp in data["checkpoints"]]
    for directory in (store, store_subdir(store, "files"), store_subdir(store, "git")):
        if directory.is_dir():
            names.extend(path.stem for path in directory.iterdir())
    state = root / VIBE / "state.md"
    if (info := lstat(state)) is not None and stat.S_ISREG(info.st_mode):
        # 老版在 state.md 先印了 cp-0，手工流程也可能先写上编号。
        names.extend(re.findall(r"(?m)^\s*\|\s*(cp-\d+)\s*\|", state.read_text(encoding="utf-8")))
    return {int(m.group(1)) for name in names if (m := CHECKPOINT_ID.fullmatch(name))}


def pack_staged(root, entries, path):
    ids = sorted({line.split(" ", 2)[1] for lines in entries.values() for line in lines})
    if not ids:
        return None
    with path.open("wb") as file:
        git_checked(root, "pack-objects", "--stdout",
                    input=("\n".join(ids) + "\n").encode("ascii"), stdout=file)
    return digest(path)


def create_snapshot(root, store, data, message, entries, current):
    number = max(data.get("next_id", 0), max(reserved_ids(root, store, data), default=-1) + 1)
    cp_id = f"cp-{number}"
    files_dir = store_subdir(store, "files")
    git_dir = store_subdir(store, "git")
    with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=store) as folder:
        pending = Path(folder)
        payload = pending / "files"
        payload.mkdir()
        manifest = {}
        for rel, info in current.items():
            source = root / rel
            before = path_at(root, rel)
            if not same_file_version(info, before):
                raise CheckpointError(f"建立检查点时文件已变化：{rel}")
            if link_info(info):
                manifest[rel] = describe(source, info)
            elif stat.S_ISREG(info.st_mode):
                target = payload / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target, follow_symlinks=False)
                target_info = lstat(target)
                if target_info is None or not stat.S_ISREG(target_info.st_mode):
                    raise CheckpointError(f"建立检查点时文件类型已变化：{rel}")
                manifest[rel] = describe(target, target_info)
            else:
                raise CheckpointError(f"无法对特殊文件或目录联接建立检查点：{rel}")
            if not same_file_version(before, path_at(root, rel)):
                raise CheckpointError(f"建立检查点时文件已变化：{rel}")
        record = {
            "id": cp_id, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message": message, "mode": "git" if entries is not None else "files",
            "version": 2, "files": sorted(manifest), "file_count": len(manifest),
            "manifest": manifest,
        }
        if entries is not None:
            staged = scoped_index(root, entries)
            record["staged"] = [line for lines in staged.values() for line in lines]
            head = git(root, "rev-parse", "--verify", "HEAD")
            record["commit"] = os.fsdecode(head.stdout).strip() if not head.returncode else ""
            record["pack_sha256"] = pack_staged(root, staged, pending / "staged.pack")
            if live_index(root) != entries:
                raise CheckpointError("建立检查点时 Git 暂存区已变化。")
        if set(project_files(root, entries)) != set(current):
            raise CheckpointError("建立检查点时项目文件列表已变化。")
        files_dir.mkdir(exist_ok=True)
        payload.rename(files_dir / cp_id)
        if record.get("pack_sha256"):
            git_dir.mkdir(exist_ok=True)
            (pending / "staged.pack").rename(git_dir / f"{cp_id}.pack")
        data["checkpoints"].append(record)
        data["next_id"] = number + 1
        save_index(store, data)
    print(f"检查点 {cp_id} 已创建（{record['mode']}，{len(manifest)} 个文件）。")
    return record



def manual_record(store, cp_id):
    directory = store_subdir(store, "files") / cp_id
    info = lstat(directory)
    if not plain_directory(info):
        return None
    return {
        "id": cp_id, "time": datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "message": "手工文件备份（仅恢复现有副本）", "mode": "files",
        "files": [rel for rel, _ in scan_tree(directory, directory) if not excluded(rel)],
    }


def get_checkpoint(store, data, cp_id):
    if not CHECKPOINT_ID.fullmatch(cp_id):
        raise CheckpointError(f"检查点编号无效：{cp_id}")
    for record in data["checkpoints"]:
        if record["id"] == cp_id:
            return record
    record = manual_record(store, cp_id)
    if record is None:
        raise CheckpointError(f"找不到检查点 {cp_id} 的索引或文件副本。")
    return record


def list_checkpoints(store, data):
    records = {cp["id"]: cp for cp in data["checkpoints"]}
    files = store_subdir(store, "files")
    if files.is_dir():
        for child in files.iterdir():
            if CHECKPOINT_ID.fullmatch(child.name) and child.name not in records:
                record = manual_record(store, child.name)
                if record is not None:
                    records[child.name] = record
    if not records:
        print("暂无检查点。用 snap -m 创建第一个。")
    for cp_id in sorted(records, key=lambda key: int(key[3:])):
        cp = records[cp_id]
        print(f"{cp_id}\t{cp.get('time', '')}\t{cp.get('mode', '')}\t{cp.get('message', '')}")


def set_git_index(root, path, existing, desired):
    options = {"env": {"GIT_INDEX_FILE": str(path)}}
    if lstat(path) is None:
        git_checked(root, "read-tree", "--empty", **options)
    changed = [rel for rel in sorted(existing.keys() | desired.keys())
               if existing.get(rel) != desired.get(rel)]
    if not changed:
        return
    oid = next(iter((existing or desired).values()))[0].split(" ", 2)[1]
    zero = "0" * len(oid)
    records = [f"0 {zero}\t{rel}" for rel in changed]
    records += [line for rel in changed for line in desired.get(rel, [])]
    git_checked(root, "update-index", "-z", "--index-info",
                input=os.fsencode("\0".join(records) + "\0"), **options)


def legacy_git_target(root, cp, scratch):
    if cp.get("dirty_count") or cp.get("dirty"):
        raise CheckpointError("旧版 Git 检查点只记录了未提交改动的摘要，无法完整恢复。")
    commit = cp.get("commit")
    if not isinstance(commit, str) or not OBJECT_ID.fullmatch(commit):
        raise CheckpointError("旧版 Git 检查点没有可恢复的提交。")
    raw = git_checked(root, "ls-tree", "-r", "-z", f"{commit}^{{tree}}")
    staged = []
    for line in os.fsdecode(raw).split("\0"):
        if line:
            header, _, rel = line.partition("\t")
            mode, _, oid = header.split()
            staged.append(f"{mode} {oid} 0\t{rel}")
    index_entries = scoped_index(root, parse_index(os.fsencode("\0".join(staged))))
    index_file = scratch / "legacy.index"
    payload = scratch / "legacy"
    payload.mkdir()
    set_git_index(root, index_file, {}, index_entries)
    git_checked(root, "checkout-index", "--all", f"--prefix={payload.as_posix()}/",
                env={"GIT_INDEX_FILE": str(index_file)})
    manifest = {rel: describe(payload / rel, info)
                for rel, info in scan_tree(payload, payload)}
    return payload, manifest, index_entries, None, True


def legacy_file_target(store, cp):
    payload = store_subdir(store, "files") / cp["id"]
    if not plain_directory(lstat(payload)):
        raise CheckpointError(f"快照目录不存在：{payload}")
    if not isinstance(cp.get("files"), list):
        raise CheckpointError("旧版文件检查点没有文件清单。")
    manifest = {}
    for rel in cp["files"]:
        rel = validate_path(rel)
        if excluded(rel):
            continue
        info = path_at(payload, rel)
        if info is None:
            raise CheckpointError(f"快照里没有：{rel}")
        manifest[rel] = describe(payload / rel, info)
    return payload, manifest, None, None, False


def checked_manifest(payload, manifest):
    if not isinstance(manifest, dict):
        raise CheckpointError("检查点文件清单格式无效。")
    for rel, item in manifest.items():
        validate_path(rel)
        if excluded(rel) or not isinstance(item, dict):
            raise CheckpointError(f"检查点含无效或保留路径：{rel}")
        if "link" in item:
            if not isinstance(item["link"], str) or "\x00" in item["link"] or type(item.get("directory")) is not bool:
                raise CheckpointError(f"快照链接记录不完整：{rel}")
        else:
            info = path_at(payload, rel)
            if info is None or not stat.S_ISREG(info.st_mode):
                raise CheckpointError(f"快照里没有普通文件：{rel}")
            if (type(item.get("mode")) is not int or not 0 <= item["mode"] <= 0o7777
                    or digest(payload / rel) != item.get("sha256")):
                raise CheckpointError(f"快照内容校验失败：{rel}")
    return manifest


def load_target(root, store, cp, entries, scratch):
    mode = cp.get("mode")
    if mode not in {"git", "files"}:
        raise CheckpointError("未知的检查点模式。")
    if "version" not in cp and mode == "files":
        return legacy_file_target(store, cp)
    if (mode == "git") != (entries is not None):
        raise CheckpointError("检查点和当前项目的 Git 模式不同，无法确认完整回退的边界。")
    if "version" not in cp:
        return legacy_git_target(root, cp, scratch)
    if cp["version"] != 2:
        raise CheckpointError("未知的检查点版本。")

    payload = store_subdir(store, "files") / cp["id"]
    if not plain_directory(lstat(payload)):
        raise CheckpointError(f"快照目录不存在：{payload}")
    manifest = checked_manifest(payload, cp.get("manifest"))
    staged, pack = None, None
    if mode == "git":
        records = cp.get("staged")
        if not isinstance(records, list) or not all(isinstance(line, str) for line in records):
            raise CheckpointError("检查点没有有效的 Git 暂存区记录。")
        staged = parse_index(os.fsencode("\0".join(records)))
        if staged != scoped_index(root, staged):
            raise CheckpointError("检查点的暂存记录含保留目录或子仓库。")
        if staged:
            pack = store_subdir(store, "git") / f"{cp['id']}.pack"
            info = lstat(pack)
            if info is None or not stat.S_ISREG(info.st_mode) or digest(pack) != cp.get("pack_sha256"):
                raise CheckpointError(f"检查点的暂存对象包缺失或损坏：{pack}")
            fmt = git_checked(root, "rev-parse", "--show-object-format").strip()
            sample = next(iter(staged.values()))[0].split(" ", 2)[1]
            if (fmt, len(sample)) not in {(b"sha1", 40), (b"sha256", 64)}:
                raise CheckpointError("检查点和当前 Git 仓库使用不同的对象格式。")
    return payload, manifest, staged, pack, True


def file_layout(root, current, target, complete):
    norm = os.path.normcase
    aliases = {}
    for rel in target:
        key = norm(rel)
        if key in aliases:
            raise CheckpointError(f"目标文件名冲突：{aliases[key]} 和 {rel}")
        aliases[key] = rel
    for rel in target:
        parent = Path(rel).parent
        while parent != Path("."):
            if norm(parent.as_posix()) in aliases:
                raise CheckpointError(f"同一路径不能同时是普通文件和目录：{parent}")
            parent = parent.parent

    remove = sorted(current.keys() - target.keys()) if complete else []
    removing = {norm(rel) for rel in remove}
    writing = sorted(rel for rel in target if target[rel] != current.get(rel))
    prune = set()
    for rel in writing:
        parts = rel.split("/")
        for n in range(1, len(parts)):
            ancestor = "/".join(parts[:n])
            info = path_at(root, ancestor)
            if info is not None and not plain_directory(info):
                if norm(ancestor) not in removing:
                    raise CheckpointError(f"目标路径的父目录被未纳入回退的文件占用：{ancestor}")
                break
        else:
            info = path_at(root, rel)
            if plain_directory(info):
                directory = root / rel
                dirs = [directory]
                while dirs:
                    child = dirs.pop()
                    prune.add(relative_child(root, child))
                    for member in child.iterdir():
                        member_info = lstat(member)
                        if plain_directory(member_info):
                            dirs.append(member)
                        elif norm(relative_child(root, member)) not in removing:
                            raise CheckpointError(f"目标目录中有未纳入回退的文件：{member}")
            elif info is not None and rel not in current and norm(rel) not in removing:
                raise CheckpointError(f"目标会覆盖未纳入回退的文件：{rel}")

    return remove, sorted(prune, key=lambda path: (-path.count("/"), path)), writing


def show_plan(cp_id, complete, remove, writing, index_changed):
    mode = "完整恢复快照覆盖的范围" if complete else "仅恢复旧版或手工备份中列出的文件"
    print(f"回退目标 {cp_id}（{mode}）。")
    for path in remove:
        print(f"  删除：{path}")
    for path in writing:
        print(f"  恢复：{path}")
    if index_changed:
        print("  恢复 Git 暂存区记录，保留当前 HEAD。")
    print("  保留 docs/vibe/ 的流程文档、备份和历史。")


def ensure_parents(root, rel, created_dirs):
    path = root
    for part in rel.split("/")[:-1]:
        path /= part
        info = lstat(path)
        if info is None:
            path.mkdir()
            created_dirs.append(path)
        elif not plain_directory(info):
            raise CheckpointError(f"无法写入，父目录不再是普通目录：{path}")


@contextmanager
def allow_windows_file_change(path):
    info = lstat(path) if os.name == "nt" else None
    if info is None or not stat.S_ISREG(info.st_mode) or info.st_mode & stat.S_IWRITE:
        yield
        return
    if info.st_nlink > 1:
        raise CheckpointError(f"无法安全清除只读文件的属性，因为它有多个硬链接：{path}")

    mode = stat.S_IMODE(info.st_mode)
    try:
        path.chmod(mode | stat.S_IWRITE)
        yield
    except BaseException:
        # If the operation left the original file in place, restore its attribute.
        current = lstat(path)
        if current is not None and current.st_mode & stat.S_IWRITE and os.path.samestat(info, current):
            path.chmod(mode)
        raise


def install_file(source, target, item):
    with tempfile.TemporaryDirectory(prefix=".vibe-restore-", dir=target.parent) as folder:
        pending = Path(folder) / "pending"
        if "link" in item:
            pending.symlink_to(item["link"], target_is_directory=item["directory"])
        else:
            shutil.copy2(source, pending)
            pending.chmod(item["mode"])
        with allow_windows_file_change(target):
            os.replace(pending, target)


def apply_files(root, store, payload, target, safety, remove, prune, writing, publish_index):
    removed_files = []
    written_files = []
    created_dirs = []
    removed_dirs = []
    try:
        for rel in remove:
            path = root / rel
            with allow_windows_file_change(path):
                path.unlink()
            removed_files.append(rel)
        for rel in prune:
            (root / rel).rmdir()
            removed_dirs.append(root / rel)
        for rel in writing:
            ensure_parents(root, rel, created_dirs)
            install_file(payload / rel, root / rel, target[rel])
            written_files.append(rel)
        publish_index()
    except (OSError, CheckpointError, KeyboardInterrupt) as original:
        saved = store_subdir(store, "files") / safety["id"]
        manifest = safety["manifest"]
        try:
            for rel in reversed(written_files):
                path = root / rel
                with allow_windows_file_change(path):
                    path.unlink(missing_ok=True)
            for directory in reversed(created_dirs):
                directory.rmdir()
            for directory in reversed(removed_dirs):
                directory.mkdir(exist_ok=True)
            for rel in dict.fromkeys(removed_files + written_files):
                if rel in manifest:
                    ensure_parents(root, rel, [])
                    install_file(saved / rel, root / rel, manifest[rel])
        except (OSError, CheckpointError) as rollback_error:
            raise CheckpointError(
                f"恢复失败：{original}。自动撤销也失败：{rollback_error}。"
                f"请使用安全检查点 {safety['id']}。"
            ) from original
        raise CheckpointError(f"恢复中止，已撤销本次文件变更：{original}") from original


@contextmanager
def locking_git_index(path):
    if path is None:
        yield lambda _prepared: None
        return
    lock = path.with_name(path.name + ".lock")
    try:
        lock.touch(exist_ok=False)
    except FileExistsError:
        raise CheckpointError(f"Git 暂存区正在使用：{lock}") from None
    owned = True

    def publish(prepared):
        nonlocal owned
        if prepared is not None:
            shutil.copyfile(prepared, lock)
            os.replace(lock, path)
            owned = False

    try:
        yield publish
    finally:
        if owned:
            lock.unlink(missing_ok=True)


def prepare_staged(root, git_path, current, desired, pack, scratch):
    pending = scratch / "restore.index"
    if pack is not None:
        with pack.open("rb") as stream:
            git_checked(root, "unpack-objects", "-q", stdin=stream)
    if lstat(git_path) is not None:
        shutil.copyfile(git_path, pending)
    set_git_index(root, pending, current, desired)
    return pending



def snapshot_command(root, store, message):
    store.mkdir(parents=True, exist_ok=True)
    with exclusive_file(store / ".checkpoint.lock"):
        entries = live_index(root) if git_index(root) is not None else None
        data = load_index(store)
        create_snapshot(root, store, data, message, entries, project_files(root, entries))


def restore_command(root, store, cp_id, confirmed):
    data = load_index(store)
    cp = get_checkpoint(store, data, cp_id)
    git_path = git_index(root)
    if confirmed and lstat(store) is None:
        raise CheckpointError("项目没有检查点目录。")
    store_lock = exclusive_file(store / ".checkpoint.lock") if confirmed else nullcontext()
    index_lock = locking_git_index(git_path) if confirmed else nullcontext()
    with store_lock, index_lock as publish_staged, tempfile.TemporaryDirectory(prefix="vibe-restore-") as folder:
        if confirmed:
            data = load_index(store)
            cp = get_checkpoint(store, data, cp_id)
        scratch = Path(folder)
        entries = live_index(root) if git_path is not None else None
        payload, target, staged, pack, complete = load_target(root, store, cp, entries, scratch)
        files = project_files(root, entries)
        current = {rel: describe(root / rel, info) for rel, info in files.items()}
        remove, prune, writing = file_layout(root, current, target, complete)
        scoped = scoped_index(root, entries) if entries is not None else None
        index_changed = staged is not None and staged != scoped
        show_plan(cp_id, complete, remove, writing, index_changed)
        if not confirmed:
            print("仅预览。核对后用 --yes 执行。")
            return
        if not (remove or writing or index_changed):
            print("无需回退，项目已与目标检查点一致。")
            return
        pending = prepare_staged(root, git_path, scoped, staged, pack, scratch) if index_changed else None
        safety = create_snapshot(root, store, data, f"回退前安全快照（目标 {cp_id}）", entries, files)
        if safety["manifest"] != current:
            raise CheckpointError("预检后项目内容已变化，已保留安全快照，请重新预览。")
        apply_files(root, store, payload, target, safety, remove, prune, writing,
                    lambda: publish_staged(pending))
        print(f"已恢复 {cp_id}。撤销本次回退请恢复安全检查点 {safety['id']}。")


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=".", help="项目根目录（默认当前目录）")
    commands = parser.add_subparsers(dest="cmd", required=True)
    snap = commands.add_parser("snap", help="创建检查点")
    snap.add_argument("-m", "--message", required=True, help="检查点说明")
    commands.add_parser("list", help="列出检查点")
    show = commands.add_parser("show", help="显示检查点详情")
    show.add_argument("cp_id")
    restore = commands.add_parser("restore", help="预览或恢复检查点")
    restore.add_argument("cp_id")
    restore.add_argument("--dry-run", action="store_true", help="只预览（默认）")
    restore.add_argument("--yes", action="store_true", help="执行已经核对过的回退计划")
    args = parser.parse_args()

    try:
        root = Path(args.project).resolve()
        if not root.is_dir():
            raise CheckpointError(f"项目路径不是目录：{root}")
        store = safe_store(root)
        if args.cmd == "snap":
            snapshot_command(root, store, args.message)
        elif args.cmd == "restore":
            restore_command(root, store, args.cp_id, args.yes and not args.dry_run)
        elif args.cmd == "list":
            list_checkpoints(store, load_index(store))
        else:
            cp = get_checkpoint(store, load_index(store), args.cp_id)
            print(json.dumps(cp, ensure_ascii=False, indent=2))
    except (CheckpointError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
