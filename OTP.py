import os
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction
from tool.main import OTPMainWindow

# how many results are written while running batch script
PRINT_EVERY_N_LINES = 100

XML_FILTER = u'XML-Dateien (*.xml)'
CSV_FILTER = u'Comma-seperated values (*.csv)'
JAR_FILTER = u'Java Archive (*.jar)'
ALL_FILE_FILTER = u'Java Executable (java.*)'


class OTP(object):
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface

        # Declare instance attributes
        self.actions = []
        self.menu = 'Grünflächenbewertung OTP'
        self.toolbar = self.iface.addToolBar('Grünflächenbewertung OTP')
        self.toolbar.setObjectName('Grünflächenbewertung OTP')

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/OTP/icon.png'
        icon = QIcon(icon_path)
        self.action = QAction(icon, 'Grünflächenbewertung OTP',
                              self.iface.mainWindow())
        self.action.triggered.connect(lambda: self.run())
        self.toolbar.addAction(self.action)
        self.iface.addPluginToMenu('Grünflächenbewertung', self.action)

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginMenu('OpenTripPlanner', action)
            self.iface.removeToolBarIcon(action)
        # remove the toolbar
        del self.toolbar
        if self.main_window:
            self.main_window.close()

    def run(self):
        '''
        open the plugin UI
        '''
        # initialize and show main window
        if not self.main_window:
            self.main_window = OTPMainWindow()

        self.main_window.show()


