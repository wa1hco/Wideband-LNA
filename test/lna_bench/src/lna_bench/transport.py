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
