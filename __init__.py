# -*- coding: utf-8 -*-
"""SatIrriga QGIS Plugin — Entry point."""


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """QGIS plugin factory.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    from .plugin import SatIrrigaPlugin
    return SatIrrigaPlugin(iface)
