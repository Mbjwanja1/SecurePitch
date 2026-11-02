import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends

from app import __version__
from app.security import require_internal_key

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Public liveness check for Docker, the tunnel and the web app."""
    return {"status": "ok", "service": "securepitch-engine", "version": __version__}


def _root_is_read_only() -> bool:
    try:
        tempfile.NamedTemporaryFile(dir=Path(__file__).resolve().parent).close()
    except OSError:
        return True
    return False


def _tmp_is_ram() -> bool:
    mounts = Path("/proc/mounts")
    if not mounts.exists():  # not Linux, e.g. running natively on Windows
        return False
    return any(
        # Reads the mount table only; nothing is written to /tmp.
        line.split()[1:3] == ["/tmp", "tmpfs"]  # noqa: S108
        for line in mounts.read_text().splitlines()
    )


@router.get("/v1/ping", dependencies=[Depends(require_internal_key)])
def ping() -> dict[str, bool]:
    """Authenticated check that also reports the container's storage guarantees."""
    return {
        "pong": True,
        "root_filesystem_read_only": _root_is_read_only(),
        "tmp_is_ram": _tmp_is_ram(),
    }
