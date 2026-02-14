"""Configuracao global de fixtures para pytest."""

import sys
import os

# Adiciona root do plugin ao PYTHONPATH para imports diretos
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
