"""Closing applications, and listing the running ones.

process_manager (built on psutil) does the cross-platform work.
"""

import asyncio
import json
from typing import Any

from src.logging import get_logger

from .process_manager import kill_application_by_name
from .process_manager import list_running_applications as _list_apps

logger = get_logger()


async def kill_application(args: dict[str, Any]) -> bool:
    """Close an application.

    Args:
        args: the arguments
            - app_name: the application name
            - force: kill rather than ask it to quit (optional, False by default)

    Returns:
        whether it closed
    """
    try:
        app_name = args["app_name"]
        force = args.get("force", False)
        logger.info(f"[AppKiller] closing: {app_name}, force: {force}")

        success = await asyncio.to_thread(kill_application_by_name, app_name, force)

        if success:
            logger.info(f"[AppKiller] closed: {app_name}")
        else:
            logger.warning(f"[AppKiller] could not close: {app_name}")

        return success

    except Exception as e:
        logger.error(
            f"[AppKiller] error while closing the application: {e}", exc_info=True
        )
        return False


async def list_running_applications(args: dict[str, Any]) -> str:
    """List every running application.

    Args:
        args: the arguments
            - filter_name: only applications whose name matches (optional)

    Returns:
        the running applications, as JSON
    """
    try:
        filter_name = args.get("filter_name", "")
        logger.info(
            f"[AppKiller] listing the running applications, filter: {filter_name}"
        )

        apps = await asyncio.to_thread(_list_apps, filter_name)

        result = {
            "success": True,
            "total_count": len(apps),
            "applications": apps[:50],
            "message": f"Found {len(apps)} running applications",
        }

        logger.info(
            f"[AppKiller] listing complete, {len(apps)} running applications found"
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        error_msg = f"Could not list the running applications: {e}"
        logger.error(f"[AppKiller] {error_msg}", exc_info=True)
        return json.dumps(
            {
                "success": False,
                "total_count": 0,
                "applications": [],
                "message": error_msg,
            },
            ensure_ascii=False,
        )
