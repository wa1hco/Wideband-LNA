from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pyvisa


class VisaUnavailableError(RuntimeError):
    pass


@dataclass(slots=True)
class VisaResourceSettings:
    resource_name: str
    backend: str | None
    timeout_ms: int
    read_termination: str
    write_termination: str


class VisaTransport:
    def __init__(self, settings: VisaResourceSettings) -> None:
        self._settings = settings
        self._resource_manager: Any = None
        self._resource: Any = None

    def open(self) -> None:
        try:
            import pyvisa
        except ModuleNotFoundError as exc:
            raise VisaUnavailableError("pyvisa is not installed in this environment") from exc

        if self._resource is not None:
            return

        if self._settings.backend:
            self._resource_manager = pyvisa.ResourceManager(self._settings.backend)
        else:
            self._resource_manager = pyvisa.ResourceManager()
        resource = self._resource_manager.open_resource(self._settings.resource_name)
        resource.timeout = self._settings.timeout_ms
        resource.read_termination = self._settings.read_termination
        resource.write_termination = self._settings.write_termination
        self._resource = resource

    def close(self) -> None:
        if self._resource is not None:
            try:
                self._resource.close()
            finally:
                self._resource = None
        if self._resource_manager is not None:
            try:
                self._resource_manager.close()
            finally:
                self._resource_manager = None

    def __enter__(self) -> "VisaTransport":
        self.open()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def list_resources(self) -> tuple[str, ...]:
        self.open()
        assert self._resource_manager is not None
        return tuple(self._resource_manager.list_resources())

    def query(self, command: str) -> str:
        def _op() -> str:
            self.open()
            assert self._resource is not None
            return str(self._resource.query(command)).strip()

        return self._with_abort_retry(_op)

    def write(self, command: str) -> None:
        def _op() -> None:
            self.open()
            assert self._resource is not None
            self._resource.write(command)

        self._with_abort_retry(_op)

    def read_raw(self) -> bytes:
        def _op() -> bytes:
            self.open()
            assert self._resource is not None
            return bytes(self._resource.read_raw())

        return self._with_abort_retry(_op)

    def _with_abort_retry(self, operation):
        try:
            return operation()
        except Exception as exc:
            # Recover once from transient bus-abort state caused by interrupted transfers.
            error_code = getattr(exc, "error_code", None)
            if error_code != -1073807312:
                raise
            self.close()
            return operation()

    def release_to_local(self) -> None:
        """Return front-panel control to the instrument user if supported by backend/resource."""
        self.open()
        assert self._resource is not None
        try:
            import pyvisa

            self._resource.control_ren(pyvisa.constants.VI_GPIB_REN_DEASSERT_GTL)
        except Exception:
            # Some backends/resources do not support REN control; ignore and continue.
            return


import math


class MockTransport:
    """Synthetic GPIB transport for offline development and report testing.

    Returns plausible NF and gain curves for a wideband LNA without
    any real instrument connected.
    """

    def __init__(self, start_hz: float = 1e9, stop_hz: float = 2e9, points: int = 201) -> None:
        self._start_hz = start_hz
        self._stop_hz = stop_hz
        self._points = points

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self) -> "MockTransport":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        pass

    def list_resources(self) -> tuple[str, ...]:
        return ("MOCK::0::INSTR",)

    def query(self, command: str) -> str:
        command = command.strip().upper()
        if "*IDN?" in command:
            return "MOCK INSTRUMENTS,N8973A-SIM,000000,A.07.00"
        if "NFIG" in command:
            return self._mock_nf_csv()
        if "GAIN" in command:
            return self._mock_gain_csv()
        if "*OPC?" in command:
            return "1"
        if "INIT:CONT?" in command:
            return "1"
        return "0"

    def write(self, command: str) -> None:
        pass  # Swallow all writes silently

    def read_raw(self) -> bytes:
        return b""

    def release_to_local(self) -> None:
        pass

    def _freqs(self) -> list[float]:
        step = (self._stop_hz - self._start_hz) / (self._points - 1)
        return [self._start_hz + step * i for i in range(self._points)]

    def _mock_nf_csv(self) -> str:
        """Return a realistic NF curve: ~0.8 dB at low end, rising to ~1.5 dB at high end."""
        freqs = self._freqs()
        span = self._stop_hz - self._start_hz or 1.0
        values = [
            0.8 + 0.7 * ((f - self._start_hz) / span) + 0.05 * math.sin(6 * math.pi * (f - self._start_hz) / span)
            for f in freqs
        ]
        return ",".join(f"{v:.4f}" for v in values)

    def _mock_gain_csv(self) -> str:
        """Return a realistic gain curve: ~22 dB flat with slight rolloff at edges."""
        freqs = self._freqs()
        span = self._stop_hz - self._start_hz or 1.0
        values = [
            22.0 - 1.5 * ((f - self._start_hz) / span) ** 2 + 0.2 * math.sin(4 * math.pi * (f - self._start_hz) / span)
            for f in freqs
        ]
        return ",".join(f"{v:.4f}" for v in values)

