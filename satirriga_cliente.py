# -*- coding: utf-8 -*-
"""
/***************************************************************************
 SatIrrigaQGISCliente
                                 A QGIS plugin
 Cliente do SatIrriga para carregar as camadas
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2024-10-28
        git sha              : $Format:%H$
        author               : Tharles de Sousa Andrade ANA - INPE
        email                : irtharles@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
import json
import os
import requests
import tempfile
import zipfile
from PyQt5.QtCore import QTimer
from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, Qt, pyqtSignal
from qgis.PyQt.QtGui import QIcon, QPixmap
from qgis.PyQt.QtWidgets import QAction, QLabel, QTextEdit, QLineEdit, QPushButton, QVBoxLayout, QWidget, QDockWidget, QHBoxLayout, QProgressBar
from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer

# Import the code for the DockWidget
from .resources import *


class SatIrrigaQGISClienteDockWidget(QDockWidget):
    # Define o sinal customizado para fechamento
    closed = pyqtSignal()

    def __init__(self, iface, parent=None):
        """Constructor."""
        super().__init__(parent)
        self.iface = iface
        # Configuração de layout principal
        self.main_layout = QVBoxLayout()
        
        # Adiciona título e logotipo
        header_layout = QHBoxLayout()
        logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
        logo_label = QLabel(self)
        logo_pixmap = QPixmap(logo_path)
        logo_label.setPixmap(logo_pixmap)
        header_layout.addWidget(logo_label)

        title_label = QLabel("SATIRRIGA CLIENTE", self)
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; text-align: center;")
        header_layout.addWidget(title_label)

        self.main_layout.addLayout(header_layout)
        
        # Campo de texto para o nome do grupo de camadas
        self.group_name_input = QLineEdit(self)
        self.group_name_input.setPlaceholderText("Digite o nome do grupo de camadas")
        self.main_layout.addWidget(self.group_name_input)

        # Área de texto para JSON do usuário
        self.text_area = QTextEdit(self)
        self.text_area.setPlaceholderText("Insira o array JSON de camadas XYZ aqui...")
        self.main_layout.addWidget(self.text_area)
        
        # Botão para adicionar camadas
        self.add_layers_button = QPushButton("Adicionar Camadas", self)
        self.add_layers_button.clicked.connect(self.add_layers_from_json)
        self.main_layout.addWidget(self.add_layers_button)
        
        # Configuração do widget principal
        container = QWidget()
        container.setLayout(self.main_layout)
        self.setWidget(container)

    def closeEvent(self, event):
        """Emite o sinal de fechamento ao fechar o dock widget."""
        self.closed.emit()
        event.accept()
    
    def add_layers_from_json(self):
        """Adiciona camadas ao mapa com base no JSON fornecido na área de texto."""
        try:
            # Obtém o nome do grupo e o JSON do usuário
            group_name = self.group_name_input.text().strip()
            layers_data = json.loads(self.text_area.toPlainText())
            
            # Verifica se o nome do grupo foi fornecido
            if not group_name:
                print("Erro: O nome do grupo de camadas está vazio.")
                return
            
            # Cria um grupo para as camadas XYZ
            group_layer = QgsProject.instance().layerTreeRoot().addGroup(group_name)
            
            # Itera sobre as camadas e as adiciona ao grupo
            for layer_info in layers_data:
                name = layer_info.get("name")
                url = layer_info.get("url")
                token = layer_info.get("token")
                download_shp_url = layer_info.get("downloadSHPURL")
                
                # Cria camada XYZ
                xyz_layer = QgsRasterLayer(f"type=xyz&url={url}", name, "wms")
                
                # Verifica se a camada foi criada com sucesso
                if xyz_layer.isValid():
                    QgsProject.instance().addMapLayer(xyz_layer, False)
                    group_layer.addLayer(xyz_layer)
                else:
                    print(f"Falha ao carregar camada: {name}")

                # Se houver um downloadSHPURL, faz o download do SHP
                if download_shp_url:
                    print(f"Iniciando download do SHP para {name}...")
                    self.download_shp(download_shp_url, token, name)

            # Limpa os campos após adicionar as camadas
            self.group_name_input.clear()
            self.text_area.clear()
        except json.JSONDecodeError:
            print("Erro: JSON inválido. Verifique o formato do array.")

    def download_shp(self, url, token, layer_name):
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(url, headers=headers, stream=True)

        # Progress bar to track the download
        progress_bar = QProgressBar()
        progress_bar.setMinimum(0)
        progress_bar.setMaximum(0)  # Set to indeterminate initially
        self.main_layout.addWidget(progress_bar)

        def remove_progress_bar():
            """Helper function to remove the progress bar with a slight delay."""
            progress_bar.setValue(100)
            QTimer.singleShot(100, progress_bar.deleteLater)  # 100ms delay to ensure cleanup

        if response.status_code == 200:
            # Check Content-Type to verify if it’s a ZIP
            content_type = response.headers.get("Content-Type", "")
            if "zip" not in content_type:
                print("Error: Expected a ZIP file but received a different content type.")
                print("Response Content:", response.text)  # Log the response content for debugging
                remove_progress_bar()
                return

            # Using tempfile for secure temporary file management
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as zip_file:
                temp_zip_filename = zip_file.name

                # Write data to the temporary ZIP file in chunks
                total_length = response.headers.get('content-length')
                if total_length is None:
                    print("Warning: Content-Length missing, progress may be inaccurate.")
                    for data in response.iter_content(chunk_size=4096):
                        zip_file.write(data)
                    progress_bar.setMaximum(100)  # Set to determinate when done
                else:
                    downloaded = 0
                    total_length = int(total_length)
                    progress_bar.setMaximum(100)  # Set determinate mode
                    for data in response.iter_content(chunk_size=4096):
                        zip_file.write(data)
                        downloaded += len(data)
                        progress_value = int(downloaded * 100 / total_length)
                        progress_bar.setValue(progress_value)

            # Load the ZIP file directly as a vector layer in QGIS
            try:
                zip_layer_path = f"/vsizip/{temp_zip_filename}"
                shp_layer = QgsVectorLayer(zip_layer_path, layer_name, "ogr")

                if shp_layer.isValid():
                    # Add the vector layer to a group
                    vector_group = QgsProject.instance().layerTreeRoot().findGroup("VETORES DA CLASSIFICACAO")
                    if not vector_group:
                        vector_group = QgsProject.instance().layerTreeRoot().addGroup("VETORES DA CLASSIFICACAO")
                    QgsProject.instance().addMapLayer(shp_layer, False)
                    vector_group.addLayer(shp_layer)

                    # Set CRS if not defined
                    if not shp_layer.crs().isValid():
                        shp_layer.setCrs(QgsProject.instance().crs())
                        print("Layer CRS was undefined; set to project CRS.")

                    # Zoom to the extent of the vector layer
                    extent = shp_layer.extent()
                    self.iface.mapCanvas().setExtent(extent)
                    self.iface.mapCanvas().refresh()
                    print("Shapefile loaded successfully.")
                else:
                    print("Error: SHP layer is invalid or could not be loaded from ZIP.")
            except Exception as e:
                print(f"An error occurred while loading the SHP from ZIP: {e}")
        else:
            print("Failed to download SHP file: HTTP status code", response.status_code)

        # Ensure progress bar is removed after download completes
        remove_progress_bar()

class SatIrrigaQGISCliente:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at runtime.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface

        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)

        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'SatIrrigaQGISCliente_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&SatIrriga QGIS Cliente')
        self.toolbar = self.iface.addToolBar(u'SatIrrigaQGISCliente')
        self.toolbar.setObjectName(u'SatIrrigaQGISCliente')

        self.pluginIsActive = False
        self.dockwidget = None


    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        return QCoreApplication.translate('SatIrrigaQGISCliente', message)


    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar."""
        
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action


    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/satirriga_cliente/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'Satirriga Camadas'),
            callback=self.run,
            parent=self.iface.mainWindow())

    def onClosePlugin(self):
        """Cleanup necessary items here when plugin dockwidget is closed"""
        self.pluginIsActive = False

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""

        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr(u'&SatIrriga QGIS Cliente'),
                action)
            self.iface.removeToolBarIcon(action)
        del self.toolbar

    def run(self):
        """Run method that loads and starts the plugin"""
        if not self.pluginIsActive:
            self.pluginIsActive = True

            if self.dockwidget is None:
                # Pass iface to SatIrrigaQGISClienteDockWidget
                self.dockwidget = SatIrrigaQGISClienteDockWidget(self.iface)
                self.dockwidget.closed.connect(self.onClosePlugin)

            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dockwidget)
            self.dockwidget.show()