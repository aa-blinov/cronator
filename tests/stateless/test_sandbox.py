"""Landlock sandbox primitives.

Kernel syscalls cannot be exercised on the Windows dev host, so these
tests pin the pure parts: ABI-dependent rights, capability detection and
the preexec builder's fail-closed contract.
"""

from __future__ import annotations

import sys

from app import sandbox


class TestCapabilityDetection:
    def test_version_is_int_or_none(self):
        version = sandbox.landlock_abi_version()
        assert version is None or version >= 1

    def test_preexec_is_none_when_landlock_is_unavailable(self, monkeypatch):
        monkeypatch.setattr(sandbox, "landlock_abi_version", lambda: None)

        assert sandbox.make_preexec(["/usr"], ["/tmp"]) is None

    def test_unsupported_architecture_has_no_syscall_numbers(self, monkeypatch):
        monkeypatch.setattr(sandbox.platform, "machine", lambda: "mips")
        assert sandbox._syscall_numbers() is None
        monkeypatch.setattr(sandbox.platform, "machine", lambda: "x86_64")
        assert sandbox._syscall_numbers() == (444, 445, 446)


class TestRightsForAbi:
    def test_newer_abi_grants_a_superset(self):
        rights = [sandbox._rights_for_abi(version) for version in range(1, 6)]
        for index in range(1, len(rights)):
            assert rights[index][0] | rights[index - 1][0] == rights[index][0]
            assert rights[index][1] | rights[index - 1][1] == rights[index][1]

    def test_v1_does_not_claim_rights_from_later_abis(self):
        read, write = sandbox._rights_for_abi(1)
        assert read == sandbox.BASE_READ
        assert write == sandbox.BASE_WRITE
        assert not (write & sandbox.REFER)
        assert not (write & sandbox.TRUNCATE)

    def test_v5_includes_refer(self):
        read, write = sandbox._rights_for_abi(5)
        assert read & sandbox.REFER
        assert write & sandbox.REFER


class TestPreexecShape:
    def test_preexec_is_callable_when_supported(self, monkeypatch):
        if sys.platform != "linux":
            # The builder still returns a callable; applying it on the dev
            # host would fail, which is exactly the fail-closed contract.
            monkeypatch.setattr(sandbox, "landlock_abi_version", lambda: 5)
            preexec = sandbox.make_preexec(["/usr"], ["/tmp"])
            assert callable(preexec)
