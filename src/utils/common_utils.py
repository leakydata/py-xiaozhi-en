"""
Assorted shared helpers.

Opening a browser, the clipboard, pulling a verification code out of text, and so on.
"""

import re
import webbrowser
from typing import Optional

from src.logging import get_logger

logger = get_logger()


def open_url(url: str) -> bool:
    """Open a web page."""
    try:
        success = webbrowser.open(url)
        if success:
            logger.info(f"opened the page: {url}")
        else:
            logger.warning(f"could not open the page: {url}")
        return success
    except Exception as e:
        logger.error(f"error while opening the page: {e}", exc_info=True)
        return False


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the clipboard."""
    try:
        import pyperclip

        pyperclip.copy(text)
        logger.info(f'copied "{text}" to the clipboard')
        return True
    except ImportError:
        logger.warning("pyperclip is not installed, cannot copy to the clipboard")
        return False
    except Exception as e:
        logger.error(f"error while copying to the clipboard: {e}", exc_info=True)
        return False


def extract_verification_code(text: str) -> Optional[str]:
    """Pull a verification code out of some text."""
    try:
        # The activation keywords. These stay in Chinese deliberately: they are
        # matched against what the tenclass server speaks aloud during activation,
        # which is Chinese whatever language this client runs in. Same goes for
        # the patterns below.
        activation_keywords = [
            "登录",
            "控制面板",
            "激活",
            "验证码",
            "绑定设备",
            "添加设备",
            "输入验证码",
            "输入",
            "面板",
            "xiaozhi.me",
            "激活码",
        ]

        # does the text mention activation at all?
        has_activation_keyword = any(keyword in text for keyword in activation_keywords)

        if not has_activation_keyword:
            logger.debug(
                f"no activation keyword in the text, not looking for a code: {text}"
            )
            return None

        # the more precise code patterns
        patterns = [
            r"验证码[：:]\s*(\d{6})",
            r"输入验证码[：:]\s*(\d{6})",
            r"输入\s*(\d{6})",
            r"验证码\s*(\d{6})",
            r"激活码[：:]\s*(\d{6})",
            r"(\d{6})[，,。.]",
            r"[，,。.]\s*(\d{6})",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                code = match.group(1)
                logger.info(f"verification code found: {code}")
                return code

        # the catch-all pattern
        match = re.search(r"((?:\d\s*){6,})", text)
        if match:
            code = "".join(match.group(1).split())
            if len(code) == 6 and code.isdigit():
                logger.info(f"verification code found (catch-all pattern): {code}")
                return code

        logger.warning(f"no verification code in the text: {text}")
        return None
    except Exception as e:
        logger.error(
            f"error while extracting the verification code: {e}", exc_info=True
        )
        return None


def handle_verification_code(text: str) -> None:
    """Handle a verification code: extract it and copy it to the clipboard."""
    code = extract_verification_code(text)
    if code:
        copy_to_clipboard(code)
