"""The host reader behind the execution budget (#1715)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_adapters.host_capacity import ProcHostCapacity, parse_cpu_pressure_avg60

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

PSI = "some avg10=0.50 avg60=12.25 avg300=3.00 total=123\nfull avg10=0.00 avg60=7.00 avg300=0.00 total=0\n"


def test_cpu_pressure_is_the_some_line_not_the_full_line() -> None:
    assert parse_cpu_pressure_avg60(PSI) == 12.25


def test_cpu_pressure_without_a_some_line_is_unknown() -> None:
    assert parse_cpu_pressure_avg60("full avg10=0.00 avg60=7.00\n") is None


def test_the_reader_reports_this_host_and_its_pressure(tmp_path: Path) -> None:
    pressure = tmp_path / "cpu"
    pressure.write_text(PSI)

    capacity = ProcHostCapacity(str(tmp_path), pressure_file=pressure).read()

    assert capacity.cpu_cores >= 1
    assert capacity.memory_bytes > 0
    assert capacity.disk_free_bytes > 0
    assert capacity.cpu_pressure_avg60 == 12.25


def test_a_kernel_without_psi_reads_no_pressure(tmp_path: Path) -> None:
    capacity = ProcHostCapacity(str(tmp_path), pressure_file=tmp_path / "absent").read()

    assert capacity.cpu_pressure_avg60 is None


def test_an_unreadable_disk_path_raises_oserror(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        ProcHostCapacity(str(tmp_path / "missing")).read()
