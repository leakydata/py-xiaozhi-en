# -*- coding: utf-8 -*-
"""Activation: device identity, OTA, the HTTP client and the UI factory."""

from .factory import create_activation_ui
from .service import ActivationService

__all__ = ["ActivationService", "create_activation_ui"]
