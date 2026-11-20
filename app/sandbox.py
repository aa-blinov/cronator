"""Optional filesystem sandbox for script subprocesses, using Landlock.

Landlock is an unprivileged Linux LSM (kernel 5.13+): a process builds a
ruleset and then irreversibly restricts itself with `landlock_restrict_self`.
Cronator applies it in the child between fork and exec, so the script starts
with only the filesystem rights we grant. No new Python dependency is
needed — the three syscalls are made through ctypes.

Scope is deliberately narrow: this restricts **filesystem** access only.
Network calls, CPU and memory are untouched (Landlock v6 can restrict network
ports, but the built-in templates call HTTP APIs, so enabling that by
default would break the product's common case). See docs/SECURITY.md.

Fail-loud contract: when the sandbox is requested and Landlock is not
usable (Windows, old kernel, seccomp), the script still runs but the
executor logs an ERROR and prefixes this run's stderr with a warning, so
an operator can tell from the execution page that no isolation was
applied. This is an explicit operator trade-off, not a silent downgrade.
"""

from __future__ import annotations

import ctypes
import os
import platform
import struct
import sys
from collections.abc import Callable, Iterable

SYS_CREATE_RULESET = {
    "x86_64": 444,
    "aarch64": 444,
    "arm64": 444,
    "i386": 386,
    "i686": 386,
}
SYS_ADD_RULE = {
    "x86_64": 445,
    "aarch64": 445,
    "arm64": 445,
    "i386": 387,
    "i686": 387,
}
SYS_RESTRICT_SELF = {
    "x86_64": 446,
    "aarch64": 446,
    "arm64": 446,
    "i386": 388,
    "i686": 388,
}

CREATE_RULESET_VERSION = 1

# linux/landlock.h — bit positions are fixed across ABI versions; which
# bits a kernel accepts depends on the ABI. Rights introduced later are
# only requested when the running kernel understands them.
EXECUTE = 1 << 0
WRITE_FILE = 1 << 1
READ_FILE = 1 << 2
READ_DIR = 1 << 3
REMOVE_DIR = 1 << 4
REMOVE_FILE = 1 << 5
MAKE_CHAR = 1 << 6
MAKE_DIR = 1 << 7
MAKE_REG = 1 << 8
MAKE_SOCK = 1 << 9
MAKE_FIFO = 1 << 10
MAKE_BLOCK = 1 << 11
MAKE_SYM = 1 << 12
REFER = 1 << 13  # ABI v5
TRUNCATE = 1 << 14  # ABI v3

# Present since ABI v1. A script needs EXECUTE on the interpreter and its
# own files; the MAKE_* rights are what let Python write artifacts and
# create cache files inside the writable roots.
BASE_READ = EXECUTE | READ_FILE | READ_DIR
BASE_WRITE = (
    WRITE_FILE
    | REMOVE_DIR
    | REMOVE_FILE
    | MAKE_CHAR
    | MAKE_DIR
    | MAKE_REG
    | MAKE_SOCK
    | MAKE_FIFO
    | MAKE_BLOCK
    | MAKE_SYM
)

PR_SET_NO_NEW_PRIVS = 38


class SandboxUnavailable(RuntimeError):
    """Landlock cannot be applied on this host — refuse to run the script."""


def _syscall_numbers() -> tuple[int, int, int] | None:
    arch = platform.machine().lower()
    try:
        return (
            SYS_CREATE_RULESET[arch],
            SYS_ADD_RULE[arch],
            SYS_RESTRICT_SELF[arch],
        )
    except KeyError:
        return None


def _libc() -> ctypes.CDLL:
    libc = ctypes.CDLL(None, use_errno=True)
    # Syscalls return long-sized values (file descriptors); the default
    # c_int restype would truncate any unexpected large return.
    libc.syscall.restype = ctypes.c_long
    return libc


def landlock_abi_version() -> int | None:
    """Highest Landlock ABI the running kernel supports, or None."""
    if sys.platform != "linux":
        return None
    numbers = _syscall_numbers()
    if numbers is None:
        return None
    try:
        libc = _libc()
        version = libc.syscall(numbers[0], None, 0, CREATE_RULESET_VERSION)
        if version < 0:
            return None
        return int(version)
    except (OSError, AttributeError):
        return None


def _rights_for_abi(version: int) -> tuple[int, int]:
    read = BASE_READ | (REFER if version >= 5 else 0)
    write = BASE_WRITE
    if version >= 3:
        write |= TRUNCATE
    if version >= 5:
        write |= REFER
    return read, write


def _errno_message(operation: str) -> str:
    code = ctypes.get_errno()
    return f"{operation} failed: {os.strerror(code)} (errno {code})"


def apply_landlock(read_paths: Iterable[str], write_paths: Iterable[str]) -> None:
    """Restrict the *current* process to the given paths. Call in preexec_fn.

    Missing paths are skipped: a configured directory may not exist on a
    given host, and failing to start every script because of that would be
    worse than granting fewer rights.
    """
    version = landlock_abi_version()
    if version is None or version < 1:
        raise SandboxUnavailable(
            "Landlock is unavailable on this host (needs Linux 5.13+ and "
            "a supported CPU architecture)"
        )

    numbers = _syscall_numbers()
    assert numbers is not None
    create_nr, add_nr, restrict_nr = numbers
    libc = _libc()

    read_rights, write_rights = _rights_for_abi(version)
    # The v1 ruleset attribute is the first field of the newer structs;
    # passing 8 bytes keeps this working across all ABI levels.
    attr = ctypes.c_uint64(read_rights | write_rights)
    ctypes.set_errno(0)
    ruleset_fd = libc.syscall(create_nr, ctypes.byref(attr), 8, 0)
    if ruleset_fd < 0:
        raise SandboxUnavailable(_errno_message("landlock_create_ruleset"))

    try:
        for paths, rights in ((read_paths, read_rights), (write_paths, write_rights)):
            for raw_path in paths:
                path = os.fspath(raw_path)
                if not os.path.isdir(path):
                    continue
                directory_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
                if directory_fd < 0:
                    continue
                try:
                    # struct landlock_path_beneath_attr: u64 allowed_access,
                    # s32 parent_fd, 4 bytes padding.
                    rule = ctypes.create_string_buffer(struct.pack("=qi4x", rights, directory_fd))
                    ctypes.set_errno(0)
                    # syscall signature: (ruleset_fd, rule_type, attr_ptr,
                    # flags). LANDLOCK_RULE_PATH_BENEATH == 1 — omitting
                    # rule_type makes the kernel read the pointer as the
                    # type and return EINVAL.
                    result = libc.syscall(add_nr, ruleset_fd, 1, rule, 0)
                    if result < 0:
                        raise SandboxUnavailable(_errno_message("landlock_add_rule"))
                finally:
                    os.close(directory_fd)

        # restrict_self refuses without no_new_privs unless we hold
        # CAP_SYS_ADMIN — the compact process deliberately has neither.
        ctypes.set_errno(0)
        if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0:
            raise SandboxUnavailable(_errno_message("prctl(NO_NEW_PRIVS)"))
        ctypes.set_errno(0)
        if libc.syscall(restrict_nr, ruleset_fd, 0) < 0:
            raise SandboxUnavailable(_errno_message("landlock_restrict_self"))
    finally:
        os.close(ruleset_fd)


def make_preexec(
    read_paths: Iterable[str], write_paths: Iterable[str]
) -> Callable[[], None] | None:
    """Return a preexec_fn for the child, or None when unsupported."""
    if landlock_abi_version() is None:
        return None

    def _restrict() -> None:
        try:
            apply_landlock(read_paths, write_paths)
        except Exception as exc:
            # preexec runs after fork: raising would surface as a bare
            # SubprocessError in the parent. Say what happened on stderr,
            # then exit with a distinct code so the executor can report it.
            message = f"Landlock setup failed: {exc}\n".encode(errors="replace")
            os.write(2, message)
            os._exit(127)

    return _restrict
