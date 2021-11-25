import os
import math
from PyQt5 import uic,  QtCore, QtWidgets
from qgis import utils
from qgis._core import QgsCoordinateReferenceSystem
from qgis.core import (QgsVectorFileWriter, QgsProject, QgsMapLayerProxyModel,
                       QgsSymbol, QgsSimpleFillSymbolLayer, QgsRendererRange,
                       QgsRendererCategory, QgsCategorizedSymbolRenderer,
                       QgsGraduatedSymbolRenderer)

from gruenflaechenotp.base.project import (ProjectManager, settings,
                                           ProjectLayer, OSMBackgroundLayer)
from gruenflaechenotp.tool.dialogs import (ExecOTPDialog, RouterDialog, InfoDialog,
                                           SettingsDialog, NewProjectDialog,
                                           ImportLayerDialog)
from gruenflaechenotp.base.database import Workspace
from gruenflaechenotp.tool.tables import (
    ProjectSettings, Projektgebiet, Adressen, Baubloecke, Gruenflaechen,
    GruenflaechenEingaenge, AdressenProcessed, GruenflaechenEingaengeProcessed,
    BaublockErgebnisse
)
from gruenflaechenotp.base.dialogs import ProgressDialog
from gruenflaechenotp.tool.jobs import (CloneProject, ImportLayer, ResetLayers,
                                        AnalyseRouting, PrepareRouting)
from gruenflaechenotp.batch.config import Config as OTPConfig

import tempfile
import webbrowser

TITLE = "Grünflächenbewertung"

# how many results are written while running batch script
PRINT_EVERY_N_LINES = 100
main_form = os.path.join(settings.UI_PATH, 'OTP_main_window.ui')


class OTPMainWindow(QtCore.QObject):
    def __init__(self, on_close=None, parent=None):
        """Constructor."""
        super().__init__(parent)

        self.ui = QtWidgets.QMainWindow()
        uic.loadUi(main_form, self.ui)
        self.project_manager = ProjectManager()
        self.project_settings = None
        graph_path = self.project_manager.settings.graph_path
        self.canvas = utils.iface.mapCanvas()
        #project = QgsProject.instance()
        #crs = QgsCoordinateReferenceSystem(f'epsg:{settings.EPSG}')
        #project.setCrs(crs)
        #self.canvas.mapSettings().setDestinationCrs(crs)
        if graph_path and not os.path.exists(graph_path):
            try:
                os.makedirs(graph_path)
            except:
                pass
        self.on_close = on_close
        self.ui.setWindowTitle(TITLE)
        self.setupUi()

    def closeEvent(self, evnt):
        if self.on_close:
            self.on_close()

    def setupUi(self):
        '''
        prefill UI-elements and connect slots and signals
        '''
        self.ui.create_project_button.clicked.connect(self.create_project)
        self.ui.remove_project_button.clicked.connect(self.remove_project)
        self.ui.clone_project_button.clicked.connect(self.clone_project)

        self.ui.project_combo.currentIndexChanged.connect(
            lambda index: self.change_project(
                self.ui.project_combo.itemData(index)))

        # connect menu actions
        self.ui.info_action.triggered.connect(self.show_info)

        # connect menu actions
        self.ui.settings_action.triggered.connect(self.show_settings)

        def save_project_setting(attr, value):
            self.project_settings[attr] = value
            self.project_settings.save()

        self.ui.required_green_edit.valueChanged.connect(
            lambda x: save_project_setting('required_green', x))
        self.ui.required_green_edit.valueChanged.connect(
            self.set_result_categories)
        self.ui.max_walk_dist_edit.valueChanged.connect(
            lambda x: save_project_setting('max_walk_dist', x))
        self.ui.project_buffer_edit.valueChanged.connect(
            lambda x: save_project_setting('project_buffer', x))

        self.ui.router_combo.currentTextChanged.connect(
            lambda x: save_project_setting('router', x))
        self.ui.walk_speed_edit.valueChanged.connect(
            lambda x: save_project_setting('walk_speed', x))
        self.ui.wheelchair_check.stateChanged.connect(
            lambda: save_project_setting('wheelchair',
                                         self.ui.wheelchair_check.isChecked()))
        self.ui.max_slope_edit.valueChanged.connect(
            lambda x: save_project_setting('max_slope', x))

        self.ui.create_router_button.clicked.connect(self.create_router)

        self.ui.import_project_area_button.clicked.connect(
            self.import_project_area)
        self.ui.import_green_spaces_button.clicked.connect(
            self.import_green_spaces)
        self.ui.import_green_entrances_button.clicked.connect(
            self.import_green_entrances)
        self.ui.import_blocks_button.clicked.connect(self.import_blocks)
        self.ui.import_addresses_button.clicked.connect(self.import_addresses)

        self.ui.reset_project_area_button.clicked.connect(
            lambda: self.reset_layer(Projektgebiet))
        self.ui.reset_green_spaces_button.clicked.connect(
            lambda: self.reset_layer(Gruenflaechen))
        self.ui.reset_green_entrances_button.clicked.connect(
            lambda: self.reset_layer(GruenflaechenEingaenge))
        self.ui.reset_blocks_button.clicked.connect(
            lambda: self.reset_layer(Baubloecke))
        self.ui.reset_addresses_button.clicked.connect(
            lambda: self.reset_layer(Adressen))

        self.ui.start_calculation_button.clicked.connect(self.calculate)
        # router
        self.setup_projects()

    def setup_projects(self):
        '''
        fill project combobox with available projects
        '''
        self.ui.tabWidget.setEnabled(False)
        self.ui.start_calculation_button.setEnabled(False)

        self.project_manager.active_project = None

        self.ui.project_combo.blockSignals(True)
        self.ui.project_combo.clear()
        self.ui.project_combo.addItem('Projekt wählen')
        self.ui.project_combo.model().item(0).setEnabled(False)
        self.project_manager.reset_projects()
        for project in self.project_manager.projects:
            if project.name == '__test__':
                continue
            self.ui.project_combo.addItem(project.name, project)
        self.ui.project_combo.blockSignals(False)

    def create_project(self):
        '''
        Open a dialog for setting up a new project and create the project
        based on this setup. Automatically set the new project as active project
        if successfully created
        '''
        dialog = NewProjectDialog()
        ok, project_name = dialog.show()

        if ok:
            project = self.project_manager.create_project(project_name)
            project_settings = ProjectSettings.features(project=project,
                                                        create=True)
            project_settings.add()
            self.project_manager.active_project = project
            self.ui.project_combo.addItem(project.name, project)
            self.ui.project_combo.setCurrentIndex(
                self.ui.project_combo.count() - 1)

            job = ResetLayers(tables=[
                Projektgebiet.get_table(create=True),
                Baubloecke.get_table(create=True),
                Gruenflaechen.get_table(create=True),
                Adressen.get_table(create=True),
                GruenflaechenEingaenge.get_table(create=True)
            ])
            dialog = ProgressDialog(job, parent=self.ui)
            dialog.show()

    def import_project_area(self):
        table = Projektgebiet.get_table()
        dialog = ImportLayerDialog(
            title='Projektgebiet importieren',
            filter_class=QgsMapLayerProxyModel.PolygonLayer)
        ok, layer, crs, fields = dialog.show()
        if ok:
            job = ImportLayer(table, layer, crs, fields=fields, parent=self.ui)
            dialog = ProgressDialog(
                job, parent=self.ui,
                on_success=lambda x: self.project_area_output.draw(redraw=False))
            dialog.show()

    def import_green_spaces(self):
        table = Gruenflaechen.get_table()
        dialog = ImportLayerDialog(
            title='Grünflächen importieren',
            filter_class=QgsMapLayerProxyModel.PolygonLayer)
        ok, layer, crs, fields = dialog.show()
        if ok:
            job = ImportLayer(table, layer, crs, fields=fields, parent=self.ui)
            dialog = ProgressDialog(
                job, parent=self.ui,
                on_success=lambda x: self.green_output.draw(redraw=False))
            dialog.show()

    def import_blocks(self):
        table = Baubloecke.get_table()
        dialog = ImportLayerDialog(
            title='Baublöcke importieren',
            required_fields=[('einwohner', 'Anzahl Einwohner')],
            filter_class=QgsMapLayerProxyModel.PolygonLayer)
        ok, layer, crs, fields = dialog.show()
        if ok:
            job = ImportLayer(table, layer, crs, fields=fields, parent=self.ui)
            dialog = ProgressDialog(
                job, parent=self.ui,
                on_success=lambda x: self.blocks_output.draw(redraw=False))
            dialog.show()

    def import_addresses(self):
        table = Adressen.get_table()
        dialog = ImportLayerDialog(
            title='Adressen importieren',
            optional_fields=[
                ('strasse', 'Straße'), ('hausnummer', 'Hausnummer'),
                ('ort', 'Ort'), ('beschreibung', 'Beschreibung')],
            help_text='Die Angabe der Felder ist optional und dient nur der '
            'besseren manuellen Zuordenbarkeit. Die Felder haben weder '
            'Einfluss auf die Ergebnisse noch auf die Ergebnisdarstellung.',
            filter_class=QgsMapLayerProxyModel.PointLayer)
        ok, layer, crs, fields = dialog.show()
        if ok:
            job = ImportLayer(table, layer, crs, fields=fields, parent=self.ui)
            dialog = ProgressDialog(
                job, parent=self.ui,
                on_success=lambda x: self.addr_output.draw(redraw=False))
            dialog.show()

    def import_green_entrances(self):
        table = GruenflaechenEingaenge.get_table()
        dialog = ImportLayerDialog(
            title='Grünflächeneingänge importieren',
            filter_class=QgsMapLayerProxyModel.PointLayer)
        ok, layer, crs, fields = dialog.show()
        if ok:
            job = ImportLayer(table, layer, crs, fields=fields, parent=self.ui)
            dialog = ProgressDialog(
                job, parent=self.ui,
                on_success=lambda x: self.green_entrances_output.draw(redraw=False))
            dialog.show()

    def reset_layer(self, table_class):
        job = ResetLayers(tables=[table_class.get_table()])
        dialog = ProgressDialog(
            job, parent=self.ui,
            on_success=lambda x: self.canvas.refreshAllLayers())
        dialog.show()

    def clone_project(self):
        '''
        clone the currently selected project
        '''
        project = self.project_manager.active_project
        if not project:
            return
        dialog = NewProjectDialog(placeholder=f'{project.name}_kopie')
        ok, project_name = dialog.show()

        if ok:
            job = CloneProject(project_name, project, parent=self.ui)
            def on_success(project):
                self.ui.project_combo.addItem(project.name, project)
                self.ui.project_combo.setCurrentIndex(
                    self.ui.project_combo.count() - 1)
                self.project_manager.active_project = project
            dialog = ProgressDialog(job, parent=self.ui,
                                    on_success=on_success)
            dialog.show()

    def remove_project(self):
        '''
        remove the currently selected project
        '''
        project = self.project_manager.active_project
        if not project:
            return
        reply = QtWidgets.QMessageBox.question(
            self.ui, 'Projekt entfernen',
            f'Soll das Projekt "{project.name}" entfernt werden?\n'
            '(alle Projektdaten werden gelöscht)',
             QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No)
        if reply == QtWidgets.QMessageBox.Yes:
            idx = self.ui.project_combo.currentIndex()
            self.ui.project_combo.setCurrentIndex(0)
            self.ui.project_combo.removeItem(idx)
            instances = list(Workspace.get_instances())
            for ws in instances:
                # close all writable workspaces (read_only indicate the
                # base data)
                # ToDo: adress project workspaces somehow else
                if not ws.database.read_only:
                    ws.close()
            # close and remove layers in project group (in TOC)
            qgisproject = QgsProject.instance()
            root = qgisproject.layerTreeRoot()
            project_group = root.findGroup(project.groupname)
            if project_group:
                for layer in project_group.findLayers():
                    qgisproject.removeMapLayer(layer.layerId())
                project_group.removeAllChildren()
                root.removeChildNode(project_group)
            # wait for canvas to refresh because it blocks the datasources for
            # the layers as long they are visible
            def on_refresh():
                try:
                    self.project_manager.remove_project(project)
                except:
                    # ToDo: catch properly
                    pass
                self.project_manager.active_project = None
                self.canvas.mapCanvasRefreshed.disconnect(on_refresh)
            self.canvas.mapCanvasRefreshed.connect(on_refresh)
            self.canvas.refreshAllLayers()

    def change_project(self, project):
        if not project:
            self.ui.tabWidget.setEnabled(False)
            self.ui.start_calculation_button.setEnabled(False)
            return
        try:
            self.project_settings = ProjectSettings.features(project=project)[0]
        except FileNotFoundError:
            return
        self.ui.start_calculation_button.setEnabled(True)
        self.project_manager.active_project = project
        # ToDo: load layers and settings
        try:
            self.apply_project_settings(project)
        except FileNotFoundError:
            return
        self.ui.tabWidget.setEnabled(True)

        # check active project, uncheck other projects
        layer_root = QgsProject.instance().layerTreeRoot()
        for p in self.project_manager.projects:
            group = layer_root.findGroup(p.groupname)
            if group:
                group.setItemVisibilityChecked(
                    p.groupname==project.groupname)

        self.add_input_layers()
        self.add_result_layers()

        backgroundOSM = OSMBackgroundLayer(groupname='Hintergrundkarten')
        backgroundOSM.draw()

    def add_input_layers(self):
        groupname = 'Eingangsdaten'

        addresses = Adressen.get_table(create=True)
        self.addr_output = ProjectLayer.from_table(
            addresses, groupname=groupname)
        self.addr_output.draw(
            label='Adressen',
            style_file='adressen.qml',
            redraw=False)

        green_entrances = GruenflaechenEingaenge.get_table(create=True)
        self.green_entrances_output = ProjectLayer.from_table(
            green_entrances, groupname=groupname)
        self.green_entrances_output.draw(
            label='Grünflächen Eingänge',
            style_file='gruen_eingaenge.qml',
            redraw=False)

        green = Gruenflaechen.get_table(create=True)
        self.green_output = ProjectLayer.from_table(
            green, groupname=groupname)
        self.green_output.draw(
            label='Grünflächen',
            style_file='gruenflaechen.qml',
            redraw=False)

        blocks = Baubloecke.get_table(create=True)
        self.blocks_output = ProjectLayer.from_table(
            blocks, groupname=groupname)
        self.blocks_output.draw(label='Baublöcke',
            style_file='bloecke.qml',
            redraw=False)

        project_area = Projektgebiet.get_table(create=True)
        self.project_area_output = ProjectLayer.from_table(
            project_area, groupname=groupname)
        self.project_area_output.draw(label='Projektgebiet',
            style_file='projektgebiet.qml',
            redraw=False)

        self.project_area_output.zoom_to()

    def add_result_layers(self):
        groupname = 'Ergebnisse'

        addresses = BaublockErgebnisse.get_table(create=True)
        self.results_output = ProjectLayer.from_table(
            addresses, groupname=groupname, prepend=True)
        self.results_output.draw(
            label='verfügbare Grünfläche je Einwohner je Baublock',
            style_file='baublock_ergebnisse.qml',
            redraw=False)
        self.set_result_categories()

    def set_result_categories(self):
        def interpolate(start: float, end: float, step: float, n_steps: float) -> float:
            ''' interpolate a value between start and end value '''
            return (end - start) * step / n_steps + start
        layer = self.results_output.layer
        step = 2
        b_point = self.project_settings.required_green
        b = round(b_point / step)
        bins = [(0, 0)] + [(i * step, (i + 1) *step) for i in range(b)]
        if b_point > b * step:
            bins.append((b*step, b_point))
        bins.append((b_point, 500000))

        geometry_type = layer.geometryType()
        categories = []

        start_color = (166, 97, 26)
        end_color = (1, 133, 113)

        for i, (lower, upper) in enumerate(bins):
            if (i == 0):
                label = lower
            elif (i == len(bins) - 1):
                label = f'>{lower}'
            else:
                label = f'>{lower} bis ≤{upper}'

            symbol = QgsSymbol.defaultSymbol(geometry_type)

            # configure a symbol layer
            layer_style = {}
            rgb = []
            for c in range(3):
                rgb.append(str(int(interpolate(start_color[c], end_color[c],
                                               i, len(bins)))))
            layer_style['color'] = ','.join(rgb)
            symbol_layer = QgsSimpleFillSymbolLayer.create(layer_style)

            # replace default symbol layer with the configured one
            if symbol_layer is not None:
                symbol.changeSymbolLayer(0, symbol_layer)

            label = f'{label}m²'
            # create renderer object
            category = QgsRendererRange(lower, upper, symbol, label)
            # entry for the list of category items
            categories.append(category)

        # create renderer object
        renderer = QgsGraduatedSymbolRenderer('gruenflaeche_je_einwohner',
                                              categories)
        layer.setRenderer(renderer)

    def apply_project_settings(self, project):
        self.ui.required_green_edit.setValue(self.project_settings.required_green)
        self.ui.max_walk_dist_edit.setValue(self.project_settings.max_walk_dist)
        self.ui.project_buffer_edit.setValue(self.project_settings.project_buffer)

        #self.router_combo.setValue(project_settings.router)
        self.ui.walk_speed_edit.setValue(self.project_settings.walk_speed)
        self.ui.wheelchair_check.setChecked(self.project_settings.wheelchair)
        self.ui.max_slope_edit.setValue(self.project_settings.max_slope)

        self.setup_routers()

    def setup_routers(self):
        # try to keep old router selected
        current_router = self.project_settings.router
        self.ui.router_combo.blockSignals(True)
        self.ui.router_combo.clear()
        idx = 0
        graph_path = settings.graph_path
        if not os.path.exists(graph_path):
            self.ui.router_combo.addItem(
                'Verzeichnis mit Routern nicht gefunden')
            self.ui.router_combo.setEnabled(False)
            self.ui.create_router_button.setEnabled(False)
        else:
            # subdirectories in graph-dir are treated as routers by OTP
            for i, subdir in enumerate(os.listdir(graph_path)):
                path = os.path.join(graph_path, subdir)
                if os.path.isdir(path):
                    graph_file = os.path.join(path, 'Graph.obj')
                    if os.path.exists(graph_file):
                        self.ui.router_combo.addItem(subdir)
                        if current_router and current_router == subdir:
                            idx = i
            self.ui.router_combo.setEnabled(True)
            self.ui.create_router_button.setEnabled(True)
        self.ui.router_combo.setCurrentIndex(idx)
        self.ui.router_combo.blockSignals(False)
        if not current_router:
            self.project_settings.router = self.ui.router_combo.currentText()
            self.project_settings.save()

    def calculate(self):
        otp_jar = settings.system['otp_jar_file']
        if not os.path.exists(otp_jar):
            msg_box = QtWidgets.QMessageBox(
                QtWidgets.QMessageBox.Warning, "Fehler",
                u'Die angegebene OTP Datei existiert nicht!')
            msg_box.exec_()
            return
        jython_jar = settings.system['jython_jar_file']
        if not os.path.exists(jython_jar):
            msg_box = QtWidgets.QMessageBox(
                QtWidgets.QMessageBox.Warning, "Fehler",
                u'Der angegebene Jython Interpreter existiert nicht!')
            msg_box.exec_()
            return
        java_executable = settings.system['java']
        if not os.path.exists(java_executable):
            msg_box = QtWidgets.QMessageBox(
                QtWidgets.QMessageBox.Warning, "Fehler",
                u'Der angegebene Java-Pfad existiert nicht!')
            msg_box.exec_()
            return
        self.prepare_routing()

    def prepare_routing(self):
        job = PrepareRouting(parent=self.ui)
        # workaround for not being able to run process together with
        # preparation and analysis in one Thread (and therefore in one dialog)
        # keeping track of elapsed time and log to hide this
        dialog = None
        self.elapsed_time = 0
        self.progress_log = []
        def on_close():
            if dialog.success:
                self.elapsed_time = dialog.elapsed_time
                self.progress_log = dialog.logs
                self.route()
        dialog = ProgressDialog(job, on_close=on_close, auto_close=True,
                                title='Vorbereitung',
                                hide_auto_close=True, parent=self.ui)
        dialog.show()

    def route(self):
        otp_jar = settings.system['otp_jar_file']
        jython_jar = settings.system['jython_jar_file']
        java_executable = settings.system['java']
        memory = settings.system['reserved']

        self.add_input_layers() # reload to make sure they are there
        origin_layer = GruenflaechenEingaengeProcessed.as_layer()
        destination_layer = AdressenProcessed.as_layer()
        wgs84 = QgsCoordinateReferenceSystem(4326)

        tmp_dir = tempfile.mkdtemp()
        # convert layers to csv and write them to temporary directory
        orig_tmp_filename = os.path.join(tmp_dir, 'origins.csv')
        dest_tmp_filename = os.path.join(tmp_dir, 'destinations.csv')
        target_file = os.path.join(tmp_dir, 'results.csv')

        o_fid_idx = [f.name() for f in origin_layer.fields()].index('eingang')
        d_fid_idx = [f.name() for f in destination_layer.fields()].index('adresse')

        QgsVectorFileWriter.writeAsVectorFormat(
            origin_layer,
            orig_tmp_filename,
            "utf-8",
            wgs84,
            "CSV",
            attributes=[o_fid_idx],
            layerOptions=["GEOMETRY=AS_YX"])

        QgsVectorFileWriter.writeAsVectorFormat(
            destination_layer,
            dest_tmp_filename,
            "utf-8",
            wgs84,
            "CSV",
            attributes=[d_fid_idx],
            layerOptions=["GEOMETRY=AS_YX"])

        config_xml = os.path.join(tmp_dir, 'config.xml')
        config = OTPConfig(filename=config_xml)
        config.settings['system']['n_threads'] = settings.system['n_threads']
        config.settings['origin']['id_field'] = 'eingang'
        config.settings['destination']['id_field'] = 'adresse'
        config.settings['post_processing']['details'] = True

        router_config = config.settings['router_config']
        buffered_dist = self.project_settings.max_walk_dist + 500
        router_config['path'] = settings.graph_path
        router_config['router'] = self.project_settings.router
        router_config['max_walk_distance'] = buffered_dist
        router_config['traverse_modes'] = 'WALK'
        router_config['walk_speed'] = self.project_settings.walk_speed
        router_config['max_time_min'] = math.ceil(
            buffered_dist / self.project_settings.walk_speed / 60)
        config.write()

        working_dir = os.path.join(settings.BASE_PATH, 'batch')

        cmd = (f'"{java_executable}" -Xmx{memory}G -jar "{jython_jar}" '
               f'-Dpython.path="{otp_jar}" '
               f'{working_dir}/otp_batch.py '
               f'--config "{config_xml}" '
               f'--origins "{orig_tmp_filename}" --destinations "{dest_tmp_filename}" '
               f'--target "{target_file}" --nlines {PRINT_EVERY_N_LINES}'
               )

        dialog = None
        # workaround
        def on_close():
            if dialog.success:
                self.elapsed_time = dialog.elapsed_time
                self.progress_log = dialog.logs
                self.analyse(target_file)

        dialog = ExecOTPDialog(cmd, parent=self.ui,
                               start_elapsed=self.elapsed_time,
                               logs=self.progress_log,
                               n_points=origin_layer.featureCount(),
                               points_per_tick=PRINT_EVERY_N_LINES,
                               on_close=on_close,
                               auto_close=True, hide_auto_close=True)
        dialog.show()

    def analyse(self, target_file):
        job = AnalyseRouting(target_file, self.green_output.layer.getFeatures(),
                             parent=self.ui)
        dialog = ProgressDialog(job, parent=self.ui, title='Analyse',
                                start_elapsed=self.elapsed_time,
                                logs=self.progress_log,
                                on_success=lambda x: self.add_result_layers())
        dialog.show()

    def create_router(self):
        java_executable = settings.system['java']
        otp_jar = settings.system['otp_jar_file']
        if not os.path.exists(otp_jar):
            msg_box = QtWidgets.QMessageBox(
                QtWidgets.QMessageBox.Warning, "Fehler",
                'Die angegebene OTP JAR Datei existiert nicht!')
            msg_box.exec_()
            return
        if not os.path.exists(java_executable):
            msg_box = QtWidgets.QMessageBox(
                QtWidgets.QMessageBox.Warning, "Fehler",
                'Der angegebene Java-Pfad existiert nicht!')
            msg_box.exec_()
            return
        graph_path = settings.graph_path
        memory = settings.system['reserved']
        diag = RouterDialog(graph_path, java_executable, otp_jar,
                            memory=memory, parent=self.ui)
        diag.exec_()
        self.setup_routers()

    def show_info(self):
        diag = InfoDialog(parent=self.ui)
        diag.exec_()

    def show_settings(self):
        diag = SettingsDialog(parent=self.ui)
        ok = diag.show()
        if ok:
            self.setup_projects()

    def open_manual(self):
        webbrowser.open_new(MANUAL_URL)

    def close(self):
        '''
        override, set inactive on close
        '''
        self.close_all_projects()
        try:
            self.ui.close()
        # ui might already be deleted by QGIS
        except RuntimeError:
            pass

    def close_all_projects(self):
        '''
        remove all project-related layers and try to close all workspaces
        '''
        #qgisproject = QgsProject.instance()
        #layer_root = qgisproject.layerTreeRoot()
        ## remove all project layers from layer tree
        #for project in self.project_manager.projects:
            #group = layer_root.findGroup(project.groupname)
            #if group:
                #for layer in group.findLayers():
                    #qgisproject.removeMapLayer(layer.layerId())
                #group.removeAllChildren()
                #layer_root.removeChildNode(group)
        for ws in Workspace.get_instances():
            if not ws.database.read_only:
                ws.close()
        self.canvas.refreshAllLayers()

    def show(self):
        '''
        show the widget inside QGIS
        '''
        self.ui.show()
