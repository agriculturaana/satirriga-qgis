# -*- coding: utf-8 -*-
"""
/***************************************************************************
 SatIrrigaQGISCliente
                                 A QGIS plugin
 Cliente do SatIrriga para carregar as camadas
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                             -------------------
        begin                : 2024-10-28
        copyright            : (C) 2024 by Tharles de Sousa Andrade ANA - INPE
        email                : irtharles@gmail.com
        git sha              : $Format:%H$
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
 This script initializes the plugin, making it known to QGIS.
"""


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load SatIrrigaQGISCliente class from file SatIrrigaQGISCliente.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .satirriga_cliente import SatIrrigaQGISCliente
    return SatIrrigaQGISCliente(iface)
