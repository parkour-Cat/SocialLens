from fastapi import APIRouter

from . import data, internal, items, meta, platforms, resolve, system, tasks

router = APIRouter(prefix="/api/v1")
# Fixed-path routers first: platforms.router has /{platform}/... catch-alls.
router.include_router(system.router)
router.include_router(tasks.router)
router.include_router(internal.router)
router.include_router(items.router)
router.include_router(resolve.router)
router.include_router(meta.router)
router.include_router(data.router)
router.include_router(platforms.router)

__all__ = ["router"]
