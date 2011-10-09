# -*- coding: utf-8 -*-

from PySide import QtCore, QtGui
import pymongo

import datetime, re
import threading, time, logging, sys

GLOBAL_PAUSE = None

QtCore.QTextCodec.setCodecForCStrings(QtCore.QTextCodec.codecForName('utf-8'))

log = logging.getLogger("")

def gen_date(*args, **kargs):
    d = datetime.datetime(*args, **kargs)
    return d + datetime.timedelta(seconds=time.timezone)

def setup_logging():
    formatter = logging.Formatter("%(asctime)s %(message)s")
    stream_handler = logging.StreamHandler(sys.stdout,)
    stream_handler.setFormatter(formatter)
    log.addHandler(stream_handler)

    logging.getLogger('').setLevel(logging.INFO)

def get_default_splitter(settings, name, splitter):
    sizes = settings.value(name, [])
    sizes = [int(x) for x in sizes]
    
    current_sizes = splitter.sizes()

    if len(sizes) != len(current_sizes):
        count = len(current_sizes)
        sizes = [int(sum(current_sizes)/count)] * count
    
    splitter.setSizes(sizes)

def get_history(settings, name):
    history = settings.value(name, [])
    if history is None:
        history = []
    if not isinstance(history, list):
        history = [history]
    return history

def update_history(settings, section, name, checked):
    history = get_history(settings, section)
    flag = False
    if checked and name not in history:
        history.append(name)
        flag = True
    if not checked and name in history:
        history.remove(name)
        flag = True
    if flag:
        save_history(settings, section, history)

def save_history(settings, name, history):
    settings.setValue(name, history)
    settings.sync()

class CheckboxCallback(object):
    def __init__(self, callback, name):
        self._callback = callback
        self._name = name

    def __call__(self, checked):
        return self._callback(self._name, checked)

def trans_doc(src):
    dst = {}
    def _trans_item(item):
        if isinstance(item, unicode):
            return item.encode("utf-8")
        if isinstance(item, datetime.datetime):
            return item - datetime.timedelta(seconds=time.timezone)
        return item
    
    def _trans(sub_src, sub_dst):
        for k,v in sub_src.items():
            t_k = _trans_item(k)
            if isinstance(v, dict):
                sub_dst[t_k] = {}
                _trans(v, sub_dst[t_k])
            else:
                sub_dst[t_k] = _trans_item(v)
    _trans(src, dst)
    return dst

def show_dic(dic_lst):
    prefix = ' '*4
    def _sub_show(dic, prefix_count, detail):
        detail.append('{\n')
        for k,v in dic.items():
            detail.append(prefix * prefix_count + '"%s": ' % k)
            if not isinstance(v, dict):
                detail.append('"%s",\n' % v)
            else:
                _sub_show(v, prefix_count+1, detail)
        detail.append(prefix*(prefix_count-1) + '}\n')

    detail = []
    for dic in dic_lst:
        _sub_show(dic, 1, detail)
    return ''.join(detail)

def createComboBox(name, settings, default=None):
    maxCount = int(settings.value('max_history', 10))
    comboBox = QtGui.QComboBox()
    comboBox.setEditable(True)
    comboBox.setMaxCount(maxCount)

    history = settings.value(name, [])
    if not isinstance(history, list):
        history = [history]
    comboBox.addItems(history)
    
    comboBox.setSizePolicy(QtGui.QSizePolicy.Expanding,
                           QtGui.QSizePolicy.Preferred)
    if default is not None and comboBox.count() == 0:
        comboBox.addItem(default)
    return comboBox

def saveComboBox(comboBox, name, settings):
    history = [comboBox.currentText()]
    for index in xrange(comboBox.count()):
        text = comboBox.itemText(index)
        if not text in history:
            history.append(text)
    settings.setValue(name, history)
    comboBox.clear()
    comboBox.addItems(history)
        
class TabDialog(QtGui.QWidget):
    svnCheck = QtCore.Signal(bool)
    
    def __init__(self, parent=None):
        super(TabDialog, self).__init__(parent)

        self.svnCheck.connect(self._svn_check)

        self.mdb_conn = None
        self._db = None
        self._selected_coll = {}
        self._collections = {}

        self.settings = QtCore.QSettings("gui.ini", QtCore.QSettings.IniFormat)

        self.hostLineEdit = createComboBox('host', self.settings, '127.0.0.1')
        self._host = None
        self.hostLabel = QtGui.QLabel("Host:")
        self.hostLabel.setBuddy(self.hostLineEdit)
        self.hostLineEdit.lineEdit().returnPressed.connect(self.connectMDB)

        self.dbComboBox = QtGui.QComboBox()
        self.dbComboBox.setSizePolicy(QtGui.QSizePolicy.Expanding,
                                      QtGui.QSizePolicy.Preferred)
        self.dbLabel = QtGui.QLabel("Db:")
        self.dbLabel.setBuddy(self.dbComboBox)
        self.dbComboBox.currentIndexChanged.connect(self.changeDB)

        self.connectButton = QtGui.QPushButton("&Connect")
        self.connectButton.clicked.connect(self.connectMDB)

        global GLOBAL_PAUSE
        self.pauseCheckbox = GLOBAL_PAUSE = QtGui.QCheckBox("&Pause")
        self.pauseCheckbox.setChecked(False)

        connectLayout = QtGui.QHBoxLayout()
        connectLayout.addWidget(self.hostLabel)
        connectLayout.addWidget(self.hostLineEdit)
        connectLayout.addWidget(self.dbLabel)
        connectLayout.addWidget(self.dbComboBox)
        connectLayout.addWidget(self.connectButton)
        connectLayout.addWidget(self.pauseCheckbox)

        self.collectionLayout = QtGui.QHBoxLayout()

        self._tabWidget = tabWidget = QtGui.QTabWidget()
        self._tabWidget.currentChanged.connect(self.tabChanged)

        

        self._right_w = CollectionWindow(None, None, None,
                                         self, True)
        self.leftRightSplitter = QtGui.QSplitter()
        f = lambda x,y :self.splitter_move('leftright', self.leftRightSplitter)
        self.leftRightSplitter.splitterMoved.connect(f)
        self.leftRightSplitter.addWidget(self._tabWidget)
        self.leftRightSplitter.addWidget(self._right_w)
        self._right_w.hide()
        get_default_splitter(self.settings, 'leftright',
                             self.leftRightSplitter)

        self._bottom_w = []
        self.upDownSplitter = QtGui.QSplitter(QtCore.Qt.Vertical)
        f = lambda x,y :self.splitter_move('updown', self.upDownSplitter)
        self.upDownSplitter.splitterMoved.connect(f)
        self.upDownSplitter.addWidget(self.leftRightSplitter)

        mainLayout = QtGui.QVBoxLayout()
        mainLayout.addLayout(connectLayout)
        mainLayout.addLayout(self.collectionLayout)
        mainLayout.addWidget(self.upDownSplitter)
        self.setLayout(mainLayout)

        self.setWindowTitle("MongoDB Monitor")

        self._last_update_db = None
        self._is_reset = False

        timer = QtCore.QTimer(self)
        timer.timeout.connect(self._polling)
        timer.setInterval(50)
        timer.start()

    def svn_check(self, result):
        self.svnCheck.emit(result)

    def _svn_check(self, result):
        if result:
            return
        QtGui.QMessageBox.information(None, 'New Version',
                                      'There is new version of this program. '
                                      'Run "svn up" to get it.')

    def splitter_move(self, section, splitter):
        self.settings.setValue(section, splitter.sizes())
        self.settings.sync()

    def right_window(self, name):
        if self._right_w.name != name:
            self._right_w.set_data(name, self._host, self._db.name)
            self._right_w.show()

    def bottom_window(self, name):
        for w in self._bottom_w:
            if w.name is None:
                w.set_data(name, self._host, self._db.name)
                w.show()
                return
            
            if w.name == name:
                return
        
        w = CollectionWindow(None, None, None,
                             self, True)
        self.upDownSplitter.addWidget(w)
        w.set_data(name, self._host, self._db.name)
        self._bottom_w.append(w)
        w.show()

        get_default_splitter(self.settings, 'updown',
                             self.upDownSplitter)
        
    def connectMDB(self):
        if self.mdb_conn is None:
            self._host = host = str(self.hostLineEdit.currentText())
            self.mdb_conn = pymongo.Connection(host)
            self._last_update_db = None

            self.connectButton.setText("&Disconnect")
            self.hostLineEdit.setEnabled(False)

            saveComboBox(self.hostLineEdit, 'host', self.settings)
            self.settings.sync()
        else:
            self.mdb_conn.disconnect()
            del self.mdb_conn
            del self._db
            self.mdb_conn = None
            self._db = None
            self._host = None
            self.reset_coll()
            self.connectButton.setText("&Connect")
            self.hostLineEdit.setEnabled(True)
            self.dbComboBox.clear()

    def tabChanged(self, index):
        if self._tabWidget.count() == 1 or self._is_reset:
            return
        self.save_tab_pos()

    def save_tab_pos(self):
        w = self._tabWidget.currentWidget()
        if w is None or self._host is None or self._db is None:
            return
        self.settings.beginGroup('%s-%s' % (self._host,
                                            self._db.name))
        history = self.settings.value('collection', None)
        name = w.name
        if not history == name:
            self.settings.setValue('collection', name)
            self.settings.sync()
        self.settings.endGroup()

    def changeDB(self):
        if self.mdb_conn is None:
            return

        db_name = self.dbComboBox.currentText()
        if self._db is not None and self._db.name == db_name:
            return

        if len(db_name) == 0:
            return

        self.settings.beginGroup(self._host)
        self.settings.setValue('db', db_name)
        self.settings.endGroup()
        self.settings.sync()

        self.reset_coll()

        self._db = self.mdb_conn[db_name]

    def reset_coll(self):
        self._is_reset = True
        for name, check_box in self._collections.items():
            self.close_window(name)
            check_box.hide()
            self.collectionLayout.removeWidget(check_box)
        self._is_reset = False
        self._collections = {}
        self.update()

        self._right_w.mouseDoubleClickEvent(None)
        for w in self._bottom_w:
            w.mouseDoubleClickEvent(None)

    def _polling(self):
        if self.mdb_conn is None:
            return

        try:
            self.db_info_update()
            self.coll_info_update(self._db.collection_names())

            if  self.pauseCheckbox.isChecked():
                return

            self.coll_detail_update()
        except:
            log.error("-"*60, exc_info=True)

    def db_info_update(self):
        if self._last_update_db != None and \
               time.clock() - self._last_update_db <= 5:
            return
        self._last_update_db = time.clock()

        db_names = self.mdb_conn.database_names()
        c = self.dbComboBox
        last_db_names = [c.itemText(x) for x in xrange(c.count())]

        db_names.sort()
        last_db_names.sort()

        if db_names == last_db_names:
            return

        self.settings.beginGroup(self._host)
        last_db = self.settings.value('db', None)
        self.settings.endGroup()

        if last_db in db_names:
            db_names.remove(last_db)
            db_names.insert(0, last_db)

        self.dbComboBox.clear()
        self.dbComboBox.addItems(db_names)

    def coll_info_update(self, coll_names):
        flag = False
        for name in coll_names:
            if name in self._collections:
                continue
            check_box = QtGui.QCheckBox(name)
            check_box.toggled.connect(CheckboxCallback(self.collectionChanged,
                                                       name))
            self._collections[name] = check_box
            self.collectionLayout.addWidget(check_box)
            flag = True

        for name, check_box in self._collections.items():
            if not name in coll_names:
                self.close_window(name)
                check_box.hide()
                self.collectionLayout.removeWidget(check_box)
                del self._collections[name]
                flag = True
        
        if flag:
            self.settings.beginGroup('%s-%s' % (self._host,
                                                self._db.name))
            history = get_history(self.settings, 'collections')
            self.settings.endGroup()
            
            for name in history:
                if not name in self._collections:
                    continue
                
                check_box = self._collections[name]
                if not check_box.isChecked():
                    check_box.setChecked(True)

            self.update()

    def collectionChanged(self, coll_name, checked):
        if checked and coll_name not in self._selected_coll:
            self.add_window(coll_name)

        if not checked and coll_name in self._selected_coll:
            self.close_window(coll_name)

        self.settings.beginGroup('%s-%s' % (self._host,
                                            self._db.name))
        update_history(self.settings, 'collections',
                       coll_name, checked)
        self.settings.endGroup()

    def add_window(self, name):
        w = CollectionWindow(name, self._host, self._db.name,
                             self)
        self._tabWidget.addTab(w, name)
        self._selected_coll[name] = w
        
        self.settings.beginGroup('%s-%s' % (self._host,
                                            self._db.name))
        history = self.settings.value('collection', None)
        self.settings.endGroup()

        if history == name:
            self._tabWidget.setCurrentWidget(w)

    def close_window(self, name, untoggled=False):
        if not name in self._selected_coll:
            return
        w = self._selected_coll[name]
        w.close()
        index = self._tabWidget.indexOf(w)
        self._tabWidget.removeTab(index)
        del self._selected_coll[name]

        if untoggled:
            self._collections[name].setChecked(False)
            if self._tabWidget.count() == 1:
                self.save_tab_pos()

    def clear_collection(self, name):
        self._db[name].remove()

    def coll_detail_update(self):
        self.coll_window_update(self._tabWidget.currentWidget())
        self.coll_window_update(self._right_w)
        for w in self._bottom_w:
            self.coll_window_update(w)

    def coll_window_update(self, w):
        if w is None or w.name is None:
            return
        name = w.name
        w.polling(self._db[name])
        
class CollectionWindow(QtGui.QWidget):
    def __init__(self, coll_name, host, db_name,
                 parent, is_side=False):
        super(CollectionWindow, self).__init__(parent)
        self.parent = parent
        self.is_side = is_side

        self.name = coll_name
        self._column_actions = {}
        self._hints = {}
        self._tab_text = "List"

        self.settings = QtCore.QSettings("gui.ini", QtCore.QSettings.IniFormat)
        self.connect_info = (host, db_name, coll_name)
        self.settings.beginGroup('%s-%s-%s' % self.connect_info)
        
        self._tabWidget = QtGui.QTabWidget()

        self.model = QtGui.QStandardItemModel(0, 1, self)
        self._headers = [None]

        self.proxyView = QtGui.QTreeView(self)
        self.proxyView.setSelectionMode(QtGui.QAbstractItemView.SingleSelection)
        self.proxyView.setRootIsDecorated(False)
        self.proxyView.setAlternatingRowColors(True)
        self.proxyView.setSortingEnabled(True)
        self.proxyView.setModel(self.model)
        
        header = self.proxyView.header()
        header.setStretchLastSection(False)
        header.sectionResized.connect(self.sectionSizeChanged)
        header.sectionClicked.connect(self.sortChanged)
        
        self.proxyView.setColumnHidden(0, True)

        self.detailViewer = QtGui.QTextBrowser()
        self._last_docs = []
        self._last_ids = []

        self._tabWidget.addTab(self.proxyView, self._tab_text)
        self._tabWidget.addTab(self.detailViewer, 'Detail')

        funcs = self.functionAction = []
        def _add_func(funcs, name, trigger, parent):
            action = QtGui.QAction(name, parent,
                                   triggered=trigger)
            funcs.append(action)
        if not self.is_side:
            _add_func(funcs, "Clear", self.clearCollection, self)
            _add_func(funcs, "to Right", self.toRight, self)
            _add_func(funcs, "to Bottom", self.toBottom, self)

        mainLayout = QtGui.QHBoxLayout()
        mainLayout.addWidget(self._tabWidget)
        self.setLayout(mainLayout)

        self.fnt = QtGui.QFont()
        self.fnt.setPixelSize(14)
        self.proxyView.setFont(self.fnt)

        self.subDialogAction = []

        self.subDialogAction.append(QtGui.QAction("filter", self,
                                                  triggered=lambda : \
                                                  self.showSubDialog('filter')))
        self._filter_exp = ""
        self._criteria = self._gen_criteria()

        self.subDialogAction.append(QtGui.QAction("Columns", self,
                                                  triggered=lambda :\
                                                  self.showSubDialog('column_select')))
        self.subDialogAction.append(QtGui.QAction("Indexes", self,
                                                  triggered=lambda :\
                                                  self.showSubDialog('index_info')))

        self._sub_dialogs = {}
        self._sub_dialog_gen = {
            'filter': lambda : CollectionFilterDialog(self,
                                                      self.settings),
            'column_select': lambda : ColumnSelectDialog(self,
                                                         self._column_actions),
            'index_info': lambda : IndexinfoDialog(self,
                                                   self.connect_info)
            }
        
        f = lambda : self.mouseDoubleClickEvent(None)
        self.closeAction = QtGui.QAction("close", self,
                                         triggered=f)

        self.color = QtGui.QColor(QtCore.qrand() % 256, QtCore.qrand() % 256,
                                  QtCore.qrand() % 256)
        self._start_drag = False

    def keyReleaseEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.proxyView.scrollToTop()
            self.proxyView.reset()

    def closeSubDialog(self, name=None):
        if name == None:
            for dialog in self._sub_dialogs.values():
                dialog.close()
            self._sub_dialogs = {}
        else:
            if not name in self._sub_dialogs:
                return
            self._sub_dialogs[name].close()
            del self._sub_dialogs[name]

    def showSubDialog(self, name):
        self.closeSubDialog(name)
        self._sub_dialogs[name] = self._sub_dialog_gen[name]()
        self._sub_dialogs[name].show()

    def add_filter(self, filter_exp):
        self._filter_exp = filter_exp
        self._criteria = self._gen_criteria()

    def _change_hint(self, key, hint):
        if not key in self._hints:
            self._hints[key] = None

        if self._hints[key] == hint:
            return

        self._hints[key] = hint
        self._tabWidget.setTabText(0, self._tab_text+''.join(self._hints.values()))

    def _gen_criteria(self):
        hint = " - Filtering"
        key = 'filter'
            
        if len(self._filter_exp) == 0:
            self._change_hint(key, '')
            return {}

        self._change_hint(key, hint)
        
        criteria = {}
        try:
            if not self._filter_exp.startswith("{"):
                exp = '{%s}' % self._filter_exp
            else:
                exp = self._filter_exp
            criteria = eval(exp)
        except:
            pass
        return criteria

    def closeEvent(self, event):
        self.closeSubDialog()
        super(CollectionWindow, self).closeEvent(event)

    def paint(self, painter, option, widget):
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtCore.Qt.darkGray)
        painter.drawEllipse(-12, -12, 30, 30)
        painter.setPen(QtGui.QPen(QtCore.Qt.black, 1))
        painter.setBrush(QtGui.QBrush(self.color))
        painter.drawEllipse(-15, -15, 30, 30)

    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton or self.is_side:
            event.ignore()
            return

        self._start_drag = True

    def mouseMoveEvent(self, event):
        if not self._start_drag:
            return
        self._start_drag = False
        
        start_pos = QtGui.QCursor.pos()

        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        drag.setMimeData(mime)
        
        mime.setColorData(self.color)
        mime.setText("#%02x%02x%02x" % (self.color.red(),
                                        self.color.green(),
                                        self.color.blue()))
        
        pixmap = QtGui.QPixmap(34, 34)
        pixmap.fill(QtCore.Qt.white)

        painter = QtGui.QPainter(pixmap)
        painter.translate(15, 15)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        self.paint(painter, None, None)
        painter.end()

        pixmap.setMask(pixmap.createHeuristicMask())

        drag.setPixmap(pixmap)
        drag.setHotSpot(QtCore.QPoint(15, 20))

        drag.exec_()

        end_pos = QtGui.QCursor.pos()

        dx = end_pos.x() - start_pos.x()
        dy = end_pos.y() - start_pos.y()

        if dx <= 0 and dy <= 0:
            return
        
        if dx > dy:
            self.toRight()
        else:
            self.toBottom()

    def contextMenuEvent(self, event):
        menu = QtGui.QMenu(self)
        for action in self.subDialogAction:
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(self.closeAction)
        for action in self.functionAction:
            menu.addAction(action)
        menu.addSeparator()
        for action in self._column_actions.values():
            menu.addAction(action)
        menu.exec_(event.globalPos())

    def set_data(self, coll_name, host, db_name):
        if not self.is_side:
            return

        self.closeSubDialog()
        self.add_filter('')

        m = self.model
        m.removeRows(0, m.rowCount())

        m.removeColumns(1, len(self._headers)-1)
        self._headers = [None]
        self._column_actions = {}

        self.detailViewer.clear()
        self._last_docs = []
        self._last_ids = []
        
        self.name = coll_name
        self.settings.endGroup()
        self.connect_info = (host, db_name, coll_name)
        self.settings.beginGroup('%s-%s-%s' % self.connect_info)

        self._tab_text = '%s/List' % coll_name

    def toRight(self):
        self.parent.right_window(self.name)

    def toBottom(self):
        self.parent.bottom_window(self.name)

    def clearCollection(self):
        warning = 'Do you really want to clear this collection?'
        ret = QtGui.QMessageBox.warning(self, 'Warning',
                                        warning,
                                        QtGui.QMessageBox.Yes |
                                        QtGui.QMessageBox.No,
                                        QtGui.QMessageBox.No)
        if ret == QtGui.QMessageBox.No:
            return
        self.parent.clear_collection(self.name)

    def mouseDoubleClickEvent(self, event):
        if not self.is_side:
            self.parent.close_window(self.name, True)
        else:
            self.set_data(None, None, None)
            self.hide()

    def polling(self, coll):
        max_count = 50
        if self.name.endswith('.chunks'):
            cursor = coll.find(self._criteria, {'data':0})
        else:
            cursor = coll.find(self._criteria)
        total_count = cursor.count()
        if total_count > max_count:
            hint = ' - limited(%s/%s)' % (max_count, total_count)
            cursor = cursor.limit(max_count)
            result = self._get_purpose_orderby()
            if result is None:
                key = '_id'
                order = pymongo.DESCENDING
            else:
                key = result[0]
                order = getattr(pymongo, result[1].upper().replace('ORDER',''))
            cursor = cursor.sort(key, order)
        else:
            hint = ' - total(%s)' % total_count

        self._change_hint('limit', hint)
            
        docs = [trans_doc(x) for x in cursor]
        self._updateDoc(docs)

    def _updateDoc(self, docs):
        self.column_info_update(docs)

        self.process_docs(docs)

        if len(self.new_doc) == 0 and \
           len(self.modify_doc) == 0 and \
           len(self.delete_doc) == 0:
            return
        
        self.detail_viewer_update()
        self.column_detail_update()

    def process_docs(self, docs):
        self.new_doc = []
        self.modify_doc = []
        self.same_doc = []
        self.delete_doc = []

        if len(docs) == 0:
            self.delete_doc = self._last_docs
            self._last_docs = []
            self._last_ids = []
            return

        if not '_id' in docs[0]:
            return

        last_docs = self._last_docs
        last_ids = self._last_ids

        for doc in docs:
            if not doc in last_docs:
                if doc['_id'] not in last_ids:
                    self.new_doc.append(doc)
                else:
                    index = last_ids.index(doc['_id'])
                    old_doc = last_docs[index]
                    self.modify_doc.append((doc, old_doc))
            else:
                self.same_doc.append(doc)

        new_ids = [doc['_id'] for doc in docs]
        for _id in last_ids:
            if not _id in new_ids:
                index = last_ids.index(_id)
                self.delete_doc.append(last_docs[index])

        self._last_docs = docs
        self._last_ids = new_ids

    def detail_viewer_update(self):
        self.detailViewer.clear()
        fnt = self.fnt
        
        fnt.setBold(True)
        self.detailViewer.setCurrentFont(fnt)
        self.detailViewer.insertPlainText(show_dic(self.new_doc))

        for new, old in self.modify_doc:
            new_detail = show_dic([new]).split('\n')
            old_detail = show_dic([old]).split('\n')

            for line in new_detail:
                if line in old_detail:
                    fnt.setBold(False)
                else:
                    fnt.setBold(True)
                self.detailViewer.setCurrentFont(fnt)
                self.detailViewer.insertPlainText(line+'\n')
            self.detailViewer.moveCursor(QtGui.QTextCursor.MoveOperation.PreviousCharacter)

        fnt.setBold(False)
        self.detailViewer.setCurrentFont(fnt)
        self.detailViewer.insertPlainText("="*80 + '\n' + show_dic(self.same_doc))

        self.detailViewer.moveCursor(QtGui.QTextCursor.MoveOperation.Start)

    def sectionSizeChanged(self, index, old_size, new_size):
        if self.is_side:
            return

        name = self._headers[index]
        if not name in self._column_actions or \
               not self._column_actions[name].isChecked():
            return

        self.settings.setValue(name, new_size)
        self.settings.sync()

    def sortChanged(self, index):
        name = self._headers[index]
        order = self.proxyView.header().sortIndicatorOrder().name
        self.settings.setValue('orderBy', [name, order])
        self.settings.sync()

    def columnChanged(self, name, checked):
        self.display_column(name, not checked)
        if not self.is_side:
            update_history(self.settings, 'columns',
                           name, checked)

    def display_column(self, name, is_hide):
        index = self._headers.index(name)
        
        size = self.settings.value(name, None)
        if size is not None:
            self.proxyView.header().resizeSection(index,
                                                  int(size))
        
        self.proxyView.setColumnHidden(index, is_hide)

    def column_info_update(self, docs):
        columns = set()
        for doc in docs:
            columns.update(doc.keys())

        history = get_history(self.settings, 'columns')
        for name in columns:
            if name in self._headers:
                continue
            
            index = len(self._headers)
            self._headers.append(name)

            action = QtGui.QAction(name, self, checkable=True)
            action.toggled.connect(CheckboxCallback(self.columnChanged,
                                                    name))
            self._column_actions[name] = action

            self.model.appendColumn([])
            self.model.setHeaderData(index, QtCore.Qt.Horizontal, name)

            if name in history or len(history) == 0:
                action.setChecked(True)
            else:
                self.proxyView.setColumnHidden(index, True)

    def update_model_item(self, row, doc):
        m = self.model
        for index in xrange(1, len(self._headers)):
            k = self._headers[index]
            v = doc.get(k, '')
            m.setData(m.index(row, index), str(v)+'\n')
        m.setData(m.index(row, 0), str(doc))

    def column_detail_update(self):
        m = self.model

        delete_str = [str(doc) for doc in self.delete_doc]
        flag = True
        while flag:
            flag = False
            for row in xrange(m.rowCount()):
                old_str = m.data(m.index(row, 0))
                if old_str in delete_str:
                    m.removeRow(row)
                    flag = True
                    break

        modify_new = {}
        for new, old in self.modify_doc:
            modify_new[str(old)] = new
            
        for row in xrange(m.rowCount()):
            old = m.data(m.index(row, 0))
            if old in modify_new:
                self.update_model_item(row, modify_new[old])

        for doc in self.new_doc:
            m.insertRow(0)
            self.update_model_item(0, doc)

        result = self._get_purpose_orderby()
        if result is None:
            return
        name, order = result
        index = self._headers.index(name)
        order = QtCore.Qt.SortOrder.values[order]
        self.proxyView.header().setSortIndicator(index, order)

    def _get_purpose_orderby(self):
        history = self.settings.value('orderBy', None)
        if history is None:
            return None
        name = history[0]
        order = history[1]
        if not name in self._column_actions or \
               not self._column_actions[name].isChecked():
            return None
        return name, order

class IndexinfoDialog(QtGui.QDialog):
    def __init__(self, parent, connect_info):
        super(IndexinfoDialog, self).__init__(parent)

        self.parent = parent
        self.setWindowTitle(parent.name)

        host, db_name, coll_name = connect_info
        self.conn = pymongo.Connection(host)
        self.coll = self.conn[db_name][coll_name]

        self.indexInfoLayout = QtGui.QVBoxLayout()
        self.index_checkbox = {}

        self.exampleButton = QtGui.QPushButton("Example")
        self.exampleButton.clicked.connect(self.showExample)

        self.indexLineEdit = QtGui.QLineEdit()
        applyButton = QtGui.QPushButton('Apply')
        self.indexLineEdit.returnPressed.connect(self.new_index)
        applyButton.clicked.connect(self.new_index)

        newIndexLayout = QtGui.QHBoxLayout()
        newIndexLayout.addWidget(self.exampleButton)
        newIndexLayout.addWidget(self.indexLineEdit)
        newIndexLayout.addWidget(applyButton)

        mainLayout = QtGui.QVBoxLayout()
        mainLayout.addLayout(self.indexInfoLayout)
        mainLayout.addLayout(newIndexLayout)

        self.setLayout(mainLayout)

        self.resize(500, 50)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.updateIndexInfo)
        self.timer.setInterval(1000)
        self.timer.start()
        self.updateIndexInfo()

    def new_index(self):
        index_exp = self.indexLineEdit.text()
        self.indexLineEdit.setText('')
        
        if len(index_exp) == 0:
            return
        
        if not index_exp.startswith('['):
            index_exp = '[%s]' % index_exp
        try:
            new_indexes = eval(index_exp)
            self.coll.ensure_index(new_indexes)
        except:
            pass

    def removeIndex(self, name, checked):
        if checked:
            return
        
        cb = self.index_checkbox[name]
        
        warning = 'Do you really want to remove index "%s"?' % name
        ret = QtGui.QMessageBox.warning(self, 'Warning',
                                        warning,
                                        QtGui.QMessageBox.Yes |
                                        QtGui.QMessageBox.No,
                                        QtGui.QMessageBox.No)
        if ret == QtGui.QMessageBox.No:
            cb.setChecked(True)
            return

        cb.hide()
        self.indexInfoLayout.removeWidget(cb)
        del self.index_checkbox[name]

        self.coll.drop_index(name)

    def updateIndexInfo(self):
        index_info = self.coll.index_information()
        for name in index_info.keys():
            if name == '_id_' or name in self.index_checkbox:
                continue
            cb = QtGui.QCheckBox(name)
            cb.setChecked(True)
            cb.toggled.connect(CheckboxCallback(self.removeIndex,
                                                name))
            self.index_checkbox[name] = cb
            self.indexInfoLayout.addWidget(cb)

    def closeEvent(self, e):
        self.timer.stop()
        e.accept()

    def showExample(self):
        example = u"""index on 'ready_time' field with ASENDING direction
('ready_time',1)
-------------------------------------
index on 'finish_time' field with DESENDING direction
('finish_time',-1)
-------------------------------------
create a compound index on 'ready_time' and 'finish_time'
('ready_time',1), ('finish_time', 1)"""
        QtGui.QMessageBox.information(None,
                                      "Index example",
                                      example)
        

class ColumnSelectDialog(QtGui.QDialog):
    def __init__(self, parent, column_actions):
        super(ColumnSelectDialog, self).__init__(parent)

        self.parent = parent
        self._column_actions = column_actions
        self.setWindowTitle(parent.name)

        keys = column_actions.keys()
        total = len(keys)
        for rc in range(total+1):
            if rc ** 2 >= total:
                break

        self._check_boxs = []
        for key, action in column_actions.items():
            check_box = QtGui.QCheckBox(key)
            check_box.setChecked(action.isChecked())
            check_box.toggled.connect(CheckboxCallback(self._columnChanged, key))
            self._check_boxs.append(check_box)

        columnLayout = QtGui.QGridLayout()

        for index in range(total):
            check_box = self._check_boxs[index]

            r = int(index/rc)
            c = index%rc

            columnLayout.addWidget(check_box, r, c)

        groupBoxLayout = QtGui.QHBoxLayout()
        select_all = QtGui.QRadioButton('Select all')
        select_all.clicked.connect(self._select_all)
        select_none = QtGui.QRadioButton('Select none')
        select_none.clicked.connect(self._select_none)
        groupBoxLayout.addWidget(select_all)
        groupBoxLayout.addWidget(select_none)
        groupBox = QtGui.QGroupBox("Select")
        groupBox.setLayout(groupBoxLayout) 

        mainLayout = QtGui.QVBoxLayout()
        mainLayout.addWidget(groupBox)
        mainLayout.addLayout(columnLayout)

        self.setLayout(mainLayout)

    def _columnChanged(self, name, checked):
        self._column_actions[name].setChecked(checked)

    def _select_all(self):
        for check_box in self._check_boxs:
            check_box.setChecked(True)

    def _select_none(self):
        for check_box in self._check_boxs:
            check_box.setChecked(False)

class CollectionFilterDialog(QtGui.QDialog):
    def __init__(self, parent, settings):
        super(CollectionFilterDialog, self).__init__(parent)

        self.parent = parent
        self.settings = settings
        self.setWindowTitle(parent.name)

        self.exampleButton = QtGui.QPushButton("Example")
        self.exampleButton.clicked.connect(self.showExample)

        global GLOBAL_PAUSE
        self.g_pause = GLOBAL_PAUSE
        self.pauseCheckbox = QtGui.QCheckBox("Pause")
        self.pauseCheckbox.setChecked(self.g_pause.isChecked())
        self.pauseCheckbox.toggled.connect(lambda x: self.g_pause.setChecked(x))

        self.filterLineEdit = createComboBox('filter', self.settings, "")
        self._filter = parent._filter_exp
        self.filterLabel = QtGui.QLabel(u"Doc Filter")
        self.filterLabel.setBuddy(self.filterLineEdit)
        self.filterLineEdit.lineEdit().returnPressed.connect(self.apply_filter)
        self.filterLineEdit.editTextChanged.connect(self.filterChanged)

        self.applyButton = QtGui.QPushButton("Apply")
        self.applyButton.clicked.connect(self.apply_filter)

        self._filterTitle = QtGui.QLabel("Current Filter: ")
        self._currentFilter = QtGui.QLabel('"%s"' % self._filter)

        self.filterChanged()
        topLayout = QtGui.QHBoxLayout()
        topLayout.addWidget(self._filterTitle)
        topLayout.addWidget(self._currentFilter)

        filterLayout = QtGui.QHBoxLayout()
        
        filterLayout.addWidget(self.filterLabel)
        filterLayout.addWidget(self.filterLineEdit)
        filterLayout.addWidget(self.applyButton)
        filterLayout.addWidget(self.pauseCheckbox)
        filterLayout.addWidget(self.exampleButton)

        mainLayout = QtGui.QVBoxLayout()
        mainLayout.addLayout(topLayout)
        mainLayout.addLayout(filterLayout)

        self.setLayout(mainLayout)

        self.resize(750, 50)

    def showExample(self):
        example = u"""show all documents where the 'location' field is 'abc'
'location':'abc'
-------------------------------------
show all documents where the 'user_id' field is not 'check1'
'user_id':{'$nin':['check1']}
-------------------------------------
empty string means no filtering"""
        QtGui.QMessageBox.information(None,
                                      "filter example",
                                      example)

    def filterChanged(self):
        if self.filterLineEdit.currentText() != self._filter:
            self.applyButton.setEnabled(True)
            self.pauseCheckbox.setChecked(True)
        else:
            self.applyButton.setEnabled(False)

    def apply_filter(self):
        nfilter = self.filterLineEdit.currentText()
        if nfilter != self._filter:
            self._filter = nfilter
        self.applyButton.setEnabled(False)

        self.parent.add_filter(self._filter)
        self._currentFilter.setText('"%s"' % self.parent._filter_exp)
        
        saveComboBox(self.filterLineEdit, 'filter', self.settings)
        self.settings.sync()

        self.pauseCheckbox.setChecked(False)

if __name__ == '__main__':
    setup_logging()
    app = QtGui.QApplication(sys.argv)
    tabdialog = TabDialog()
    tabdialog.showMaximized()
    sys.exit(app.exec_())
