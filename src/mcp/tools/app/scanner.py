"""The single entry point for scanning applications.

Picks the right scanner for whichever platform this is
"""

import asyncio
import json
from typing import Any, Dict

from src.logging import get_logger

from .utils import get_system_scanner

logger = get_logger()


async def scan_installed_applications(args: Dict[str, Any]) -> str:
    """Scan every application installed on this system.

    Args:
        args: the scan arguments
            - force_refresh: rescan even if there is a cache (optional, False by default)

    Returns:
        str: the applications, as JSON
    """
    try:
        force_refresh = args.get("force_refresh", False)
        logger.info(
            f"[AppScanner] scanning the installed applications, force_refresh: {force_refresh}"
        )

        # get the scanner for this platform
        scanner = get_system_scanner()
        if not scanner:
            error_msg = "This operating system is not supported"
            logger.error(f"[AppScanner] {error_msg}")
            return json.dumps(
                {
                    "success": False,
                    "total_count": 0,
                    "applications": [],
                    "message": error_msg,
                },
                ensure_ascii=False,
            )

        # run the scan on a thread pool, so the event loop is not blocked
        apps = await asyncio.to_thread(scanner.scan_installed_applications)

        result = {
            "success": True,
            "total_count": len(apps),
            "applications": apps,
            "message": f"Found {len(apps)} installed applications",
        }

        logger.info(f"[AppScanner] scan complete, {len(apps)} applications found")
        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        error_msg = f"Could not scan the applications: {str(e)}"
        logger.error(f"[AppScanner] {error_msg}", exc_info=True)
        return json.dumps(
            {
                "success": False,
                "total_count": 0,
                "applications": [],
                "message": error_msg,
            },
            ensure_ascii=False,
        )


async def list_running_applications(args: Dict[str, Any]) -> str:
    """List the applications currently running.

    Args:
        args: the filter arguments
            - filter_name: only applications whose name matches (optional)

    Returns:
        str: the running applications, as JSON
    """
    try:
        filter_name = args.get("filter_name", "")
        logger.info(
            f"[AppScanner] listing the running applications, filter: {filter_name}"
        )

        # get the scanner for this platform
        scanner = get_system_scanner()
        if not scanner:
            error_msg = "This operating system is not supported"
            logger.error(f"[AppScanner] {error_msg}")
            return json.dumps(
                {
                    "success": False,
                    "total_count": 0,
                    "applications": [],
                    "message": error_msg,
                },
                ensure_ascii=False,
            )

        # run the scan on a thread pool, so the event loop is not blocked
        apps = await asyncio.to_thread(scanner.scan_running_applications)

        # apply the filter
        if filter_name:
            filter_lower = filter_name.lower()
            filtered_apps = []
            for app in apps:
                if (
                    filter_lower in app.get("name", "").lower()
                    or filter_lower in app.get("display_name", "").lower()
                    or filter_lower in app.get("command", "").lower()
                ):
                    filtered_apps.append(app)
            apps = filtered_apps

        result = {
            "success": True,
            "total_count": len(apps),
            "applications": apps,
            "message": f"Found {len(apps)} running applications",
        }

        logger.info(
            f"[AppScanner] listing complete, {len(apps)} running applications found"
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        error_msg = f"Could not list the running applications: {str(e)}"
        logger.error(f"[AppScanner] {error_msg}", exc_info=True)
        return json.dumps(
            {
                "success": False,
                "total_count": 0,
                "applications": [],
                "message": error_msg,
            },
            ensure_ascii=False,
        )
